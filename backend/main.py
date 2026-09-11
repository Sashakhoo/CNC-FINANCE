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
import re
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

# Same idea, separate store, for /student registrations pending confirmation
# before they're pushed to the LMS (kept apart from PENDING/transactions so
# the confirm/cancel callback_data prefixes can never collide).
PENDING_STUDENTS = {}


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


def _parse_doc_fields(body: str) -> dict:
    """Parses the multi-line /invoice and /quote field format:
        Contact: Name
        Email: optional
        Phone: optional
        Due: YYYY-MM-DD      (or "Valid:" for /quote)
        Discount: 10
        Remarks: free text
        Item: description, qty, unit price   (repeatable)
    """
    fields = {"items": []}
    for line in body.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "item":
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
        elif key in ("contact", "email", "phone", "due", "valid", "remarks"):
            fields[key] = value
    return fields


# Bilingual (Chinese/English) label -> field aliases for /student. Matches
# registration slips like:
#   姓名：许玟涵 Koh Wen Han          Name: Celeste Lee
#   电话号码：0108212528              Phone: +65 91174188
#   邮件：whkoh12@gmail.com          Email: celesteleeling@gmail.com
#   course : AI for workplace        workshop/course: AI for workplace
#   Date : 12/9/2026                 Date : 12/9/2026
#   Time : 2PM-6PM                   Time: 2PM-6 PM
_STUDENT_LABEL_ALIASES = {
    "name": ("姓名", "名字", "name"),
    "phone": ("电话号码", "电话", "手机号码", "手机", "phone", "tel"),
    "email": ("邮件", "邮箱", "email", "e-mail"),
    "course": ("课程", "workshop/course", "workshop", "course"),
    "date": ("日期", "date"),
    "time": ("时间", "time"),
}


def _parse_student_fields(body: str) -> dict:
    """Parses a free-form 'label: value' registration slip (Chinese and/or
    English labels, half- or full-width colon) into
    {name, phone, email, course, date, time} — whichever fields are present.
    Unrecognised lines (e.g. "我需要一些资料") are ignored."""
    fields = {}
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = re.split(r"[:：]", line, maxsplit=1)
        if len(parts) != 2:
            continue
        label, value = parts[0].strip().lower(), parts[1].strip()
        if not value:
            continue
        for key, aliases in _STUDENT_LABEL_ALIASES.items():
            if label in aliases:
                fields[key] = value
                break
    return fields


def format_student_pending(f: dict) -> str:
    return (
        f"<b>New student registration</b>\n"
        f"👤 {f.get('name') or '—'}\n"
        f"✉️ {f.get('email') or '—'}\n"
        f"📱 {f.get('phone') or '—'}\n"
        f"📚 {f.get('course') or '—'}\n"
        f"📅 {f.get('date') or '—'}  ⏰ {f.get('time') or '—'}\n\n"
        f"Create this student in the LMS?"
    )


def student_confirm_keyboard(pending_key):
    return {
        "inline_keyboard": [[
            {"text": "✅ Confirm", "callback_data": f"sconfirm:{pending_key}"},
            {"text": "❌ Cancel", "callback_data": f"scancel:{pending_key}"},
        ]]
    }


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
            "<b>Multi-line invoice</b> (several line items, like a quotation):\n"
            "<code>/invoice\nContact: Sinar Retail\nDue: 2026-09-24\n"
            "Item: AI for Automation, 3, 288\nItem: Vibe Coding, 3, 800\n"
            "Discount: 10\nRemarks: Weekly Saturday sessions</code>\n\n"
            "<b>Quotation</b> (same multi-line format, never logged to the ledger):\n"
            "<code>/quote\nContact: Sinar Retail\nValid: 2026-09-24\n"
            "Item: AI for Automation, 3, 288</code>\n\n"
            "<b>New student</b> (creates/enrolls in the LMS — Chinese or English labels, any order):\n"
            "<code>/student\n姓名：许玟涵 Koh Wen Han\n电话号码：0108212528\n"
            "邮件：whkoh12@gmail.com\ncourse : AI for workplace\n"
            "Date : 12/9/2026\nTime : 2PM-6PM</code>\n\n"
            "<b>Certificate</b> (looks up completion on the LMS, generates the PDF here):\n"
            "<code>/cert Celeste Lee</code> or <code>/cert celesteleeling@gmail.com | AI for Workplace</code>"
        )
        return {"ok": True}

    if "text" in msg and msg["text"].startswith("/student"):
        body = msg["text"][len("/student"):].strip()
        fields = _parse_student_fields(body)
        missing = [k for k in ("name", "email", "course") if not fields.get(k)]
        if missing:
            await tg_send_message(
                chat_id,
                f"Missing {', '.join(missing)}. Send /student with no arguments to see the format."
            )
            return {"ok": True}
        key = f"{chat_id}:{msg['message_id']}"
        PENDING_STUDENTS[key] = fields
        await tg_send_message(chat_id, format_student_pending(fields), reply_markup=student_confirm_keyboard(key))
        return {"ok": True}

    if "text" in msg and msg["text"].startswith("/cert"):
        body = msg["text"][len("/cert"):].strip()
        if not body:
            await tg_send_message(
                chat_id,
                "Usage: <code>/cert Name or email</code>\n"
                "or <code>/cert Name or email | Course title</code> to pick a specific "
                "course when the student completed more than one."
            )
            return {"ok": True}
        identifier, _, course_filter = body.partition("|")
        identifier, course_filter = identifier.strip(), course_filter.strip()

        data, err = lms_sync.lookup_student_completion(identifier)
        if not data or not data.get("courses"):
            await tg_send_message(chat_id, f"⚠️ {err or 'Student not found in the LMS.'}")
            return {"ok": True}

        courses = data["courses"]
        if course_filter:
            courses = [c for c in courses if course_filter.lower() in c.get("title", "").lower()]
            if not courses:
                titles = ", ".join(c.get("title", "") for c in data["courses"])
                await tg_send_message(chat_id, f"No completed course matching \"{course_filter}\". "
                                                 f"Completed courses on file: {titles}")
                return {"ok": True}

        course = sorted(courses, key=lambda c: c.get("completed_at") or "", reverse=True)[0]
        extra_note = ""
        if len(courses) > 1 and not course_filter:
            others = ", ".join(c.get("title", "") for c in courses if c is not course)
            extra_note = f" (most recent completion; also completed: {others} — add \"| course title\" to pick one)"

        no = storage.next_document_number("CERT")
        pdf = pdf_generator.render_certificate_pdf(
            data.get("name") or identifier, course.get("title", ""),
            course.get("completed_at") or today, no,
        )
        await tg_send_document(chat_id, f"{no}.pdf", pdf,
                                caption=f"{no} — {data.get('name')} — {course.get('title')}{extra_note}")
        return {"ok": True}

    if "text" in msg and (msg["text"].startswith("/invoice") or msg["text"].startswith("/quote")):
        is_quote = msg["text"].startswith("/quote")
        cmd = "/quote" if is_quote else "/invoice"
        body = msg["text"][len(cmd):].strip()

        if "\n" in body or "item:" in body.lower():
            fields = _parse_doc_fields(body)
            contact_name = fields.get("contact", "")
            items = fields.get("items", [])
            when = fields.get("valid" if is_quote else "due", "")
            if not contact_name or not items or not when:
                await tg_send_message(chat_id, f"Need at least Contact:, {'Valid:' if is_quote else 'Due:'}, "
                                                 "and one Item: line (description, qty, unit price).")
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

        if is_quote:
            await tg_send_message(chat_id, "Quotations need the multi-line format — send /quote with no "
                                             "arguments to see it.")
            return {"ok": True}

        # Legacy single-line-item /invoice — unchanged.
        description = ""
        if "|" in body:
            parts_pipe = [f.strip() for f in body.split("|")]
            if len(parts_pipe) < 3:
                await tg_send_message(chat_id, "Format: /invoice Contact | Amount | YYYY-MM-DD | Description")
                return {"ok": True}
            contact_name, amount_str, due = parts_pipe[0], parts_pipe[1], parts_pipe[2]
            description = parts_pipe[3] if len(parts_pipe) > 3 else ""
        else:
            parts = body.split()
            if len(parts) < 3:
                await tg_send_message(chat_id, "Format: /invoice ContactName Amount YYYY-MM-DD\ne.g. /invoice Sinar Retail 4200 2026-09-24")
                return {"ok": True}
            due = parts[-1]
            amount_str = parts[-2]
            contact_name = " ".join(parts[:-2])
        try:
            amount = float(amount_str)
        except ValueError:
            await tg_send_message(chat_id, "Couldn't read the amount — make sure it's a plain number, e.g. 4200")
            return {"ok": True}
        if not contact_name:
            await tg_send_message(chat_id, "Missing contact name.")
            return {"ok": True}
        storage.find_or_create_contact(contact_name, "debtor")
        no = storage.next_document_number("INV")
        storage.insert_invoice(no, contact_name, today, due, amount, status="Pending", description=description)
        pdf = pdf_generator.render_invoice_pdf(no, contact_name, today, due, amount, description=description)
        caption = f"{no} — {contact_name} — RM {amount:,.2f}, due {due}"
        await tg_send_document(chat_id, f"{no}.pdf", pdf, caption=caption)
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

    if data.startswith("sconfirm:"):
        key = data.split(":", 1)[1]
        f = PENDING_STUDENTS.pop(key, None)
        if not f:
            await tg_answer_callback(callback_id, "This entry already expired.")
            return
        await tg_answer_callback(callback_id, "Creating…")
        note = lms_sync.create_student(
            name=f.get("name", ""), email=f.get("email", ""), phone=f.get("phone", ""),
            course=f.get("course", ""), session_date=f.get("date", ""), session_time=f.get("time", ""),
        )
        await tg_send_message(chat_id, f"👤 <b>{f.get('name')}</b>\n{note}")
        return

    if data.startswith("scancel:"):
        key = data.split(":", 1)[1]
        PENDING_STUDENTS.pop(key, None)
        await tg_answer_callback(callback_id, "Cancelled")
        await tg_send_message(chat_id, "Discarded — no student created.")
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
