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


_WORKPLACE_AI = ("workplace", "productivity", "automation", "workflow", "operations")


def match_programme(topics: list, programmes: list):
    """The approved HRD Corp programme an enquiry's topics point at, or None.
    Python topics -> the Python programme; workplace / productivity /
    automation AI topics -> the "AI for Workflow ..." programme."""
    approved = [p for p in programmes if p.get("status") == "Approved"]
    for t in topics:
        low = (t or "").lower()
        if "python" in low:
            hit = next((p for p in approved if "python" in p["title"].lower()), None)
        elif any(w in low for w in _WORKPLACE_AI):
            hit = next((p for p in approved if "workflow" in p["title"].lower()), None)
        else:
            hit = None
        if hit:
            return hit
    return None


def _fmt_people(participants: list) -> str:
    return "; ".join(p["name"] + (f" ({', '.join(x for x in (p.get('department'), p.get('level')) if x)})"
                                  if p.get("department") or p.get("level") else "")
                     for p in participants)


def _hrdc_details(*, prog: dict, ssm: str, mycoid: str, contact: str, email: str, phone: str, pax,
                  dates: list, start_time: str, end_time: str, mode: str, location: str, company: str,
                  participants: list) -> dict:
    online = (mode or "").lower().startswith("online") or (not mode and prog.get("mode") == "online")
    at_client = (mode or "").lower().startswith("at our office")
    return {
        "programme_id": prog["id"], "ssm": ssm, "mycoid": mycoid or ssm,
        "hr_contact": contact, "hr_email": email, "hr_phone": phone,
        "training_type": "in-house", "grant_scheme": "", "grant_id": "", "grant_status": "Quote",
        "pax": pax or len(participants) or None, "dates": dates, "start_time": start_time, "end_time": end_time,
        "hours": prog.get("hours"), "mode": "online" if online else "physical",
        "venue": "" if online else (f"{company}, {location}".strip(", ") if at_client else qs.ACADEMY_VENUE),
        "venue_type": "client" if at_client else "academy",
        "platform": "Zoom (live, instructor-led)" if online else "",
        # IC numbers are never collected on the public form; add them in the builder.
        "participants": [{"name": p["name"], "ic": "",
                          "designation": ", ".join(x for x in (p.get("department"), p.get("level")) if x)}
                         for p in participants],
    }


def raise_corporate_quote(*, external_ref: str, company: str, contact_name: str, email: str, phone: str,
                          pax: int | None, hrd_claim: str, topics: list, location: str, requirements: str,
                          ssm: str = "", mycoid: str = "", contact_role: str = "", mode: str = "",
                          dates: list = (), start_time: str = "", end_time: str = "",
                          participants: list = ()) -> dict:
    link = _existing(external_ref)
    if link:
        q = qs.get_quotation(link["quote_id"]) or {}
        return {"created": False, "quote_id": link["quote_id"], "quote_number": link["quote_number"],
                "status": q.get("status")}

    topics = [t.strip() for t in topics if (t or "").strip()] or ["Corporate training"]
    participants = [p for p in (participants or []) if (p.get("name") or "").strip()]
    dates = sorted(d for d in (dates or []) if d)
    pax = pax or (len(participants) or None)
    claim = (hrd_claim or "").lower()
    attention = contact_name.strip() + (f" ({contact_role.strip()})" if contact_role.strip() else "")
    prog = match_programme(topics, qs.list_programmes()) if claim == "yes" else None

    notes = []
    if prog:
        qtype = "hrdc"
        days = prog.get("days") or 1
        items = [{"kind": "course", "course_id": None, "title": prog["title"],
                  "description": f"{days:g}-day training ({prog.get('hours') or 0:g} training hours). "
                                 "Includes course materials, hands-on exercises and a certificate of completion.",
                  "qty": pax or 1, "unit_price": 0, "claimable": True}]
        hrdc = _hrdc_details(prog=prog, ssm=ssm, mycoid=mycoid, contact=attention, email=email, phone=phone,
                             pax=pax, dates=dates, start_time=start_time, end_time=end_time, mode=mode,
                             location=location, company=company, participants=participants)
        notes.append(f"HRDC quotation on the approved programme \"{prog['title']}\". "
                     "Set the fee per pax before sending (left at RM0 on purpose).")
        others = [t for t in topics if match_programme([t], [prog]) is None]
        if others:
            notes.append("Also asked about: " + ", ".join(others) + ".")
        if participants:
            notes.append("Add participants' IC numbers before sending (not collected on the public form).")
        unmatched = []
    else:
        qtype = "standard"
        items = [_line(t, pax, qs.list_courses()) for t in topics]
        hrdc = {}
        if pax:
            notes.append(f"Participants: {pax} pax (from the enquiry).")
        if ssm or mycoid:
            notes.append(f"SSM: {ssm or '-'} · HRD Corp Employer No.: {mycoid or '-'}.")
        if mode or location:
            notes.append("Delivery: " + " · ".join(x for x in (mode, location) if x) + ".")
        if dates:
            notes.append("Preferred dates: " + ", ".join(dates)
                         + (f" ({start_time}-{end_time})" if start_time else "") + ".")
        if participants:
            notes.append("Participants: " + _fmt_people(participants) + ".")
        if claim == "yes":
            notes.append("HRD Corp claim requested, but no approved HRD Corp programme matches these topics - "
                         "switch to an HRDC quotation if one applies.")
        elif claim == "not sure":
            notes.append("HRD Corp claim: not sure yet - check with the client.")
        unmatched = [i["title"] for i in items if not i["course_id"]]
        if unmatched:
            notes.append("Price to fill in: " + ", ".join(unmatched) + " (not in the course catalogue).")
    if requirements:
        notes.append(f"Client's needs: {requirements}")

    today = date.today()
    q = {
        "qtype": qtype, "number": qs.next_number(qtype), "status": "Draft",
        "company": company.strip(), "contact": company.strip(), "attention": attention,
        "email": email.strip(), "phone": phone.strip(), "address": "",
        "date": today.isoformat(), "validity_days": VALIDITY_DAYS,
        "valid_until": (today + timedelta(days=VALIDITY_DAYS)).isoformat(),
        "plain_language": True, "reference_no": external_ref, "sales_type": "Corporate Training",
        "notes": "\n".join(notes), "remarks": "Raised automatically from a learn.codencode.my corporate enquiry.",
        "items": items, "hrdc": hrdc,
    }
    saved = qs.save_quotation(q)
    qs.remember_client({"company": q["company"], "attention": q["attention"], "email": q["email"], "phone": q["phone"],
                        "ssm": ssm, "mycoid": mycoid or ssm})
    with storage.get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO lms_quote_links(external_ref, quote_id, quote_number) VALUES (?, ?, ?)",
                     (external_ref, saved["id"], saved["number"]))
    return {"created": True, "quote_id": saved["id"], "quote_number": saved["number"], "status": saved["status"],
            "unpriced": unmatched}
