"""
Pushes student/enrollment data to learn.codencode.my so the student profile
and course/workshop enrollment are created automatically — CNC Finance (and
now the Telegram bot directly) is the source of truth for who registered,
the LMS is the source of truth for enrollment/course access, and this is
the one-way bridge between them.

Two callers:
  - sync_invoice_to_lms(): fired when an invoice is marked Paid/Deposit in
    the dashboard (see backend/api.py's _sync_invoice_to_lms_if_relevant).
  - create_student(): fired directly from the Telegram bot's /student
    command, for registrations that never go through an invoice at all
    (e.g. a workshop sign-up slip with no payment on file yet).

Fire-and-log: a failed or unconfigured sync never blocks the caller — it's
recorded as a short note the dashboard/bot can show
("Synced", "2 unmatched — needs manual enroll", "LMS sync failed: ...").

NOTE on payment_status="manual" and session_date/session_time: these are
sent to learn.codencode.my's /api/integrations/finance/enroll endpoint on
the assumption that endpoint is extended to accept them (per the owner's
confirmation) — verify learn.codencode.my's finance-sync route actually
reads these before relying on them; an endpoint that doesn't recognise
"manual" may error or fall through to its own default handling instead of
silently accepting it.
"""
import os
import httpx

LMS_SYNC_URL = os.environ.get("LMS_SYNC_URL", "").rstrip("/")
LMS_SYNC_SECRET = os.environ.get("LMS_SYNC_SECRET", "")


def _post_enroll(payload: dict) -> str:
    """Shared POST + response-summary logic for both sync entry points below.
    Never raises — always returns a short human-readable note."""
    if not LMS_SYNC_URL or not LMS_SYNC_SECRET:
        return "LMS sync not configured"
    if not (payload.get("email") or "").strip():
        return "LMS sync skipped — no email on file"

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


def sync_invoice_to_lms(inv: dict, status: str, email: str = "", phone: str = "") -> str:
    """inv is a storage.get_invoice()-shaped dict (has contact/items/number).
    email/phone come from the invoice's contact record (invoices don't store
    them directly). status is 'Paid' or 'Deposit'. Returns a short note to
    store on the invoice; never raises."""
    payload = {
        "name": inv.get("contact", ""),
        "email": (email or "").strip(),
        "phone": phone or "",
        "payment_status": "paid" if status == "Paid" else "deposit",
        "payment_method": None,
        "document_number": inv.get("number", "").split("-")[-1] if inv.get("number") else None,
        "items": [
            {"title": item["description"], "amount": item["qty"] * item["unit_price"]}
            for item in (inv.get("items") or [])
        ],
    }
    return _post_enroll(payload)


def create_student(name: str, email: str, phone: str, course: str,
                    session_date: str = "", session_time: str = "") -> str:
    """Creates/enrolls a student directly — used by the Telegram bot's
    /student command for registrations with no invoice/payment behind them
    (e.g. a workshop sign-up slip). Sends payment_status="manual" (distinct
    from the invoice-sync path's "paid"/"deposit") plus session_date/
    session_time so the LMS can show which session the student registered
    for, if the receiving endpoint has been extended to read them."""
    payload = {
        "name": name,
        "email": (email or "").strip(),
        "phone": phone or "",
        "payment_status": "manual",
        "payment_method": None,
        "document_number": None,
        "items": [{"title": course, "amount": 0}],
        "session_date": session_date or None,
        "session_time": session_time or None,
    }
    return _post_enroll(payload)


def lookup_student_completion(identifier: str) -> tuple[dict | None, str]:
    """Looks up a student's completed courses on learn.codencode.my, for the
    Telegram bot's /cert command to generate a certificate from.

    ASSUMED CONTRACT (this endpoint does not exist yet as far as this repo
    can tell — it needs to be added on the learn.codencode.my side, mirroring
    the finance/enroll endpoint's auth):
        GET {LMS_SYNC_URL}/api/integrations/finance/student-lookup?query=<identifier>
        Header: X-Finance-Secret: <LMS_SYNC_SECRET>
        200 -> {"name": str, "email": str,
                "courses": [{"title": str, "completed_at": "YYYY-MM-DD"}, ...]}
        404 -> student not found / no completed courses

    Returns (data, error_note): data is the parsed JSON on success or None on
    any failure, with error_note explaining why (never raises)."""
    if not LMS_SYNC_URL or not LMS_SYNC_SECRET:
        return None, "LMS sync not configured"
    identifier = (identifier or "").strip()
    if not identifier:
        return None, "Need a name or email to look up"

    try:
        resp = httpx.get(
            f"{LMS_SYNC_URL}/api/integrations/finance/student-lookup",
            params={"query": identifier},
            headers={"X-Finance-Secret": LMS_SYNC_SECRET},
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        return None, f"LMS lookup failed: {exc}"

    if resp.status_code == 404:
        return None, f"No student matching \"{identifier}\" found in the LMS"
    if resp.status_code != 200:
        return None, f"LMS lookup failed ({resp.status_code}): {resp.text[:200]}"

    data = resp.json()
    if not data.get("courses"):
        return data, f"{data.get('name', identifier)} has no completed courses on file"
    return data, ""
