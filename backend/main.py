"""
CNC Finance Telegram bot — send a message or a receipt photo, confirm what got
parsed, and it logs the transaction plus generates the matching PDF
(Receipt for cash in, Payment Voucher for cash out, Cash Voucher on
request) straight back into the chat.

Deploy: same GitHub + Railway pipeline as your other bots. Set the env
vars from .env.example in Railway's dashboard, then run the /set-webhook
step described in README.md once after deploying.
"""
import os
import io
from datetime import date as _date

import pathlib

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import storage
import seed
import migrations
import auth
import gemini_parser
import pdf_generator
import lms_sync
from api import router as api_router

FRONTEND_DIR = pathlib.Path(__file__).resolve().parent.parent / "frontend"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
TELEGRAM_FILE_API = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}"
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
ALLOWED_USER_IDS = {
    int(x) for x in os.environ.get("ALLOWED_USER_IDS", "").split(",") if x.strip()
}

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


# --- security headers ------------------------------------------------------
@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    # The dashboard is a single self-contained file plus Google Fonts.
    resp.headers.setdefault("Content-Security-Policy", (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ))
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    if proto == "https":
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return resp

# In-memory "pending confirmation" store: message_id -> parsed transaction.
# Fine for a single-instance deploy; move to Redis/DB if you scale to
# multiple workers or want pending items to survive a restart.
PENDING = {}


@app.on_event("startup")
def on_startup():
    storage.init_db()
    auth.seed_users()
    if seed.seed_if_empty():
        print("Seeded historical ledger (Apr-Aug 2026) into an empty database.")
    migrations.run_migrations()


app.include_router(api_router)


@app.get("/health")
def health():
    return {"status": "ok"}


app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return FileResponse(FRONTEND_DIR / "dashboard.html")


@app.get("/favicon.ico")
def favicon():
    return FileResponse(FRONTEND_DIR / "assets" / "favicon.ico")


# --- Telegram helpers -------------------------------------------------------

async def tg_send_message(chat_id, text, reply_markup=None):
    async with httpx.AsyncClient(timeout=20) as client:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        r = await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)
        return r.json()


async def tg_send_document(chat_id, filename, file_bytes, caption=None):
    async with httpx.AsyncClient(timeout=30) as client:
        files = {"document": (filename, file_bytes, "application/pdf")}
        data = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption
        await client.post(f"{TELEGRAM_API}/sendDocument", data=data, files=files)


async def tg_answer_callback(callback_id, text=None):
    async with httpx.AsyncClient(timeout=20) as client:
        payload = {"callback_query_id": callback_id}
        if text:
            payload["text"] = text
        await client.post(f"{TELEGRAM_API}/answerCallbackQuery", json=payload)


async def tg_get_file_bytes(file_id):
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{TELEGRAM_API}/getFile", params={"file_id": file_id})
        file_path = r.json()["result"]["file_path"]
        r2 = await client.get(f"{TELEGRAM_FILE_API}/{file_path}")
        return r2.content, file_path


def confirm_keyboard(pending_key):
    return {
        "inline_keyboard": [[
            {"text": "✅ Confirm", "callback_data": f"confirm:{pending_key}"},
            {"text": "❌ Cancel", "callback_data": f"cancel:{pending_key}"},
        ]]
    }


def document_keyboard(tx_id, tx_type):
    if tx_type == "in":
        return {"inline_keyboard": [[
            {"text": "🧾 Receipt", "callback_data": f"doc:receipt:{tx_id}"},
            {"text": "📗 Cash Voucher", "callback_data": f"doc:cash:{tx_id}"},
        ]]}
    return {"inline_keyboard": [[
        {"text": "📕 Payment Voucher", "callback_data": f"doc:payment:{tx_id}"},
    ]]}


def format_pending_summary(parsed):
    arrow = "IN ⬆️" if parsed["type"] == "in" else "OUT ⬇️"
    return (
        f"<b>{arrow}</b>  RM {parsed['amount']:,.2f}\n"
        f"📅 {parsed['date']}\n"
        f"🏷 {parsed['category']}\n"
        f"👤 {parsed.get('payer_or_payee') or '—'}\n"
        f"📝 {parsed['description']}\n\n"
        f"Log this?"
    )


def is_allowed(user_id):
    return not ALLOWED_USER_IDS or user_id in ALLOWED_USER_IDS


def _safe_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_doc_fields(body: str) -> dict:
    """Parses the multi-line /invoice and /quote field format:
        Contact: Name        (or "Name:")
        Email: optional
        Phone: optional
        Due: YYYY-MM-DD      (or "Valid:" for /quote) — optional
        Discount: 10
        Remarks: free text
        Item: description, qty, unit price   (repeatable — or "Course:")
    """
    fields = {"items": []}
    for line in body.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key in ("item", "course"):
            # Split from the right so a description containing its own
            # commas (e.g. "Claude - Chat, Code & Cowork") isn't broken up —
            # only the trailing qty and unit price are peeled off.
            parts = [p.strip() for p in value.rsplit(",", 2)]
            try:
                price = float(parts[-1]) if len(parts) >= 3 else 0.0
            except ValueError:
                price = 0.0
            try:
                qty = float(parts[-2]) if len(parts) >= 2 else 1.0
            except ValueError:
                qty = 1.0
            desc = parts[0] if len(parts) >= 3 else value
            if not desc:
                continue
            fields["items"].append({"description": desc, "qty": qty, "unit_price": price})
        elif key == "discount":
            try:
                fields["discount"] = float(value.replace("%", "").strip())
            except ValueError:
                pass
        elif key in ("contact", "name"):
            fields["contact"] = value
        elif key in ("email", "phone", "due", "valid", "remarks"):
            fields[key] = value
    return fields


# --- Webhook -----------------------------------------------------------------

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    # Telegram echoes the secret set via setWebhook(secret_token=...) in this
    # header — reject anything that doesn't carry it, so the endpoint can't be
    # driven by random POSTs (which would still cost Gemini calls).
    if TELEGRAM_WEBHOOK_SECRET:
        if request.headers.get("x-telegram-bot-api-secret-token") != TELEGRAM_WEBHOOK_SECRET:
            return JSONResponse({"ok": False}, status_code=403)

    update = await request.json()

    if "callback_query" in update:
        await handle_callback(update["callback_query"])
        return {"ok": True}

    if "message" not in update:
        return {"ok": True}

    msg = update["message"]
    chat_id = msg["chat"]["id"]
    user_id = msg["from"]["id"]

    if not is_allowed(user_id):
        await tg_send_message(chat_id, "This bot is restricted. Ask the owner to add your Telegram user ID to ALLOWED_USER_IDS.")
        return {"ok": True}

    today = _date.today().isoformat()

    if "text" in msg and msg["text"].startswith("/start"):
        await tg_send_message(
            chat_id,
            "👋 Send me a transaction as text (e.g. \"received RM800 from Ali for vibe coding class\") "
            "or forward/upload a photo of a receipt, and I'll parse it, log it, and generate the "
            "matching PDF (Receipt / Cash Voucher / Payment Voucher).\n\n"
            "<b>Quick invoice</b> (one line item):\n"
            "<code>/invoice ContactName Amount YYYY-MM-DD</code>\n"
            "e.g. <code>/invoice Sinar Retail 4200 2026-09-24</code>\n"
            "or with a description: <code>/invoice Contact | Amount | YYYY-MM-DD | Description</code>\n\n"
            "<b>Multi-line invoice</b> (several line items, like a quotation — "
            "Name:/Course: also work instead of Contact:/Item:, and Due: is optional):\n"
            "<code>/invoice\nName: Sinar Retail\n"
            "Course: AI for Automation, 3, 288\nCourse: Vibe Coding, 3, 800\n"
            "Discount: 10\nRemarks: Weekly Saturday sessions</code>\n\n"
            "<b>Quotation</b> (same multi-line format, never logged to the ledger):\n"
            "<code>/quote\nContact: Sinar Retail\nValid: 2026-09-24\n"
            "Item: AI for Automation, 3, 288</code>\n\n"
            "Don't want to match any of these exactly? Just write it naturally, "
            "e.g. <code>/invoice Samuel Kam, Python Fundamentals RM1500, "
            "loadinginterestexe@gmail.com</code> — I'll read it either way.\n\n"
            "<b>Mark an invoice paid</b> (posts the income transaction + clears their balance):\n"
            "<code>/paid INV-164</code> (or just <code>/paid 164</code>)"
        )
        return {"ok": True}

    if "text" in msg and (msg["text"].startswith("/invoice") or msg["text"].startswith("/quote")):
        is_quote = msg["text"].startswith("/quote")
        cmd = "/quote" if is_quote else "/invoice"
        body = msg["text"][len(cmd):].strip()

        # 1) Cheap legacy positional parse for /invoice — unchanged, no AI
        #    involved, only when the message is plainly in that exact shape
        #    (no "Key:" labels at all — those go through the parsers below).
        if not is_quote and body and ":" not in body:
            description = ""
            if "|" in body:
                parts_pipe = [f.strip() for f in body.split("|")]
                if len(parts_pipe) >= 3:
                    contact_name, amount_str, due = parts_pipe[0], parts_pipe[1], parts_pipe[2]
                    description = parts_pipe[3] if len(parts_pipe) > 3 else ""
                    amount = _safe_float(amount_str)
                else:
                    contact_name = amount = due = None
            else:
                parts = body.split()
                if len(parts) >= 3:
                    due, amount_str = parts[-1], parts[-2]
                    contact_name = " ".join(parts[:-2])
                    amount = _safe_float(amount_str)
                else:
                    contact_name = amount = due = None
            if contact_name and amount is not None:
                storage.find_or_create_contact(contact_name, "debtor")
                no = storage.next_document_number("INV")
                storage.insert_invoice(no, contact_name, today, due, amount, status="Pending", description=description)
                pdf = pdf_generator.render_invoice_pdf(no, contact_name, today, due, amount, description=description)
                await tg_send_document(chat_id, f"{no}.pdf", pdf,
                                        caption=f"{no} — {contact_name} — RM {amount:,.2f}, due {due}")
                return {"ok": True}
            # Didn't cleanly fit the legacy shape — fall through to the
            # structured/AI parse below instead of erroring immediately.

        # 2) Structured "Key: value" parse (free, no AI) — Contact:/Name:,
        #    Item:/Course:, Email:, Phone:, Due:/Valid:, Discount:, Remarks:.
        fields = _parse_doc_fields(body) if body else {"items": []}

        # 3) If that didn't find both a contact and at least one item, let
        #    Gemini read the free-form text instead of rejecting it — the
        #    message doesn't have to follow any particular line format.
        if body and (not fields.get("contact") or not fields.get("items")):
            try:
                ai_fields = await gemini_parser.parse_invoice_fields(body, today)
            except Exception as exc:
                ai_fields = {}
                await tg_send_message(chat_id, f"⚠️ Couldn't reach Gemini to read that: {exc}")
                return {"ok": True}
            fields = {
                "contact": fields.get("contact") or ai_fields.get("contact") or "",
                "email": fields.get("email") or ai_fields.get("email"),
                "phone": fields.get("phone") or ai_fields.get("phone"),
                "due": fields.get("due") or ai_fields.get("due") or "",
                "valid": fields.get("valid") or ai_fields.get("due") or "",
                "discount": fields.get("discount") or ai_fields.get("discount") or 0.0,
                "remarks": fields.get("remarks") or ai_fields.get("remarks"),
                "items": fields.get("items") or ai_fields.get("items") or [],
            }

        contact_name = fields.get("contact", "")
        items = fields.get("items", [])
        when = fields.get("valid" if is_quote else "due", "")
        if not contact_name or not items:
            await tg_send_message(chat_id, "Couldn't find enough info for an invoice — I need at least "
                                             "a customer name and one course/item (with a price if you "
                                             "have it). Send it however reads naturally, e.g. \"Invoice "
                                             "Samuel Kam, Python Fundamentals RM1500\".")
            return {"ok": True}
        discount = fields.get("discount", 0.0)
        remarks = fields.get("remarks")
        email = fields.get("email")
        phone = fields.get("phone")

        if is_quote:
            no = storage.next_document_number("QUO")
            pdf = pdf_generator.render_quotation_pdf(no, contact_name, today, when, items,
                                                      discount_pct=discount, remarks=remarks,
                                                      email=email, phone=phone)
        else:
            storage.find_or_create_contact(contact_name, "debtor", email=email or "", phone=phone or "")
            no = storage.next_document_number("INV")
            iid = storage.insert_invoice(no, contact_name, today, when, 0, status="Pending",
                                          remarks=remarks or "", discount_pct=discount, items=items)
            inv = storage.get_invoice(iid)
            pdf = pdf_generator.render_invoice_pdf(no, contact_name, today, when, inv["amount"],
                                                    status="Pending", email=email, phone=phone,
                                                    discount_pct=discount, remarks=remarks, items=items)
        total = sum((i.get("qty", 1) or 1) * (i.get("unit_price", 0) or 0) for i in items)
        total *= (1 - (discount or 0) / 100)
        await tg_send_document(chat_id, f"{no}.pdf", pdf,
                                caption=f"{no} — {contact_name} — RM {total:,.2f}")
        return {"ok": True}

    if "text" in msg and msg["text"].startswith("/paid"):
        number = msg["text"][len("/paid"):].strip()
        if not number:
            await tg_send_message(chat_id, "Usage: <code>/paid INV-164</code> (or just <code>/paid 164</code>)")
            return {"ok": True}
        inv = storage.get_invoice_by_number(number)
        if not inv:
            await tg_send_message(chat_id, f"Couldn't find an invoice matching \"{number}\" — check the number and try again.")
            return {"ok": True}
        if inv["status"] == "Paid":
            await tg_send_message(chat_id, f"{inv['number']} ({inv['contact']}) is already marked Paid — nothing to do.")
            return {"ok": True}
        updated = storage.mark_invoice_paid(inv["id"])
        tx_id = updated.pop("_transaction_id", None)
        await tg_send_message(
            chat_id,
            f"✅ {updated['number']} marked <b>Paid</b>\n"
            f"👤 {updated['contact']}\n"
            f"💰 RM {updated['amount']:,.2f}\n"
            f"Logged to the ledger and their balance is cleared."
        )
        if tx_id:
            tx = storage.get_transaction(tx_id)
            rcp_no = storage.get_or_create_document_number("receipt", tx_id, "RCP")
            pdf = pdf_generator.render_receipt_pdf(rcp_no, tx["date"], tx["payer_payee"], tx["description"], tx["amount"])
            await tg_send_document(chat_id, f"{rcp_no}.pdf", pdf, caption=f"{rcp_no} — RM {tx['amount']:,.2f}")

        # Same LMS auto-enroll sync the dashboard's "mark paid" button
        # triggers — fire-and-log, never blocks the invoice update itself.
        contact = storage.get_contact_by_name(updated["contact"], "debtor")
        note = lms_sync.sync_invoice_to_lms(
            updated, "Paid",
            email=(contact or {}).get("email", ""),
            phone=(contact or {}).get("phone", ""),
        )
        storage.set_invoice_lms_sync(updated["id"], note)
        await tg_send_message(chat_id, f"🔗 LMS: {note}")
        return {"ok": True}

    try:
        if "photo" in msg:
            file_id = msg["photo"][-1]["file_id"]  # largest size
            img_bytes, file_path = await tg_get_file_bytes(file_id)
            mime = "image/png" if file_path.endswith(".png") else "image/jpeg"
            caption = msg.get("caption", "")
            parsed = await gemini_parser.parse_image(img_bytes, mime, caption, today)
        elif "text" in msg:
            parsed = await gemini_parser.parse_text(msg["text"], today)
        else:
            await tg_send_message(chat_id, "I can only read text messages or photos right now.")
            return {"ok": True}
    except Exception as e:
        await tg_send_message(chat_id, f"⚠️ Couldn't reach Gemini: {e}")
        return {"ok": True}

    if not parsed.get("amount"):
        await tg_send_message(chat_id, "🤔 I couldn't confidently find an amount in that — try rephrasing with the figure spelled out, e.g. \"RM250\".")
        return {"ok": True}

    key = f"{chat_id}:{msg['message_id']}"
    PENDING[key] = {**parsed, "chat_id": chat_id}
    await tg_send_message(chat_id, format_pending_summary(parsed), reply_markup=confirm_keyboard(key))
    return {"ok": True}


async def handle_callback(cb):
    callback_id = cb["id"]
    chat_id = cb["message"]["chat"]["id"]
    data = cb["data"]

    if data.startswith("confirm:"):
        key = data.split(":", 1)[1]
        parsed = PENDING.pop(key, None)
        if not parsed:
            await tg_answer_callback(callback_id, "This entry already expired.")
            return
        tx_id = storage.insert_transaction(
            date=parsed["date"], description=parsed["description"], tx_type=parsed["type"],
            category=parsed["category"], amount=parsed["amount"],
            payer_payee=parsed.get("payer_or_payee"), chat_id=chat_id,
        )
        await tg_answer_callback(callback_id, "Logged ✅")
        await tg_send_message(chat_id, "Logged to the ledger. Generate a document for it?",
                               reply_markup=document_keyboard(tx_id, parsed["type"]))
        return

    if data.startswith("cancel:"):
        key = data.split(":", 1)[1]
        PENDING.pop(key, None)
        await tg_answer_callback(callback_id, "Cancelled")
        await tg_send_message(chat_id, "Discarded — nothing was logged.")
        return

    if data.startswith("doc:"):
        _, doc_type, tx_id = data.split(":")
        tx = storage.get_transaction(int(tx_id))
        if not tx:
            await tg_answer_callback(callback_id, "Transaction not found.")
            return
        payer = tx["payer_payee"] or "—"

        if doc_type == "receipt":
            no = storage.next_document_number("RCP")
            pdf = pdf_generator.render_receipt_pdf(no, tx["date"], payer, tx["description"], tx["amount"])
            filename = f"{no}.pdf"
        elif doc_type == "cash":
            no = storage.next_document_number("CV")
            pdf = pdf_generator.render_voucher_pdf(no, "cash", tx["date"], payer, tx["description"], tx["category"], tx["amount"])
            filename = f"{no}.pdf"
        else:  # payment
            no = storage.next_document_number("PV")
            pdf = pdf_generator.render_voucher_pdf(no, "payment", tx["date"], payer, tx["description"], tx["category"], tx["amount"])
            filename = f"{no}.pdf"

        await tg_answer_callback(callback_id, "Generating…")
        await tg_send_document(chat_id, filename, pdf, caption=f"{filename} — RM {tx['amount']:,.2f}")
        return


# --- One-off setup helper: run `python main.py` locally to register the
# webhook with Telegram after you've deployed and have a PUBLIC_URL. -------
if __name__ == "__main__":
    import asyncio

    async def set_webhook():
        public_url = os.environ["PUBLIC_URL"].rstrip("/")
        payload = {"url": f"{public_url}/telegram/webhook"}
        if TELEGRAM_WEBHOOK_SECRET:
            payload["secret_token"] = TELEGRAM_WEBHOOK_SECRET
        else:
            print("note: TELEGRAM_WEBHOOK_SECRET not set — webhook will accept unauthenticated POSTs.")
        async with httpx.AsyncClient() as client:
            r = await client.post(f"{TELEGRAM_API}/setWebhook", json=payload)
            print(r.json())

    asyncio.run(set_webhook())
