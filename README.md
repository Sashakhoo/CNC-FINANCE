# CmPro

Bookkeeping system for Code N Code Solution (Codencode). One FastAPI app
serves three things off one SQLite database:

- **Dashboard** (`/`) — the bento-grid UI, now wired to a real JSON API
- **JSON API** (`/api/*`) — CRUD for transactions, contacts, invoices,
  assets, notes + PDF document generation
- **Telegram bot** (`/telegram/webhook`) — parse a message/photo → log → PDF

The dashboard and the bot share the same tables, the same auto
chart-of-accounts, and the same `RCP-/PV-/CV-/INV-` numbering sequences,
so documents from either surface are byte-identical.

## Folder structure

```
frontend/dashboard.html   single-file dashboard (fetches /api/*)
backend/
  main.py                 FastAPI app: bot webhook + static dashboard + router
  api.py                  JSON API router (/api/*) + PDF endpoints
  auth.py                 single-user login + signed session cookie
  storage.py              SQLite data layer + auto chart-of-accounts
  seed.py                 one-time historical seed (Apr–Aug 2026)
  gemini_parser.py        Gemini text/photo extraction (bot)
  pdf_generator.py        WeasyPrint receipt/voucher/invoice templates
  requirements.txt
  .env.example
nixpacks.toml / Procfile / railway.json   deploy config
docs/bank-ledger-apr-aug-2026.md
```

## Run locally

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # then edit: DASH_PASSWORD, SESSION_SECRET at minimum
uvicorn main:app --reload
```

Open http://localhost:8000 and sign in with `DASH_USERNAME` / `DASH_PASSWORD`.
On first run the database is seeded with the reconciled Apr–Aug 2026 ledger.

> WeasyPrint needs native libraries (Pango/Cairo/GDK-Pixbuf). On macOS:
> `brew install pango`. On Debian/Ubuntu: `apt install libpango-1.0-0
> libpangocairo-1.0-0 libgdk-pixbuf-2.0-0`. Railway handles this via
> `nixpacks.toml`.

## Deploy — GitHub + Railway

Same pipeline as `codencode.sg` / `gocare.my` / `cccrest.my`.

### 1. Push to GitHub

Create a new **private** repo `cmpro` under the `codencodemy` account
(empty — no README/licence), then from this folder:

```bash
git init
git add -A
git commit -m "CmPro: wire dashboard to backend API + auth + deploy config"
git branch -M main
git remote add origin https://github.com/codencodemy/cmpro.git
git push -u origin main
```

### 2. Railway service

1. **New Project → Deploy from GitHub repo → `codencodemy/cmpro`.**
   Railway auto-detects `nixpacks.toml` / `railway.json`.
2. **Add a Volume** to the service, mount path `/data`
   (Settings → Volumes). This keeps the SQLite file across redeploys.
3. **Variables** (Settings → Variables) — set:
   | Variable | Value |
   |---|---|
   | `DB_PATH` | `/data/cmpro.db` |
   | `DASH_USERNAME` | your login name |
   | `DASH_PASSWORD` | a strong password |
   | `SESSION_SECRET` | `python -c "import secrets;print(secrets.token_hex(32))"` |
   | `TELEGRAM_BOT_TOKEN` | from @BotFather |
   | `ALLOWED_USER_IDS` | your numeric Telegram id (from @userinfobot) |
   | `GEMINI_API_KEY` | from aistudio.google.com/apikey |
   | `GEMINI_MODEL` | current cheap vision model (check the Gemini docs) |
   | `PUBLIC_URL` | the Railway URL, e.g. `https://cmpro-production.up.railway.app` |
4. Deploy. Check `https://<PUBLIC_URL>/health` returns `{"status":"ok"}`.

### 3. Register the Telegram webhook (once, after first deploy)

```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://<PUBLIC_URL>/telegram/webhook"
```

(or run `PUBLIC_URL=... TELEGRAM_BOT_TOKEN=... python backend/main.py` locally).

## What changed from the mockup

- `dashboard.html` no longer holds data in JS arrays — every add/delete/pay
  hits `/api/*` and re-renders from the response.
- Receipt / Cash Voucher / Payment Voucher / invoice buttons now open a
  backend-rendered PDF (same code the Telegram bot uses).
- The `zc123` `window.prompt()` lock is replaced by a real username +
  password login behind a signed httpOnly session cookie.
- `storage.py` gained `assets`, `notes`, and `documents` tables.
