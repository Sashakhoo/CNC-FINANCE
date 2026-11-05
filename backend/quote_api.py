"""
Quotation builder API (/api/quotes/...). Type A Non-HRDC (QUO-) and Type B
HRDC Claimable (QHR-). Quotations never touch the ledger; an accepted one can
be converted into an invoice.
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

import auth
import storage
import quote_pdf
import quote_store as qs

router = APIRouter(prefix="/api")


def _director(request: Request) -> dict:
    user = auth.require_auth(request)
    if not auth.can(user["role"], "users"):
        raise HTTPException(403, "Only a director can change quotation settings")
    return user


class Item(BaseModel):
    kind: str = "course"
    course_id: int | None = None
    title: str = ""
    description: str = ""
    qty: float = 1
    unit_price: float = 0
    claimable: bool = False


class Participant(BaseModel):
    name: str = ""
    ic: str = ""
    designation: str = ""


class Hrdc(BaseModel):
    programme_id: int | None = None
    ssm: str = ""
    mycoid: str = ""
    hr_contact: str = ""
    hr_email: str = ""
    hr_phone: str = ""
    training_type: str = "in-house"
    grant_scheme: str = ""
    grant_id: str = ""
    grant_status: str = "Quote"
    pax: int | None = None
    dates: list[str] = []
    start_time: str = ""
    end_time: str = ""
    hours: float | None = None
    mode: str = ""
    venue: str = ""
    venue_type: str = "academy"           # academy | client (the employer's own premises)
    platform: str = ""
    participants: list[Participant] = []


class QuoteBody(BaseModel):
    qtype: str = "standard"
    number: str = ""
    status: str = "Draft"
    company: str = ""
    attention: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""
    date: str = ""
    validity_days: int = 30
    valid_until: str = ""
    prepared_by: str = ""
    show_address: bool = False
    sst: bool = False
    plain_language: bool = True
    claude_block: bool = False
    tier_note: bool = False
    discount_rm: float = 0
    payment_terms: str = ""
    notes: str = ""
    items: list[Item] = []
    hrdc: Hrdc = Hrdc()


def _normalise(body: QuoteBody, qid: int = None, existing: dict = None) -> dict:
    if body.qtype not in qs.TYPES:
        raise HTTPException(422, "Unknown quotation type")
    if body.status not in qs.STATUSES:
        raise HTTPException(422, "Unknown status")
    q = body.model_dump()
    q["company"] = (q["company"] or "").strip()
    q["contact"] = q["company"]
    try:
        issued = date.fromisoformat(q["date"]) if q["date"] else date.today()
    except ValueError:
        raise HTTPException(422, "Issue date must be YYYY-MM-DD")
    q["date"] = issued.isoformat()
    q["validity_days"] = max(1, min(365, int(q["validity_days"] or 30)))
    q["valid_until"] = (issued + timedelta(days=q["validity_days"])).isoformat()
    q["items"] = [i for i in q["items"] if (i["title"] or "").strip()]
    for i in q["items"]:
        if i["kind"] not in qs.LINE_KINDS:
            i["kind"] = "other"
        i["title"] = i["title"].strip()[:200]
        i["description"] = (i["description"] or "").strip()[:1500]
        if q["qtype"] != "hrdc":
            i["claimable"] = False
    if q["qtype"] == "hrdc":
        q["discount_rm"] = 0
        q["tier_note"] = False
        q["claude_block"] = False
        h = q["hrdc"]
        h["participants"] = [{"name": p["name"].strip()[:120], "ic": qs.mask_ic(p["ic"]),
                              "designation": p["designation"].strip()[:120]}
                             for p in h["participants"] if (p["name"] or "").strip()]
        h["dates"] = [d for d in h["dates"] if d][:30]
        if h["venue_type"] not in ("academy", "client"):
            h["venue_type"] = "academy"
        if h["grant_status"] not in qs.GRANT_STEPS:
            h["grant_status"] = "Quote"
    else:
        q["hrdc"] = {}
    number = (q["number"] or "").strip().upper()
    if existing and existing["qtype"] != q["qtype"] and number == existing["number"]:
        number = ""                                  # type changed: give it the other prefix
    if not number:
        number = qs.next_number(q["qtype"])
    if qs.number_taken(number, exclude_id=qid):
        raise HTTPException(409, f"Quotation number {number} is already used")
    q["number"] = number
    return q


def _guard_status(q: dict, result: dict):
    if q["status"] in ("Sent", "Accepted"):
        if result["errors"]:
            raise HTTPException(422, "Fix these before marking it " + q["status"] + ": " + " ".join(result["errors"]))
        if q["qtype"] == "hrdc":
            prog = qs.get_programme(q["hrdc"].get("programme_id"))
            if prog and prog["status"] != "Approved":
                raise HTTPException(422, f"'{prog['title']}' is {prog['status']} with HRD Corp. Keep the quote as "
                                         "Draft until the programme is approved.")


@router.get("/quotes/meta", dependencies=[Depends(auth.require_finance)])
def meta(request: Request):
    user = auth.current_user(request)
    return {"settings": qs.get_settings(), "courses": qs.list_courses(include_inactive=True),
            "programmes": qs.list_programmes(include_inactive=True), "clients": qs.list_clients(),
            "statuses": qs.STATUSES, "grant_steps": qs.GRANT_STEPS, "grant_schemes": qs.GRANT_SCHEMES,
            "line_kinds": qs.LINE_KINDS, "can_edit": auth.can(user["role"], "invoices"),
            "is_director": auth.can(user["role"], "users")}


@router.get("/quotes", dependencies=[Depends(auth.require_finance)])
def list_quotes():
    return qs.list_quotations()


@router.get("/quotes/{qid}", dependencies=[Depends(auth.require_finance)])
def get_quote(qid: int):
    q = qs.get_quotation(qid)
    if not q:
        raise HTTPException(404, "Quotation not found")
    return {"quote": q, "check": qs.check(q)}


@router.post("/quotes/preview", dependencies=[Depends(auth.require_finance)])
def preview(body: QuoteBody):
    q = body.model_dump()
    q["contact"] = q["company"]
    try:
        issued = date.fromisoformat(q["date"]) if q["date"] else date.today()
    except ValueError:
        issued = date.today()
    q["date"] = issued.isoformat()
    q["valid_until"] = (issued + timedelta(days=max(1, int(q["validity_days"] or 30)))).isoformat()
    q["number"] = (q["number"] or "").strip().upper() or f"{qs.PREFIX.get(q['qtype'], 'QUO')}-###"
    q["items"] = [i for i in q["items"] if (i["title"] or "").strip()]
    if q["qtype"] == "hrdc":
        for p in q["hrdc"]["participants"]:
            p["ic"] = qs.mask_ic(p["ic"])
    return {"html": quote_pdf.build_html(q, for_pdf=False), "totals": qs.totals(q), "check": qs.check(q)}


@router.post("/quotes", dependencies=[Depends(auth.require_cap("invoices"))])
def create_quote(body: QuoteBody):
    q = _normalise(body)
    result = qs.check(q)
    _guard_status(q, result)
    saved = qs.save_quotation(q)
    qs.remember_client({**q, **{k: v for k, v in (q.get("hrdc") or {}).items() if isinstance(v, str)}})
    return {"quote": saved, "check": result}


@router.put("/quotes/{qid}", dependencies=[Depends(auth.require_cap("invoices"))])
def update_quote(qid: int, body: QuoteBody):
    existing = qs.get_quotation(qid)
    if not existing:
        raise HTTPException(404, "Quotation not found")
    if existing.get("invoice_id") and storage.get_invoice(existing["invoice_id"]):
        raise HTTPException(409, "This quotation has been turned into an invoice — edit the invoice instead, "
                                 "or duplicate the quotation")
    q = _normalise(body, qid, existing)
    result = qs.check(q)
    _guard_status(q, result)
    saved = qs.save_quotation(q, qid)
    qs.remember_client({**q, **{k: v for k, v in (q.get("hrdc") or {}).items() if isinstance(v, str)}})
    return {"quote": saved, "check": result}


@router.post("/quotes/{qid}/duplicate", dependencies=[Depends(auth.require_cap("invoices"))])
def duplicate_quote(qid: int):
    q = qs.duplicate(qid)
    if not q:
        raise HTTPException(404, "Quotation not found")
    return {"quote": q, "check": qs.check(q)}


class StatusBody(BaseModel):
    status: str


@router.patch("/quotes/{qid}/status", dependencies=[Depends(auth.require_cap("invoices"))])
def set_status(qid: int, body: StatusBody):
    q = qs.get_quotation(qid)
    if not q:
        raise HTTPException(404, "Quotation not found")
    if body.status not in qs.STATUSES:
        raise HTTPException(422, "Unknown status")
    q["status"] = body.status
    _guard_status(q, qs.check(q))
    storage.set_quotation_status(qid, body.status)
    return qs.get_quotation(qid)


class GrantBody(BaseModel):
    grant_status: str
    grant_id: str = ""


@router.patch("/quotes/{qid}/grant", dependencies=[Depends(auth.require_cap("invoices"))])
def set_grant(qid: int, body: GrantBody):
    q = qs.get_quotation(qid)
    if not q or q["qtype"] != "hrdc":
        raise HTTPException(404, "HRDC quotation not found")
    if body.grant_status not in qs.GRANT_STEPS:
        raise HTTPException(422, "Unknown grant step")
    q["hrdc"]["grant_status"] = body.grant_status
    if body.grant_id.strip():
        q["hrdc"]["grant_id"] = body.grant_id.strip()[:60]
    return qs.save_quotation(q, qid)


@router.post("/quotes/{qid}/convert", dependencies=[Depends(auth.require_cap("invoices"))])
def convert(qid: int):
    """Accepted quotation -> invoice with the same company and lines, dated
    today, due in 30 days. HRDC quotes carry the grant ID into the invoice."""
    q = qs.get_quotation(qid)
    if not q:
        raise HTTPException(404, "Quotation not found")
    if q.get("invoice_id") and storage.get_invoice(q["invoice_id"]):
        raise HTTPException(409, "This quotation is already an invoice")
    h = q.get("hrdc") or {}
    storage.find_or_create_contact(q["contact"], "debtor", email=q.get("email") or h.get("hr_email") or "",
                                   phone=q.get("phone") or h.get("hr_phone") or "")
    items = [{"description": i["title"] + (f" — {i['description']}" if i.get("description") else ""),
              "qty": i.get("qty") or 1, "unit_price": i.get("unit_price") or 0} for i in q["items"]]
    t = q["totals"]
    remarks = f"From quotation {q['number']}."
    if q["qtype"] == "hrdc" and h.get("grant_id"):
        remarks += f" HRD Corp grant ID: {h['grant_id']}."
    if t["discount"]:
        items.append({"description": "Discount", "qty": 1, "unit_price": -t["discount"]})
    today = date.today()
    number = storage.next_document_number("INV")
    iid = storage.insert_invoice(number, q["contact"], today.isoformat(), (today + timedelta(days=30)).isoformat(),
                                 0, status="Pending", remarks=remarks, items=items,
                                 attention=q.get("attention") or h.get("hr_contact") or "", company=q["contact"],
                                 address=q.get("address") or "", reference_no=h.get("grant_id") or q["number"],
                                 tax_pct=t["sst_rate"] if q.get("sst") else (q.get("tax_pct") or 0))
    storage.set_quotation_status(qid, "Accepted", invoice_id=iid)
    if q["qtype"] == "hrdc":
        q = qs.get_quotation(qid)
        q["hrdc"]["grant_status"] = "Invoiced"
        qs.save_quotation(q, qid)
    return {"quote": qs.get_quotation(qid), "invoice": storage.get_invoice(iid)}


@router.delete("/quotes/{qid}", dependencies=[Depends(auth.require_cap("invoices"))])
def delete_quote(qid: int):
    storage.delete_quotation(qid)
    return {"ok": True}


@router.get("/quotes/{qid}/pdf", dependencies=[Depends(auth.require_cap("documents"))])
def quote_pdf_file(qid: int):
    q = qs.get_quotation(qid)
    if not q:
        raise HTTPException(404, "Quotation not found")
    result = qs.check(q)
    if result["errors"]:
        raise HTTPException(422, "Fix these first: " + " ".join(result["errors"]))
    pdf = quote_pdf.render_pdf(q)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{q["number"]}.pdf"'})


# --- catalogue & settings ---------------------------------------------------------

class CourseBody(BaseModel):
    name: str
    default_price: float = 0
    price_unit: str = "pax"
    group_note: str = ""
    tiered: bool = False
    sessions: list[dict] = []
    active: bool = True
    sort: int = 0


@router.post("/quotes-admin/courses", dependencies=[Depends(auth.require_cap("invoices"))])
def add_course(body: CourseBody):
    if not body.name.strip():
        raise HTTPException(422, "Course name is required")
    return qs.save_course(body.model_dump())


@router.put("/quotes-admin/courses/{cid}", dependencies=[Depends(auth.require_cap("invoices"))])
def edit_course(cid: int, body: CourseBody):
    return qs.save_course(body.model_dump(), cid)


class ProgrammeBody(BaseModel):
    title: str
    programme_code: str = ""
    fee_cap: float = 0
    days: float = 1
    hours: float = 8
    mode: str = "physical"
    venue: str = ""
    trainers: str = ""
    status: str = "Pending"
    min_pax: int = 1
    max_pax: int = 30
    sessions: list[dict] = []
    outline_note: str = ""
    active: bool = True


@router.post("/quotes-admin/programmes")
def add_programme(body: ProgrammeBody, request: Request):
    _director(request)
    if body.status not in ("Approved", "Pending", "Returned"):
        raise HTTPException(422, "Status must be Approved, Pending or Returned")
    return qs.save_programme(body.model_dump())


@router.put("/quotes-admin/programmes/{pid}")
def edit_programme(pid: int, body: ProgrammeBody, request: Request):
    _director(request)
    if body.status not in ("Approved", "Pending", "Returned"):
        raise HTTPException(422, "Status must be Approved, Pending or Returned")
    return qs.save_programme(body.model_dump(), pid)


@router.put("/quotes-admin/settings")
def put_settings(values: dict, request: Request):
    _director(request)
    values.pop("attachments", None)          # files are managed by the attachment endpoints only
    return qs.save_settings(values)


# --- official PDFs attached to HRDC quotations ----------------------------------
# TP certificate, each trainer's profile, and each programme's course outline,
# uploaded once and appended to every HRDC quotation PDF that needs them.

ATTACH_MAX = 10 * 1024 * 1024


def _attachment_slot(kind: str, ref: str):
    if kind == "tp":
        return None
    if kind == "trainer":
        if (ref or "").strip() == "*":
            return "*"
        names = [t.get("name", "") for t in qs.get_settings().get("trainers") or []]
        match = next((n for n in names if n.lower() == (ref or "").strip().lower()), None)
        if not match:
            raise HTTPException(404, "Add this trainer under Settings → Trainer profiles first")
        return match
    if kind == "programme":
        try:
            pid = int(ref)
        except (TypeError, ValueError):
            raise HTTPException(404, "Programme not found")
        if not qs.get_programme(pid):
            raise HTTPException(404, "Programme not found")
        return pid
    raise HTTPException(422, "kind must be tp, trainer or programme")


def _set_attachment(kind: str, slot, value):
    if kind == "programme":
        qs.set_programme_outline_pdf(slot, value)
        return
    att = qs.get_settings().get("attachments") or {"tp_certificate": None, "trainers": {}}
    att.setdefault("trainers", {})
    if kind == "tp":
        att["tp_certificate"] = value
    elif value:
        att["trainers"][slot] = value
    else:
        att["trainers"].pop(slot, None)
    qs.save_settings({"attachments": att})


def _get_attachment(kind: str, slot):
    if kind == "programme":
        return (qs.get_programme(slot) or {}).get("outline_pdf")
    att = qs.get_settings().get("attachments") or {}
    return att.get("tp_certificate") if kind == "tp" else (att.get("trainers") or {}).get(slot)


@router.post("/quotes-admin/attachments")
async def upload_attachment(request: Request, kind: str, ref: str = "", filename: str = "document.pdf"):
    import os
    import stamp_files
    import stamp_pdf
    _director(request)
    slot = _attachment_slot(kind, ref)
    data = b""
    async for chunk in request.stream():
        data += chunk
        if len(data) > ATTACH_MAX:
            raise HTTPException(413, "PDF is larger than 10 MB")
    try:
        stamp_pdf.open_pdf(data, ATTACH_MAX)
    except stamp_pdf.StampError as e:
        raise HTTPException(e.status, e.message)
    key = stamp_files.get_storage().put(data, "pdf")
    name = os.path.basename((filename or "document.pdf").replace("\\", "/"))[:120] or "document.pdf"
    _set_attachment(kind, slot, {"key": key, "name": name, "uploaded": date.today().isoformat()})
    return {"ok": True, "name": name}


@router.delete("/quotes-admin/attachments")
def remove_attachment(request: Request, kind: str, ref: str = ""):
    _director(request)
    _set_attachment(kind, _attachment_slot(kind, ref), None)
    return {"ok": True}


@router.get("/quotes-admin/attachments/file", dependencies=[Depends(auth.require_finance)])
def attachment_file(kind: str, ref: str = ""):
    import stamp_files
    f = _get_attachment(kind, _attachment_slot(kind, ref))
    if not f:
        raise HTTPException(404, "No file uploaded")
    try:
        data = stamp_files.get_storage().get(f["key"])
    except stamp_files.StorageError:
        raise HTTPException(404, "File missing")
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{f["name"]}"', "Cache-Control": "private, no-store"})
