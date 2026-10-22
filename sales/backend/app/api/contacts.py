from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import exists, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.analytics import live_companies, live_contacts
from app.api.common import activity_out, email_out, iso, note_out, num, paging, profile_out, source_out
from app.core.auth import CurrentUser, get_current_user, require_editor
from app.core.config import get_settings
from app.core.db import get_session
from app.models import (Activity, CampaignContact, Company, CompanyLocation, Contact, ContactConfidenceScore, ContactEmail,
                        ContactProfile, ContactSource, FinanceInvoice, LeadScore, Note, Suppression,
                        TrainingOpportunity, TrainingProgram, User)
from app.models.base import (Department, EmailDiscoveryMethod, EmailType, PipelineStatus, Priority, Provenance,
                             Seniority, SourceType, VerificationStatus)
from app.services.audit import audit
from app.services.crm import log_activity, suppress, suppressed_reasons, unsuppress, user_source
from app.services.finance import InvoiceError, raise_won_invoice
from app.services.normalize import normalize_person_name, normalize_website, profile_platform, split_name
from app.services.scores import rescore_contact
from app.services.titles import normalize_title

router = APIRouter(prefix="/api", tags=["contacts"])

ROLE_LOCALPARTS = {"info", "sales", "admin", "hr", "careers", "career", "jobs", "enquiry", "enquiries", "contact",
                   "support", "marketing", "office", "hello", "general", "recruitment", "account", "accounts", "finance"}
TOUCHED = {PipelineStatus.CONTACTED, PipelineStatus.REPLIED, PipelineStatus.MEETING, PipelineStatus.PROPOSAL}
STATUS_LABEL = {"APPROVED": "Approved", "REJECTED": "Rejected", "DO_NOT_CONTACT": "Marked Do Not Contact"}


async def _rescore(db: AsyncSession, contact_id: int) -> None:
    await rescore_contact(db, contact_id)
    await db.commit()


def _email_type(email: str) -> EmailType:
    return EmailType.ROLE if email.split("@", 1)[0].lower() in ROLE_LOCALPARTS else EmailType.PERSONAL_BUSINESS


# --- prospects list ------------------------------------------------------

def _prospect_query():
    best_email = (select(ContactEmail.email, ContactEmail.verification_status, ContactEmail.provenance)
                  .where(ContactEmail.contact_id == Contact.id)
                  .order_by((ContactEmail.verification_status == VerificationStatus.VERIFIED).desc(),
                            ContactEmail.is_primary.desc(), ContactEmail.confidence.desc().nulls_last(), ContactEmail.id)
                  .limit(1).correlate(Contact).lateral())
    lead = (select(LeadScore.score, LeadScore.priority).where(LeadScore.contact_id == Contact.id, LeadScore.is_current.is_(True))
            .limit(1).correlate(Contact).lateral())
    conf = (select(ContactConfidenceScore.score).where(ContactConfidenceScore.contact_id == Contact.id,
                                                       ContactConfidenceScore.is_current.is_(True))
            .limit(1).correlate(Contact).lateral())
    opp = (select(TrainingProgram.name.label("program"), TrainingOpportunity.match_score)
           .join(TrainingProgram, TrainingProgram.id == TrainingOpportunity.program_id)
           .where(TrainingOpportunity.company_id == Contact.company_id, TrainingOpportunity.is_current.is_(True))
           .order_by(TrainingOpportunity.match_score.desc()).limit(1).correlate(Contact).lateral())
    profile = (select(ContactProfile.url).where(ContactProfile.contact_id == Contact.id).order_by(ContactProfile.id)
               .limit(1).correlate(Contact).lateral())
    loc = (select(CompanyLocation.city, CompanyLocation.state).where(CompanyLocation.company_id == Contact.company_id)
           .order_by(CompanyLocation.is_primary.desc(), CompanyLocation.id).limit(1).correlate(Contact).lateral())
    nsources = (select(func.count()).select_from(ContactSource).where(ContactSource.contact_id == Contact.id)
                .correlate(Contact).scalar_subquery())
    dnc = exists().where(Suppression.kind == "CONTACT", Suppression.value == func.cast(Contact.id, Suppression.value.type))
    q = (select(Contact, Company, best_email.c.email, best_email.c.verification_status, best_email.c.provenance,
                lead.c.score, lead.c.priority, conf.c.score.label("confidence"), opp.c.program, opp.c.match_score,
                profile.c.url, loc.c.city, loc.c.state, nsources.label("sources"), dnc.label("suppressed"))
         .join(Company, Company.id == Contact.company_id)
         .outerjoin(best_email, literal(True)).outerjoin(lead, literal(True)).outerjoin(conf, literal(True))
         .outerjoin(opp, literal(True)).outerjoin(profile, literal(True)).outerjoin(loc, literal(True))
         .where(live_contacts(), live_companies()))
    return q, {"email_status": best_email.c.verification_status, "lead_score": lead.c.score, "priority": lead.c.priority,
               "confidence": conf.c.score, "program": opp.c.program, "match": opp.c.match_score, "state": loc.c.state,
               "city": loc.c.city}


def _prospect_out(row) -> dict:
    (c, co, email, email_status, email_prov, score, priority, confidence, program, match, profile, city, state,
     sources, suppressed) = row
    return {"id": c.id, "full_name": c.full_name, "original_title": c.original_title,
            "normalized_title": c.normalized_title, "department": c.department.value if c.department else None,
            "seniority": c.seniority.value if c.seniority else None, "status": c.status.value,
            "status_changed_at": iso(c.status_changed_at), "last_contacted_at": iso(c.last_contacted_at),
            "follow_up_at": iso(c.follow_up_at), "created_at": iso(c.created_at),
            "company": {"id": co.id, "legal_name": co.legal_name, "display_name": co.display_name, "industry": co.industry,
                        "employee_estimate": co.employee_estimate, "domain": co.domain, "deal_value": num(co.deal_value)},
            "location": {"city": city, "state": state} if (city or state) else None,
            "email": email, "email_status": email_status.value if email_status else None,
            "email_provenance": email_prov.value if email_prov else None, "profile_url": profile,
            "lead_score": score, "priority": priority.value if priority else None, "contact_confidence": confidence,
            "training_program": program, "match_score": match, "source_count": sources, "suppressed": bool(suppressed)}


SORTS = {"lead_score", "confidence", "match", "name", "company", "status", "created_at", "last_contacted_at", "follow_up_at"}


@router.get("/prospects")
async def list_prospects(
        q: str | None = Query(None, max_length=200), status: list[PipelineStatus] = Query(default=[]),
        department: list[Department] = Query(default=[]), seniority: list[Seniority] = Query(default=[]),
        industry: list[str] = Query(default=[]), state: list[str] = Query(default=[]),
        email_status: list[VerificationStatus] = Query(default=[]), priority: list[Priority] = Query(default=[]),
        program: list[str] = Query(default=[]), min_lead_score: int | None = Query(None, ge=0, le=100),
        min_confidence: int | None = Query(None, ge=0, le=100), min_match: int | None = Query(None, ge=0, le=100),
        size_min: int | None = Query(None, ge=0), size_max: int | None = Query(None, ge=0),
        source_type: list[SourceType] = Query(default=[]), company_id: int | None = None, campaign_id: int | None = None,
        has_email: bool | None = None, hide_suppressed: bool = False,
        sort: str = "lead_score", desc: bool = True, pg: tuple[int, int] = Depends(paging),
        _: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    page, size = pg
    if sort not in SORTS:
        raise HTTPException(422, f"sort must be one of {sorted(SORTS)}")
    base, cols = _prospect_query()
    if q:
        like = f"%{q.strip()}%"
        base = base.where(Contact.full_name.ilike(like) | Company.legal_name.ilike(like) | Contact.original_title.ilike(like))
    if status:
        base = base.where(Contact.status.in_(status))
    if department:
        base = base.where(Contact.department.in_(department))
    if seniority:
        base = base.where(Contact.seniority.in_(seniority))
    if industry:
        base = base.where(Company.industry.in_(industry))
    if state:
        base = base.where(cols["state"].in_(state))
    if email_status:
        base = base.where(cols["email_status"].in_(email_status))
    if has_email is not None:
        base = base.where(cols["email_status"].is_not(None) if has_email else cols["email_status"].is_(None))
    if priority:
        base = base.where(cols["priority"].in_(priority))
    if program:
        base = base.where(cols["program"].in_(program))
    if min_lead_score is not None:
        base = base.where(cols["lead_score"] >= min_lead_score)
    if min_confidence is not None:
        base = base.where(cols["confidence"] >= min_confidence)
    if min_match is not None:
        base = base.where(cols["match"] >= min_match)
    if size_min is not None:
        base = base.where(Company.employee_estimate >= size_min)
    if size_max is not None:
        base = base.where(Company.employee_estimate <= size_max)
    if source_type:
        base = base.where(exists().where(ContactSource.contact_id == Contact.id, ContactSource.source_type.in_(source_type)))
    if company_id is not None:
        base = base.where(Contact.company_id == company_id)
    if campaign_id is not None:
        base = base.where(exists().where(CampaignContact.campaign_id == campaign_id, CampaignContact.contact_id == Contact.id))
    if hide_suppressed:
        base = base.where(~exists().where(Suppression.kind == "CONTACT",
                                          Suppression.value == func.cast(Contact.id, Suppression.value.type)))
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    order = {"lead_score": cols["lead_score"], "confidence": cols["confidence"], "match": cols["match"],
             "name": Contact.full_name, "company": Company.legal_name, "status": Contact.status,
             "created_at": Contact.created_at, "last_contacted_at": Contact.last_contacted_at,
             "follow_up_at": Contact.follow_up_at}[sort]
    rows = (await db.execute(base.order_by(order.desc().nulls_last() if desc else order.asc().nulls_last(), Contact.id)
                             .offset((page - 1) * size).limit(size))).all()
    return {"items": [_prospect_out(r) for r in rows], "total": total, "page": page, "page_size": size}


# --- contact CRUD ----------------------------------------------------------

class ContactIn(BaseModel):
    company_id: int
    full_name: str = Field(min_length=2, max_length=200)
    original_title: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=60)
    email: EmailStr | None = None
    profile_url: str | None = Field(default=None, max_length=1000)
    source_url: str | None = Field(default=None, max_length=1000)

    @field_validator("profile_url", "source_url")
    @classmethod
    def _url(cls, v):
        return normalize_website(v) if v else None


class ContactPatch(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    original_title: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=60)
    follow_up_at: datetime | None = None
    source_url: str | None = Field(default=None, max_length=1000)


async def _get(db: AsyncSession, contact_id: int) -> Contact:
    c = await db.get(Contact, contact_id)
    if not c or c.deleted_at or c.is_demo != get_settings().demo_mode:
        raise HTTPException(404, "Contact not found")
    return c


def _apply_title(c: Contact, title: str | None) -> None:
    c.original_title = title
    nt = normalize_title(title)
    c.normalized_title, c.department, c.seniority = nt.normalized_title, nt.department, nt.seniority


async def _add_email(db: AsyncSession, c: Contact, email: str, source_url: str | None) -> ContactEmail:
    email = email.lower()
    if await db.scalar(select(ContactEmail.id).where(ContactEmail.contact_id == c.id, ContactEmail.email == email)):
        raise HTTPException(409, "This email is already on the contact")
    has_primary = await db.scalar(select(exists().where(ContactEmail.contact_id == c.id, ContactEmail.is_primary.is_(True))))
    e = ContactEmail(contact_id=c.id, email=email, email_type=_email_type(email),
                     discovery_method=EmailDiscoveryMethod.USER_ENTRY, provenance=Provenance.USER_PROVIDED,
                     source="User entered", source_url=source_url, verification_status=VerificationStatus.UNVERIFIED,
                     is_primary=not has_primary)
    db.add(e)
    return e


@router.post("/contacts", status_code=201)
async def create_contact(body: ContactIn, request: Request, user: CurrentUser = Depends(require_editor),
                         db: AsyncSession = Depends(get_session)):
    company = await db.get(Company, body.company_id)
    if not company or company.deleted_at or company.is_demo != get_settings().demo_mode:
        raise HTTPException(404, "Company not found")
    normalized = normalize_person_name(body.full_name)
    if not normalized:
        raise HTTPException(422, "Name has no usable characters")
    similar = (await db.execute(
        select(Contact.id, Contact.full_name, func.similarity(Contact.normalized_name, normalized))
        .where(live_contacts(), Contact.company_id == company.id, func.similarity(Contact.normalized_name, normalized) >= 0.5)
        .order_by(func.similarity(Contact.normalized_name, normalized).desc()).limit(5))).all()
    first, last = split_name(body.full_name)
    c = Contact(company_id=company.id, full_name=body.full_name.strip(), normalized_name=normalized, first_name=first,
                last_name=last, phone=body.phone, status=PipelineStatus.REVIEW, owner_id=user.id,
                is_demo=get_settings().demo_mode)
    _apply_title(c, body.original_title)
    db.add(c)
    await db.flush()
    db.add(user_source(contact_id=c.id, field="full_name", value=c.full_name, source_url=body.source_url))
    if body.original_title:
        db.add(user_source(contact_id=c.id, field="title", value=body.original_title, source_url=body.source_url))
    if body.email:
        await _add_email(db, c, str(body.email), body.source_url)
    if body.profile_url:
        db.add(ContactProfile(contact_id=c.id, platform=profile_platform(body.profile_url), url=body.profile_url,
                              source_type=SourceType.USER_ENTRY, source_url=body.source_url))
    log_activity(db, "discovered", f"Added manually by {user.username}", contact_id=c.id, company_id=company.id,
                 user_id=user.id)
    audit(db, user.id, "contact_created", "contact", c.id, {"company_id": company.id}, request)
    await db.commit()
    await _rescore(db, c.id)
    out = await contact_detail(c.id, user, db)
    out["possible_duplicates"] = [{"id": i, "full_name": n, "similarity": round(float(s), 2)} for i, n, s in similar]
    return out


@router.get("/contacts/{contact_id}")
async def get_contact(contact_id: int, user: CurrentUser = Depends(get_current_user),
                      db: AsyncSession = Depends(get_session)):
    return await contact_detail(contact_id, user, db)


async def contact_detail(contact_id: int, user: CurrentUser, db: AsyncSession) -> dict:
    c = (await db.execute(select(Contact).options(selectinload(Contact.emails), selectinload(Contact.profiles),
                                                  selectinload(Contact.sources)).where(Contact.id == contact_id))).scalar_one_or_none()
    if not c or c.deleted_at or c.is_demo != get_settings().demo_mode:
        raise HTTPException(404, "Contact not found")
    co = await db.get(Company, c.company_id)
    lead = (await db.execute(select(LeadScore).where(LeadScore.contact_id == c.id, LeadScore.is_current.is_(True)))).scalar_one_or_none()
    conf = (await db.execute(select(ContactConfidenceScore).where(ContactConfidenceScore.contact_id == c.id,
                                                                  ContactConfidenceScore.is_current.is_(True)))).scalar_one_or_none()
    opps = (await db.execute(
        select(TrainingOpportunity, TrainingProgram.name).join(TrainingProgram, TrainingProgram.id == TrainingOpportunity.program_id)
        .where(TrainingOpportunity.company_id == c.company_id, TrainingOpportunity.is_current.is_(True))
        .order_by(TrainingOpportunity.match_score.desc()))).all()
    acts = (await db.execute(select(Activity, User.finance_username).outerjoin(User, User.id == Activity.user_id)
                             .where(Activity.contact_id == c.id).order_by(Activity.created_at.desc()).limit(200))).all()
    notes = (await db.execute(select(Note, User.finance_username).outerjoin(User, User.id == Note.user_id)
                              .where(Note.contact_id == c.id, Note.deleted_at.is_(None)).order_by(Note.created_at.desc()))).all()
    invoice = (await db.execute(select(FinanceInvoice).where(FinanceInvoice.company_id == c.company_id))).scalar_one_or_none()
    loc = (await db.execute(select(CompanyLocation).where(CompanyLocation.company_id == c.company_id)
                            .order_by(CompanyLocation.is_primary.desc()).limit(1))).scalar_one_or_none()
    return {
        "id": c.id, "full_name": c.full_name, "first_name": c.first_name, "last_name": c.last_name,
        "original_title": c.original_title, "normalized_title": c.normalized_title,
        "department": c.department.value if c.department else None, "seniority": c.seniority.value if c.seniority else None,
        "phone": c.phone, "status": c.status.value, "status_changed_at": iso(c.status_changed_at),
        "last_contacted_at": iso(c.last_contacted_at), "follow_up_at": iso(c.follow_up_at),
        "created_at": iso(c.created_at), "updated_at": iso(c.updated_at),
        "company": {"id": co.id, "legal_name": co.legal_name, "display_name": co.display_name, "industry": co.industry,
                    "domain": co.domain, "website": co.website, "deal_value": num(co.deal_value),
                    "location": {"city": loc.city, "state": loc.state} if loc else None},
        "emails": [email_out(e) for e in sorted(c.emails, key=lambda e: (not e.is_primary, e.id))],
        "profiles": [profile_out(p) for p in c.profiles],
        "sources": [source_out(s) for s in sorted(c.sources, key=lambda s: s.retrieved_at, reverse=True)],
        "lead_score": {"score": lead.score, "priority": lead.priority.value, "breakdown": lead.breakdown,
                       "computed_at": iso(lead.computed_at)} if lead else None,
        "contact_confidence": {"score": conf.score, "breakdown": conf.breakdown,
                               "computed_at": iso(conf.computed_at)} if conf else None,
        "training_opportunities": [{"id": o.id, "program": n, "match_score": o.match_score, "reason": o.reason,
                                    "evidence": o.evidence, "recommended_decision_maker": o.recommended_decision_maker,
                                    "method": o.method} for o, n in opps],
        "activities": [activity_out(a, u) for a, u in acts],
        "notes": [note_out(n, u) for n, u in notes],
        "invoice": {"invoice_number": invoice.invoice_number, "amount": num(invoice.amount),
                    "created_at": iso(invoice.created_at)} if invoice else None,
        "suppressed": await suppressed_reasons(db, contact_id=c.id, company_id=c.company_id,
                                               emails=[e.email for e in c.emails]),
        "can_edit": user.can_edit(),
    }


@router.patch("/contacts/{contact_id}")
async def update_contact(contact_id: int, body: ContactPatch, request: Request,
                         user: CurrentUser = Depends(require_editor), db: AsyncSession = Depends(get_session)):
    c = await _get(db, contact_id)
    data = body.model_dump(exclude_unset=True)
    source_url = normalize_website(data.pop("source_url")) if data.get("source_url") else None
    changed = {}
    if "full_name" in data and data["full_name"] != c.full_name:
        changed["full_name"] = [c.full_name, data["full_name"]]
        c.full_name = data["full_name"].strip()
        c.normalized_name = normalize_person_name(c.full_name)
        c.first_name, c.last_name = split_name(c.full_name)
        db.add(user_source(contact_id=c.id, field="full_name", value=c.full_name, source_url=source_url))
    if "original_title" in data and data["original_title"] != c.original_title:
        changed["title"] = [c.original_title, data["original_title"]]
        _apply_title(c, data["original_title"])
        db.add(user_source(contact_id=c.id, field="title", value=data["original_title"], source_url=source_url))
    if "phone" in data and data["phone"] != c.phone:
        changed["phone"] = [c.phone, data["phone"]]
        c.phone = data["phone"]
    if "follow_up_at" in data:
        changed["follow_up_at"] = [iso(c.follow_up_at), iso(data["follow_up_at"])]
        c.follow_up_at = data["follow_up_at"]
        if data["follow_up_at"]:
            log_activity(db, "activity", f"Follow-up scheduled for {data['follow_up_at']:%d %b %Y}", contact_id=c.id,
                         company_id=c.company_id, user_id=user.id)
    if changed:
        audit(db, user.id, "contact_updated", "contact", c.id, {"changes": changed}, request)
    await db.commit()
    await _rescore(db, c.id)
    return await contact_detail(c.id, user, db)


@router.delete("/contacts/{contact_id}")
async def delete_contact(contact_id: int, request: Request, user: CurrentUser = Depends(require_editor),
                         db: AsyncSession = Depends(get_session)):
    c = await _get(db, contact_id)
    c.deleted_at = datetime.now(timezone.utc)
    audit(db, user.id, "contact_deleted", "contact", c.id, {"full_name": c.full_name}, request)
    await db.commit()
    return {"ok": True}


# --- pipeline -----------------------------------------------------------

class StatusIn(BaseModel):
    status: PipelineStatus
    note: str | None = Field(default=None, max_length=2000)


async def _set_status(db: AsyncSession, c: Contact, status: PipelineStatus, user: CurrentUser, note: str | None,
                      request: Request) -> None:
    old = c.status
    if old == status:
        return
    if old == PipelineStatus.DO_NOT_CONTACT and user.role.value != "ADMIN":
        raise HTTPException(403, "Only an admin can take a contact off Do Not Contact")
    now = datetime.now(timezone.utc)
    c.status, c.status_changed_at = status, now
    if status in TOUCHED or status == PipelineStatus.WON:
        c.last_contacted_at = now
    emails = (await db.execute(select(ContactEmail.email).where(ContactEmail.contact_id == c.id))).scalars().all()
    if status == PipelineStatus.DO_NOT_CONTACT:
        await suppress(db, "CONTACT", str(c.id), note or "Marked Do Not Contact", user.id)
        for e in emails:
            await suppress(db, "EMAIL", e, note or f"Contact {c.id} marked Do Not Contact", user.id)
    elif old == PipelineStatus.DO_NOT_CONTACT:
        await unsuppress(db, "CONTACT", [str(c.id)])
        await unsuppress(db, "EMAIL", [e.lower() for e in emails])
    text = STATUS_LABEL.get(status.value, f"Status changed to {status.value}") + (f" — {note}" if note else "")
    log_activity(db, "status", text, contact_id=c.id, company_id=c.company_id, user_id=user.id,
                 meta={"from": old.value, "to": status.value})
    audit(db, user.id, "status_changed", "contact", c.id, {"from": old.value, "to": status.value}, request)


async def _invoice_for(db: AsyncSession, c: Contact, user: CurrentUser) -> dict:
    company = await db.get(Company, c.company_id)
    try:
        inv = await raise_won_invoice(db, c, company, user.username)
    except InvoiceError as e:
        log_activity(db, "status", f"Invoice not raised in Finance: {e}", contact_id=c.id, company_id=c.company_id,
                     user_id=user.id)
        await db.commit()
        return {"invoice": None, "invoice_error": str(e)}
    log_activity(db, "status", f"Invoice {inv.invoice_number} (RM {inv.amount:,.2f}) raised in Finance",
                 contact_id=c.id, company_id=c.company_id, user_id=user.id, meta={"invoice": inv.invoice_number})
    await db.commit()
    return {"invoice": {"invoice_number": inv.invoice_number, "amount": num(inv.amount)}, "invoice_error": None}


@router.post("/contacts/{contact_id}/status")
async def change_status(contact_id: int, body: StatusIn, request: Request, user: CurrentUser = Depends(require_editor),
                        db: AsyncSession = Depends(get_session)):
    c = await _get(db, contact_id)
    if body.status == PipelineStatus.WON:
        company = await db.get(Company, c.company_id)
        if not company.deal_value or company.deal_value <= 0:
            raise HTTPException(422, "Set a deal value on the company before marking the deal WON.")
    await _set_status(db, c, body.status, user, body.note, request)
    await db.commit()
    await _rescore(db, c.id)
    result = {"invoice": None, "invoice_error": None}
    if body.status == PipelineStatus.WON:
        result = await _invoice_for(db, c, user)
    return {**await contact_detail(c.id, user, db), **result}


@router.post("/contacts/{contact_id}/raise-invoice")
async def retry_invoice(contact_id: int, user: CurrentUser = Depends(require_editor), db: AsyncSession = Depends(get_session)):
    c = await _get(db, contact_id)
    if c.status != PipelineStatus.WON:
        raise HTTPException(409, "Only a WON deal can be invoiced")
    return await _invoice_for(db, c, user)


class BulkStatusIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)
    status: PipelineStatus
    note: str | None = Field(default=None, max_length=2000)


@router.post("/contacts/bulk-status")
async def bulk_status(body: BulkStatusIn, request: Request, user: CurrentUser = Depends(require_editor),
                      db: AsyncSession = Depends(get_session)):
    if body.status == PipelineStatus.WON:
        raise HTTPException(422, "Mark deals WON one at a time — each raises an invoice in Finance.")
    rows = (await db.execute(select(Contact).where(Contact.id.in_(body.ids), live_contacts()))).scalars().all()
    changed, skipped = 0, []
    for c in rows:
        try:
            before = c.status
            await _set_status(db, c, body.status, user, body.note, request)
            changed += c.status != before
        except HTTPException as e:
            skipped.append({"id": c.id, "reason": e.detail})
    await db.commit()
    return {"changed": changed, "skipped": skipped, "not_found": sorted(set(body.ids) - {c.id for c in rows})}


# --- emails & profiles ----------------------------------------------------

class EmailIn(BaseModel):
    email: EmailStr
    source_url: str | None = Field(default=None, max_length=1000)


@router.post("/contacts/{contact_id}/emails", status_code=201)
async def add_email(contact_id: int, body: EmailIn, request: Request, user: CurrentUser = Depends(require_editor),
                    db: AsyncSession = Depends(get_session)):
    c = await _get(db, contact_id)
    e = await _add_email(db, c, str(body.email), normalize_website(body.source_url) if body.source_url else None)
    if c.status == PipelineStatus.DO_NOT_CONTACT:
        await suppress(db, "EMAIL", e.email, f"Contact {c.id} is Do Not Contact", user.id)
    log_activity(db, "activity", f"Email {e.email} added (unverified)", contact_id=c.id, company_id=c.company_id, user_id=user.id)
    audit(db, user.id, "email_added", "contact", c.id, {"email": e.email}, request)
    await db.commit()
    await _rescore(db, c.id)
    return await contact_detail(c.id, user, db)


@router.post("/contacts/{contact_id}/emails/{email_id}/primary")
async def make_primary(contact_id: int, email_id: int, user: CurrentUser = Depends(require_editor),
                       db: AsyncSession = Depends(get_session)):
    c = await _get(db, contact_id)
    emails = (await db.execute(select(ContactEmail).where(ContactEmail.contact_id == c.id))).scalars().all()
    if email_id not in {e.id for e in emails}:
        raise HTTPException(404, "Email not found")
    for e in emails:
        e.is_primary = e.id == email_id
    await db.commit()
    await _rescore(db, c.id)
    return await contact_detail(c.id, user, db)


@router.delete("/contacts/{contact_id}/emails/{email_id}")
async def remove_email(contact_id: int, email_id: int, request: Request, user: CurrentUser = Depends(require_editor),
                       db: AsyncSession = Depends(get_session)):
    c = await _get(db, contact_id)
    e = await db.get(ContactEmail, email_id)
    if not e or e.contact_id != c.id:
        raise HTTPException(404, "Email not found")
    await db.delete(e)
    audit(db, user.id, "email_removed", "contact", c.id, {"email": e.email}, request)
    await db.commit()
    await _rescore(db, c.id)
    return await contact_detail(c.id, user, db)


class ProfileIn(BaseModel):
    url: str = Field(min_length=8, max_length=1000)
    source_url: str | None = Field(default=None, max_length=1000)

    @field_validator("url", "source_url")
    @classmethod
    def _url(cls, v):
        return normalize_website(v) if v else None


@router.post("/contacts/{contact_id}/profiles", status_code=201)
async def add_profile(contact_id: int, body: ProfileIn, user: CurrentUser = Depends(require_editor),
                      db: AsyncSession = Depends(get_session)):
    c = await _get(db, contact_id)
    if await db.scalar(select(ContactProfile.id).where(ContactProfile.contact_id == c.id, ContactProfile.url == body.url)):
        raise HTTPException(409, "This profile is already on the contact")
    db.add(ContactProfile(contact_id=c.id, platform=profile_platform(body.url), url=body.url,
                          source_type=SourceType.USER_ENTRY, source_url=body.source_url))
    await db.commit()
    await _rescore(db, c.id)
    return await contact_detail(c.id, user, db)


@router.delete("/contacts/{contact_id}/profiles/{profile_id}")
async def remove_profile(contact_id: int, profile_id: int, user: CurrentUser = Depends(require_editor),
                         db: AsyncSession = Depends(get_session)):
    c = await _get(db, contact_id)
    p = await db.get(ContactProfile, profile_id)
    if not p or p.contact_id != c.id:
        raise HTTPException(404, "Profile not found")
    await db.delete(p)
    await db.commit()
    await _rescore(db, c.id)
    return await contact_detail(c.id, user, db)
