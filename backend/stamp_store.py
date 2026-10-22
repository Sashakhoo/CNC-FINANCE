"""
Database layer for the Document Centre (digital stamp + document
verification). Same SQLite database as the rest of CNC Finance; every table
is prefixed `stamp_` so nothing collides with the finance tables (there is
already an unrelated `documents` table for receipt/voucher numbering).

Tables are created by `init_db()` on startup (CREATE TABLE IF NOT EXISTS),
the same additive convention storage.py uses.

The audit table is append-only at the database level: triggers reject any
UPDATE or DELETE, so not even application code can rewrite history.
"""
import json
import secrets
from datetime import datetime, timedelta, timezone

import storage

ID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O/1/I - unambiguous when read aloud

DEFAULT_SETTINGS = {
    "company_name": "CODE N CODE SOLUTION",
    "registration_number": "AS0511861-M",
    "location": "Johor, Malaysia",
    "date_format": "DD MMM YYYY",
    "timezone": "Asia/Kuala_Lumpur",
    "default_stamp_size": 0.22,        # fraction of the page width
    "qr_enabled": False,
    "qr_position": "bottom-right",
    "footer_enabled": False,
    "max_upload_mb": 20,
    "public_show_filename": False,
}

TEXT_PRESETS = ["APPROVED", "CERTIFIED", "RECEIVED", "PAID", "CONFIDENTIAL",
                "FOR INTERNAL USE", "SIGNED"]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_tz(name: str = None):
    """Timestamps are stored in UTC and shown in the configured zone. Falls
    back to a fixed +08:00 (Malaysia has no DST) if the tz database is missing."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name or "Asia/Kuala_Lumpur")
    except Exception:
        return timezone(timedelta(hours=8), "MYT")


def init_db():
    with storage.get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS stamp_stamps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'custom',
            kind TEXT NOT NULL DEFAULT 'image' CHECK(kind IN ('image','text')),
            text TEXT NOT NULL DEFAULT '',
            color TEXT NOT NULL DEFAULT '#16168a',
            file_key TEXT,
            mime_type TEXT,
            allowed_roles TEXT NOT NULL DEFAULT 'director,admin',
            active INTEGER NOT NULL DEFAULT 1,
            is_default INTEGER NOT NULL DEFAULT 0,
            created_by INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS stamp_signatures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            file_key TEXT NOT NULL,
            mime_type TEXT NOT NULL DEFAULT 'image/png',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_stamp_signatures_user ON stamp_signatures(user_id, active);

        CREATE TABLE IF NOT EXISTS stamp_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT NOT NULL UNIQUE,
            original_filename TEXT NOT NULL,
            original_file_key TEXT NOT NULL,
            final_file_key TEXT,
            original_sha256 TEXT NOT NULL,
            final_sha256 TEXT,
            file_size INTEGER NOT NULL DEFAULT 0,
            final_size INTEGER,
            page_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'DRAFT'
                CHECK(status IN ('DRAFT','PROCESSING','COMPLETED','FAILED','VOID')),
            version INTEGER NOT NULL DEFAULT 1,
            draft_json TEXT,
            summary_json TEXT,
            created_by INTEGER NOT NULL,
            created_by_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            completed_at TEXT,
            voided_at TEXT,
            voided_by INTEGER,
            void_reason TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_stamp_documents_final ON stamp_documents(final_sha256);
        CREATE INDEX IF NOT EXISTS ix_stamp_documents_created ON stamp_documents(created_at);
        CREATE INDEX IF NOT EXISTS ix_stamp_documents_owner ON stamp_documents(created_by);

        CREATE TABLE IF NOT EXISTS stamp_document_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER NOT NULL REFERENCES stamp_documents(id),
            version_number INTEGER NOT NULL,
            file_key TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            created_by INTEGER,
            created_at TEXT NOT NULL,
            UNIQUE(doc_id, version_number)
        );
        CREATE TABLE IF NOT EXISTS stamp_placements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER NOT NULL REFERENCES stamp_documents(id),
            kind TEXT NOT NULL,
            stamp_id INTEGER,
            signature_id INTEGER,
            text TEXT,
            page_number INTEGER NOT NULL,
            x REAL NOT NULL, y REAL NOT NULL,
            width REAL NOT NULL, height REAL NOT NULL,
            rotation REAL NOT NULL DEFAULT 0,
            opacity REAL NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_stamp_placements_doc ON stamp_placements(doc_id);

        CREATE TABLE IF NOT EXISTS stamp_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            user_id INTEGER,
            username TEXT,
            document_id TEXT,
            ip_address TEXT,
            user_agent TEXT,
            metadata TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_stamp_audit_doc ON stamp_audit(document_id);
        CREATE INDEX IF NOT EXISTS ix_stamp_audit_created ON stamp_audit(created_at);
        CREATE TRIGGER IF NOT EXISTS stamp_audit_no_update BEFORE UPDATE ON stamp_audit
            BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
        CREATE TRIGGER IF NOT EXISTS stamp_audit_no_delete BEFORE DELETE ON stamp_audit
            BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;

        CREATE TABLE IF NOT EXISTS stamp_verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT,
            verification_type TEXT NOT NULL,
            result TEXT NOT NULL,
            ip_address TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_stamp_verifications_created ON stamp_verifications(created_at);

        CREATE TABLE IF NOT EXISTS stamp_signing (
            document_id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','COMPLETED','CANCELLED')),
            plan_json TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            created_by_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS stamp_sign_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT NOT NULL,
            signer_name TEXT NOT NULL,
            signer_contact TEXT NOT NULL DEFAULT '',
            token_hash TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'PENDING'
                CHECK(status IN ('PENDING','SIGNED','DECLINED','CANCELLED')),
            signature_file_key TEXT,
            initials_file_key TEXT,
            values_json TEXT,
            decline_reason TEXT,
            signed_at TEXT,
            signer_ip TEXT,
            signer_user_agent TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_stamp_sign_requests_doc ON stamp_sign_requests(document_id);

        CREATE TABLE IF NOT EXISTS stamp_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT NOT NULL,
            updated_by INTEGER,
            updated_at TEXT NOT NULL
        );
        """)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(stamp_signatures)")}
        if "kind" not in cols:      # signatures and initials, several saved per person
            conn.execute("ALTER TABLE stamp_signatures ADD COLUMN kind TEXT NOT NULL DEFAULT 'signature'")
        if "saved" not in cols:     # 0 = used once ("Save signature" unticked), hidden from the list
            conn.execute("ALTER TABLE stamp_signatures ADD COLUMN saved INTEGER NOT NULL DEFAULT 1")
        conn.execute("""CREATE TABLE IF NOT EXISTS stamp_doc_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT NOT NULL,
            file_key TEXT NOT NULL,
            created_by INTEGER,
            created_at TEXT NOT NULL)""")


# --- settings ------------------------------------------------------------

def get_settings() -> dict:
    out = dict(DEFAULT_SETTINGS)
    with storage.get_conn() as conn:
        for r in conn.execute("SELECT setting_key, setting_value FROM stamp_settings"):
            if r["setting_key"] in DEFAULT_SETTINGS:
                try:
                    out[r["setting_key"]] = json.loads(r["setting_value"])
                except ValueError:
                    pass
    return out


def save_settings(values: dict, user_id: int):
    with storage.get_conn() as conn:
        for k, v in values.items():
            if k not in DEFAULT_SETTINGS:
                continue
            conn.execute(
                "INSERT INTO stamp_settings(setting_key, setting_value, updated_by, updated_at) "
                "VALUES (?,?,?,?) ON CONFLICT(setting_key) DO UPDATE SET "
                "setting_value=excluded.setting_value, updated_by=excluded.updated_by, "
                "updated_at=excluded.updated_at",
                (k, json.dumps(v), user_id, now_iso()))


# --- audit (append-only) -------------------------------------------------

def audit(event_type: str, *, user: dict = None, document_id: str = None,
          ip: str = None, user_agent: str = None, metadata: dict = None):
    with storage.get_conn() as conn:
        conn.execute(
            "INSERT INTO stamp_audit(event_type, user_id, username, document_id, ip_address, "
            "user_agent, metadata, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (event_type, (user or {}).get("id"), (user or {}).get("username"), document_id,
             ip, (user_agent or "")[:300], json.dumps(metadata or {}), now_iso()))


def list_audit(document_id: str = None, limit: int = 200, event_type: str = None) -> list:
    q, params = "SELECT * FROM stamp_audit", []
    where = []
    if document_id:
        where.append("document_id = ?"); params.append(document_id)
    if event_type:
        where.append("event_type = ?"); params.append(event_type)
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 1000)))
    with storage.get_conn() as conn:
        rows = [dict(r) for r in conn.execute(q, params)]
    for r in rows:
        try:
            r["metadata"] = json.loads(r["metadata"] or "{}")
        except ValueError:
            r["metadata"] = {}
    return rows


def log_verification(document_id, verification_type: str, result: str, ip: str):
    with storage.get_conn() as conn:
        conn.execute(
            "INSERT INTO stamp_verifications(document_id, verification_type, result, ip_address, created_at) "
            "VALUES (?,?,?,?,?)", (document_id, verification_type, result, ip, now_iso()))


def list_verifications(limit: int = 20) -> list:
    with storage.get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM stamp_verifications ORDER BY id DESC LIMIT ?", (limit,))]


# --- stamps ----------------------------------------------------------------

def _stamp(row) -> dict:
    d = dict(row)
    d["active"] = bool(d["active"])
    d["is_default"] = bool(d["is_default"])
    d["allowed_roles"] = [r for r in (d["allowed_roles"] or "").split(",") if r]
    d["has_image"] = bool(d.pop("file_key", None))
    return d


def list_stamps(include_inactive: bool = False) -> list:
    q = "SELECT * FROM stamp_stamps"
    if not include_inactive:
        q += " WHERE active = 1"
    q += " ORDER BY is_default DESC, kind, id"
    with storage.get_conn() as conn:
        return [_stamp(r) for r in conn.execute(q)]


def get_stamp_row(stamp_id: int):
    with storage.get_conn() as conn:
        r = conn.execute("SELECT * FROM stamp_stamps WHERE id = ?", (stamp_id,)).fetchone()
        return dict(r) if r else None


def create_stamp(*, name, category, kind, text="", color="#16168a", file_key=None,
                 mime_type=None, allowed_roles="director,admin", is_default=False,
                 created_by=None) -> int:
    ts = now_iso()
    with storage.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO stamp_stamps(name, category, kind, text, color, file_key, mime_type, "
            "allowed_roles, active, is_default, created_by, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,1,?,?,?,?)",
            (name, category, kind, text, color, file_key, mime_type, allowed_roles,
             1 if is_default else 0, created_by, ts, ts))
        return cur.lastrowid


def update_stamp(stamp_id: int, fields: dict):
    allowed = {"name", "category", "text", "color", "file_key", "mime_type", "allowed_roles", "active"}
    sets, params = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k} = ?")
            params.append((1 if v else 0) if k == "active" else v)
    if not sets:
        return
    sets.append("updated_at = ?"); params.append(now_iso())
    params.append(stamp_id)
    with storage.get_conn() as conn:
        conn.execute(f"UPDATE stamp_stamps SET {', '.join(sets)} WHERE id = ?", params)


def stamp_count() -> int:
    with storage.get_conn() as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM stamp_stamps").fetchone()["c"]


# --- signatures ------------------------------------------------------------

def get_signature(user_id: int):
    with storage.get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM stamp_signatures WHERE user_id = ? AND active = 1 ORDER BY id DESC LIMIT 1",
            (user_id,)).fetchone()
        return dict(r) if r else None


def list_signatures(user_id: int) -> list:
    with storage.get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, kind, created_at FROM stamp_signatures WHERE user_id = ? AND active = 1 AND saved = 1 "
            "ORDER BY id DESC", (user_id,))]


def get_own_signature(user_id: int, sig_id: int):
    """A signature row only ever resolves for the person who created it."""
    with storage.get_conn() as conn:
        r = conn.execute("SELECT * FROM stamp_signatures WHERE id = ? AND user_id = ? AND active = 1",
                         (sig_id, user_id)).fetchone()
        return dict(r) if r else None


def add_signature(user_id: int, file_key: str, kind: str = "signature", saved: bool = True) -> int:
    ts = now_iso()
    with storage.get_conn() as conn:
        return conn.execute(
            "INSERT INTO stamp_signatures(user_id, file_key, mime_type, active, kind, saved, created_at, updated_at) "
            "VALUES (?,?,'image/png',1,?,?,?,?)",
            (user_id, file_key, kind, 1 if saved else 0, ts, ts)).lastrowid


def remove_signature(user_id: int, sig_id: int) -> bool:
    with storage.get_conn() as conn:
        return conn.execute("UPDATE stamp_signatures SET active = 0, updated_at = ? WHERE id = ? AND user_id = ?",
                            (now_iso(), sig_id, user_id)).rowcount == 1


def add_doc_image(document_id: str, file_key: str, user_id: int) -> int:
    with storage.get_conn() as conn:
        return conn.execute("INSERT INTO stamp_doc_images(document_id, file_key, created_by, created_at) "
                            "VALUES (?,?,?,?)", (document_id, file_key, user_id, now_iso())).lastrowid


def get_doc_image(document_id: str, image_id: int):
    with storage.get_conn() as conn:
        r = conn.execute("SELECT * FROM stamp_doc_images WHERE id = ? AND document_id = ?",
                         (image_id, document_id)).fetchone()
        return dict(r) if r else None


def get_signature_by_id(sig_id: int):
    with storage.get_conn() as conn:
        r = conn.execute("SELECT * FROM stamp_signatures WHERE id = ?", (sig_id,)).fetchone()
        return dict(r) if r else None


def set_signature(user_id: int, file_key: str) -> int:
    """Old signatures are kept (inactive) because finished documents refer to them."""
    ts = now_iso()
    with storage.get_conn() as conn:
        conn.execute("UPDATE stamp_signatures SET active = 0, updated_at = ? WHERE user_id = ? AND active = 1",
                     (ts, user_id))
        cur = conn.execute(
            "INSERT INTO stamp_signatures(user_id, file_key, mime_type, active, created_at, updated_at) "
            "VALUES (?,?,'image/png',1,?,?)", (user_id, file_key, ts, ts))
        return cur.lastrowid


def disable_signature(user_id: int):
    with storage.get_conn() as conn:
        conn.execute("UPDATE stamp_signatures SET active = 0, updated_at = ? WHERE user_id = ? AND active = 1",
                     (now_iso(), user_id))


# --- documents -------------------------------------------------------------

def _new_document_id() -> str:
    suffix = "".join(secrets.choice(ID_ALPHABET) for _ in range(6))
    return f"CNC-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{suffix}"


def create_document(*, original_filename, original_file_key, original_sha256, file_size,
                    page_count, user: dict, id_date: str = None) -> dict:
    """The Document ID is random (not sequential) and the UNIQUE constraint is
    the real guarantee - on the rare collision we simply draw again."""
    ts = now_iso()
    for _ in range(12):
        doc_id = _new_document_id()
        if id_date:
            doc_id = f"CNC-{id_date}-{doc_id.rsplit('-', 1)[1]}"
        try:
            with storage.get_conn() as conn:
                conn.execute(
                    "INSERT INTO stamp_documents(document_id, original_filename, original_file_key, "
                    "original_sha256, file_size, page_count, status, created_by, created_by_name, created_at) "
                    "VALUES (?,?,?,?,?,?,'DRAFT',?,?,?)",
                    (doc_id, original_filename, original_file_key, original_sha256, file_size,
                     page_count, user["id"], user["username"], ts))
            return get_document(doc_id)
        except storage.sqlite3.IntegrityError:
            continue
    raise RuntimeError("could not allocate a unique document id")


def _doc(row) -> dict:
    d = dict(row)
    for k in ("draft_json", "summary_json"):
        raw = d.pop(k, None)
        try:
            d[k[:-5]] = json.loads(raw) if raw else None
        except ValueError:
            d[k[:-5]] = None
    return d


def get_document(document_id: str):
    with storage.get_conn() as conn:
        r = conn.execute("SELECT * FROM stamp_documents WHERE document_id = ?", (document_id,)).fetchone()
        return _doc(r) if r else None


def find_by_final_hash(sha256: str):
    with storage.get_conn() as conn:
        r = conn.execute("SELECT * FROM stamp_documents WHERE final_sha256 = ? ORDER BY id DESC LIMIT 1",
                         (sha256,)).fetchone()
        return _doc(r) if r else None


def list_documents(*, owner_id: int = None, completed_only: bool = False, q: str = None,
                   status: str = None, user: str = None, date_from: str = None,
                   date_to: str = None, limit: int = 200) -> list:
    where, params = [], []
    if owner_id is not None:
        where.append("created_by = ?"); params.append(owner_id)
    if completed_only:
        where.append("status IN ('COMPLETED','VOID')")
    if q:
        where.append("(document_id LIKE ? OR original_filename LIKE ?)")
        like = f"%{q.strip()}%"; params += [like, like]
    if status:
        where.append("status = ?"); params.append(status)
    if user:
        where.append("created_by_name = ? COLLATE NOCASE"); params.append(user)
    if date_from:
        where.append("created_at >= ?"); params.append(date_from)
    if date_to:
        where.append("created_at <= ?"); params.append(date_to + "T23:59:59Z")
    sql = "SELECT * FROM stamp_documents"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    with storage.get_conn() as conn:
        return [_doc(r) for r in conn.execute(sql, params)]


def save_draft(document_id: str, draft: dict):
    with storage.get_conn() as conn:
        conn.execute("UPDATE stamp_documents SET draft_json = ? WHERE document_id = ? AND status IN ('DRAFT','FAILED')",
                     (json.dumps(draft), document_id))


def claim_for_processing(document_id: str) -> bool:
    """Atomic DRAFT/FAILED -> PROCESSING. Returns False if someone else got
    there first or the document is already finished - a completed document
    is never regenerated or overwritten."""
    with storage.get_conn() as conn:
        cur = conn.execute(
            "UPDATE stamp_documents SET status = 'PROCESSING' WHERE document_id = ? "
            "AND status IN ('DRAFT','FAILED')", (document_id,))
        return cur.rowcount == 1


def mark_failed(document_id: str):
    with storage.get_conn() as conn:
        conn.execute("UPDATE stamp_documents SET status = 'FAILED' WHERE document_id = ? AND status = 'PROCESSING'",
                     (document_id,))


def complete_document(document_id: str, *, final_file_key, final_sha256, final_size,
                      placements: list, summary: dict, user: dict):
    ts = now_iso()
    with storage.get_conn() as conn:
        row = conn.execute("SELECT id, version FROM stamp_documents WHERE document_id = ?",
                           (document_id,)).fetchone()
        conn.execute(
            "UPDATE stamp_documents SET status = 'COMPLETED', final_file_key = ?, final_sha256 = ?, "
            "final_size = ?, completed_at = ?, summary_json = ? WHERE id = ? AND status = 'PROCESSING'",
            (final_file_key, final_sha256, final_size, ts, json.dumps(summary), row["id"]))
        conn.execute(
            "INSERT INTO stamp_document_versions(doc_id, version_number, file_key, sha256, created_by, created_at) "
            "VALUES (?,?,?,?,?,?)", (row["id"], row["version"], final_file_key, final_sha256, user["id"], ts))
        for p in placements:
            conn.execute(
                "INSERT INTO stamp_placements(doc_id, kind, stamp_id, signature_id, text, page_number, "
                "x, y, width, height, rotation, opacity, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (row["id"], p["kind"], p.get("stamp_id"), p.get("signature_id"), p.get("text"),
                 p["page"], p["x"], p["y"], p["w"], p["h"], p.get("rotation", 0),
                 p.get("opacity", 1), ts))


def void_document(document_id: str, user: dict, reason: str) -> bool:
    with storage.get_conn() as conn:
        cur = conn.execute(
            "UPDATE stamp_documents SET status = 'VOID', voided_at = ?, voided_by = ?, void_reason = ? "
            "WHERE document_id = ? AND status = 'COMPLETED'",
            (now_iso(), user["id"], reason, document_id))
        return cur.rowcount == 1


def stats() -> dict:
    local = datetime.now(get_tz(get_settings().get("timezone")))
    day0 = local.replace(hour=0, minute=0, second=0, microsecond=0)
    fmt = lambda d: d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with storage.get_conn() as conn:
        def c(sql, params=()):
            return conn.execute(sql, params).fetchone()["c"]
        done = "status IN ('COMPLETED','VOID')"
        return {
            "total": c(f"SELECT COUNT(*) AS c FROM stamp_documents WHERE {done}"),
            "today": c(f"SELECT COUNT(*) AS c FROM stamp_documents WHERE {done} AND completed_at >= ?",
                       (fmt(day0),)),
            "month": c(f"SELECT COUNT(*) AS c FROM stamp_documents WHERE {done} AND completed_at >= ?",
                       (fmt(day0.replace(day=1)),)),
            "drafts": c("SELECT COUNT(*) AS c FROM stamp_documents WHERE status IN ('DRAFT','FAILED')"),
            "verifications": c("SELECT COUNT(*) AS c FROM stamp_verifications"),
        }


# --- e-signature requests -----------------------------------------------------
# A document "out for signature" stays DRAFT in stamp_documents and has an
# OPEN row in stamp_signing. Each signer gets a random link; only the SHA-256
# of the link token is stored, so a database leak can't be used to sign.

def token_hash(token: str) -> str:
    import hashlib
    return hashlib.sha256((token or "").encode()).hexdigest()


def get_signing(document_id: str):
    with storage.get_conn() as conn:
        r = conn.execute("SELECT * FROM stamp_signing WHERE document_id = ?", (document_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["plan"] = json.loads(d.pop("plan_json") or "{}")
    return d


def list_sign_requests(document_id: str) -> list:
    with storage.get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM stamp_sign_requests WHERE document_id = ? ORDER BY id", (document_id,))]


def open_signing(document_id: str, plan: dict, signers: list, user: dict) -> dict:
    """signers: [{name, contact}] -> {name_lower: (request_id, token)}"""
    ts = now_iso()
    links = {}
    with storage.get_conn() as conn:
        conn.execute("DELETE FROM stamp_signing WHERE document_id = ? AND status = 'CANCELLED'", (document_id,))
        conn.execute(
            "INSERT INTO stamp_signing(document_id, status, plan_json, created_by, created_by_name, created_at) "
            "VALUES (?, 'OPEN', ?, ?, ?, ?)", (document_id, "{}", user["id"], user["username"], ts))
        for s in signers:
            token = secrets.token_urlsafe(32)
            cur = conn.execute(
                "INSERT INTO stamp_sign_requests(document_id, signer_name, signer_contact, token_hash, created_at) "
                "VALUES (?,?,?,?,?)", (document_id, s["name"], s.get("contact", ""), token_hash(token), ts))
            links[s["name"].lower()] = (cur.lastrowid, token)
        plan = dict(plan)
        plan["request_ids"] = {k: v[0] for k, v in links.items()}
        conn.execute("UPDATE stamp_signing SET plan_json = ? WHERE document_id = ?", (json.dumps(plan), document_id))
    return links


def renew_sign_token(request_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with storage.get_conn() as conn:
        conn.execute("UPDATE stamp_sign_requests SET token_hash = ? WHERE id = ? AND status = 'PENDING'",
                     (token_hash(token), request_id))
    return token


def get_sign_request_by_token(token: str):
    if not token or len(token) > 100:
        return None
    with storage.get_conn() as conn:
        r = conn.execute("SELECT * FROM stamp_sign_requests WHERE token_hash = ?", (token_hash(token),)).fetchone()
    return dict(r) if r else None


def record_signature(request_id: int, signature_key, initials_key, values: dict, ip: str,
                     user_agent: str) -> bool:
    with storage.get_conn() as conn:
        cur = conn.execute(
            "UPDATE stamp_sign_requests SET status = 'SIGNED', signature_file_key = ?, initials_file_key = ?, "
            "values_json = ?, signed_at = ?, signer_ip = ?, signer_user_agent = ? "
            "WHERE id = ? AND status = 'PENDING'",
            (signature_key, initials_key, json.dumps(values or {}), now_iso(), ip, (user_agent or "")[:300],
             request_id))
        return cur.rowcount == 1


def decline_request(request_id: int, reason: str, ip: str, user_agent: str) -> bool:
    with storage.get_conn() as conn:
        cur = conn.execute(
            "UPDATE stamp_sign_requests SET status = 'DECLINED', decline_reason = ?, signed_at = ?, "
            "signer_ip = ?, signer_user_agent = ? WHERE id = ? AND status = 'PENDING'",
            (reason, now_iso(), ip, (user_agent or "")[:300], request_id))
        return cur.rowcount == 1


def cancel_signing(document_id: str) -> bool:
    with storage.get_conn() as conn:
        cur = conn.execute("UPDATE stamp_signing SET status = 'CANCELLED' WHERE document_id = ? AND status = 'OPEN'",
                           (document_id,))
        if cur.rowcount != 1:
            return False
        conn.execute("UPDATE stamp_sign_requests SET status = 'CANCELLED' WHERE document_id = ? "
                     "AND status IN ('PENDING','DECLINED')", (document_id,))
        return True


def close_signing(document_id: str):
    with storage.get_conn() as conn:
        conn.execute("UPDATE stamp_signing SET status = 'COMPLETED', completed_at = ? WHERE document_id = ?",
                     (now_iso(), document_id))
