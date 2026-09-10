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

router = APIRouter(prefix="/api")


# --- auth ----------------------------------------------------------------

class Login(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: Login, request: Request):
    username = auth.authenticate(body.username, body.password)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = auth.issue_token(username)
    role = auth.USERS[username]["role"]
    resp = JSONResponse({"ok": True, "username": username, "role": role,
                         "can_write": role in auth.WRITE_ROLES})
    # Secure cookie in production (https); relaxed for local http development.
    forwarded = request.headers.get("x-forwarded-proto", "")
    is_https = request.url.scheme == "https" or forwarded == "https"
    resp.set_cookie(
        auth.COOKIE_NAME, token, max_age=auth.MAX_AGE, httponly=True,
        samesite="lax", secure=is_https, path="/",
    )
    return resp


@router.post("/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE_NAME, path="/")
    return resp


@router.get("/me")
def me(user: dict = Depends(auth.require_auth)):
    return {"username": user["username"], "role": user["role"],
            "can_write": user["role"] in auth.WRITE_ROLES}


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


@router.post("/transactions", dependencies=[Depends(auth.require_write)])
def create_transaction(body: TxIn):
    if body.type not in ("in", "out"):
        raise HTTPException(422, "type must be 'in' or 'out'")
    tx_id = storage.insert_transaction(
        body.date, body.description, body.type, body.category, body.amount,
        payer_payee=body.payer_payee,
    )
    return storage.get_transaction(tx_id)


@router.delete("/transactions/{tx_id}", dependencies=[Depends(auth.require_write)])
def remove_transaction(tx_id: int):
    storage.delete_row("transactions", tx_id)
    return {"ok": True}


# --- contacts --------------------------------------------------------

class ContactIn(BaseModel):
    name: str
    type: str
    balance: float = 0.0


@router.get("/contacts", dependencies=[Depends(auth.require_auth)])
def get_contacts():
    return storage.list_contacts()


@router.post("/contacts", dependencies=[Depends(auth.require_write)])
def create_contact(body: ContactIn):
    if body.type not in ("debtor", "creditor"):
        raise HTTPException(422, "type must be 'debtor' or 'creditor'")
    return storage.insert_contact(body.name, body.type, body.balance)


@router.delete("/contacts/{cid}", dependencies=[Depends(auth.require_write)])
def remove_contact(cid: int):
    storage.delete_row("contacts", cid)
    return {"ok": True}


# --- invoices -------------------------------------------------------

class InvoiceIn(BaseModel):
    contact: str
    date: str
    due: str
    amount: float


@router.get("/invoices", dependencies=[Depends(auth.require_auth)])
def get_invoices():
    return storage.list_invoices()


@router.post("/invoices", dependencies=[Depends(auth.require_write)])
def create_invoice(body: InvoiceIn):
    storage.find_or_create_contact(body.contact, "debtor")
    number = storage.next_document_number("INV")
    iid = storage.insert_invoice(number, body.contact, body.date, body.due, body.amount, status="Unpaid")
    return storage.get_invoice(iid)


@router.post("/invoices/{iid}/pay", dependencies=[Depends(auth.require_write)])
def pay_invoice(iid: int):
    inv = storage.mark_invoice_paid(iid)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    return inv


@router.delete("/invoices/{iid}", dependencies=[Depends(auth.require_write)])
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


@router.post("/assets", dependencies=[Depends(auth.require_write)])
def create_asset(body: AssetIn):
    aid = storage.insert_asset(body.name, body.category, body.cost, body.dep)
    return next(a for a in storage.list_assets() if a["id"] == aid)


@router.delete("/assets/{aid}", dependencies=[Depends(auth.require_write)])
def remove_asset(aid: int):
    storage.delete_row("assets", aid)
    return {"ok": True}


# --- notes --------------------------------------------------------

class NotesIn(BaseModel):
    text: str


@router.get("/notes", dependencies=[Depends(auth.require_auth)])
def read_notes():
    return storage.get_notes()


@router.put("/notes", dependencies=[Depends(auth.require_write)])
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


@router.get("/documents/{kind}/{ref_id}", dependencies=[Depends(auth.require_auth)])
def generate_document(kind: str, ref_id: int):
    if kind == "invoice":
        inv = storage.get_invoice(ref_id)
        if not inv:
            raise HTTPException(404, "Invoice not found")
        pdf = pdf_generator.render_invoice_pdf(
            inv["number"], inv["contact"], inv["date"], inv["due"], inv["amount"]
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
