from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.analytics import live_companies, live_contacts
from app.api.common import (activity_out, company_out, iso, note_out, num, paging, signal_out, source_out)
from app.core.auth import CurrentUser, get_current_user, require_editor
from app.core.config import get_settings
from app.core.db import get_session
from app.models import (Activity, Company, CompanyLocation, CompanySignal, Contact, CrawlJob, DuplicateCandidate,
                        FinanceInvoice, LeadScore, Note, TrainingOpportunity, TrainingProgram, User)
from app.services.audit import audit
from app.services.crm import log_activity, suppressed_reasons, user_source
from app.services.normalize import domain_from_url, normalize_company_name, normalize_website

router = APIRouter(prefix="/api/companies", tags=["companies"])

SORTS = {"name": Company.display_name, "industry": Company.industry, "created_at": Company.created_at,
         "employees": Company.employee_estimate, "deal_value": Company.deal_value}
DUPLICATE_SIMILARITY = 0.55


class CompanyIn(BaseModel):
    legal_name: str = Field(min_length=2, max_length=300)
    display_name: str | None = Field(default=None, max_length=300)
    website: str | None = Field(default=None, max_length=500)
    industry: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=5000)
    employee_estimate: int | None = Field(default=None, ge=1, le=10_000_000)
    phone: str | None = Field(default=None, max_length=60)
    general_email: EmailStr | None = None
    deal_value: Decimal | None = Field(default=None, ge=0, le=100_000_000)
    address: str | None = Field(default=None, max_length=1000)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=80)
    source_url: str | None = Field(default=None, max_length=1000)

    @field_validator("website")
    @classmethod
    def _website(cls, v):
        return normalize_website(v)

    @field_validator("source_url")
    @classmethod
    def _source(cls, v):
        return normalize_website(v) if v else None


class CompanyPatch(CompanyIn):
    legal_name: str | None = Field(default=None, min_length=2, max_length=300)


COMPANY_FIELDS = ("legal_name", "display_name", "website", "industry", "description", "employee_estimate", "phone",
                  "general_email", "deal_value")
LOCATION_FIELDS = ("address", "city", "state", "country")


async def _similar(db: AsyncSession, normalized: str, exclude_id: int | None = None) -> list[dict]:
    rows = (await db.execute(
        select(Company.id, Company.legal_name, Company.domain, func.similarity(Company.normalized_name, normalized))
        .where(live_companies(), func.similarity(Company.normalized_name, normalized) >= DUPLICATE_SIMILARITY,
               Company.id != (exclude_id or 0))
        .order_by(func.similarity(Company.normalized_name, normalized).desc()).limit(5))).all()
    return [{"id": i, "legal_name": n, "domain": d, "similarity": round(float(s), 2)} for i, n, d, s in rows]


async def _get(db: AsyncSession, company_id: int) -> Company:
    c = await db.get(Company, company_id)
    if not c or c.deleted_at or c.is_demo != get_settings().demo_mode:
        raise HTTPException(404, "Company not found")
    return c


def _location_out(loc: CompanyLocation | None) -> dict | None:
    if not loc:
        return None
    return {"id": loc.id, "address": loc.address, "city": loc.city, "state": loc.state, "postcode": loc.postcode,
            "country": loc.country, "is_primary": loc.is_primary}


@router.get("")
async def list_companies(q: str | None = Query(None, max_length=200), industry: str | None = None,
                         state: str | None = None, sort: str = "name", desc: bool = False,
                         pg: tuple[int, int] = Depends(paging), _: CurrentUser = Depends(get_current_user),
                         db: AsyncSession = Depends(get_session)):
    page, size = pg
    if sort not in SORTS:
        raise HTTPException(422, f"sort must be one of {sorted(SORTS)}")
    primary = (select(CompanyLocation.company_id, CompanyLocation.city, CompanyLocation.state, CompanyLocation.country)
               .where(CompanyLocation.is_primary.is_(True)).subquery())
    counts = (select(Contact.company_id, func.count().label("n")).where(live_contacts())
              .group_by(Contact.company_id).subquery())
    base = (select(Company, primary.c.city, primary.c.state, primary.c.country, func.coalesce(counts.c.n, 0))
            .outerjoin(primary, primary.c.company_id == Company.id).outerjoin(counts, counts.c.company_id == Company.id)
            .where(live_companies()))
    if q:
        like = f"%{q.strip()}%"
        base = base.where(Company.legal_name.ilike(like) | Company.domain.ilike(like) | Company.display_name.ilike(like))
    if industry:
        base = base.where(Company.industry == industry)
    if state:
        base = base.where(primary.c.state == state)
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    col = SORTS[sort]
    rows = (await db.execute(base.order_by(col.desc().nulls_last() if desc else col.asc().nulls_last(), Company.id)
                             .offset((page - 1) * size).limit(size))).all()
    items = [company_out(c, location={"city": city, "state": st, "country": country} if (city or st) else None,
                         contact_count=n) for c, city, st, country, n in rows]
    return {"items": items, "total": total, "page": page, "page_size": size}


@router.post("", status_code=201)
async def create_company(body: CompanyIn, request: Request, user: CurrentUser = Depends(require_editor),
                         db: AsyncSession = Depends(get_session)):
    domain = domain_from_url(body.website)
    if domain:
        clash = await db.scalar(select(Company.id).where(live_companies(), Company.domain == domain))
        if clash:
            raise HTTPException(409, {"message": f"A company with domain {domain} already exists.", "existing_id": clash})
    normalized = normalize_company_name(body.legal_name)
    if not normalized:
        raise HTTPException(422, "Company name has no usable characters")
    similar = await _similar(db, normalized)

    c = Company(legal_name=body.legal_name.strip(), display_name=(body.display_name or body.legal_name).strip(),
                normalized_name=normalized, website=body.website, domain=domain,
                domain_status="USER_PROVIDED" if domain else "UNRESOLVED", industry=body.industry,
                description=body.description, employee_estimate=body.employee_estimate,
                employee_estimate_source="User entered" if body.employee_estimate else None, phone=body.phone,
                general_email=str(body.general_email).lower() if body.general_email else None,
                deal_value=body.deal_value, is_demo=get_settings().demo_mode, created_by_id=user.id)
    db.add(c)
    await db.flush()
    for f in COMPANY_FIELDS + LOCATION_FIELDS:
        v = getattr(body, f)
        if v is not None and f not in ("display_name", "deal_value"):
            db.add(user_source(c.id, field=f, value=v, source_url=body.source_url))
    if any(getattr(body, f) for f in LOCATION_FIELDS):
        db.add(CompanyLocation(company_id=c.id, address=body.address, city=body.city, state=body.state,
                               country=body.country or "Malaysia", is_primary=True))
    for s in similar:
        lo, hi = sorted((c.id, s["id"]))
        db.add(DuplicateCandidate(entity_type="company", left_id=lo, right_id=hi, similarity=s["similarity"],
                                  reasons=[f"Similar name: {s['legal_name']}"]))
    log_activity(db, "created", f"Company added by {user.username}", company_id=c.id, user_id=user.id)
    audit(db, user.id, "company_created", "company", c.id, {"legal_name": c.legal_name}, request)
    await db.commit()
    out = await company_detail(c.id, user, db)
    out["possible_duplicates"] = similar
    return out


@router.get("/{company_id}")
async def get_company(company_id: int, user: CurrentUser = Depends(get_current_user),
                      db: AsyncSession = Depends(get_session)):
    return await company_detail(company_id, user, db)


async def company_detail(company_id: int, user: CurrentUser, db: AsyncSession) -> dict:
    c = (await db.execute(select(Company).options(selectinload(Company.locations), selectinload(Company.sources))
                          .where(Company.id == company_id))).scalar_one_or_none()
    if not c or c.deleted_at or c.is_demo != get_settings().demo_mode:
        raise HTTPException(404, "Company not found")
    primary = next((loc for loc in c.locations if loc.is_primary), c.locations[0] if c.locations else None)

    score = select(LeadScore.contact_id, LeadScore.score, LeadScore.priority).where(LeadScore.is_current.is_(True)).subquery()
    contacts = (await db.execute(
        select(Contact, score.c.score, score.c.priority).outerjoin(score, score.c.contact_id == Contact.id)
        .where(live_contacts(), Contact.company_id == c.id)
        .order_by(score.c.score.desc().nulls_last(), Contact.full_name))).all()
    opps = (await db.execute(
        select(TrainingOpportunity, TrainingProgram.name).join(TrainingProgram, TrainingProgram.id == TrainingOpportunity.program_id)
        .where(TrainingOpportunity.company_id == c.id, TrainingOpportunity.is_current.is_(True))
        .order_by(TrainingOpportunity.match_score.desc()))).all()
    signals = (await db.execute(select(CompanySignal).where(CompanySignal.company_id == c.id)
                                .order_by(CompanySignal.discovered_at.desc()))).scalars().all()
    acts = (await db.execute(select(Activity, User.finance_username).outerjoin(User, User.id == Activity.user_id)
                             .where(Activity.company_id == c.id).order_by(Activity.created_at.desc()).limit(100))).all()
    notes = (await db.execute(select(Note, User.finance_username).outerjoin(User, User.id == Note.user_id)
                              .where(Note.company_id == c.id, Note.contact_id.is_(None), Note.deleted_at.is_(None))
                              .order_by(Note.created_at.desc()))).all()
    crawls = (await db.execute(select(CrawlJob).where(CrawlJob.company_id == c.id)
                               .order_by(CrawlJob.id.desc()).limit(20))).scalars().all()
    invoices = (await db.execute(select(FinanceInvoice).where(FinanceInvoice.company_id == c.id))).scalars().all()
    dupes = (await db.execute(select(DuplicateCandidate).where(
        DuplicateCandidate.entity_type == "company", DuplicateCandidate.status == "OPEN",
        (DuplicateCandidate.left_id == c.id) | (DuplicateCandidate.right_id == c.id)))).scalars().all()

    out = company_out(c, location=_location_out(primary), contact_count=len(contacts))
    out.update({
        "locations": [_location_out(loc) for loc in c.locations],
        "sources": [source_out(s) for s in sorted(c.sources, key=lambda s: s.retrieved_at, reverse=True)],
        "contacts": [{"id": ct.id, "full_name": ct.full_name, "original_title": ct.original_title,
                      "normalized_title": ct.normalized_title, "department": ct.department.value if ct.department else None,
                      "seniority": ct.seniority.value if ct.seniority else None, "status": ct.status.value,
                      "lead_score": s, "priority": p.value if p else None} for ct, s, p in contacts],
        "training_opportunities": [{"id": o.id, "program": name, "match_score": o.match_score, "reason": o.reason,
                                    "target_department": o.target_department,
                                    "recommended_decision_maker": o.recommended_decision_maker, "evidence": o.evidence,
                                    "method": o.method, "computed_at": iso(o.computed_at)} for o, name in opps],
        "signals": [signal_out(s) for s in signals],
        "activities": [activity_out(a, u) for a, u in acts],
        "notes": [note_out(n, u) for n, u in notes],
        "crawl_history": [{"id": j.id, "domain": j.domain, "status": j.status.value, "pages_fetched": j.pages_fetched,
                           "pages_skipped": j.pages_skipped, "robots_allowed": j.robots_allowed, "error": j.error,
                           "started_at": iso(j.started_at), "finished_at": iso(j.finished_at)} for j in crawls],
        "invoices": [{"invoice_number": i.invoice_number, "amount": num(i.amount), "contact_id": i.contact_id,
                      "created_at": iso(i.created_at)} for i in invoices],
        "possible_duplicates": [{"other_id": d.right_id if d.left_id == c.id else d.left_id,
                                 "similarity": d.similarity, "reasons": d.reasons} for d in dupes],
        "suppressed": await suppressed_reasons(db, company_id=c.id),
        "can_edit": user.can_edit(),
    })
    return out


@router.patch("/{company_id}")
async def update_company(company_id: int, body: CompanyPatch, request: Request,
                         user: CurrentUser = Depends(require_editor), db: AsyncSession = Depends(get_session)):
    c = await _get(db, company_id)
    data = body.model_dump(exclude_unset=True)
    source_url = data.pop("source_url", None)
    changed: dict[str, list] = {}
    if "website" in data:
        domain = domain_from_url(data["website"])
        if domain and domain != c.domain:
            clash = await db.scalar(select(Company.id).where(live_companies(), Company.domain == domain, Company.id != c.id))
            if clash:
                raise HTTPException(409, {"message": f"Another company already uses {domain}.", "existing_id": clash})
        changed["domain"] = [c.domain, domain]
        c.domain, c.domain_status, c.domain_confidence = domain, ("USER_PROVIDED" if domain else "UNRESOLVED"), None
    for f in COMPANY_FIELDS:
        if f in data:
            v = data[f]
            if f == "general_email" and v:
                v = str(v).lower()
            old = getattr(c, f)
            if old != v:
                changed[f] = [num(old) if isinstance(old, Decimal) else old, num(v) if isinstance(v, Decimal) else v]
                setattr(c, f, v)
                if f not in ("display_name", "deal_value"):
                    db.add(user_source(c.id, field=f, value=v, source_url=source_url))
    if "legal_name" in changed:
        c.normalized_name = normalize_company_name(c.legal_name)
    if "employee_estimate" in changed:
        c.employee_estimate_source = "User entered"
    if any(f in data for f in LOCATION_FIELDS):
        loc = (await db.execute(select(CompanyLocation).where(CompanyLocation.company_id == c.id,
                                                              CompanyLocation.is_primary.is_(True)))).scalar_one_or_none()
        if not loc:
            loc = CompanyLocation(company_id=c.id, is_primary=True, country="Malaysia")
            db.add(loc)
        for f in LOCATION_FIELDS:
            if f in data and getattr(loc, f) != data[f]:
                changed[f] = [getattr(loc, f), data[f]]
                setattr(loc, f, data[f] if f != "country" else (data[f] or "Malaysia"))
                db.add(user_source(c.id, field=f, value=data[f], source_url=source_url))
    if changed:
        c.updated_at = datetime.now(timezone.utc)
        log_activity(db, "updated", f"{', '.join(changed)} updated by {user.username}", company_id=c.id, user_id=user.id)
        audit(db, user.id, "company_updated", "company", c.id, {"changes": changed}, request)
    await db.commit()
    return await company_detail(c.id, user, db)


@router.delete("/{company_id}")
async def delete_company(company_id: int, request: Request, user: CurrentUser = Depends(require_editor),
                         db: AsyncSession = Depends(get_session)):
    c = await _get(db, company_id)
    now = datetime.now(timezone.utc)
    c.deleted_at = now
    await db.execute(text("UPDATE contacts SET deleted_at = :now WHERE company_id = :cid AND deleted_at IS NULL"),
                     {"now": now, "cid": c.id})
    audit(db, user.id, "company_deleted", "company", c.id, {"legal_name": c.legal_name}, request)
    await db.commit()
    return {"ok": True}
