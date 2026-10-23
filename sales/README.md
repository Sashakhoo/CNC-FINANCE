# Codencode Lead Intelligence

Corporate training prospecting CRM for Codencode Academy. It finds companies likely
to need technology training, confirms their websites, identifies the right decision
makers from legitimate public sources, finds and verifies business emails, matches
companies to Codencode programmes, scores prospects, and runs the sales pipeline
through outreach and campaigns to a won deal — which raises the invoice in CNC Finance.

Every fact is stored with its provenance (DISCOVERED / INFERRED / ENRICHED / VERIFIED /
USER_PROVIDED), source URL, evidence text, confidence and time. Unknown stays unknown.

| Site | What |
|---|---|
| main.codencode.my | Workspace launcher (Sales, Learn, Finance) |
| crm.codencode.my | This CRM |
| finance.codencode.my | CNC Finance — owns user accounts; raises invoices for WON deals |

## Status

All 12 phases of the build plan are implemented and tested (backend: 386 pytest
cases against Postgres; frontend: Vitest component tests). Verified end to end in a
browser against the local stack, including a live crawl of a real public website.

| Area | What's there |
|---|---|
| CRM | Companies, contacts, Prospects (all spec filters, bulk actions), Works Space cards, company/contact profiles, pipeline, notes, activity, sources drawer, Do Not Contact, audit log, settings, team roles |
| Discovery | Saved searches, weekly re-runs, search provider (Brave), candidate filtering, domain resolution (uncertain domains never assigned), seed-website mode |
| Website intelligence | SSRF-safe crawler (DNS checked + IP pinned per request, redirects re-validated), robots.txt + crawl-delay, page limits, content hashing, company facts, signals, decision makers |
| Contact & email intelligence | Title normalization, decision-maker filtering, profile discovery via search results only (never logs into or scrapes LinkedIn), email discovery (Hunter), pattern inference (always INFERRED + UNVERIFIED), verification (Hunter / ZeroBounce) |
| AI | Gemini / Anthropic / OpenAI; training match with verbatim-quote evidence; outreach drafts fact-checked against inputs; rules-only when no key |
| Scores | Contact Confidence, Training Match and Lead Score kept separate, each with an explanation |
| Outreach | Email / LinkedIn-style / follow-up drafts in 4 tones, edit → approve → "mark as sent" (nothing is ever sent by the app), campaigns with stage metrics |
| Analytics | Dashboard + full report: growth, quality, confidence, conversion rates, pipeline, revenue won, industry / location / role / source / campaign / provider performance |
| Data operations | CSV/XLSX import wizard (dedupe, fill-blanks-only, suppression-aware), audited CSV/XLSX export (Do Not Contact excluded, formula-injection safe), duplicate merge, permanent erasure, retention |
| Hardening | Shared sign-in with Finance, ADMIN/SALES/VIEWER roles, cross-site write blocking, rate limits, provider quotas with backoff, cached provider calls, structured logs with secret redaction, job monitor with cancel/retry |

Training providers (sites that sell courses) are detected and not scored as training
prospects — they're competitors.

## Architecture

```
Browser ─► nginx (React build, /api proxy) ─► backend (FastAPI)
                                              ├─ Postgres 16 (+pg_trgm)
                                              ├─ Redis ─► worker (Celery) · scheduler (Celery beat)
                                              └─ CNC Finance: /api/me (session) · /api/integrations/crm/won (invoice)
```

- `backend/app/models` — normalized schema (§26), Alembic migrations in `backend/alembic`.
- `backend/app/services/pipeline.py` — the discovery pipeline; per-company failures are isolated.
- `backend/app/crawler`, `app/extract` — crawler and extraction; `app/providers` — swappable provider adapters
  (`registry.py`, `ratelimit.py`); `app/services` — scoring, identity, training match, outreach, data ops.
- `frontend/` — React + TypeScript + Vite + Tailwind, TanStack Query/Table, React Hook Form + Zod.

### Sign-in and roles

Accounts live in CNC Finance. The CRM validates Finance's `cnc_session` cookie through
Finance `/api/me` (cached 60 s). First sign-in maps Finance *director* → `ADMIN`,
*admin* → `SALES`; a CRM admin can change roles (`VIEWER` = read-only). The account
also needs Finance's `crm` capability.

## Providers and the keys they need

Everything works without keys; missing providers show **Not configured** in
Provider Usage and the matching pipeline step is skipped with a warning.

| Provider | Purpose | Environment variables | Where to get it | Without it |
|---|---|---|---|---|
| Brave Search API | Find companies; find public profile URLs in search results | `SEARCH_PROVIDER=brave`, `SEARCH_API_KEY` | Brave Search API dashboard | No automatic company discovery — list websites in the search, or import |
| Hunter.io | Business email discovery | `EMAIL_DISCOVERY_PROVIDER=hunter`, `EMAIL_DISCOVERY_API_KEY` | hunter.io → API keys | Emails only from public pages, plus INFERRED pattern guesses |
| Hunter or ZeroBounce | Email verification | `EMAIL_VERIFICATION_PROVIDER=hunter` or `zerobounce`, `EMAIL_VERIFICATION_API_KEY` | Provider dashboard | Emails stay UNVERIFIED |
| Gemini / Anthropic / OpenAI | AI training analysis, title fallback, outreach drafts | `LLM_PROVIDER`, `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | Google AI Studio / Claude Console / OpenAI platform | Rule-based analysis and template drafts |

Quotas: defaults come from each adapter; override with `PROVIDER_LIMITS`
(JSON, per minute/day/month). Usage, success rate, latency and errors are recorded
per call (Provider Usage page). Costs are shown only when a provider publishes them.

## Local development

```bash
cd sales
docker compose up -d
```

| URL | What |
|---|---|
| http://localhost:8080/launcher | Launcher |
| http://localhost:8080/sales | CRM (built, via nginx) |
| http://localhost:5173/sales | CRM with hot reload |
| http://localhost:8081 | CNC Finance — create the first account here |
| http://localhost:8000/api/docs | OpenAPI docs |

Demo data (fictional, flagged, never shown when `DEMO_MODE=false`):

```bash
docker compose run --rm -e DEMO_MODE=true backend python -m app.scripts.seed_demo
```

### Tests

```bash
docker compose run --rm -v "$PWD/backend:/app" backend pytest -q    # uses the crm_test database only
cd frontend && npm test
```

### Migrations

```bash
docker compose run --rm -v "$PWD/backend:/app" backend alembic revision --autogenerate -m "describe change"
```

The backend runs `alembic upgrade head` on every start — deploys never need a manual DB step.

## Deploying to Railway

One Railway project, all from this repo:

| Service | Root dir | Dockerfile | Start command | Domain |
|---|---|---|---|---|
| Postgres | — | Railway Postgres | — | — |
| Redis | — | Railway Redis | — | — |
| backend | `sales/backend` | `Dockerfile` | default | none (private) |
| worker | `sales/backend` | `Dockerfile` | `celery -A app.worker worker --loglevel=INFO --concurrency=4` | none |
| scheduler | `sales/backend` | `Dockerfile` | `celery -A app.worker beat --loglevel=INFO --schedule=/tmp/celerybeat-schedule` | none |
| web | `sales` | `Dockerfile` | default | crm.codencode.my, main.codencode.my |

backend / worker / scheduler variables:
`DATABASE_URL` (Railway's URL with `postgresql+asyncpg://`), `REDIS_URL`, `APP_ENV=production`,
`FINANCE_INTERNAL_URL=https://finance.codencode.my`, `FINANCE_PUBLIC_URL=https://finance.codencode.my`,
`CRM_INTEGRATION_SECRET`, `FRONTEND_URL=https://crm.codencode.my`, `ALLOWED_ORIGINS=https://main.codencode.my`,
provider keys. backend also `HOST=::` (Railway's private network is IPv6).

web: `BACKEND_URL=http://backend.railway.internal:8000`.

Finance service: add `COOKIE_DOMAIN=.codencode.my` and the same `CRM_INTEGRATION_SECRET`.

`pg_trgm` is created by the first migration.

## Scheduled jobs (Celery beat, Asia/Kuala_Lumpur)

| When | Job |
|---|---|
| Daily 03:15 | Purge expired provider cache |
| Daily 03:45 | Retention (Settings → Retention) |
| Mondays 02:00 | Re-run saved searches marked weekly |
| 1st of month 03:00 | Re-enrich high-priority companies not refreshed for 30 days |
| Wednesdays 04:00 | Re-verify emails verified more than 90 days ago |

## Backup & restore

```bash
pg_dump --format=custom "$DATABASE_URL_PLAIN" > crm-$(date +%F).dump        # backup
pg_restore --clean --no-owner -d "$DATABASE_URL_PLAIN" crm-2026-10-22.dump    # restore
```

`DATABASE_URL_PLAIN` is the `postgresql://` form. Restore into a fresh database, then
deploy — the backend migrates it forward on start. Railway Postgres also offers scheduled
backups. Upgrades: deploy the new image; migrations run automatically before the API starts.

## Security

- No passwords in this service; sessions are validated against Finance on every request (60 s cache).
- Writes from other origins are refused (`Origin` / `Sec-Fetch-Site` checks); rate limits on sign-in,
  discovery, enrichment, provider tests, import, export and drafts.
- Crawler: http(s) only, ports 80/443, private / loopback / link-local / metadata addresses refused,
  DNS checked on every hop and the connection pinned to the checked IP; TLS still verified against the hostname.
- Imports: 5 MB / 5,000 rows, CSV or XLSX only, formula cells never evaluated. Exports neutralise
  spreadsheet formulas and exclude Do Not Contact records.
- Logs are JSON with secrets redacted; audit log records sign-ins, changes, merges, erasures, exports.

## Compliance

Built for legitimate B2B corporate-training prospecting. No LinkedIn login or scraping behind
authentication, no CAPTCHA or anti-bot circumvention, no proxy rotation, no automatic sending.
Business contact details of named people are personal data under Malaysia's PDPA: use the
suppression list, keep sources visible, honour deletion requests with **Erase** (admin), and keep
retention periods sensible.

## Troubleshooting

| Symptom | Check |
|---|---|
| "Sign-in service (Finance) is unreachable" | `FINANCE_INTERNAL_URL`; Finance health at `/health` |
| Signed in on Finance but not on Sales | Finance `COOKIE_DOMAIN=.codencode.my`; both on HTTPS |
| WON doesn't raise an invoice | Company deal value set; `CRM_INTEGRATION_SECRET` identical on both services |
| Discovery finds nothing | Provider Usage → Test connection; job warnings in Jobs |
| Website "could not be crawled" | Job → Websites: robots.txt disallow, DNS, TLS or HTTP errors are listed per site |
| Request blocked: origin … not allowed | Add the site to `ALLOWED_ORIGINS` |
