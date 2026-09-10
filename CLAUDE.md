# CNC Finance — Project Brief for Claude Code

(Formerly "CmPro". The original Excel workbook is still named `CmPro.xlsm`
on disk — that filename is left as-is below where it refers to the real file.)

## What this is

A bookkeeping system for **Code N Code Solution** (trading as Codencode),
a Malaysian sole proprietorship (SSM Reg. No. AS0511861-M, Johor Bahru)
running coding/AI education courses and consulting projects. This is a
software rebuild of an existing Excel workbook (`CmPro.xlsm`) that the
business currently uses for bookkeeping.

**Read this whole file before changing anything** — it explains what's
real, what's a mockup, and what you're actually being asked to build.

## Current state (important: two disconnected halves)

- **`frontend/dashboard.html`** — a fully client-side, single-file HTML/JS
  dashboard. Looks and behaves like a real app (add/delete transactions,
  contacts, invoices, assets; generates receipts/vouchers as printable
  PDFs via the browser's print dialog; a Balance Sheet/P&L/Trial Balance
  that recalculate live). **But all state lives in JS arrays in memory —
  nothing persists, nothing is real, there is no backend call.** It was
  built as a design/UX proof of concept, seeded once with real historical
  data reconciled from 5 months of actual bank statements (see
  `docs/bank-ledger-apr-aug-2026.md`), but that seed data is just hardcoded
  into the HTML.

- **`backend/`** — a **working, tested** Telegram bot (FastAPI + SQLite +
  Gemini for text/photo extraction + WeasyPrint for PDF generation). This
  is real, deployable code, already smoke-tested. It has its own SQLite
  database and does not talk to `frontend/dashboard.html` at all.

**These two do not know about each other yet.** That's the main gap.

## Your primary task

Wire the two together into one real system:

1. **Turn `backend/storage.py` into a proper JSON API.** Add a thin FastAPI
   router (or extend `backend/main.py`) exposing REST/JSON endpoints for
   transactions, contacts, invoices, and assets — CRUD operations that
   mirror exactly what `frontend/dashboard.html`'s JS functions
   (`addTransaction`, `deleteTransaction`, `addContact`, `addInvoice`,
   `markPaid`, `addAsset`, etc.) currently do to their in-memory arrays.
   The schema is already defined in `storage.py` — extend it with an
   `assets` table (name, category, cost, dep) and a `notes` table
   (free-text, single row) to match what the dashboard expects.

2. **Replace the dashboard's in-memory arrays with `fetch()` calls.** Every
   place in `dashboard.html`'s `<script>` that currently does
   `transactions.push(...)`, `contacts.push(...)`, etc. should instead
   `POST`/`GET`/`DELETE` against the new API and re-render from the
   response. Keep the exact same visual design, CSS, and layout — only the
   data layer changes.

3. **Reuse `backend/pdf_generator.py` for the dashboard's document
   generation**, instead of the current client-side `window.print()`
   approach. When someone clicks 🧾 Receipt / 📗 Cash Voucher / 📕 Payment
   Voucher / an invoice in the dashboard, that should hit a backend
   endpoint that calls the same `render_receipt_pdf` /
   `render_voucher_pdf` / `render_invoice_pdf` functions already used by
   the Telegram bot, and return the PDF for download. This guarantees the
   Telegram bot and the dashboard produce byte-identical documents with
   consistent auto-numbering (RCP-/PV-/CV-/INV- sequences shared via the
   same `counters` table).

4. **Replace the dashboard's access control.** It currently "locks" the UI
   client-side and unlocks with a hardcoded password (`zc123`) typed into
   a `window.prompt()` — this is a placeholder, not real security. Replace
   it with actual auth (even something simple like a single shared login
   behind a session cookie is fine for a one-person business; don't
   over-engineer this into multi-tenant RBAC).

5. **Deploy both as one service to Railway** (this business already
   deploys `codencode.sg`, `gocare.my`, and `cccrest.my` via GitHub +
   Railway — follow the same pattern). The Telegram bot and the dashboard
   API can be the same FastAPI app on one Railway service, sharing one
   SQLite file (or migrate to Postgres if Railway makes that easier —
   your call, just keep the schema equivalent).

## Data model (already implemented in `backend/storage.py`)

```
transactions: id, date, description, type ('in'|'out'), category, amount, payer_payee, chat_id, created_at
contacts:     id, name, type ('debtor'|'creditor'), balance, code (auto-provisioned account code)
invoices:     id, number, contact, date, due, amount, status ('Unpaid'|'Paid'|'Overdue')
counters:     name, value          -- shared sequences for RCP-/PV-/CV-/INV- numbering
category_codes: category, code    -- auto chart-of-accounts, provisioned on first use
```

Add for full dashboard parity:
```
assets: id, name, category, cost, dep
notes:  id (always 1), text, updated_at
```

## Design system (preserve this — don't restyle)

The dashboard uses a "premium bento-grid SaaS" aesthetic:
- Off-white background (`#f2efe8`), white cards, 18–24px border radius, soft shadows
- Neutral black/charcoal (`#15141a`) structural cards + pastel accents: lime
  `#d7f26d`, lavender `#d9d3fb`, coral `#ffb7a6`, cyan `#bdeef2`, yellow `#ffe08a`
  — roughly 75% neutral / 25% colour
- Typography: Space Grotesk (headings/numbers), Inter (body), JetBrains
  Mono (figures/codes) — all loaded from Google Fonts already in the `<head>`
- Rounded pill nav in a left sidebar with minimal line-icon SVGs
- All CSS variables are defined in `:root` at the top of `dashboard.html` —
  reuse them, don't hardcode new colors

## Known gaps / open questions to flag back to the user, don't silently guess

- Several ledger entries in the seeded historical data are labeled
  "·unclear" in `docs/bank-ledger-apr-aug-2026.md` (a RM6,000 transfer
  from "Gao Carey Yueming," a RM1,549 transfer from "Lim Ban Soon," and
  recurring "Salary - NSJB" deposits) — these were bucketed as generic
  "Other Income" for lack of better information. Don't reclassify them
  without asking.
- `backend/gemini_parser.py`'s default model string
  (`gemini-flash-lite-latest`) may be stale by the time you read this —
  Gemini model names and pricing change often. Check
  https://ai.google.dev/gemini-api/docs/models before relying on it.
- WhatsApp integration was scoped in conversation but not started —
  Telegram was built first because it needs no business verification.
  If asked to add WhatsApp, use the Meta Cloud API (official), matching
  the pattern already used in this business's other automation
  (`telegram-tax-bot`/`whatsapp-tax-bot` project).
- The dashboard's Trial Balance uses a plug entry ("Owner's Equity") to
  force debit = credit, since the underlying ledger isn't true
  double-entry — this is intentional and mirrors how the original
  `CmPro.xlsm` workbook also used plug entries (e.g. "Accumulated Profit
  & Loss" on its Balance Sheet). Don't "fix" this into full double-entry
  bookkeeping unless asked — it's a deliberate simplification for a
  single-person sole proprietorship.
