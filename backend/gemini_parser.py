"""
Extracts a structured transaction (date, type, category, amount, payer/payee,
description) from a free-text message or a photo of a receipt, using a
Gemini Flash-Lite tier model — the cheapest currently-available option that
still accepts images.

IMPORTANT: Gemini model names and pricing change frequently. Check
https://ai.google.dev/gemini-api/docs/models before deploying and set
GEMINI_MODEL in .env to whatever is current — don't assume the default
below is still the cheapest or even still available.
"""
import os
import json
import base64
import httpx

from storage import CATEGORY_CHOICES

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

EXTRACTION_PROMPT = f"""You are a bookkeeping assistant for a Malaysian sole
proprietorship that runs coding/AI education courses and consulting projects
(business name: Code N Code Solution). Extract ONE financial transaction
from the user's message or the attached receipt/photo.

Respond with ONLY valid JSON (no markdown fences, no commentary), matching
exactly this shape:
{{
  "date": "YYYY-MM-DD",
  "type": "in" or "out",
  "category": one of {CATEGORY_CHOICES},
  "amount": number,
  "payer_or_payee": "name mentioned, or null",
  "description": "short human-readable description"
}}

Rules:
- "in" = money received; "out" = money paid.
- If no date is stated, use today's date: {{today}}.
- Pick the single closest category from the allowed list — never invent a new one.
- If you cannot confidently find an amount, set "amount" to null and explain
  nothing else — the amount field alone signals a failed extraction.

Revenue classification (this business's income streams):
- "Course Revenue"     = fees for a structured multi-session course/class:
  "Vibe Coding" (4-7 sessions), "Python Fundamentals", "Python + ML",
  enrolment fees, per-class fees, evening-school teaching fees.
- "Workshop Revenue"   = shorter one-off or few-session workshops, usually
  titled "AI for Automation", "AI for Work", "AI for Workplace", "AI
  Automation project", corporate/on-site AI sessions.
- "Consulting Revenue" = advisory / build / implementation work that is NOT
  teaching a class (custom software, automation delivery, retainers).
- "Referral Income"    = a referral fee received from a partner.
- "Refund"             = money coming back to us (bank / FPX / gateway refund).
- "Other Income"       = income that fits none of the above.
When the memo names a course ("Vibe Coding", "Python") choose Course Revenue;
when it says "AI for ..." or "workshop" choose Workshop Revenue.
"""


async def _call_gemini(parts: list, today: str) -> dict:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set")
    prompt = EXTRACTION_PROMPT.replace("{today}", today)
    payload = {
        "contents": [{"parts": [{"text": prompt}] + parts}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(GEMINI_URL, params={"key": GEMINI_API_KEY}, json=payload)
        resp.raise_for_status()
        data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


async def parse_text(message: str, today: str) -> dict:
    return await _call_gemini([{"text": f"Message from user: {message}"}], today)


INVOICE_EXTRACTION_PROMPT = """You are a bookkeeping assistant for a Malaysian
sole proprietorship that runs coding/AI education courses and consulting
projects (business name: Code N Code Solution). The user sent a message
meant to generate an invoice or quotation, but did NOT follow any fixed
line-by-line format — the information may be labelled loosely (e.g. "Full
Name :", "Course :", "Fee :"), in a different order, in prose, or missing
some fields entirely. Extract whatever invoice information IS present.

Respond with ONLY valid JSON (no markdown fences, no commentary), matching
exactly this shape:
{
  "contact": "the customer/student's name, or null if not found",
  "email": "email address, or null",
  "phone": "phone number, or null",
  "due": "YYYY-MM-DD, or null if no date/deadline is mentioned",
  "discount": number (percent) or null,
  "remarks": "any free-text notes, or null",
  "items": [
    {"description": "course/service name", "qty": number, "unit_price": number}
  ]
}

Rules:
- items is a list — usually one entry, but include every distinct course/
  service/fee mentioned as its own item.
- If a quantity isn't stated, use 1. If a price/amount isn't stated for an
  item you can still name (e.g. just "Python Fundamentals" with no RM
  figure), set unit_price to 0 rather than guessing.
- If you cannot find a customer name AND cannot find at least one
  identifiable item/course, return {"contact": null, "email": null,
  "phone": null, "due": null, "discount": null, "remarks": null, "items": []}
  — do not fabricate any field.
- Today's date is {today}, only relevant if the user references a relative
  date like "next Friday" for the due date.
"""


async def parse_invoice_fields(message: str, today: str) -> dict:
    """Lenient extraction for /invoice and /quote: pulls contact/items/email/
    phone/due/discount/remarks out of free-form text that doesn't follow the
    strict 'Key: value' line format. Returns the same shape _parse_doc_fields
    in main.py produces, so callers can merge/use it as a drop-in fallback."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set")
    prompt = INVOICE_EXTRACTION_PROMPT.replace("{today}", today)
    payload = {
        "contents": [{"parts": [{"text": prompt}, {"text": f"User's message: {message}"}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(GEMINI_URL, params={"key": GEMINI_API_KEY}, json=payload)
        resp.raise_for_status()
        data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    result = json.loads(text)
    # Normalise so downstream code can rely on these keys always existing.
    result.setdefault("items", [])
    for it in result["items"]:
        it["qty"] = it.get("qty") or 1
        it["unit_price"] = it.get("unit_price") or 0
    return result


async def parse_image(image_bytes: bytes, mime_type: str, caption: str, today: str) -> dict:
    parts = [{
        "inline_data": {
            "mime_type": mime_type,
            "data": base64.b64encode(image_bytes).decode("ascii"),
        }
    }]
    if caption:
        parts.append({"text": f"Caption from user: {caption}"})
    return await _call_gemini(parts, today)
