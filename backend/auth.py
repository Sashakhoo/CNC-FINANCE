"""
Auth for the CNC dashboard — database-backed user accounts.

Accounts live in the `users` table (see storage.py). A director manages them
from the dashboard (Team screen). Roles:

  - director : sees everything, edits everything, manages accounts
  - admin    : sees everything, can ONLY create invoices and generate
               documents (receipts / vouchers / invoice PDFs)

Any other role has no access — login is refused.

First run: when the users table is empty, the dashboard shows a one-time
"create the first account" screen (POST /api/setup) — you choose your own
username and password and become the director. No account is ever created
automatically.

Optional: setting the DASH_USERS environment variable
(`username:password:role,...`, password may be `scrypt:<salt>:<hash>`) will
pre-create those accounts on first boot instead. Leave it unset to use the
setup screen. Either way it is ignored once any user exists.

Passwords are scrypt-hashed; login is constant-time and rate-limited.
"""
import hashlib
import hmac
import os
import secrets
import time

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, HTTPException

import storage

COOKIE_NAME = "cnc_session"
MAX_AGE = int(os.environ.get("SESSION_MAX_AGE_SECONDS", 60 * 60 * 24 * 7))  # 7 days

ROLE_CAPS = {
    "director": {"*"},
    "admin": {"invoices", "documents"},
}
ALL_CAPS = ["transactions", "contacts", "invoices", "assets", "notes", "documents", "users", "payroll"]
ASSIGNABLE_ROLES = ["admin", "director"]

_SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32)
_DUMMY = ("00" * 16, "ff" * 32)  # burns ~equal CPU for unknown usernames

SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
if not SESSION_SECRET:
    SESSION_SECRET = secrets.token_hex(32)
    print("WARNING: SESSION_SECRET not set — using an ephemeral one (all sessions "
          "drop on restart). Set SESSION_SECRET to a long random string.")

_serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="cnc-session")


class NoAccess(Exception):
    """Valid credentials, but the role grants no access at all."""


# --- capabilities ----------------------------------------------------------

def caps_for(role: str) -> list:
    c = ROLE_CAPS.get(role, set())
    return ALL_CAPS[:] if "*" in c else sorted(c)


def has_access(role: str) -> bool:
    return role in ROLE_CAPS


def can(role: str, cap: str) -> bool:
    c = ROLE_CAPS.get(role, set())
    return "*" in c or cap in c


# --- password hashing ----------------------------------------------------

def _hash(password: str, salt_hex: str) -> str:
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT).hex()


def hash_new(password: str) -> tuple[str, str]:
    salt_hex = secrets.token_hex(16)
    return salt_hex, _hash(password, salt_hex)


def _record_from_secret(secret: str) -> tuple[str, str]:
    if secret.startswith("scrypt:"):
        _, salt_hex, hash_hex = secret.split(":", 2)
        return salt_hex, hash_hex
    return hash_new(secret)


# --- bootstrap ---------------------------------------------------------

def needs_setup() -> bool:
    return storage.user_count() == 0


def create_first_account(username: str, password: str) -> str:
    """First-run only: create the initial director. Refuses once any user
    exists. Returns the canonical username."""
    if storage.user_count() > 0:
        raise HTTPException(status_code=409, detail="Setup has already been completed")
    username = (username or "").strip()
    if not username or len(username) > 40:
        raise HTTPException(status_code=422, detail="Username must be 1-40 characters")
    if len(password or "") < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    salt_hex, hash_hex = hash_new(password)
    storage.create_user(username, salt_hex, hash_hex, "director")
    return username


def seed_users() -> None:
    """Optional: pre-create accounts from DASH_USERS on an empty table.
    No-op if DASH_USERS is unset or any user already exists — the dashboard's
    setup screen handles the empty case."""
    if storage.user_count() > 0:
        return
    raw = os.environ.get("DASH_USERS", "").strip()
    if not raw:
        return
    seeded = []
    for chunk in raw.split(","):
        parts = [p.strip() for p in chunk.split(":")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            continue
        name = parts[0]
        if parts[1] == "scrypt" and len(parts) >= 4:
            secret = ":".join(parts[1:4])
            role = parts[4] if len(parts) > 4 else "director"
        else:
            secret = parts[1]
            role = parts[2] if len(parts) > 2 else "director"
        if storage.get_user(name):
            continue
        salt_hex, hash_hex = _record_from_secret(secret)
        storage.create_user(name, salt_hex, hash_hex, role if role in ROLE_CAPS else "admin")
        seeded.append(f"{name}({role})")
    if seeded:
        print(f"Auth: pre-created {len(seeded)} account(s) from DASH_USERS: {', '.join(seeded)}")


# --- login -----------------------------------------------------------

def authenticate(username: str, password: str) -> str | None:
    """Returns the canonical username on success, else None.
    Raises NoAccess if the password is right but the role has no access."""
    username = (username or "").strip()
    user = storage.get_user(username)
    salt_hex, expected = (user["salt"], user["hash"]) if user else _DUMMY
    ok = hmac.compare_digest(_hash(password or "", salt_hex), expected)
    if not user or not ok or not user["active"]:
        return None
    if not has_access(user["role"]):
        raise NoAccess()
    return user["username"]


def issue_token(username: str) -> str:
    return _serializer.dumps({"u": username, "t": int(time.time())})


def _token_username(token: str) -> str | None:
    try:
        return _serializer.loads(token, max_age=MAX_AGE).get("u")
    except (BadSignature, SignatureExpired, Exception):
        return None


def current_user(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    name = _token_username(token)
    if not name:
        return None
    user = storage.get_user(name)
    if not user or not user["active"] or not has_access(user["role"]):
        return None
    return {"id": user["id"], "username": user["username"], "role": user["role"],
            "caps": caps_for(user["role"])}


def is_authed(request: Request) -> bool:
    return current_user(request) is not None


def require_auth(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_cap(cap: str):
    def dep(request: Request) -> dict:
        user = require_auth(request)
        if not can(user["role"], cap):
            raise HTTPException(status_code=403, detail=f"Your account can't modify {cap}")
        return user
    return dep


# --- login rate limiting (in-memory, per client IP) --------------------
_ATTEMPTS: dict[str, list[float]] = {}
_WINDOW = 300
_MAX_TRIES = 8


def register_login_attempt(ip: str) -> bool:
    now = time.time()
    q = [t for t in _ATTEMPTS.get(ip, []) if now - t < _WINDOW]
    q.append(now)
    _ATTEMPTS[ip] = q
    if len(_ATTEMPTS) > 5000:
        for k in [k for k, v in list(_ATTEMPTS.items()) if not v or now - v[-1] > _WINDOW]:
            _ATTEMPTS.pop(k, None)
    return len(q) > _MAX_TRIES


def clear_login_attempts(ip: str) -> None:
    _ATTEMPTS.pop(ip, None)
