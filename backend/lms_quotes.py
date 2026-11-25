"""
Draft quotations raised from learn.codencode.my corporate training enquiries.

A company fills in the corporate form on the LMS form portal (company,
contact, pax, HRD Corp claim, topics, location, needs). The LMS calls
POST /api/integrations/lms/corporate and we save a **Draft** standard
quotation in the normal quotation builder, so the owner reviews, prices and
sends it from here as usual.

Each ticked topic becomes a line item. A topic that matches a course in the
quotation catalogue (quote_courses) takes that course's id (so the PDF
prints its course content) and default price, times pax when it's priced
per pax. Unmatched topics come in at RM0 for the owner to price.

Idempotent per external_ref (e.g. "lms-corp-7"): a retry returns the
quotation already raised.
"""
import re
from datetime import date, timedelta

import quote_store as qs
import storage

VALIDITY_DAYS = 14
_STOP = {"for", "and", "the", "with", "from", "to", "of", "a", "an", "ai", "&", "-"}


def _existing(external_ref: str):
    """A link whose quotation was since deleted in Finance no longer counts."""
    with storage.get_conn() as conn:
        link = conn.execute("SELECT * FROM lms_quote_links WHERE external_ref = ?", (external_ref,)).fetchone()
        if not link:
            return None
        if not conn.execute("SELECT 1 FROM quotations WHERE id = ?", (link["quote_id"],)).fetchone():
            conn.execute("DELETE FROM lms_quote_links WHERE external_ref = ?", (external_ref,))
            return None
        return dict(link)


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in _STOP and len(w) > 2}


def match_course(topic: str, courses: list):
    """Best catalogue course for a topic name, or None. Needs at least one
    shared meaningful word ("Vibe Coding" -> "Vibe Coding from Scratch");
    "AI" alone never counts, so "AI for Marketing" won't land on "AI for
    Automation"."""
    want = _words(topic)
    best, best_score = None, 0
    for c in courses:
        have = _words(c["name"])
        score = len(want & have)
        if score > best_score or (score == best_score and score and len(have) < len(_words(best["name"]))):
            best, best_score = c, score
    return best if best_score else None


def _line(topic: str, pax, courses: list) -> dict:
    c = match_course(topic, courses)
    if not c:
        return {"kind": "course", "course_id": None, "title": topic, "description": "",
                "qty": pax or 1, "unit_price": 0, "claimable": False}
    per_pax = (c.get("price_unit") or "pax") == "pax"
    return {"kind": "course", "course_id": c["id"], "title": c["name"],
            "description": c.get("group_note") or "",
            "qty": (pax or 1) if per_pax else 1, "unit_price": float(c.get("default_price") or 0),
            "claimable": False}


def raise_corporate_quote(*, external_ref: str, company: str, contact_name: str, email: str, phone: str,
                          pax: int | None, hrd_claim: str, topics: list, location: str, requirements: str) -> dict:
    link = _existing(external_ref)
    if link:
        q = qs.get_quotation(link["quote_id"]) or {}
        return {"created": False, "quote_id": link["quote_id"], "quote_number": link["quote_number"],
                "status": q.get("status")}

    courses = qs.list_courses()
    topics = [t.strip() for t in topics if (t or "").strip()] or ["Corporate training"]
    items = [_line(t, pax, courses) for t in topics]

    notes = []
    if pax:
        notes.append(f"Participants: {pax} pax (from the enquiry).")
    if location:
        notes.append(f"Preferred location: {location}.")
    if (hrd_claim or "").lower() == "yes":
        notes.append("HRD Corp claim requested - switch this to an HRDC quotation if it will be claimed.")
    elif (hrd_claim or "").lower() == "not sure":
        notes.append("HRD Corp claim: not sure yet - check with the client.")
    if requirements:
        notes.append(f"Client's needs: {requirements}")
    unmatched = [i["title"] for i in items if not i["course_id"]]
    if unmatched:
        notes.append("Price to fill in: " + ", ".join(unmatched) + " (not in the course catalogue).")

    today = date.today()
    q = {
        "qtype": "standard", "number": qs.next_number("standard"), "status": "Draft",
        "company": company.strip(), "contact": company.strip(), "attention": contact_name.strip(),
        "email": email.strip(), "phone": phone.strip(), "address": "",
        "date": today.isoformat(), "validity_days": VALIDITY_DAYS,
        "valid_until": (today + timedelta(days=VALIDITY_DAYS)).isoformat(),
        "plain_language": True, "reference_no": external_ref, "sales_type": "Corporate Training",
        "notes": "\n".join(notes), "remarks": "Raised automatically from a learn.codencode.my corporate enquiry.",
        "items": items, "hrdc": {},
    }
    saved = qs.save_quotation(q)
    qs.remember_client({"company": q["company"], "attention": q["attention"], "email": q["email"], "phone": q["phone"]})
    with storage.get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO lms_quote_links(external_ref, quote_id, quote_number) VALUES (?, ?, ?)",
                     (external_ref, saved["id"], saved["number"]))
    return {"created": True, "quote_id": saved["id"], "quote_number": saved["number"], "status": saved["status"],
            "unpriced": unmatched}
