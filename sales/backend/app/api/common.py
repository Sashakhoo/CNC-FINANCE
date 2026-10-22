from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import Query
from pydantic import BaseModel

from app.models import (Activity, Company, CompanySignal, CompanySource, ContactEmail, ContactProfile, ContactSource,
                        Note)


class Page(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int


def paging(page: int = Query(1, ge=1, le=10_000), page_size: int = Query(25, ge=1, le=200)) -> tuple[int, int]:
    return page, page_size


def num(v: Decimal | None) -> float | None:
    return None if v is None else float(v)


def iso(v: datetime | None) -> str | None:
    return v.isoformat() if v else None


def source_out(s: CompanySource | ContactSource) -> dict:
    return {"id": s.id, "field": s.field_name, "value": s.value, "provenance": s.provenance.value,
            "source_type": s.source_type.value, "provider": s.provider, "source_url": s.source_url,
            "evidence": s.evidence_text, "confidence": s.confidence, "retrieved_at": iso(s.retrieved_at)}


def signal_out(s: CompanySignal) -> dict:
    return {"id": s.id, "signal_type": s.signal_type, "title": s.title, "description": s.description,
            "evidence": s.evidence_text, "source_url": s.source_url, "source_date": iso(s.source_date),
            "provenance": s.provenance.value, "confidence": s.confidence, "discovered_at": iso(s.discovered_at)}


def email_out(e: ContactEmail) -> dict:
    return {"id": e.id, "email": e.email, "email_type": e.email_type.value, "discovery_method": e.discovery_method.value,
            "provenance": e.provenance.value, "source": e.source, "source_url": e.source_url, "confidence": e.confidence,
            "verification_status": e.verification_status.value, "verification_provider": e.verification_provider,
            "verified_at": iso(e.verified_at), "is_primary": e.is_primary, "created_at": iso(e.created_at)}


def profile_out(p: ContactProfile) -> dict:
    return {"id": p.id, "platform": p.platform, "url": p.url, "source_type": p.source_type.value,
            "provider": p.provider, "source_url": p.source_url, "confidence": p.confidence,
            "retrieved_at": iso(p.retrieved_at)}


def activity_out(a: Activity, username: str | None = None) -> dict:
    return {"id": a.id, "type": a.activity_type, "text": a.text, "meta": a.meta, "contact_id": a.contact_id,
            "company_id": a.company_id, "user": username, "created_at": iso(a.created_at)}


def note_out(n: Note, username: str | None = None) -> dict:
    return {"id": n.id, "body": n.body, "contact_id": n.contact_id, "company_id": n.company_id, "user": username,
            "user_id": n.user_id, "created_at": iso(n.created_at), "updated_at": iso(n.updated_at)}


def company_out(c: Company, *, location: dict | None = None, contact_count: int | None = None) -> dict:
    return {"id": c.id, "legal_name": c.legal_name, "display_name": c.display_name, "website": c.website,
            "domain": c.domain, "domain_confidence": c.domain_confidence, "domain_status": c.domain_status,
            "industry": c.industry, "description": c.description, "employee_estimate": c.employee_estimate,
            "employee_estimate_source": c.employee_estimate_source, "phone": c.phone, "general_email": c.general_email,
            "deal_value": num(c.deal_value), "is_demo": c.is_demo, "location": location, "contact_count": contact_count,
            "last_crawled_at": iso(c.last_crawled_at), "last_enriched_at": iso(c.last_enriched_at),
            "created_at": iso(c.created_at), "updated_at": iso(c.updated_at)}
