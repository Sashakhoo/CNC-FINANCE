"""Recompute Contact Confidence and Lead Score for contacts from stored evidence."""
import logging

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (Company, CompanyLocation, CompanySignal, Contact, ContactConfidenceScore, ContactEmail,
                        ContactProfile, ContactSource, LeadScore, Setting, TrainingOpportunity)
from app.models.base import Priority, Provenance, SourceType, VerificationStatus
from app.services import scoring
from app.services.defaults import CONTACT_CONFIDENCE, LEAD_SCORING
from app.services.normalize import email_domain

log = logging.getLogger("app.scores")

CONFIRMING_SOURCES = {SourceType.COMPANY_WEBSITE, SourceType.SEARCH_PROVIDER, SourceType.BUSINESS_DATA_PROVIDER,
                      SourceType.EMAIL_PROVIDER, SourceType.DIRECTORY}
EMAIL_RANK = {VerificationStatus.VERIFIED: 5, VerificationStatus.LIKELY: 4, VerificationStatus.UNVERIFIED: 3,
              VerificationStatus.UNKNOWN: 2, VerificationStatus.RISKY: 1, VerificationStatus.INVALID: 0}


async def load_weights(db: AsyncSession) -> tuple[dict, dict]:
    rows = {s.key: s.value for s in (await db.execute(select(Setting).where(
        Setting.key.in_(["lead_scoring", "contact_confidence"])))).scalars()}
    lead, conf = rows.get("lead_scoring") or LEAD_SCORING, rows.get("contact_confidence") or CONTACT_CONFIDENCE
    try:
        scoring.validate_lead_weights(lead)
    except Exception:
        log.warning("invalid lead_scoring settings; using defaults")
        lead = LEAD_SCORING
    try:
        scoring.validate_confidence_weights(conf)
    except Exception:
        log.warning("invalid contact_confidence settings; using defaults")
        conf = CONTACT_CONFIDENCE
    return lead, conf


async def rescore_contact(db: AsyncSession, contact_id: int, weights: tuple[dict, dict] | None = None) -> tuple[int, Priority] | None:
    c = await db.get(Contact, contact_id)
    if not c or c.deleted_at:
        return None
    company = await db.get(Company, c.company_id)
    lead_w, conf_w = weights or await load_weights(db)

    sources = (await db.execute(select(ContactSource).where(ContactSource.contact_id == c.id))).scalars().all()
    emails = (await db.execute(select(ContactEmail).where(ContactEmail.contact_id == c.id))).scalars().all()
    profiles = (await db.execute(select(ContactProfile).where(ContactProfile.contact_id == c.id))).scalars().all()

    on_site = any(s.field_name == "full_name" and s.source_type == SourceType.COMPANY_WEBSITE for s in sources)
    title_ok = any(s.field_name == "title" and s.source_type in CONFIRMING_SOURCES for s in sources)
    profile_ok = any(p.source_type == SourceType.COMPANY_WEBSITE or (p.confidence or 0) >= 0.7 for p in profiles)
    best = max(emails, key=lambda e: (EMAIL_RANK[e.verification_status], e.provenance != Provenance.INFERRED), default=None)
    domain_email = bool(company.domain) and any(
        email_domain(e.email) == company.domain and e.provenance != Provenance.INFERRED
        and e.verification_status in (VerificationStatus.VERIFIED, VerificationStatus.LIKELY, VerificationStatus.UNVERIFIED)
        for e in emails)
    company_ok = on_site or domain_email or any(s.field_name == "company" and s.source_type in CONFIRMING_SOURCES for s in sources)

    conf = scoring.contact_confidence(scoring.ContactEvidence(
        name_on_company_site=on_site, title_confirmed=title_ok, company_confirmed=company_ok, profile_matched=profile_ok,
        best_email_status=best.verification_status if best else None, best_email_provenance=best.provenance if best else None,
    ), conf_w)

    loc = (await db.execute(select(CompanyLocation).where(CompanyLocation.company_id == company.id)
                            .order_by(CompanyLocation.is_primary.desc()).limit(1))).scalar_one_or_none()
    best_match = await db.scalar(select(func.max(TrainingOpportunity.match_score)).where(
        TrainingOpportunity.company_id == company.id, TrainingOpportunity.is_current.is_(True)))
    signal_conf = await db.scalar(select(func.max(CompanySignal.confidence)).where(CompanySignal.company_id == company.id))
    lead = scoring.lead_score(scoring.LeadInputs(
        normalized_title=c.normalized_title, department=c.department.value if c.department else None,
        seniority=c.seniority.value if c.seniority else None, state=loc.state if loc else None,
        city=loc.city if loc else None, industry=company.industry, employee_estimate=company.employee_estimate,
        best_email_status=best.verification_status if best else None, contact_confidence=conf.score,
        best_training_match=best_match, strongest_signal_confidence=signal_conf, engagement=c.status,
    ), lead_w)

    await db.execute(update(ContactConfidenceScore).where(ContactConfidenceScore.contact_id == c.id).values(is_current=False))
    await db.execute(update(LeadScore).where(LeadScore.contact_id == c.id).values(is_current=False))
    db.add(ContactConfidenceScore(contact_id=c.id, score=conf.score, breakdown=conf.breakdown_dicts()))
    priority = lead.priority or Priority.LOW
    db.add(LeadScore(contact_id=c.id, score=lead.score, priority=priority, breakdown=lead.breakdown_dicts()))
    await db.flush()
    return lead.score, priority


async def rescore_company(db: AsyncSession, company_id: int) -> int:
    weights = await load_weights(db)
    ids = (await db.execute(select(Contact.id).where(Contact.company_id == company_id, Contact.deleted_at.is_(None)))).scalars().all()
    high = 0
    for cid in ids:
        r = await rescore_contact(db, cid, weights)
        high += bool(r and r[1] == Priority.HIGH)
    return high
