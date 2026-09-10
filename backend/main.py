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
import auth
import gemini_parser
import pdf_generator
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
            "👋 Send me a transaction as text (e.g. \"received RM800 from Zaid for vibe coding class\") "
            "or forward/upload a photo of a receipt, and I'll parse it, log it, and generate the "
            "matching PDF (Receipt / Cash Voucher / Payment Voucher).\n\n"
            "To create an invoice directly: <code>/invoice ContactName Amount YYYY-MM-DD</code>\n"
            "e.g. <code>/invoice Sinar Retail 4200 2026-09-24</code>"
        )
        return {"ok": True}

    if "text" in msg and msg["text"].startswith("/invoice"):
        parts = msg["text"].split()
        if len(parts) < 4:
            await tg_send_message(chat_id, "Format: /invoice ContactName Amount YYYY-MM-DD\ne.g. /invoice Sinar Retail 4200 2026-09-24")
            return {"ok": True}
        due = parts[-1]
        amount_str = parts[-2]
        contact_name = " ".join(parts[1:-2])
        try:
            amount = float(amount_str)
        except ValueError:
            await tg_send_message(chat_id, "Couldn't read the amount — make sure it's a plain number, e.g. 4200")
            return {"ok": True}
        storage.find_or_create_contact(contact_name, "debtor")
        no = storage.next_document_number("INV")
        storage.insert_invoice(no, contact_name, today, due, amount, status="Unpaid")
        pdf = pdf_generator.render_invoice_pdf(no, contact_name, today, due, amount)
        await tg_send_document(chat_id, f"{no}.pdf", pdf, caption=f"{no} — {contact_name} — RM {amount:,.2f}, due {due}")
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
