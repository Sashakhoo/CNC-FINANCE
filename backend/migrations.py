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


def run_migrations() -> None:
    mid = "2026-09-recategorise-consulting-revenue"
    with storage.get_conn() as conn:
        if _applied(conn, mid):
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
        _mark(conn, mid)
    print(f"Migration {mid}: recategorised {n} transaction(s)")
