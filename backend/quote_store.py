"""
Quotation builder data: two quotation types sharing one table.

  Type A  standard  QUO-###   Non-HRDC course/consulting quotes
  Type B  hrdc      QHR-###   HRD Corp claimable programmes

Tables (same SQLite DB, created/extended at startup):
  quotations         one row per quote; type-specific fields live in hrdc_json
  quote_courses      Non-HRDC course catalogue (default price, session outline)
  hrdc_programmes    HRD Corp programmes (fee cap, status, trainers, outline)
  quote_clients      companies quoted before, for autocomplete
  quote_settings     editable rules: TP validity, ACM caps, lead time, ...

Line items are stored as JSON on the quotation:
  {kind, course_id, title, description, qty, unit_price, claimable}
  kind: course | materials | venue | travel | other

Nothing here touches the ledger. Rules that HRD Corp changes (ACM caps, lead
time, attendance threshold, TP validity) are settings, never hard-coded.
"""
import json
import re
from datetime import date, datetime, timedelta

import storage

TYPES = ("standard", "hrdc")
PREFIX = {"standard": "QUO", "hrdc": "QHR"}
STATUSES = ("Draft", "Sent", "Accepted", "Declined", "Expired")
LINE_KINDS = ("course", "materials", "venue", "travel", "other")
GRANT_STEPS = ("Quote", "Grant applied", "Grant approved", "Training done", "Claim docs", "Invoiced", "Paid")
GRANT_SCHEMES = ("SBL-Khas", "SBL", "Other")

CLAUDE_BLOCK = (
    "Claude comes in three ways of working:\n"
    "Chat - talk to Claude in the browser or app to write, summarise, brainstorm and analyse documents. "
    "Best for everyday questions and drafting.\n"
    "Code - Claude Code works inside your project folder or terminal and can read, write and run code. "
    "Best for building and fixing software.\n"
    "Cowork - Claude works on your computer's files and apps to carry out multi-step office tasks for you. "
    "Best for repetitive admin and research work."
)

DEFAULT_SETTINGS = {
    "validity_days": 30,
    "prepared_by": "Natasya Khoo",
    "show_address": False,
    "payment_terms": "50% deposit to confirm the booking; balance before or on the training day.",
    "sst_rate": 8,
    "tier_note": "Prices are based on 3 pax. For 2 pax add RM 388 per pax; for 1 pax add RM 488 per pax.",
    "claude_block": CLAUDE_BLOCK,
    "tp_name": "CODE N CODE SOLUTION",
    "tp_number": "",
    "tp_valid_from": "2026-10-20",
    "tp_valid_to": "2027-10-19",
    "tp_certificate_ref": "",
    "lead_days": 7,
    "attendance_threshold": 75,
    "claim_deadline_days": 30,
    "acm_caps": {"materials_per_pax": None, "venue_fnb_per_pax_per_day": None, "travel_per_day": None},
    "hrdc_sst_note": ("SST is not charged on this quotation. Check with your accountant how SST applies to "
                      "HRD Corp claimable training fees."),
    "trainers": [
        {"name": "Natasya Khoo", "trainer_id": "76085",
         "summary": ("Founder and principal trainer of CODE N CODE SOLUTION, a Johor Bahru training provider "
                     "specialising in computer education. Designs and delivers the company's Python, AI and "
                     "Machine Learning programmes with a focus on practical, workplace-ready skills."),
         "specialisations": ["Python Programming", "Artificial Intelligence and Machine Learning",
                             "AI for the Workplace / Digital Upskilling"]},
        {"name": "Teh Yong Li", "trainer_id": "", "summary": "", "specialisations": []},
    ],
}

PY_SESSIONS = [
    {"title": "Introduction to Python and setting up",
     "simple": "Install Python and write and run your first small program.",
     "detailed": "Python installation, VS Code / Jupyter set-up, running scripts, print() and comments."},
    {"title": "Variables, data types and operators",
     "simple": "Store numbers and text, and do calculations with them.",
     "detailed": "int, float, str, bool; arithmetic, comparison and logical operators; type conversion; f-strings."},
    {"title": "Control flow",
     "simple": "Make the program decide and repeat things.",
     "detailed": "if / elif / else, for and while loops, break/continue, nested conditions."},
    {"title": "Functions and modules",
     "simple": "Package steps into reusable building blocks.",
     "detailed": "def, parameters and return values, scope, importing the standard library and your own modules."},
    {"title": "Data structures",
     "simple": "Work with lists of items and look things up quickly.",
     "detailed": "Lists, tuples, dictionaries and sets; slicing, comprehensions, iterating over collections."},
    {"title": "File handling and a mini automation project",
     "simple": "Read and write files and automate a real everyday task.",
     "detailed": "open/with, CSV and text files, error handling with try/except, a small end-to-end automation script."},
]

WORKPLACE_AI_SESSIONS = [
    {"title": "What is AI? Demystifying AI for non-technical staff",
     "simple": "What AI is, what it can and can't do at work.",
     "detailed": "Generative AI and large language models in plain terms; strengths, limits and typical failure modes."},
    {"title": "Overview of workplace AI tools",
     "simple": "A tour of the AI tools people use at work.",
     "detailed": "ChatGPT, Copilot, Claude and similar tools; choosing the right tool for a task; data-privacy settings."},
    {"title": "Prompt engineering basics",
     "simple": "How to ask AI clearly to get useful answers.",
     "detailed": "Role, context, task and format; examples and constraints; iterating on a prompt; reusable prompt templates."},
    {"title": "AI for productivity - writing, research and data tasks",
     "simple": "Hands-on: emails, reports, research and spreadsheets with AI.",
     "detailed": "Drafting and summarising documents, research workflows, analysing tables, meeting notes to action items."},
    {"title": "Risks, ethics and responsible AI use at work",
     "simple": "Using AI safely and responsibly.",
     "detailed": "Accuracy checks, confidentiality, PDPA considerations, bias, company AI policy and approval flows."},
    {"title": "Personal AI adoption action plan",
     "simple": "Plan how you'll use AI in your own job.",
     "detailed": "Identify tasks to improve, set measurable goals, team rollout steps; assessment and wrap-up."},
]

SEED_COURSES = [
    # name, price, unit, group_note, tiered, sessions
    ("AI for Automation", 288, "pax", "", True, []),
    ("Claude — Chat, Code & Cowork", 288, "pax", "", True, []),
    ("Vibe Coding from Scratch", 800, "pax", "", False, []),
    ("AI for Marketing (2-day, 4.5h/day)", 2500, "group", "per group of 3–4 pax", False, []),
    ("Python for Beginners", 0, "pax", "", False, PY_SESSIONS),
]

SEED_PROGRAMMES = [
    # title, fee_cap, days, hours, mode, venue, status, sessions, note
    ("AI for Workflow Operations and People Management", 1500, 1, 8, "physical", "Mount Austin, Johor Bahru",
     "Approved", WORKPLACE_AI_SESSIONS,
     "Outline copied from the 'AI for the Workplace' course package - check it matches the approved HRD Corp submission."),
    ("Python course", 1800, 2, 16, "physical", "Mount Austin, Johor Bahru", "Pending", PY_SESSIONS,
     "Outline copied from the 'Python Programming for Beginners' course package - check it matches the submission."),
]


# --- schema ------------------------------------------------------------------

def init_db():
    storage.init_quotations()
    with storage.get_conn() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(quotations)")}
        for col, ddl in (
            ("qtype", "TEXT NOT NULL DEFAULT 'standard'"),
            ("prepared_by", "TEXT NOT NULL DEFAULT ''"),
            ("validity_days", "INTEGER NOT NULL DEFAULT 30"),
            ("show_address", "INTEGER NOT NULL DEFAULT 0"),
            ("sst", "INTEGER NOT NULL DEFAULT 0"),
            ("plain_language", "INTEGER NOT NULL DEFAULT 1"),
            ("claude_block", "INTEGER NOT NULL DEFAULT 0"),
            ("tier_note", "INTEGER NOT NULL DEFAULT 0"),
            ("payment_terms", "TEXT NOT NULL DEFAULT ''"),
            ("notes", "TEXT NOT NULL DEFAULT ''"),
            ("discount_rm", "REAL NOT NULL DEFAULT 0"),
            ("hrdc_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("updated_at", "TEXT"),
        ):
            if col not in cols:
                conn.execute(f"ALTER TABLE quotations ADD COLUMN {col} {ddl}")
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS quote_courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            default_price REAL NOT NULL DEFAULT 0,
            price_unit TEXT NOT NULL DEFAULT 'pax',
            group_note TEXT NOT NULL DEFAULT '',
            tiered INTEGER NOT NULL DEFAULT 0,
            sessions_json TEXT NOT NULL DEFAULT '[]',
            active INTEGER NOT NULL DEFAULT 1,
            sort INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS hrdc_programmes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            programme_code TEXT NOT NULL DEFAULT '',
            fee_cap REAL NOT NULL DEFAULT 0,
            days REAL NOT NULL DEFAULT 1,
            hours REAL NOT NULL DEFAULT 8,
            mode TEXT NOT NULL DEFAULT 'physical',
            venue TEXT NOT NULL DEFAULT '',
            trainers TEXT NOT NULL DEFAULT 'Natasya Khoo, Teh Yong Li',
            status TEXT NOT NULL DEFAULT 'Pending',
            min_pax INTEGER NOT NULL DEFAULT 1,
            max_pax INTEGER NOT NULL DEFAULT 30,
            sessions_json TEXT NOT NULL DEFAULT '[]',
            outline_note TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS quote_clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL UNIQUE COLLATE NOCASE,
            data_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS quote_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """)
        if conn.execute("SELECT COUNT(*) AS c FROM quote_courses").fetchone()["c"] == 0:
            for i, (name, price, unit, note, tiered, sessions) in enumerate(SEED_COURSES):
                conn.execute("INSERT INTO quote_courses(name, default_price, price_unit, group_note, tiered, "
                             "sessions_json, sort) VALUES (?,?,?,?,?,?,?)",
                             (name, price, unit, note, int(tiered), json.dumps(sessions), i))
        if conn.execute("SELECT COUNT(*) AS c FROM hrdc_programmes").fetchone()["c"] == 0:
            for title, cap, days, hours, mode, venue, status, sessions, note in SEED_PROGRAMMES:
                conn.execute("INSERT INTO hrdc_programmes(title, fee_cap, days, hours, mode, venue, status, "
                             "sessions_json, outline_note) VALUES (?,?,?,?,?,?,?,?,?)",
                             (title, cap, days, hours, mode, venue, status, json.dumps(sessions), note))


# --- settings ----------------------------------------------------------------

def get_settings() -> dict:
    out = json.loads(json.dumps(DEFAULT_SETTINGS))
    with storage.get_conn() as conn:
        for r in conn.execute("SELECT key, value FROM quote_settings"):
            try:
                out[r["key"]] = json.loads(r["value"])
            except ValueError:
                pass
    return out


def save_settings(values: dict) -> dict:
    with storage.get_conn() as conn:
        for k, v in values.items():
            if k in DEFAULT_SETTINGS:
                conn.execute("INSERT INTO quote_settings(key, value) VALUES (?, ?) "
                             "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, json.dumps(v)))
    return get_settings()


# --- catalogue -----------------------------------------------------------------

def _course(r) -> dict:
    d = dict(r)
    d["sessions"] = json.loads(d.pop("sessions_json") or "[]")
    d["tiered"] = bool(d["tiered"]); d["active"] = bool(d["active"])
    return d


def list_courses(include_inactive=False) -> list:
    q = "SELECT * FROM quote_courses" + ("" if include_inactive else " WHERE active = 1") + " ORDER BY sort, id"
    with storage.get_conn() as conn:
        return [_course(r) for r in conn.execute(q)]


def save_course(data: dict, cid: int = None) -> dict:
    vals = (data["name"], float(data.get("default_price") or 0), data.get("price_unit") or "pax",
            data.get("group_note") or "", int(bool(data.get("tiered"))), json.dumps(data.get("sessions") or []),
            int(data.get("active", True)), int(data.get("sort") or 0))
    with storage.get_conn() as conn:
        if cid:
            conn.execute("UPDATE quote_courses SET name=?, default_price=?, price_unit=?, group_note=?, tiered=?, "
                         "sessions_json=?, active=?, sort=? WHERE id=?", (*vals, cid))
        else:
            cid = conn.execute("INSERT INTO quote_courses(name, default_price, price_unit, group_note, tiered, "
                               "sessions_json, active, sort) VALUES (?,?,?,?,?,?,?,?)", vals).lastrowid
        return _course(conn.execute("SELECT * FROM quote_courses WHERE id = ?", (cid,)).fetchone())


def _programme(r) -> dict:
    d = dict(r)
    d["sessions"] = json.loads(d.pop("sessions_json") or "[]")
    d["active"] = bool(d["active"])
    return d


def list_programmes(include_inactive=False) -> list:
    q = "SELECT * FROM hrdc_programmes" + ("" if include_inactive else " WHERE active = 1") + " ORDER BY id"
    with storage.get_conn() as conn:
        return [_programme(r) for r in conn.execute(q)]


def get_programme(pid) -> dict:
    with storage.get_conn() as conn:
        r = conn.execute("SELECT * FROM hrdc_programmes WHERE id = ?", (pid,)).fetchone()
        return _programme(r) if r else None


def save_programme(data: dict, pid: int = None) -> dict:
    keys = ("title", "programme_code", "fee_cap", "days", "hours", "mode", "venue", "trainers", "status",
            "min_pax", "max_pax", "outline_note", "active")
    vals = [data.get(k) for k in keys]
    vals[keys.index("active")] = int(data.get("active", True))
    vals.append(json.dumps(data.get("sessions") or []))
    with storage.get_conn() as conn:
        if pid:
            conn.execute(f"UPDATE hrdc_programmes SET {', '.join(k + '=?' for k in keys)}, sessions_json=? WHERE id=?",
                         (*vals, pid))
        else:
            pid = conn.execute(f"INSERT INTO hrdc_programmes({', '.join(keys)}, sessions_json) "
                               f"VALUES ({', '.join('?' for _ in keys)}, ?)", vals).lastrowid
    return get_programme(pid)


# --- clients -------------------------------------------------------------------

CLIENT_FIELDS = ("company", "attention", "address", "phone", "email", "ssm", "mycoid",
                 "hr_contact", "hr_email", "hr_phone")


def list_clients() -> list:
    with storage.get_conn() as conn:
        return [{"id": r["id"], **json.loads(r["data_json"] or "{}"), "company": r["company"]}
                for r in conn.execute("SELECT * FROM quote_clients ORDER BY company")]


def remember_client(data: dict):
    company = (data.get("company") or "").strip()
    if not company:
        return
    keep = {k: (data.get(k) or "").strip() for k in CLIENT_FIELDS if k != "company" and (data.get(k) or "").strip()}
    with storage.get_conn() as conn:
        row = conn.execute("SELECT * FROM quote_clients WHERE company = ?", (company,)).fetchone()
        merged = {**(json.loads(row["data_json"]) if row else {}), **keep}
        conn.execute("INSERT INTO quote_clients(company, data_json, updated_at) VALUES (?,?,?) "
                     "ON CONFLICT(company) DO UPDATE SET data_json = excluded.data_json, updated_at = excluded.updated_at",
                     (company, json.dumps(merged), datetime.utcnow().isoformat()))


# --- quotations ----------------------------------------------------------------

def mask_ic(ic: str) -> str:
    """Only the last four digits are ever kept. The full IC number is never stored."""
    digits = re.sub(r"\D", "", ic or "")
    if not digits:
        return ""
    if (ic or "").startswith("XXXXXX-XX-"):
        return ic
    return "XXXXXX-XX-" + digits[-4:]


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def totals(q: dict, settings: dict = None) -> dict:
    settings = settings or get_settings()
    items = q.get("items") or []
    lines = [round(_num(i.get("qty"), 1) * _num(i.get("unit_price")), 2) for i in items]
    subtotal = round(sum(lines), 2)
    hrdc = q.get("qtype") == "hrdc"
    discount = 0.0 if hrdc else round(_num(q.get("discount_rm")) + subtotal * _num(q.get("discount_pct")) / 100, 2)
    after = round(subtotal - discount, 2)
    rate = _num(settings.get("sst_rate"), 8)
    sst = round(after * rate / 100, 2) if q.get("sst") else 0.0
    tax_pct = _num(q.get("tax_pct"))           # legacy quotes made before the builder
    legacy_tax = round(after * tax_pct / 100, 2) if tax_pct and not q.get("sst") else 0.0
    grand = round(after + sst + legacy_tax, 2)
    out = {"lines": lines, "subtotal": subtotal, "discount": discount, "sst": sst, "sst_rate": rate,
           "legacy_tax": legacy_tax, "grand": grand}
    if hrdc:
        claimable = round(sum(a for a, i in zip(lines, items) if i.get("claimable")), 2)
        out["claimable"] = claimable
        out["non_claimable"] = round(grand - claimable, 2)
    return out


def _row(r) -> dict:
    q = dict(r)
    q["items"] = json.loads(q.pop("items_json") or "[]")
    for it in q["items"]:
        if "title" not in it:                  # quotes saved before the builder had titles
            it["title"], it["description"] = it.get("description", ""), ""
        it.setdefault("kind", "course")
        it.setdefault("description", "")
        it.setdefault("claimable", it.get("kind") == "course")
    q["hrdc"] = json.loads(q.pop("hrdc_json") or "{}")
    for k in ("show_address", "sst", "plain_language", "claude_block", "tier_note"):
        q[k] = bool(q.get(k))
    q["qtype"] = q.get("qtype") or "standard"
    t = totals(q)
    q["totals"] = t
    q["subtotal"], q["total"] = t["subtotal"], t["grand"]
    q["display_status"] = q["status"]
    if q["status"] in ("Draft", "Sent") and q.get("valid_until") and q["valid_until"] < date.today().isoformat():
        q["display_status"] = "Expired"
    return q


def list_quotations() -> list:
    with storage.get_conn() as conn:
        return [_row(r) for r in conn.execute("SELECT * FROM quotations ORDER BY date DESC, id DESC")]


def get_quotation(qid: int):
    with storage.get_conn() as conn:
        r = conn.execute("SELECT * FROM quotations WHERE id = ?", (qid,)).fetchone()
        return _row(r) if r else None


def next_number(qtype: str) -> str:
    prefix = PREFIX[qtype]
    while True:
        number = storage.next_document_number(prefix)
        with storage.get_conn() as conn:
            if not conn.execute("SELECT 1 FROM quotations WHERE number = ?", (number,)).fetchone():
                return number


def number_taken(number: str, exclude_id: int = None) -> bool:
    with storage.get_conn() as conn:
        r = conn.execute("SELECT id FROM quotations WHERE number = ? COLLATE NOCASE", (number,)).fetchone()
        return bool(r) and r["id"] != exclude_id


COLS = ("number", "qtype", "contact", "date", "valid_until", "validity_days", "status", "prepared_by",
        "show_address", "sst", "plain_language", "claude_block", "tier_note", "payment_terms", "notes",
        "discount_pct", "discount_rm", "tax_pct", "remarks", "attention", "company", "address", "reference_no",
        "sales_type", "sales_person", "email", "phone")


def save_quotation(q: dict, qid: int = None) -> dict:
    values = []
    for k in COLS:
        v = q.get(k)
        if k in ("show_address", "sst", "plain_language", "claude_block", "tier_note"):
            v = int(bool(v))
        elif k in ("discount_pct", "discount_rm", "tax_pct"):
            v = _num(v)
        elif k == "validity_days":
            v = int(_num(v, 30))
        elif v is None:
            v = ""
        values.append(v)
    now = datetime.utcnow().isoformat()
    with storage.get_conn() as conn:
        if qid:
            conn.execute(f"UPDATE quotations SET {', '.join(k + '=?' for k in COLS)}, items_json=?, hrdc_json=?, "
                         f"updated_at=? WHERE id=?",
                         (*values, json.dumps(q.get("items") or []), json.dumps(q.get("hrdc") or {}), now, qid))
        else:
            qid = conn.execute(f"INSERT INTO quotations({', '.join(COLS)}, items_json, hrdc_json, updated_at) "
                               f"VALUES ({', '.join('?' for _ in COLS)}, ?, ?, ?)",
                               (*values, json.dumps(q.get("items") or []), json.dumps(q.get("hrdc") or {}),
                                now)).lastrowid
    return get_quotation(qid)


def duplicate(qid: int) -> dict:
    q = get_quotation(qid)
    if not q:
        return None
    copy = {k: q.get(k) for k in COLS}
    copy.update(items=q["items"], hrdc={**q["hrdc"], "grant_id": "", "grant_status": "Quote"},
                number=next_number(q["qtype"]), status="Draft", date=date.today().isoformat())
    copy["valid_until"] = (date.today() + timedelta(days=int(q.get("validity_days") or 30))).isoformat()
    return save_quotation(copy)


# --- checks (warnings shown in the builder; some block sending) -----------------

def check(q: dict, settings: dict = None) -> dict:
    """Returns {'errors': [...], 'warnings': [...]}. Errors stop the quote from
    being saved as Sent or exported; warnings are shown but don't block."""
    settings = settings or get_settings()
    errors, warnings = [], []
    items = q.get("items") or []
    if not (q.get("company") or q.get("contact") or "").strip():
        errors.append("Company name is required.")
    if not any((i.get("title") or "").strip() for i in items):
        errors.append("Add at least one line item.")
    if q.get("qtype") != "hrdc":
        return {"errors": errors, "warnings": warnings}

    h = q.get("hrdc") or {}
    prog = get_programme(h.get("programme_id")) if h.get("programme_id") else None
    if not prog:
        errors.append("Choose an HRD Corp programme.")
        return {"errors": errors, "warnings": warnings}
    if prog["status"] != "Approved":
        warnings.append(f"'{prog['title']}' is {prog['status']} with HRD Corp - the PDF is marked "
                        "SUBJECT TO HRD CORP APPROVAL and can't be marked Sent until it is approved.")
    if not prog.get("programme_code"):
        warnings.append("The HRD Corp Programme ID for this programme isn't filled in (Catalogue).")
    if prog.get("outline_note"):
        warnings.append(prog["outline_note"])
    cap = _num(prog.get("fee_cap"))
    for i in items:
        if i.get("kind") == "course" and cap and _num(i.get("unit_price")) > cap + 0.004:
            errors.append(f"Course fee RM {_num(i.get('unit_price')):,.2f} is above the approved "
                          f"RM {cap:,.2f} per pax for this programme.")
    pax = int(_num(h.get("pax"), 0))
    if pax and not (prog["min_pax"] <= pax <= prog["max_pax"]):
        errors.append(f"This programme takes {prog['min_pax']}–{prog['max_pax']} pax (you entered {pax}).")
    if not settings.get("tp_number"):
        warnings.append("Your Training Provider MyCoID / TP number is empty (Settings).")
    dates = sorted(d for d in (h.get("dates") or []) if d)
    if dates:
        if settings.get("tp_valid_to") and dates[-1] > settings["tp_valid_to"]:
            warnings.append(f"Training on {dates[-1]} is after your TP registration ends ({settings['tp_valid_to']}).")
        lead = int(_num(settings.get("lead_days"), 0))
        days_left = (date.fromisoformat(dates[0]) - date.today()).days
        if lead and days_left < lead:
            warnings.append(f"Training starts in {days_left} day(s) - the employer may not have time to get the "
                            f"grant approved (lead time set to {lead} days).")
    else:
        warnings.append("No training date yet.")
    caps = settings.get("acm_caps") or {}
    days = max(1.0, _num(prog.get("days"), 1))
    for i in items:
        if not i.get("claimable"):
            continue
        kind, unit = i.get("kind"), _num(i.get("unit_price"))
        cap_v = {"materials": caps.get("materials_per_pax"), "venue": caps.get("venue_fnb_per_pax_per_day"),
                 "travel": caps.get("travel_per_day")}.get(kind)
        if cap_v in (None, "") and kind in ("materials", "venue", "travel"):
            warnings.append(f"No ACM cap set for {kind} - check the claimable amount (Settings).")
        elif cap_v not in (None, ""):
            limit = _num(cap_v) * (days if kind == "venue" else 1)
            if unit > limit + 0.004:
                warnings.append(f"Claimable {kind} RM {unit:,.2f} is above the ACM cap of RM {limit:,.2f}.")
    return {"errors": errors, "warnings": warnings}
