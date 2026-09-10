# CNC Finance

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

Repo: `https://github.com/Sashakhoo/CNC-FINANCE.git`

```bash
git remote add origin https://github.com/Sashakhoo/CNC-FINANCE.git
git push -u origin main
```

### 2. Railway service

1. **New Project → Deploy from GitHub repo → `Sashakhoo/CNC-FINANCE`.**
   Railway auto-detects `nixpacks.toml` / `railway.json`.
2. **Attach a Volume** to the service (right-click the service, or `Cmd/Ctrl+K`
   → "volume"), mount path `/data`. This keeps the SQLite file across redeploys.
3. **Variables** (service → Variables → Raw Editor) — set:
   | Variable | Value | Required |
   |---|---|---|
   | `DB_PATH` | `/data/cnc.db` | yes |
   | `DASH_USERS` | `sashakhoo:<strong>:director,accounts:<strong>:admin` — passwords with no `:` or `,` | yes (no login without it) |
   | `SESSION_SECRET` | `python -c "import secrets;print(secrets.token_hex(32))"` | yes |
   | `PUBLIC_URL` | the Railway URL, e.g. `https://finance.codencode.my` | yes |
   | `TELEGRAM_BOT_TOKEN` | from @BotFather | bot only |
   | `TELEGRAM_WEBHOOK_SECRET` | `python -c "import secrets;print(secrets.token_urlsafe(24))"` | bot only |
   | `ALLOWED_USER_IDS` | your numeric Telegram id (from @userinfobot) | bot only |
   | `GEMINI_API_KEY` | from aistudio.google.com/apikey | bot only |
   | `GEMINI_MODEL` | current cheap vision model (check the Gemini docs) | bot only |

   To keep passwords off the server entirely, hash them locally
   (`python backend/hash_password.py`) and use
   `sashakhoo:scrypt:<salt>:<hash>:director` instead.
4. Deploy. Check `https://<PUBLIC_URL>/health` returns `{"status":"ok"}`.

### 3. Register the Telegram webhook (once, after first deploy)

Run it with the secret so the endpoint rejects forged calls:

```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -d "url=https://<PUBLIC_URL>/telegram/webhook" \
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

(or run `PUBLIC_URL=... TELEGRAM_BOT_TOKEN=... TELEGRAM_WEBHOOK_SECRET=... python backend/main.py` locally).

## What changed from the mockup

- `dashboard.html` no longer holds data in JS arrays — every add/delete/pay
  hits `/api/*` and re-renders from the response.
- Receipt / Cash Voucher / Payment Voucher / invoice buttons now open a
  backend-rendered PDF (same code the Telegram bot uses).
- The `zc123` `window.prompt()` lock is replaced by real auth.
- `storage.py` gained `assets`, `notes`, and `documents` tables.

## Security

- **Auth**: database-backed accounts (`users` table), managed by a director
  on the **Team** screen (add/disable/delete users, set roles, reset
  passwords; everyone can change their own). First boot seeds from
  `DASH_USERS` (or prints a random bootstrap password). Passwords are
  scrypt-hashed; login is constant-time and rate-limited (8 tries / 5 min /
  IP → 429). Session is a signed httpOnly `SameSite=Lax` cookie, `Secure`
  over HTTPS, 7-day default lifetime.
- **Roles**: `director` (full) vs `admin` (create invoices + generate
  documents only). Enforced per endpoint server-side (403), not just in the UI.
- **Headers**: CSP, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy`, HSTS on HTTPS. API docs (`/docs`, `/openapi.json`) disabled.
- **Telegram webhook**: verified against `TELEGRAM_WEBHOOK_SECRET`; the bot
  only acts for `ALLOWED_USER_IDS`.
- **DB**: parameterised queries throughout; table names allow-listed.
- Errors are logged server-side, not returned to the client.
