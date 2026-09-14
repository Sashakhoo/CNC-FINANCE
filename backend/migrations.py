"""
Idempotent data migrations run once at startup.

Each migration has an id; the ids that have run are recorded in the
`_migrations` table so nothing is applied twice. Use these for one-off
corrections to already-seeded ledgers (the seed itself only runs on an
empty database).
"""
import storage


def _applied(conn, mid: str) -> bool:
    conn.execute("CREATE TABLE IF NOT EXISTS _migrations (id TEXT PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    return conn.execute("SELECT 1 FROM _migrations WHERE id = ?", (mid,)).fetchone() is not None


def _mark(conn, mid: str):
    conn.execute("INSERT OR IGNORE INTO _migrations(id) VALUES (?)", (mid,))


# (date, description) -> new category. Matches the owner's reclassification
# of the Apr-Aug 2026 "Consulting Revenue" rows (Sep 2026).
_RECATEGORISE_2026_09 = {
    ("2026-08-25", "Invoice #159 — Muhammad Firdaus"): "Course Revenue",
    ("2026-08-24", "Invoice #161 — Siti Hajar Binti (Haifa Adelea)"): "Course Revenue",
    ("2026-08-21", "Invoice #162 — Koh Wen Han (AI for Workplace)"): "Workshop Revenue",
    ("2026-08-17", "Invoice #156 — Restoran Tong"): "Course Revenue",
    ("2026-08-17", "Invoice #157 — Restoran Tong"): "Workshop Revenue",
    ("2026-08-16", "Invoice #155 — Ooi Kah Seong (AI for Work)"): "Workshop Revenue",
    ("2026-08-01", "Invoice #117 — CC Crest Consultancy"): "Course Revenue",
    ("2026-07-30", "AI Automation project — Constance (Chan Siew Fuin)"): "Workshop Revenue",
    ("2026-07-27", "Invoice #117 — CC Crest Consultancy"): "Course Revenue",
}


def _migration_ran(mid: str) -> bool:
    with storage.get_conn() as conn:
        return _applied(conn, mid)


def _finish(mid: str):
    with storage.get_conn() as conn:
        _mark(conn, mid)


def _recategorise_consulting_revenue():
    mid = "2026-09-recategorise-consulting-revenue"
    if _migration_ran(mid):
        return
    storage.category_code("Workshop Revenue", "in")  # provision the new code
    with storage.get_conn() as conn:
        n = 0
        for (date, desc), cat in _RECATEGORISE_2026_09.items():
            cur = conn.execute(
                "UPDATE transactions SET category = ? "
                "WHERE date = ? AND description = ? AND type = 'in' AND category = 'Consulting Revenue'",
                (cat, date, desc),
            )
            n += cur.rowcount
    _finish(mid)
    print(f"Migration {mid}: recategorised {n} transaction(s)")


def _rename_unpaid_to_pending():
    mid = "2026-09-invoice-status-unpaid-to-pending"
    if _migration_ran(mid):
        return
    with storage.get_conn() as conn:
        cur = conn.execute("UPDATE invoices SET status = 'Pending' WHERE status = 'Unpaid'")
        n = cur.rowcount
    _finish(mid)
    print(f"Migration {mid}: updated {n} invoice(s)")


def _backfill_receipt_numbers():
    """RCP numbers used to be minted only when someone clicked to generate
    the receipt PDF, so the sequence undercounted actual cash-in
    transactions. Assigns an RCP- number to every historical cash-in
    transaction that doesn't have one yet, in date/id order, so the
    sequence tallies with the real transaction count going forward."""
    mid = "2026-09-backfill-receipt-numbers"
    if _migration_ran(mid):
        return
    with storage.get_conn() as conn:
        rows = conn.execute(
            "SELECT id FROM transactions WHERE type = 'in' "
            "AND id NOT IN (SELECT ref_id FROM documents WHERE kind = 'receipt') "
            "ORDER BY date, id"
        ).fetchall()
    for row in rows:
        storage.get_or_create_document_number("receipt", row["id"], "RCP")
    _finish(mid)
    print(f"Migration {mid}: backfilled {len(rows)} receipt number(s)")


def run_migrations() -> None:
    _recategorise_consulting_revenue()
    _rename_unpaid_to_pending()
    _backfill_receipt_numbers()
