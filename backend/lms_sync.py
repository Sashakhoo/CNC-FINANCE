"""
Pushes a paid/deposit invoice to learn.codencode.my so the student profile
and course/workshop enrollment are created automatically — CNC Finance is
the source of truth for payments, the LMS is the source of truth for
enrollment/course access, and this is the one-way bridge between them.

Fire-and-log: a failed or unconfigured sync never blocks marking an invoice
paid — it's recorded on the invoice as a note the dashboard can show
("Synced", "2 unmatched — needs manual enroll", "LMS sync failed: ...").
"""
import os
import httpx

LMS_SYNC_URL = os.environ.get("LMS_SYNC_URL", "").rstrip("/")
LMS_SYNC_SECRET = os.environ.get("LMS_SYNC_SECRET", "")


def sync_invoice_to_lms(inv: dict, status: str, email: str = "", phone: str = "") -> str:
    """inv is a storage.get_invoice()-shaped dict (has contact/items/number).
    email/phone come from the invoice's contact record (invoices don't store
    them directly). status is 'Paid' or 'Deposit'. Returns a short note to
    store on the invoice; never raises."""
    if not LMS_SYNC_URL or not LMS_SYNC_SECRET:
        return "LMS sync not configured"

    email = (email or "").strip()
    if not email:
        return "LMS sync skipped — contact has no email on file"

    payload = {
        "name": inv.get("contact", ""),
        "email": email,
        "phone": phone or "",
        "payment_status": "paid" if status == "Paid" else "deposit",
        "payment_method": None,
        "document_number": inv.get("number", "").split("-")[-1] if inv.get("number") else None,
        "items": [
            {"title": item["description"], "amount": item["qty"] * item["unit_price"]}
            for item in (inv.get("items") or [])
        ],
    }

    try:
        resp = httpx.post(
            f"{LMS_SYNC_URL}/api/integrations/finance/enroll",
            json=payload,
            headers={"X-Finance-Secret": LMS_SYNC_SECRET},
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        return f"LMS sync failed: {exc}"

    if resp.status_code != 200:
        return f"LMS sync failed ({resp.status_code}): {resp.text[:200]}"

    data = resp.json()
    matched = data.get("matched") or []
    unmatched = data.get("unmatched") or []
    created = data.get("account_created")
    bits = []
    if matched:
        bits.append(f"{len(matched)} enrolled")
    if unmatched:
        titles = ", ".join(u["title"] for u in unmatched)
        bits.append(f"{len(unmatched)} unmatched ({titles}) — enroll manually in the LMS")
    if created:
        bits.append("new LMS login emailed")
    return "Synced: " + "; ".join(bits) if bits else "Synced"
