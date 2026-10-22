"""Shared CRM write helpers: provenance rows, activity log, suppression."""
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Activity, CompanySource, ContactSource, Suppression
from app.models.base import Provenance, SourceType
from app.services.normalize import email_domain

ACTIVITY_TYPES = {"note", "call", "meeting", "email", "linkedin", "other"}


def user_source(company_id: int | None = None, contact_id: int | None = None, *, field: str, value,
                source_url: str | None = None):
    """Evidence row for a value a person typed in (USER_PROVIDED)."""
    common = dict(field_name=field, value=None if value is None else str(value), provenance=Provenance.USER_PROVIDED,
                  source_type=SourceType.USER_ENTRY, source_url=source_url, confidence=None)
    if contact_id is not None:
        return ContactSource(contact_id=contact_id, **common)
    return CompanySource(company_id=company_id, **common)


def log_activity(db: AsyncSession, activity_type: str, text: str, *, contact_id: int | None = None,
                 company_id: int | None = None, user_id: int | None = None, meta: dict | None = None) -> Activity:
    a = Activity(activity_type=activity_type, text=text, contact_id=contact_id, company_id=company_id,
                 user_id=user_id, meta=meta or {})
    db.add(a)
    return a


async def suppress(db: AsyncSession, kind: str, value: str, reason: str, user_id: int | None) -> None:
    value = value.strip().lower() if kind in ("EMAIL", "DOMAIN") else str(value)
    exists = await db.scalar(select(Suppression.id).where(Suppression.kind == kind, Suppression.value == value))
    if not exists:
        db.add(Suppression(kind=kind, value=value, reason=reason, created_by_id=user_id))


async def unsuppress(db: AsyncSession, kind: str, values: list[str]) -> None:
    if values:
        await db.execute(delete(Suppression).where(Suppression.kind == kind, Suppression.value.in_(values)))


async def suppressed_reasons(db: AsyncSession, *, contact_id: int | None = None, company_id: int | None = None,
                             emails: list[str] = ()) -> list[str]:
    """Why outreach to this person/company is blocked (empty list = not blocked)."""
    conds = []
    if contact_id is not None:
        conds.append((Suppression.kind == "CONTACT") & (Suppression.value == str(contact_id)))
    if company_id is not None:
        conds.append((Suppression.kind == "COMPANY") & (Suppression.value == str(company_id)))
    emails = [e.lower() for e in emails]
    if emails:
        conds.append((Suppression.kind == "EMAIL") & (Suppression.value.in_(emails)))
        conds.append((Suppression.kind == "DOMAIN") & (Suppression.value.in_({email_domain(e) for e in emails})))
    if not conds:
        return []
    rows = (await db.execute(select(Suppression.kind, Suppression.value).where(or_(*conds)))).all()
    return [f"{k}:{v}" for k, v in rows]
