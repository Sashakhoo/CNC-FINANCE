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
    "Payment Gateway": "6011", "Printing": "6012", "Other Expense": "6099",
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
    if table not in {"transactions", "contacts", "invoices", "assets"}:
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
                   discount_pct=0.0, remarks="", items=None) -> int:
    """If `items` (list of {description, qty, unit_price}) is given, `amount`
    is recomputed as their sum and ignored; pass items=None for the legacy
    single-line-item behaviour (amount + description used as-is)."""
    if items:
        amount = sum((i.get("qty", 1) or 1) * (i.get("unit_price", 0) or 0) for i in items)
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO invoices(number, contact, date, due, amount, status, description, discount_pct, remarks) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (number, contact, date, due, amount, status, description or "", discount_pct or 0, remarks or "")
        )
        iid = cur.lastrowid
    if items:
        set_invoice_items(iid, items)
    return iid
