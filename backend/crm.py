"""
Integration with the Sales CRM (Codencode Lead Intelligence, a separate
service with its own database). When a deal there is marked WON, the CRM
calls POST /api/integrations/crm/won with a shared secret and this raises a
Pending invoice through the normal invoice path, so it shares the INV-
sequence with the dashboard and the Telegram bot.

Idempotent per external_ref (the CRM's deal reference): a retry returns the
invoice already raised instead of creating a second one.
"""
from datetime import date, timedelta

import storage

INVOICE_DUE_DAYS = 30


def _existing(external_ref: str):
    """A link whose invoice was since deleted in Finance no longer counts."""
    with storage.get_conn() as conn:
        link = conn.execute("SELECT * FROM crm_invoice_links WHERE external_ref = ?", (external_ref,)).fetchone()
        if not link:
            return None
        if not conn.execute("SELECT 1 FROM invoices WHERE id = ?", (link["invoice_id"],)).fetchone():
            conn.execute("DELETE FROM crm_invoice_links WHERE external_ref = ?", (external_ref,))
            return None
        return dict(link)


def raise_won_invoice(*, external_ref: str, company: str, attention: str, email: str, phone: str,
                      amount: float, program: str, sales_person: str) -> dict:
    link = _existing(external_ref)
    if link:
        inv = storage.get_invoice(link["invoice_id"])
        return {"created": False, "invoice_id": link["invoice_id"], "invoice_number": link["invoice_number"],
                "amount": inv["amount"] if inv else None}

    storage.find_or_create_contact(company, "debtor", email=email, phone=phone)
    today = date.today()
    number = storage.next_document_number("INV")
    iid = storage.insert_invoice(
        number, company, today.isoformat(), (today + timedelta(days=INVOICE_DUE_DAYS)).isoformat(), amount,
        status="Pending", description=f"{program} — corporate training",
        items=[{"description": f"{program} — corporate training programme", "qty": 1, "unit_price": amount}],
        attention=attention, company=company, sales_type="Corporate Training", sales_person=sales_person,
        remarks=f"Raised from the Sales CRM when the deal with {attention or company} was marked WON.",
    )
    with storage.get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO crm_invoice_links(external_ref, invoice_id, invoice_number) VALUES (?, ?, ?)",
            (external_ref, iid, number),
        )
    return {"created": True, "invoice_id": iid, "invoice_number": number, "amount": amount}
