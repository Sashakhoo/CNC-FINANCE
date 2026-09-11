"""
JSON API for the CNC dashboard. Every endpoint mirrors one of the
dashboard's old in-memory array operations (addTransaction, deleteContact,
markPaid, addAsset, saveNotes …) — the dashboard now fetch()es these
instead of mutating JS arrays.

PDF documents (receipt / cash voucher / payment voucher / invoice) are
rendered by the SAME backend.pdf_generator functions the Telegram bot
uses, with numbers drawn from the SAME storage.counters sequences, so
both surfaces produce byte-identical documents.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import storage
import pdf_generator
import auth
import lms_sync

router = APIRouter(prefix="/api")


# --- auth ----------------------------------------------------------------

class Login(BaseModel):
    username: str
    password: str


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


def _set_session_cookie(resp: JSONResponse, request: Request, username: str):
    token = auth.issue_token(username)
    forwarded = request.headers.get("x-forwarded-proto", "")
    is_https = request.url.scheme == "https" or forwarded == "https"
    resp.set_cookie(
        auth.COOKIE_NAME, token, max_age=auth.MAX_AGE, httponly=True,
        samesite="lax", secure=is_https, path="/",
    )


@router.get("/setup")
def setup_status():
    return {"needs_setup": auth.needs_setup()}


class Setup(BaseModel):
    username: str
    password: str


@router.post("/setup")
def do_setup(body: Setup, request: Request):
    ip = _client_ip(request)
    if auth.register_login_attempt(ip):
        raise HTTPException(status_code=429, detail="Too many attempts. Wait a few minutes.")
    username = auth.create_first_account(body.username, body.password)
    auth.clear_login_attempts(ip)
    resp = JSONResponse({"ok": True, "username": username, "role": "director",
                         "caps": auth.caps_for("director")})
    _set_session_cookie(resp, request, username)
    return resp


@router.post("/login")
def login(body: Login, request: Request):
    ip = _client_ip(request)
    if auth.register_login_attempt(ip):
        raise HTTPException(status_code=429, detail="Too many attempts. Wait a few minutes and try again.")
    try:
        username = auth.authenticate(body.username, body.password)
    except auth.NoAccess:
        raise HTTPException(status_code=403, detail="This account has no access. Ask the director.")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    auth.clear_login_attempts(ip)
    role = storage.get_user(username)["role"]
    resp = JSONResponse({"ok": True, "username": username, "role": role,
                         "caps": auth.caps_for(role)})
    _set_session_cookie(resp, request, username)
    return resp


@router.post("/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE_NAME, path="/")
    return resp


@router.get("/me")
def me(user: dict = Depends(auth.require_auth)):
    return {"id": user["id"], "username": user["username"],
            "role": user["role"], "caps": user["caps"]}


# --- account: change your own password ----------------------------------

class PwChange(BaseModel):
    current_password: str
    new_password: str


@router.post("/account/password")
def change_own_password(body: PwChange, user: dict = Depends(auth.require_auth)):
    if auth.authenticate(user["username"], body.current_password) != user["username"]:
        raise HTTPException(400, "Current password is incorrect")
    if len(body.new_password) < 6:
        raise HTTPException(422, "New password must be at least 6 characters")
    salt, h = auth.hash_new(body.new_password)
    storage.set_user_password(user["id"], salt, h)
    return {"ok": True}


# --- users (director only) ---------------------------------------------

class UserIn(BaseModel):
    username: str
    password: str
    role: str = "admin"


class UserPatch(BaseModel):
    role: str | None = None
    active: bool | None = None
    password: str | None = None


@router.get("/users", dependencies=[Depends(auth.require_cap("users"))])
def list_users():
    return storage.list_users()


@router.post("/users", dependencies=[Depends(auth.require_cap("users"))])
def create_user(body: UserIn):
    name = body.username.strip()
    if not name or len(name) > 40:
        raise HTTPException(422, "Username must be 1-40 characters")
    if body.role not in auth.ASSIGNABLE_ROLES:
        raise HTTPException(422, f"Role must be one of {auth.ASSIGNABLE_ROLES}")
    if len(body.password) < 6:
        raise HTTPException(422, "Password must be at least 6 characters")
    if storage.get_user(name):
        raise HTTPException(409, "That username already exists")
    salt, h = auth.hash_new(body.password)
    uid = storage.create_user(name, salt, h, body.role)
    return next(u for u in storage.list_users() if u["id"] == uid)


@router.patch("/users/{uid}", dependencies=[Depends(auth.require_cap("users"))])
def patch_user(uid: int, body: UserPatch, me: dict = Depends(auth.require_auth)):
    target = storage.get_user_by_id(uid)
    if not target:
        raise HTTPException(404, "User not found")

    if body.role is not None:
        if body.role not in auth.ASSIGNABLE_ROLES:
            raise HTTPException(422, f"Role must be one of {auth.ASSIGNABLE_ROLES}")
        if target["role"] == "director" and body.role != "director" \
                and storage.count_active_directors(exclude_id=uid) == 0:
            raise HTTPException(400, "There must be at least one active director")
        storage.update_user(uid, role=body.role)

    if body.active is not None:
        if not body.active and uid == me["id"]:
            raise HTTPException(400, "You can't deactivate your own account")
        if not body.active and target["role"] == "director" \
                and storage.count_active_directors(exclude_id=uid) == 0:
            raise HTTPException(400, "There must be at least one active director")
        storage.update_user(uid, active=body.active)

    if body.password is not None:
        if len(body.password) < 6:
            raise HTTPException(422, "Password must be at least 6 characters")
        salt, h = auth.hash_new(body.password)
        storage.set_user_password(uid, salt, h)

    return next(u for u in storage.list_users() if u["id"] == uid)


@router.delete("/users/{uid}", dependencies=[Depends(auth.require_cap("users"))])
def remove_user(uid: int, me: dict = Depends(auth.require_auth)):
    target = storage.get_user_by_id(uid)
    if not target:
        return {"ok": True}
    if uid == me["id"]:
        raise HTTPException(400, "You can't delete your own account")
    if target["role"] == "director" and storage.count_active_directors(exclude_id=uid) == 0:
        raise HTTPException(400, "There must be at least one active director")
    storage.delete_user(uid)
    return {"ok": True}


# --- aggregate state (one call the dashboard loads on startup) ----------

@router.get("/state", dependencies=[Depends(auth.require_auth)])
def state():
    return {
        "transactions": storage.list_transactions(),
        "contacts": storage.list_contacts(),
        "invoices": storage.list_invoices(),
        "assets": storage.list_assets(),
        "category_codes": storage.list_category_codes(),
        "notes": storage.get_notes(),
    }


# --- transactions ------------------------------------------------------

class TxIn(BaseModel):
    date: str
    description: str
    type: str
    category: str
    amount: float
    payer_payee: str | None = None


@router.get("/transactions", dependencies=[Depends(auth.require_auth)])
def get_transactions():
    return storage.list_transactions()


@router.post("/transactions", dependencies=[Depends(auth.require_cap("transactions"))])
def create_transaction(body: TxIn):
    if body.type not in ("in", "out"):
        raise HTTPException(422, "type must be 'in' or 'out'")
    tx_id = storage.insert_transaction(
        body.date, body.description, body.type, body.category, body.amount,
        payer_payee=body.payer_payee,
    )
    return storage.get_transaction(tx_id)


class TxPatch(BaseModel):
    date: str | None = None
    description: str | None = None
    type: str | None = None
    category: str | None = None
    amount: float | None = None
    payer_payee: str | None = None


@router.patch("/transactions/{tx_id}", dependencies=[Depends(auth.require_cap("transactions"))])
def edit_transaction(tx_id: int, body: TxPatch):
    if not storage.get_transaction(tx_id):
        raise HTTPException(404, "Transaction not found")
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(422, "Nothing to update")
    if "type" in fields and fields["type"] not in ("in", "out"):
        raise HTTPException(422, "type must be 'in' or 'out'")
    # category_code() needs a type; fall back to the row's current type
    if "category" in fields and "type" not in fields:
        fields["type"] = storage.get_transaction(tx_id)["type"]
    storage.update_transaction(tx_id, fields)
    return storage.get_transaction(tx_id)


@router.delete("/transactions/{tx_id}", dependencies=[Depends(auth.require_cap("transactions"))])
def remove_transaction(tx_id: int):
    storage.delete_row("transactions", tx_id)
    return {"ok": True}


# --- contacts --------------------------------------------------------

class ContactIn(BaseModel):
    name: str
    type: str
    balance: float = 0.0
    email: str | None = None
    phone: str | None = None


@router.get("/contacts", dependencies=[Depends(auth.require_auth)])
def get_contacts():
    return storage.list_contacts()


@router.post("/contacts", dependencies=[Depends(auth.require_cap("contacts"))])
def create_contact(body: ContactIn):
    if body.type not in ("debtor", "creditor"):
        raise HTTPException(422, "type must be 'debtor' or 'creditor'")
    return storage.insert_contact(body.name, body.type, body.balance,
                                   email=body.email or "", phone=body.phone or "")


@router.delete("/contacts/{cid}", dependencies=[Depends(auth.require_cap("contacts"))])
def remove_contact(cid: int):
    storage.delete_row("contacts", cid)
    return {"ok": True}


# --- invoices -------------------------------------------------------

class InvoiceItemIn(BaseModel):
    description: str
    qty: float = 1
    unit_price: float = 0


class InvoiceIn(BaseModel):
    contact: str
    date: str
    due: str
    amount: float = 0
    description: str | None = None
    email: str | None = None
    phone: str | None = None
    discount_pct: float = 0.0
    remarks: str | None = None
    items: list[InvoiceItemIn] | None = None


@router.get("/invoices", dependencies=[Depends(auth.require_auth)])
def get_invoices():
    return storage.list_invoices()


@router.post("/invoices", dependencies=[Depends(auth.require_cap("invoices"))])
def create_invoice(body: InvoiceIn):
    storage.find_or_create_contact(body.contact, "debtor", email=body.email or "", phone=body.phone or "")
    number = storage.next_document_number("INV")
    items = [i.model_dump() for i in body.items] if body.items else None
    if not items and not body.amount:
        raise HTTPException(422, "Provide either an amount or at least one line item")
    iid = storage.insert_invoice(number, body.contact, body.date, body.due, body.amount,
                                  status="Pending", description=body.description or "",
                                  discount_pct=body.discount_pct or 0, remarks=body.remarks or "",
                                  items=items)
    return storage.get_invoice(iid)


class QuotationIn(BaseModel):
    contact: str
    date: str
    valid_until: str
    items: list[InvoiceItemIn]
    email: str | None = None
    phone: str | None = None
    discount_pct: float = 0.0
    remarks: str | None = None


@router.post("/quotations/pdf", dependencies=[Depends(auth.require_cap("invoices"))])
def generate_quotation(body: QuotationIn):
    """A quotation is a sales document only — never written to the ledger
    or any table. It shares the INV/PV/CV numbering pool's sibling QUO
    sequence so numbers never collide across document types."""
    if not body.items:
        raise HTTPException(422, "At least one line item is required")
    number = storage.next_document_number("QUO")
    pdf = pdf_generator.render_quotation_pdf(
        number, body.contact, body.date, body.valid_until,
        [i.model_dump() for i in body.items],
        discount_pct=body.discount_pct or 0, remarks=body.remarks,
        email=body.email, phone=body.phone,
    )
    return _pdf_response(pdf, f"{number}.pdf")


def _sync_invoice_to_lms_if_relevant(inv: dict, status: str):
    """After an invoice moves to Paid or Deposit, push it to the LMS so the
    student profile + enrollment get created automatically. Never lets a
    sync failure affect the invoice update itself."""
    if status not in ("Paid", "Deposit"):
        return
    contact = storage.get_contact_by_name(inv["contact"], "debtor")
    note = lms_sync.sync_invoice_to_lms(
        inv, status,
        email=(contact or {}).get("email", ""),
        phone=(contact or {}).get("phone", ""),
    )
    storage.set_invoice_lms_sync(inv["id"], note)


class InvoiceStatusIn(BaseModel):
    status: str


@router.patch("/invoices/{iid}/status", dependencies=[Depends(auth.require_cap("invoices"))])
def update_invoice_status(iid: int, body: InvoiceStatusIn):
    if body.status not in ("Pending", "Deposit", "Paid", "Overdue"):
        raise HTTPException(422, "status must be one of Pending, Deposit, Paid, Overdue")
    inv = storage.set_invoice_status(iid, body.status)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    _sync_invoice_to_lms_if_relevant(inv, body.status)
    return storage.get_invoice(iid)


@router.post("/invoices/{iid}/pay", dependencies=[Depends(auth.require_cap("invoices"))])
def pay_invoice(iid: int):
    inv = storage.mark_invoice_paid(iid)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    _sync_invoice_to_lms_if_relevant(inv, "Paid")
    return storage.get_invoice(iid)


@router.delete("/invoices/{iid}", dependencies=[Depends(auth.require_cap("invoices"))])
def remove_invoice(iid: int):
    storage.delete_row("invoices", iid)
    return {"ok": True}


# --- assets --------------------------------------------------------

class AssetIn(BaseModel):
    name: str
    category: str
    cost: float
    dep: float = 0.0


@router.get("/assets", dependencies=[Depends(auth.require_auth)])
def get_assets():
    return storage.list_assets()


@router.post("/assets", dependencies=[Depends(auth.require_cap("assets"))])
def create_asset(body: AssetIn):
    aid = storage.insert_asset(body.name, body.category, body.cost, body.dep)
    return next(a for a in storage.list_assets() if a["id"] == aid)


@router.delete("/assets/{aid}", dependencies=[Depends(auth.require_cap("assets"))])
def remove_asset(aid: int):
    storage.delete_row("assets", aid)
    return {"ok": True}


# --- notes --------------------------------------------------------

class NotesIn(BaseModel):
    text: str


@router.get("/notes", dependencies=[Depends(auth.require_auth)])
def read_notes():
    return storage.get_notes()


@router.put("/notes", dependencies=[Depends(auth.require_cap("notes"))])
def write_notes(body: NotesIn):
    return storage.save_notes(body.text)


# --- documents (PDF) --------------------------------------------------

def _payer(tx: dict) -> str:
    if tx.get("payer_payee"):
        return tx["payer_payee"]
    desc = tx.get("description", "")
    return desc.split("—")[1].strip() if "—" in desc else (desc or "—")


def _pdf_response(pdf_bytes: bytes, filename: str) -> Response:
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/documents/{kind}/{ref_id}", dependencies=[Depends(auth.require_cap("documents"))])
def generate_document(kind: str, ref_id: int):
    try:
        return _generate_document(kind, ref_id)
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.getLogger("cnc.pdf").exception("PDF generation failed for %s/%s", kind, ref_id)
        # Authenticated (director/admin) endpoint — surface the cause so the
        # owner can see it without digging through deploy logs.
        raise HTTPException(500, f"PDF generation failed: {type(e).__name__}: {e}")


def _generate_document(kind: str, ref_id: int):
    if kind == "invoice":
        inv = storage.get_invoice(ref_id)
        if not inv:
            raise HTTPException(404, "Invoice not found")
        contact = storage.get_contact_by_name(inv["contact"], "debtor") or {}
        pdf = pdf_generator.render_invoice_pdf(
            inv["number"], inv["contact"], inv["date"], inv["due"], inv["amount"],
            description=inv.get("description"), status=inv.get("status"),
            email=contact.get("email"), phone=contact.get("phone"),
            discount_pct=inv.get("discount_pct") or 0, remarks=inv.get("remarks"),
            items=inv.get("items"),
        )
        return _pdf_response(pdf, f"{inv['number']}.pdf")

    tx = storage.get_transaction(ref_id)
    if not tx:
        raise HTTPException(404, "Transaction not found")
    tx = dict(tx)
    party = _payer(tx)

    if kind == "receipt":
        if tx["type"] != "in":
            raise HTTPException(422, "Receipts are only for cash-in transactions")
        no = storage.get_or_create_document_number("receipt", ref_id, "RCP")
        pdf = pdf_generator.render_receipt_pdf(no, tx["date"], party, tx["description"], tx["amount"])
    elif kind == "cash-voucher":
        no = storage.get_or_create_document_number("cash-voucher", ref_id, "CV")
        pdf = pdf_generator.render_voucher_pdf(no, "cash", tx["date"], party, tx["description"], tx["category"], tx["amount"])
    elif kind == "payment-voucher":
        no = storage.get_or_create_document_number("payment-voucher", ref_id, "PV")
        pdf = pdf_generator.render_voucher_pdf(no, "payment", tx["date"], party, tx["description"], tx["category"], tx["amount"])
    else:
        raise HTTPException(404, "Unknown document kind")

    return _pdf_response(pdf, f"{no}.pdf")
