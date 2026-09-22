"""
SQLite storage for the CNC Finance system (Telegram bot + dashboard).

This mirrors the same data model used in the CNC dashboard mockup
(transactions / contacts / invoices), so this database can later become
the single source of truth the dashboard reads from too — swap this
module for a Postgres version without touching main.py's logic.
"""
import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "./cnc.db")

# Known category -> account code map, same as the dashboard's chart of
# accounts. Anything not in here gets an auto-assigned code the first
# time it's seen (see next_category_code below) — this is the "auto
# chart-of-accounts provisioning" behaviour.
KNOWN_EXPENSE_CODES = {
    "Payroll": "6001", "Rental": "6002", "Bank Charges": "6003", "Supplies": "6004",
    "Referral Expense": "6005", "Marketing": "6006", "Merchandise": "6007",
    "Courier/Postage": "6008", "Owner Withdrawal": "6009", "Refund Given": "6010",
    "Payment Gateway": "6011", "Printing": "6012", "Statutory Contributions": "6013",
    "Other Expense": "6099",
}
KNOWN_INCOME_CODES = {
    "Course Revenue": "4001", "Consulting Revenue": "4002", "Referral Income": "4003",
    "Other Income": "4004", "Refund": "4005", "Workshop Revenue": "4006",
}

CATEGORY_CHOICES = list(KNOWN_INCOME_CODES) + list(KNOWN_EXPENSE_CODES)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            description TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('in','out')),
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            payer_payee TEXT,
            chat_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('debtor','creditor')),
            balance REAL NOT NULL DEFAULT 0,
            code TEXT,
            email TEXT DEFAULT '',
            phone TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number TEXT NOT NULL,
            contact TEXT NOT NULL,
            date TEXT NOT NULL,
            due TEXT,
            amount REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            description TEXT NOT NULL DEFAULT '',
            discount_pct REAL NOT NULL DEFAULT 0,
            remarks TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS invoice_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            qty REAL NOT NULL DEFAULT 1,
            unit_price REAL NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS counters (
            name TEXT PRIMARY KEY,
            value INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS category_codes (
            category TEXT PRIMARY KEY,
            code TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            cost REAL NOT NULL DEFAULT 0,
            dep REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            text TEXT NOT NULL DEFAULT '',
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            salt TEXT NOT NULL,
            hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS documents (
            kind TEXT NOT NULL,
            ref_id INTEGER NOT NULL,
            number TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (kind, ref_id)
        );
        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT DEFAULT '',
            email TEXT DEFAULT '',
            employment_type TEXT NOT NULL DEFAULT 'freelance' CHECK(employment_type IN ('freelance','employee')),
            rate_type TEXT NOT NULL DEFAULT 'per_session' CHECK(rate_type IN ('per_session','hourly','fixed_monthly')),
            rate REAL NOT NULL DEFAULT 0,
            epf_no TEXT DEFAULT '',
            socso_no TEXT DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS payroll_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period_label TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','paid'))
        );
        CREATE TABLE IF NOT EXISTS payroll_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            teacher_id INTEGER NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            qty REAL NOT NULL DEFAULT 1,
            rate REAL NOT NULL DEFAULT 0,
            gross REAL NOT NULL DEFAULT 0,
            epf_employee REAL NOT NULL DEFAULT 0,
            epf_employer REAL NOT NULL DEFAULT 0,
            socso_employee REAL NOT NULL DEFAULT 0,
            socso_employer REAL NOT NULL DEFAULT 0,
            eis_employee REAL NOT NULL DEFAULT 0,
            eis_employer REAL NOT NULL DEFAULT 0,
            pcb REAL NOT NULL DEFAULT 0,
            net REAL NOT NULL DEFAULT 0,
            transaction_id INTEGER,
            employer_cost_transaction_id INTEGER
        );
        """)
        conn.execute("INSERT OR IGNORE INTO notes(id, text, updated_at) VALUES (1, '', NULL)")
        # Additive columns for databases created before these existed —
        # CREATE TABLE IF NOT EXISTS above won't alter an existing table.
        inv_cols = {r["name"] for r in conn.execute("PRAGMA table_info(invoices)")}
        for col, ddl in (
            ("description", "ALTER TABLE invoices ADD COLUMN description TEXT NOT NULL DEFAULT ''"),
            ("discount_pct", "ALTER TABLE invoices ADD COLUMN discount_pct REAL NOT NULL DEFAULT 0"),
            ("remarks", "ALTER TABLE invoices ADD COLUMN remarks TEXT NOT NULL DEFAULT ''"),
            ("lms_synced_at", "ALTER TABLE invoices ADD COLUMN lms_synced_at TEXT"),
            ("lms_sync_note", "ALTER TABLE invoices ADD COLUMN lms_sync_note TEXT"),
            # Matches the xlsm's Invoice template fields (Attention/Company/
            # Address block, Reference No, Sales Type, Sales Person, Tax) —
            # all optional so existing invoices keep working unchanged.
            ("attention", "ALTER TABLE invoices ADD COLUMN attention TEXT NOT NULL DEFAULT ''"),
            ("company", "ALTER TABLE invoices ADD COLUMN company TEXT NOT NULL DEFAULT ''"),
            ("address", "ALTER TABLE invoices ADD COLUMN address TEXT NOT NULL DEFAULT ''"),
            ("reference_no", "ALTER TABLE invoices ADD COLUMN reference_no TEXT NOT NULL DEFAULT ''"),
            ("sales_type", "ALTER TABLE invoices ADD COLUMN sales_type TEXT NOT NULL DEFAULT ''"),
            ("sales_person", "ALTER TABLE invoices ADD COLUMN sales_person TEXT NOT NULL DEFAULT ''"),
            ("tax_pct", "ALTER TABLE invoices ADD COLUMN tax_pct REAL NOT NULL DEFAULT 0"),
        ):
            if col not in inv_cols:
                conn.execute(ddl)
        contact_cols = {r["name"] for r in conn.execute("PRAGMA table_info(contacts)")}
        for col, ddl in (
            ("email", "ALTER TABLE contacts ADD COLUMN email TEXT DEFAULT ''"),
            ("phone", "ALTER TABLE contacts ADD COLUMN phone TEXT DEFAULT ''"),
        ):
            if col not in contact_cols:
                conn.execute(ddl)


# --- Generic list / delete helpers ---------------------------------------

def _rows(sql, params=()):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def list_transactions():
    return _rows("SELECT * FROM transactions ORDER BY date DESC, id DESC")


def list_contacts():
    return _rows("SELECT * FROM contacts ORDER BY name")


def get_invoice_items(invoice_id: int) -> list:
    return _rows(
        "SELECT description, qty, unit_price FROM invoice_items "
        "WHERE invoice_id = ? ORDER BY sort_order, id", (invoice_id,)
    )


def set_invoice_items(invoice_id: int, items: list):
    """Replaces all line items for an invoice. Each item: {description, qty, unit_price}."""
    with get_conn() as conn:
        conn.execute("DELETE FROM invoice_items WHERE invoice_id = ?", (invoice_id,))
        for i, item in enumerate(items):
            conn.execute(
                "INSERT INTO invoice_items(invoice_id, description, qty, unit_price, sort_order) "
                "VALUES (?, ?, ?, ?, ?)",
                (invoice_id, item["description"], item.get("qty", 1) or 1,
                 item.get("unit_price", 0) or 0, i)
            )


def _attach_items(inv: dict) -> dict:
    items = get_invoice_items(inv["id"])
    if not items:
        # Legacy single-line invoice (created before line items existed) —
        # synthesize one row from description/amount so callers can always
        # rely on `items` being present and non-empty.
        items = [{"description": inv.get("description") or "Services rendered",
                  "qty": 1, "unit_price": inv["amount"]}]
    inv["items"] = items
    return inv


def list_invoices():
    return [_attach_items(inv) for inv in _rows("SELECT * FROM invoices ORDER BY date DESC, id DESC")]


def list_assets():
    return _rows("SELECT * FROM assets ORDER BY id DESC")


def list_category_codes():
    with get_conn() as conn:
        return {r["category"]: r["code"] for r in conn.execute("SELECT category, code FROM category_codes")}


def delete_row(table: str, row_id: int):
    if table not in {"transactions", "contacts", "invoices", "assets", "teachers"}:
        raise ValueError("bad table")
    with get_conn() as conn:
        conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))


def insert_contact(name: str, contact_type: str, balance: float = 0.0, email: str = "", phone: str = ""):
    row = find_or_create_contact(name, contact_type, email=email, phone=phone)
    if balance:
        with get_conn() as conn:
            conn.execute("UPDATE contacts SET balance = ? WHERE id = ?", (balance, row["id"]))
    return get_contact(row["id"])


def get_contact_by_name(name: str, contact_type: str):
    with get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM contacts WHERE name = ? AND type = ?", (name, contact_type)
        ).fetchone()
        return dict(r) if r else None


def get_contact(cid: int):
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM contacts WHERE id = ?", (cid,)).fetchone()
        return dict(r) if r else None


def get_invoice(iid: int):
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM invoices WHERE id = ?", (iid,)).fetchone()
        return _attach_items(dict(r)) if r else None


def insert_asset(name, category, cost, dep=0.0) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO assets(name, category, cost, dep) VALUES (?, ?, ?, ?)",
            (name, category, float(cost), float(dep or 0)),
        )
        return cur.lastrowid


def mark_invoice_paid(iid: int):
    """Marks an invoice Paid and posts the matching cash-in transaction,
    mirroring the dashboard's markPaid()."""
    with get_conn() as conn:
        inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (iid,)).fetchone()
        if not inv or inv["status"] == "Paid":
            return dict(inv) if inv else None
        conn.execute("UPDATE invoices SET status = 'Paid' WHERE id = ?", (iid,))
        conn.execute(
            "UPDATE contacts SET balance = MAX(0, balance - ?) WHERE name = ? AND type = 'debtor'",
            (inv["amount"], inv["contact"]),
        )
    memo = inv["description"] if "description" in inv.keys() and inv["description"] else None
    desc = f"Invoice {inv['number']} — {inv['contact']}" + (f" ({memo})" if memo else "")
    # Best-guess category — the dashboard's inline category dropdown lets you
    # correct this per-transaction (e.g. to Workshop Revenue) in one click.
    category_code("Course Revenue", "in")
    insert_transaction(
        date=inv["date"], description=desc,
        tx_type="in", category="Course Revenue", amount=inv["amount"],
        payer_payee=inv["contact"],
    )
    return get_invoice(iid)


def set_invoice_status(iid: int, status: str):
    """Generic status setter for the invoice status dropdown. 'Paid' goes
    through mark_invoice_paid (posts the ledger transaction + clears the
    debtor balance); 'Deposit' just records the status — a deposit is a
    partial payment, so it doesn't post the full invoice amount as revenue.
    Any other status (Pending/Overdue) is a plain column update."""
    if status == "Paid":
        return mark_invoice_paid(iid)
    with get_conn() as conn:
        inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (iid,)).fetchone()
        if not inv:
            return None
        conn.execute("UPDATE invoices SET status = ? WHERE id = ?", (status, iid))
    return get_invoice(iid)


def set_invoice_lms_sync(iid: int, note: str):
    from datetime import datetime, timezone
    stamp = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE invoices SET lms_synced_at = ?, lms_sync_note = ? WHERE id = ?",
            (stamp, note, iid),
        )


def get_or_create_document_number(kind: str, ref_id: int, prefix: str) -> str:
    """Returns the document number for (kind, ref_id), minting the next one
    from the shared `counters` sequence the first time — so re-downloading a
    receipt/voucher reuses its original number, and the Telegram bot and the
    dashboard draw from the same RCP-/PV-/CV-/INV- sequences."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT number FROM documents WHERE kind = ? AND ref_id = ?", (kind, ref_id)
        ).fetchone()
        if row:
            return row["number"]
    number = next_document_number(prefix)
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO documents(kind, ref_id, number) VALUES (?, ?, ?)",
            (kind, ref_id, number),
        )
        row = conn.execute(
            "SELECT number FROM documents WHERE kind = ? AND ref_id = ?", (kind, ref_id)
        ).fetchone()
        return row["number"]


def get_notes() -> dict:
    with get_conn() as conn:
        r = conn.execute("SELECT text, updated_at FROM notes WHERE id = 1").fetchone()
        return dict(r) if r else {"text": "", "updated_at": None}


def save_notes(text: str):
    from datetime import datetime, timezone
    stamp = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute("UPDATE notes SET text = ?, updated_at = ? WHERE id = 1", (text, stamp))
    return {"text": text, "updated_at": stamp}


def is_empty() -> bool:
    with get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) AS c FROM transactions").fetchone()["c"]
        return n == 0


# --- users -------------------------------------------------------------

def user_count() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]


def get_user(username: str):
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
        return dict(r) if r else None


def get_user_by_id(uid: int):
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        return dict(r) if r else None


def list_users() -> list:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, username, role, active, created_at FROM users ORDER BY username COLLATE NOCASE"
        )]


def create_user(username: str, salt: str, hash_hex: str, role: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO users(username, salt, hash, role, active) VALUES (?, ?, ?, ?, 1)",
            (username.strip(), salt, hash_hex, role),
        )
        return cur.lastrowid


def set_user_password(uid: int, salt: str, hash_hex: str):
    with get_conn() as conn:
        conn.execute("UPDATE users SET salt = ?, hash = ? WHERE id = ?", (salt, hash_hex, uid))


def update_user(uid: int, *, role: str = None, active: bool = None):
    sets, params = [], []
    if role is not None:
        sets.append("role = ?"); params.append(role)
    if active is not None:
        sets.append("active = ?"); params.append(1 if active else 0)
    if not sets:
        return
    params.append(uid)
    with get_conn() as conn:
        conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", params)


def delete_user(uid: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))


def count_active_directors(exclude_id: int = None) -> int:
    q = "SELECT COUNT(*) AS c FROM users WHERE role = 'director' AND active = 1"
    params = ()
    if exclude_id is not None:
        q += " AND id != ?"
        params = (exclude_id,)
    with get_conn() as conn:
        return conn.execute(q, params).fetchone()["c"]


def next_counter(name: str) -> int:
    """Atomically increments and returns a named counter (RCP, PV, CV, INV)."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO counters(name, value) VALUES (?, 1) "
            "ON CONFLICT(name) DO UPDATE SET value = value + 1", (name,)
        )
        row = conn.execute("SELECT value FROM counters WHERE name = ?", (name,)).fetchone()
        return row["value"]


def next_document_number(prefix: str) -> str:
    """e.g. next_document_number('RCP') -> 'RCP-0007'"""
    n = next_counter(prefix)
    return f"{prefix}-{n:04d}"


def category_code(category: str, tx_type: str) -> str:
    """Returns the account code for a category, auto-provisioning a new
    one (4100+/6100+ series) the first time an unrecognised category
    is used — mirrors the dashboard's codeForCategory()."""
    with get_conn() as conn:
        row = conn.execute("SELECT code FROM category_codes WHERE category = ?", (category,)).fetchone()
        if row:
            return row["code"]
        known = KNOWN_INCOME_CODES if tx_type == "in" else KNOWN_EXPENSE_CODES
        if category in known:
            code = known[category]
        else:
            seq_name = "income_code_seq" if tx_type == "in" else "expense_code_seq"
            base = 4100 if tx_type == "in" else 6100
            code = str(base + next_counter(seq_name) - 1)
        conn.execute("INSERT INTO category_codes(category, code) VALUES (?, ?)", (category, code))
        return code


def insert_transaction(date, description, tx_type, category, amount, payer_payee=None, chat_id=None) -> int:
    category_code(category, tx_type)  # ensure it's provisioned
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO transactions(date, description, type, category, amount, payer_payee, chat_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (date, description, tx_type, category, amount, payer_payee, chat_id)
        )
        return cur.lastrowid


def get_transaction(tx_id: int):
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
        return dict(r) if r else None


def update_transaction(tx_id: int, fields: dict):
    allowed = {"date", "description", "type", "category", "amount", "payer_payee"}
    sets, params = [], []
    for k, v in fields.items():
        if k in allowed and v is not None:
            sets.append(f"{k} = ?")
            params.append(v)
    if not sets:
        return
    if "category" in fields and "type" in fields:
        category_code(fields["category"], fields["type"])
    params.append(tx_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE transactions SET {', '.join(sets)} WHERE id = ?", params)


def find_or_create_contact(name: str, contact_type: str, email: str = "", phone: str = ""):
    """Auto chart-of-accounts provisioning for contacts: looks up a debtor/
    creditor by name, or creates it with a fresh 1200-/2100-series code.
    If the contact already exists and a new email/phone is supplied while
    the stored one is blank, fills it in (never overwrites a set value)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM contacts WHERE name = ? AND type = ?", (name, contact_type)
        ).fetchone()
        if row:
            if email and not row["email"]:
                conn.execute("UPDATE contacts SET email = ? WHERE id = ?", (email, row["id"]))
            if phone and not row["phone"]:
                conn.execute("UPDATE contacts SET phone = ? WHERE id = ?", (phone, row["id"]))
            if (email and not row["email"]) or (phone and not row["phone"]):
                row = conn.execute("SELECT * FROM contacts WHERE id = ?", (row["id"],)).fetchone()
            return row
        seq_name = "debtor_code_seq" if contact_type == "debtor" else "creditor_code_seq"
        base = 1201 if contact_type == "debtor" else 2101
        code = str(base + next_counter(seq_name) - 1)
        cur = conn.execute(
            "INSERT INTO contacts(name, type, balance, code, email, phone) VALUES (?, ?, 0, ?, ?, ?)",
            (name, contact_type, code, email or "", phone or "")
        )
        return conn.execute("SELECT * FROM contacts WHERE id = ?", (cur.lastrowid,)).fetchone()


def insert_invoice(number, contact, date, due, amount, status="Pending", description="",
                   discount_pct=0.0, remarks="", items=None, attention="", company="",
                   address="", reference_no="", sales_type="", sales_person="",
                   tax_pct=0.0) -> int:
    """If `items` (list of {description, qty, unit_price}) is given, `amount`
    is recomputed as their sum and ignored; pass items=None for the legacy
    single-line-item behaviour (amount + description used as-is).

    attention/company/address/reference_no/sales_type/sales_person/tax_pct
    mirror the xlsm Invoice template's fields — all optional."""
    if items:
        amount = sum((i.get("qty", 1) or 1) * (i.get("unit_price", 0) or 0) for i in items)
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO invoices(number, contact, date, due, amount, status, description, "
            "discount_pct, remarks, attention, company, address, reference_no, sales_type, "
            "sales_person, tax_pct) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (number, contact, date, due, amount, status, description or "", discount_pct or 0,
             remarks or "", attention or "", company or "", address or "", reference_no or "",
             sales_type or "", sales_person or "", tax_pct or 0)
        )
        iid = cur.lastrowid
    if items:
        set_invoice_items(iid, items)
    return iid


# --- payroll -------------------------------------------------------------
# See payroll.py for the EPF/SOCSO/EIS calculation itself (and its accuracy
# caveats) — this section is just the CRUD + ledger-posting around it.

def list_teachers(active_only: bool = False) -> list:
    q = "SELECT * FROM teachers"
    if active_only:
        q += " WHERE active = 1"
    q += " ORDER BY name COLLATE NOCASE"
    return _rows(q)


def get_teacher(tid: int):
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM teachers WHERE id = ?", (tid,)).fetchone()
        return dict(r) if r else None


def find_teacher_by_name(name: str):
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM teachers WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
        return dict(r) if r else None


def insert_teacher(name, phone="", email="", employment_type="freelance",
                   rate_type="per_session", rate=0.0, epf_no="", socso_no="") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO teachers(name, phone, email, employment_type, rate_type, rate, epf_no, socso_no) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, phone or "", email or "", employment_type, rate_type, float(rate or 0),
             epf_no or "", socso_no or "")
        )
        return cur.lastrowid


def update_teacher(tid: int, fields: dict):
    allowed = {"name", "phone", "email", "employment_type", "rate_type", "rate",
               "epf_no", "socso_no", "active"}
    sets, params = [], []
    for k, v in fields.items():
        if k in allowed and v is not None:
            sets.append(f"{k} = ?")
            params.append(v)
    if not sets:
        return
    params.append(tid)
    with get_conn() as conn:
        conn.execute(f"UPDATE teachers SET {', '.join(sets)} WHERE id = ?", params)


def list_payroll_runs() -> list:
    """Includes item_count/total_net per run (aggregated) so the dashboard's
    runs list can show a summary without fetching every run's items."""
    return _rows("""
        SELECT payroll_runs.*,
               COUNT(payroll_items.id) AS item_count,
               COALESCE(SUM(payroll_items.net), 0) AS total_net
        FROM payroll_runs
        LEFT JOIN payroll_items ON payroll_items.run_id = payroll_runs.id
        GROUP BY payroll_runs.id
        ORDER BY payroll_runs.id DESC
    """)


def get_payroll_items(run_id: int) -> list:
    return _rows(
        "SELECT payroll_items.*, teachers.name AS teacher_name, "
        "teachers.employment_type AS teacher_employment_type "
        "FROM payroll_items JOIN teachers ON teachers.id = payroll_items.teacher_id "
        "WHERE run_id = ? ORDER BY payroll_items.id", (run_id,)
    )


def get_payroll_run(run_id: int):
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM payroll_runs WHERE id = ?", (run_id,)).fetchone()
        if not r:
            return None
        run = dict(r)
    run["items"] = get_payroll_items(run_id)
    return run


def insert_payroll_run(period_label: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO payroll_runs(period_label, status) VALUES (?, 'draft')", (period_label,)
        )
        return cur.lastrowid


def find_or_create_payroll_run(period_label: str) -> int:
    """Used by the Telegram bot's /payroll command so multiple messages for
    the same period accumulate into one draft run instead of each minting a
    new one."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM payroll_runs WHERE period_label = ? COLLATE NOCASE AND status = 'draft'",
            (period_label,)
        ).fetchone()
        if row:
            return row["id"]
    return insert_payroll_run(period_label)


def add_payroll_item(run_id: int, teacher_id: int, description: str, qty: float,
                     rate: float, pcb: float = 0.0) -> int:
    """Computes gross/deductions via payroll.compute_payroll_item() from the
    teacher's employment_type and inserts the resulting payroll_items row."""
    import payroll
    teacher = get_teacher(teacher_id)
    if not teacher:
        raise ValueError("Teacher not found")
    gross = float(qty or 1) * float(rate or 0)
    calc = payroll.compute_payroll_item(gross, teacher["employment_type"], pcb=pcb)
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO payroll_items(run_id, teacher_id, description, qty, rate, gross, "
            "epf_employee, epf_employer, socso_employee, socso_employer, eis_employee, "
            "eis_employer, pcb, net) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, teacher_id, description or "", float(qty or 1), float(rate or 0),
             calc["gross"], calc["epf_employee"], calc["epf_employer"],
             calc["socso_employee"], calc["socso_employer"], calc["eis_employee"],
             calc["eis_employer"], calc["pcb"], calc["net"])
        )
        return cur.lastrowid


def delete_payroll_item(item_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM payroll_items WHERE id = ?", (item_id,))


def post_payroll_run(run_id: int, date: str):
    """Posts every not-yet-posted item in a run to the ledger: one 'Payroll'
    transaction for the teacher's net pay, plus — for employees only, where
    there's a statutory employer cost beyond the net pay — a second
    'Statutory Contributions' transaction for the employer's EPF+SOCSO+EIS
    share. Marks the run 'paid'. Idempotent per item (skips ones that
    already have a transaction_id) so re-posting a partially-posted run
    only posts what's new."""
    run = get_payroll_run(run_id)
    if not run:
        raise ValueError("Payroll run not found")
    for item in run["items"]:
        if item["transaction_id"]:
            continue
        teacher_name = item["teacher_name"]
        desc = f"Payroll — {teacher_name}" + (f" ({item['description']})" if item["description"] else "")
        tx_id = insert_transaction(
            date=date, description=desc, tx_type="out", category="Payroll",
            amount=item["net"], payer_payee=teacher_name,
        )
        employer_statutory = (item["epf_employer"] + item["socso_employer"] + item["eis_employer"])
        cost_tx_id = None
        if employer_statutory:
            cost_tx_id = insert_transaction(
                date=date, description=f"Employer EPF/SOCSO/EIS — {teacher_name}",
                tx_type="out", category="Statutory Contributions",
                amount=employer_statutory, payer_payee=teacher_name,
            )
        with get_conn() as conn:
            conn.execute(
                "UPDATE payroll_items SET transaction_id = ?, employer_cost_transaction_id = ? WHERE id = ?",
                (tx_id, cost_tx_id, item["id"])
            )
    with get_conn() as conn:
        conn.execute("UPDATE payroll_runs SET status = 'paid' WHERE id = ?", (run_id,))
    return get_payroll_run(run_id)
