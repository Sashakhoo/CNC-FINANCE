"""Client for CNC Finance's CRM integration endpoint (WON → invoice)."""
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import finance_client
from app.core.config import get_settings
from app.models import Company, Contact, ContactEmail, FinanceInvoice, TrainingOpportunity, TrainingProgram


class InvoiceError(Exception):
    pass


async def raise_won_invoice(db: AsyncSession, contact: Contact, company: Company, sales_person: str) -> FinanceInvoice:
    """Asks Finance to raise the Pending invoice for this company's deal.
    Idempotent: Finance keys it on the company, and so do we."""
    existing = (await db.execute(select(FinanceInvoice).where(FinanceInvoice.company_id == company.id))).scalar_one_or_none()
    if existing:
        return existing
    secret = get_settings().crm_integration_secret
    if not secret:
        raise InvoiceError("Finance integration isn't configured (CRM_INTEGRATION_SECRET).")
    amount = Decimal(company.deal_value or 0)
    if amount <= 0:
        raise InvoiceError("Set a deal value on the company before marking it WON.")

    email = await db.scalar(select(ContactEmail.email).where(ContactEmail.contact_id == contact.id)
                            .order_by(ContactEmail.is_primary.desc(), ContactEmail.id).limit(1))
    program = await db.scalar(
        select(TrainingProgram.name).join(TrainingOpportunity, TrainingOpportunity.program_id == TrainingProgram.id)
        .where(TrainingOpportunity.company_id == company.id, TrainingOpportunity.is_current.is_(True))
        .order_by(TrainingOpportunity.match_score.desc()).limit(1))
    body = {
        "external_ref": f"crm-company-{company.id}", "company": company.legal_name, "attention": contact.full_name,
        "email": email or "", "phone": contact.phone or company.phone or "", "amount": float(amount),
        "program": program or "Corporate training", "sales_person": sales_person,
    }
    try:
        r = await finance_client().post("/api/integrations/crm/won", json=body, headers={"x-crm-secret": secret})
    except httpx.HTTPError as e:
        raise InvoiceError(f"Finance is unreachable: {type(e).__name__}") from e
    if r.status_code != 200:
        detail = r.text[:200]
        try:
            detail = r.json().get("detail", detail)
        except ValueError:
            pass
        raise InvoiceError(f"Finance refused the invoice ({r.status_code}): {detail}")
    data = r.json()
    inv = FinanceInvoice(company_id=company.id, contact_id=contact.id, finance_invoice_id=data["invoice_id"],
                         invoice_number=data["invoice_number"], amount=Decimal(str(data.get("amount") or amount)))
    db.add(inv)
    await db.flush()
    return inv
