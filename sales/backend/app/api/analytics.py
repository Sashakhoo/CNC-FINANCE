from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Date, cast, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, get_current_user
from app.core.config import get_settings
from app.core.db import get_session
from app.models import Company, CompanySource, Contact, ContactEmail, FinanceInvoice, Job, LeadScore, TrainingOpportunity, TrainingProgram
from app.models.base import PipelineStatus, VerificationStatus

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

ACTIVE_STAGES = [PipelineStatus.CONTACTED, PipelineStatus.REPLIED, PipelineStatus.MEETING, PipelineStatus.PROPOSAL]
FUNNEL = [PipelineStatus.REVIEW, PipelineStatus.APPROVED, PipelineStatus.CONTACTED, PipelineStatus.REPLIED,
          PipelineStatus.MEETING, PipelineStatus.PROPOSAL, PipelineStatus.WON]


def live_companies():
    return (Company.deleted_at.is_(None)) & (Company.is_demo == get_settings().demo_mode)


def live_contacts():
    return (Contact.deleted_at.is_(None)) & (Contact.is_demo == get_settings().demo_mode)


@router.get("/summary")
async def summary(days: int = Query(30, ge=7, le=366), _: CurrentUser = Depends(get_current_user),
                  db: AsyncSession = Depends(get_session)):
    scalar = lambda q: db.scalar(q)  # noqa: E731
    companies = await scalar(select(func.count()).select_from(Company).where(live_companies()))
    prospects = await scalar(select(func.count()).select_from(Contact).where(live_contacts()))
    by_status = dict((await db.execute(
        select(Contact.status, func.count()).where(live_contacts()).group_by(Contact.status))).all())
    verified = await scalar(
        select(func.count(distinct(ContactEmail.contact_id))).join(Contact, Contact.id == ContactEmail.contact_id)
        .where(live_contacts(), ContactEmail.verification_status == VerificationStatus.VERIFIED))
    quality = dict((await db.execute(
        select(LeadScore.priority, func.count()).join(Contact, Contact.id == LeadScore.contact_id)
        .where(live_contacts(), LeadScore.is_current.is_(True)).group_by(LeadScore.priority))).all())
    active_company_ids = select(Contact.company_id).where(live_contacts(), Contact.status.in_(ACTIVE_STAGES))
    pipeline = await scalar(select(func.coalesce(func.sum(Company.deal_value), 0))
                            .where(live_companies(), Company.id.in_(active_company_ids)))
    won_value = await scalar(select(func.coalesce(func.sum(FinanceInvoice.amount), 0))
                             .join(Company, Company.id == FinanceInvoice.company_id).where(live_companies()))

    since = datetime.now(timezone.utc) - timedelta(days=days)
    day = cast(Contact.created_at, Date)
    acquisition = [{"date": d.isoformat(), "leads": n} for d, n in (await db.execute(
        select(day, func.count()).where(live_contacts(), Contact.created_at >= since).group_by(day).order_by(day))).all()]

    demand = [{"program": name, "companies": n} for name, n in (await db.execute(
        select(TrainingProgram.name, func.count(distinct(TrainingOpportunity.company_id)))
        .join(TrainingOpportunity, TrainingOpportunity.program_id == TrainingProgram.id)
        .join(Company, Company.id == TrainingOpportunity.company_id)
        .where(live_companies(), TrainingOpportunity.is_current.is_(True), TrainingOpportunity.match_score >= 60)
        .group_by(TrainingProgram.name).order_by(func.count(distinct(TrainingOpportunity.company_id)).desc()))).all()]

    jobs = (await db.execute(select(Job).order_by(Job.created_at.desc()).limit(5))).scalars().all()

    return {
        "companies": companies, "prospects": prospects,
        "high_priority": quality.get("HIGH", 0), "verified_emails": verified,
        "meetings": by_status.get(PipelineStatus.MEETING, 0), "proposals": by_status.get(PipelineStatus.PROPOSAL, 0),
        "won": by_status.get(PipelineStatus.WON, 0),
        "pipeline_value": float(pipeline or 0), "won_value": float(won_value or 0),
        "funnel": [{"stage": s.value, "count": by_status.get(s, 0)} for s in FUNNEL],
        "quality": [{"name": p, "value": quality.get(p, 0)} for p in ("HIGH", "MEDIUM", "LOW")],
        "acquisition": acquisition, "training_demand": demand,
        "recent_jobs": [{"id": j.id, "name": j.name, "job_type": j.job_type, "status": j.status.value,
                         "progress": j.progress, "created_at": j.created_at} for j in jobs],
        "demo_mode": get_settings().demo_mode,
    }


# --- full analytics report (Analytics page) ---------------------------------------------

REACHED = [PipelineStatus.CONTACTED, PipelineStatus.REPLIED, PipelineStatus.MEETING, PipelineStatus.PROPOSAL,
           PipelineStatus.WON, PipelineStatus.LOST]
RESPONDED = [PipelineStatus.REPLIED, PipelineStatus.MEETING, PipelineStatus.PROPOSAL, PipelineStatus.WON]
MEETINGS = [PipelineStatus.MEETING, PipelineStatus.PROPOSAL, PipelineStatus.WON]
PROPOSALS = [PipelineStatus.PROPOSAL, PipelineStatus.WON]


def _rate(n: int, d: int) -> float | None:
    return round(n / d * 100, 1) if d else None


def _stage_cols():
    return (func.count().label("prospects"),
            func.count().filter(Contact.status.in_(REACHED)).label("reached"),
            func.count().filter(Contact.status.in_(RESPONDED)).label("responded"),
            func.count().filter(Contact.status.in_(MEETINGS)).label("meetings"),
            func.count().filter(Contact.status == PipelineStatus.WON).label("won"),
            func.avg(LeadScore.score).label("avg_lead"))


def _perf_rows(rows) -> list[dict]:
    return [{"name": str(getattr(r[0], "value", r[0]) or "Unknown"), "prospects": r.prospects, "reached": r.reached, "responded": r.responded,
             "meetings": r.meetings, "won": r.won, "response_rate": _rate(r.responded, r.reached),
             "avg_lead_score": round(float(r.avg_lead), 1) if r.avg_lead is not None else None} for r in rows]


@router.get("/report")
async def report(days: int = Query(180, ge=30, le=730), _: CurrentUser = Depends(get_current_user),
                 db: AsyncSession = Depends(get_session)):
    from app.api.outreach import _metrics
    from app.models import (Campaign, CompanyLocation, ContactConfidenceScore, ContactSource, ProviderUsage)
    from app.models.base import EmailDiscoveryMethod, Priority, SourceType

    since = datetime.now(timezone.utc) - timedelta(days=days)
    lead = select(LeadScore.contact_id, LeadScore.score, LeadScore.priority).where(LeadScore.is_current.is_(True)).subquery()

    week = func.date_trunc("week", Contact.created_at)
    growth = (await db.execute(
        select(week, func.count(), func.count().filter(lead.c.priority == Priority.HIGH),
               func.count().filter(lead.c.priority == Priority.MEDIUM))
        .outerjoin(lead, lead.c.contact_id == Contact.id)
        .where(live_contacts(), Contact.created_at >= since).group_by(week).order_by(week))).all()
    co_week = func.date_trunc("week", Company.created_at)
    co_growth = dict((await db.execute(select(co_week, func.count()).where(live_companies(), Company.created_at >= since)
                                       .group_by(co_week))).all())

    conf = select(ContactConfidenceScore.contact_id, ContactConfidenceScore.score).where(
        ContactConfidenceScore.is_current.is_(True)).subquery()
    bucket = func.least(func.floor(conf.c.score / 20), 4)
    dist = dict((await db.execute(select(bucket, func.count()).join(Contact, Contact.id == conf.c.contact_id)
                                  .where(live_contacts()).group_by(bucket))).all())

    totals = (await db.execute(select(func.count(), func.count().filter(Contact.status.in_(REACHED)),
                                      func.count().filter(Contact.status.in_(RESPONDED)),
                                      func.count().filter(Contact.status.in_(MEETINGS)),
                                      func.count().filter(Contact.status.in_(PROPOSALS)),
                                      func.count().filter(Contact.status == PipelineStatus.WON),
                                      func.count().filter(Contact.status == PipelineStatus.LOST))
                               .where(live_contacts()))).one()
    total, reached, responded, meetings, proposals, won, lost = totals
    qualified = dict((await db.execute(select(lead.c.priority, func.count()).join(Contact, Contact.id == lead.c.contact_id)
                                       .where(live_contacts()).group_by(lead.c.priority))).all())

    active_cos = select(Contact.company_id).where(live_contacts(), Contact.status.in_(ACTIVE_STAGES))
    pipeline = float(await db.scalar(select(func.coalesce(func.sum(Company.deal_value), 0))
                                     .where(live_companies(), Company.id.in_(active_cos))) or 0)
    revenue = float(await db.scalar(select(func.coalesce(func.sum(FinanceInvoice.amount), 0))
                                    .join(Company, Company.id == FinanceInvoice.company_id).where(live_companies())) or 0)

    industry = _perf_rows((await db.execute(
        select(Company.industry, *_stage_cols()).select_from(Contact).join(Company, Company.id == Contact.company_id)
        .outerjoin(LeadScore, (LeadScore.contact_id == Contact.id) & LeadScore.is_current.is_(True))
        .where(live_contacts(), live_companies()).group_by(Company.industry).order_by(func.count().desc()).limit(12))).all())
    loc = select(CompanyLocation.company_id, func.min(CompanyLocation.state).label("state")).where(
        CompanyLocation.is_primary.is_(True)).group_by(CompanyLocation.company_id).subquery()
    location = _perf_rows((await db.execute(
        select(loc.c.state, *_stage_cols()).select_from(Contact).join(Company, Company.id == Contact.company_id)
        .outerjoin(loc, loc.c.company_id == Company.id)
        .outerjoin(LeadScore, (LeadScore.contact_id == Contact.id) & LeadScore.is_current.is_(True))
        .where(live_contacts(), live_companies()).group_by(loc.c.state).order_by(func.count().desc()).limit(12))).all())
    role = _perf_rows((await db.execute(
        select(Contact.normalized_title, *_stage_cols()).select_from(Contact)
        .join(Company, Company.id == Contact.company_id)
        .outerjoin(LeadScore, (LeadScore.contact_id == Contact.id) & LeadScore.is_current.is_(True))
        .where(live_contacts(), live_companies()).group_by(Contact.normalized_title)
        .order_by(func.count().desc()).limit(12))).all())
    for r in role:
        if r["name"] == "Unknown":
            r["name"] = "Other titles"
    first_src = (select(ContactSource.contact_id, ContactSource.source_type).distinct(ContactSource.contact_id)
                 .order_by(ContactSource.contact_id, ContactSource.id).subquery())
    source = _perf_rows((await db.execute(
        select(first_src.c.source_type, *_stage_cols()).select_from(Contact).join(Company, Company.id == Contact.company_id)
        .outerjoin(first_src, first_src.c.contact_id == Contact.id)
        .outerjoin(LeadScore, (LeadScore.contact_id == Contact.id) & LeadScore.is_current.is_(True))
        .where(live_contacts(), live_companies()).group_by(first_src.c.source_type))).all())
    for r in source:
        r["name"] = r["name"].replace("_", " ").title()

    camps = (await db.execute(select(Campaign).where(Campaign.deleted_at.is_(None)).order_by(Campaign.created_at.desc()).limit(20))).scalars().all()
    cm = await _metrics(db, [c.id for c in camps])
    campaigns = [{"id": c.id, "name": c.name, "status": c.status, **cm[c.id]} for c in camps]

    usage = {r[0]: {"calls": r[1], "success_rate": _rate(r[2], r[1]), "avg_ms": round(float(r[3])) if r[3] else None}
             for r in (await db.execute(select(ProviderUsage.provider, func.count(), func.count().filter(ProviderUsage.success.is_(True)),
                                               func.avg(ProviderUsage.duration_ms)).where(ProviderUsage.created_at >= since)
                                        .group_by(ProviderUsage.provider))).all()}
    found_cos = dict((await db.execute(select(CompanySource.provider, func.count(distinct(CompanySource.company_id)))
                                       .where(CompanySource.source_type == SourceType.SEARCH_PROVIDER, CompanySource.field_name == "legal_name")
                                       .group_by(CompanySource.provider))).all())
    found_emails = dict((await db.execute(select(ContactEmail.source, func.count()).where(
        ContactEmail.discovery_method == EmailDiscoveryMethod.PROVIDER).group_by(ContactEmail.source))).all())
    verified = {}
    for prov, status, n in (await db.execute(select(ContactEmail.verification_provider, ContactEmail.verification_status, func.count())
                                             .where(ContactEmail.verification_provider.is_not(None))
                                             .group_by(ContactEmail.verification_provider, ContactEmail.verification_status))).all():
        verified.setdefault(prov, {})[status.value] = n
    providers = []
    for name in sorted(set(usage) | set(found_cos) | set(found_emails) | set(verified)):
        if not name:
            continue
        providers.append({"provider": name, **usage.get(name, {"calls": 0, "success_rate": None, "avg_ms": None}),
                          "companies_found": found_cos.get(name, 0), "emails_found": found_emails.get(name, 0),
                          "verification_results": verified.get(name, {})})

    return {
        "days": days,
        "lead_growth": [{"week": w.date().isoformat(), "leads": n, "high": h, "medium": m, "companies": co_growth.get(w, 0)} for w, n, h, m in growth],
        "confidence_distribution": [{"range": f"{i * 20}–{i * 20 + 19 if i < 4 else 100}", "contacts": dist.get(i, 0)} for i in range(5)],
        "qualified": {p.value: qualified.get(p, 0) for p in Priority},
        "funnel": {"prospects": total, "reached": reached, "responded": responded, "meetings": meetings, "proposals": proposals, "won": won, "lost": lost},
        "rates": {"response": _rate(responded, reached), "meeting": _rate(meetings, reached), "proposal": _rate(proposals, reached),
                  "win": _rate(won, won + lost)},
        "pipeline_value": pipeline, "revenue_won": revenue,
        "industry": industry, "location": location, "role": role, "lead_source": source, "campaigns": campaigns, "providers": providers,
        "rates_basis": "Based on each contact's current pipeline stage.",
    }
