"""
Invoices raised from learn.codencode.my student registrations.

The other direction of the existing LMS bridge (lms_sync.py pushes
"invoice paid -> enrol" to the LMS). Here the LMS calls us:

  1. A student registers (form portal or /register) -> raise_registration_invoice
     creates a Pending invoice for the course they picked, at its standard
     price if the LMS sends one (RM0 otherwise), so every sign-up has an
     INV- number straight away.
  2. An admin approves the sign-up in the LMS and types the fee ->
     set_registration_amount fills in the amount and renames the line item
     to the exact LMS course title. That title matters: when the invoice is
     later marked Paid here, lms_sync sends the line items to the LMS, which
     enrols the student by matching course titles.
  3. The sign-up is cancelled in the LMS -> cancel_registration_invoice
     deletes the invoice, but only while it's still Pending with no deposit;
     anything with money on it is left for the owner to sort out here.

Idempotent per external_ref (the LMS registration reference, e.g.
"lms-reg-42"): a retry returns the invoice already raised.
"""
from datetime import date, timedelta

import storage

INVOICE_DUE_DAYS = 14


def _existing(external_ref: str):
    """A link whose invoice was since deleted in Finance no longer counts."""
    with storage.get_conn() as conn:
        link = conn.execute("SELECT * FROM lms_invoice_links WHERE external_ref = ?", (external_ref,)).fetchone()
        if not link:
            return None
        if not conn.execute("SELECT 1 FROM invoices WHERE id = ?", (link["invoice_id"],)).fetchone():
            conn.execute("DELETE FROM lms_invoice_links WHERE external_ref = ?", (external_ref,))
            return None
        return dict(link)


def _summary(link: dict, created: bool) -> dict:
    inv = storage.get_invoice(link["invoice_id"]) or {}
    return {
        "created": created,
        "invoice_id": link["invoice_id"],
        "invoice_number": link["invoice_number"],
        "amount": inv.get("amount"),
        "status": inv.get("status"),
    }


def _line(course: str, location: str = "", timing: str = "") -> str:
    extra = " · ".join(x for x in (location, timing) if x)
    return f"{course} — course fee" + (f" ({extra})" if extra else "")


def raise_registration_invoice(*, external_ref: str, name: str, email: str, phone: str,
                               course: str, location: str = "", timing: str = "",
                               amount: float = 0) -> dict:
    """`amount` is the course's standard price when the LMS knows one, else 0
    (e.g. half-day courses); either way the LMS admin can change it on approval."""
    link = _existing(external_ref)
    if link:
        return _summary(link, created=False)

    storage.find_or_create_contact(name, "debtor", email=email, phone=phone)
    today = date.today()
    number = storage.next_document_number("INV")
    iid = storage.insert_invoice(
        number, name, today.isoformat(), (today + timedelta(days=INVOICE_DUE_DAYS)).isoformat(), amount,
        status="Pending", description=f"{course} — course registration",
        items=[{"description": _line(course, location, timing), "qty": 1, "unit_price": amount}],
        sales_type="Course", reference_no=external_ref,
        remarks="Raised automatically from a learn.codencode.my registration"
                + (" at the course's standard price. " if amount else ". ")
                + "The amount is confirmed when the registration is approved in the LMS.",
    )
    with storage.get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO lms_invoice_links(external_ref, invoice_id, invoice_number) VALUES (?, ?, ?)",
            (external_ref, iid, number),
        )
    return _summary({"invoice_id": iid, "invoice_number": number}, created=True)


def set_registration_amount(*, external_ref: str, amount: float, course_title: str) -> dict | None:
    """Returns None when there's no invoice for this registration. Raises
    ValueError if the invoice already has a payment on it."""
    link = _existing(external_ref)
    if not link:
        return None
    inv = storage.get_invoice(link["invoice_id"])
    if inv.get("status") in ("Paid", "Deposit") or (inv.get("deposit") or 0) > 0:
        raise ValueError(f"{link['invoice_number']} already has a payment recorded; change it in Finance.")
    items = [{"description": _line(course_title), "qty": 1, "unit_price": amount}]
    storage.update_invoice(
        link["invoice_id"], inv["contact"], inv["date"], inv["due"], amount,
        description=f"{course_title} — course registration",
        discount_pct=inv.get("discount_pct") or 0, remarks=inv.get("remarks") or "", items=items,
    )
    return _summary(link, created=False)


def cancel_registration_invoice(*, external_ref: str) -> dict:
    link = _existing(external_ref)
    if not link:
        return {"deleted": False, "reason": "no invoice"}
    inv = storage.get_invoice(link["invoice_id"]) or {}
    if inv.get("status") != "Pending" or (inv.get("deposit") or 0) > 0:
        return {"deleted": False, "invoice_number": link["invoice_number"],
                "reason": f"{link['invoice_number']} is {inv.get('status')}; left as is - handle it in Finance."}
    storage.delete_row("invoices", link["invoice_id"])
    with storage.get_conn() as conn:
        conn.execute("DELETE FROM lms_invoice_links WHERE external_ref = ?", (external_ref,))
    return {"deleted": True, "invoice_number": link["invoice_number"]}
