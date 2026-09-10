"""
Multi-user auth for the CNC dashboard.

Users are a small in-code list (no database). Each has a username, a
password, and a role. Only two roles have any access at all:

  - director : sees everything and can edit everything
  - admin    : sees everything, but can ONLY create invoices and generate
               documents (receipts / vouchers / invoice PDFs)

Any other role has no access — login is refused. The API enforces the
capability split per endpoint (403 otherwise); the dashboard greys out the
controls a user can't use.

Passwords are NEVER stored in this file. Configure them at deploy time with
the DASH_USERS environment variable (Railway → Variables), one
`username:password:role` entry per user, comma-separated:

    DASH_USERS = sashakhoo:<strong-pass>:director,accounts:<strong-pass>:admin

A password may instead be given pre-hashed as `scrypt:<salt_hex>:<hash_hex>`
(generate with `python hash_password.py`) so the plaintext never leaves your
machine. Plaintext values are hashed in memory on startup and never logged.

Login is rate-limited and uses a constant-time comparison; success sets a
signed, httpOnly session cookie (itsdangerous, SESSION_SECRET).
"""
import hashlib
import hmac
import os
import time

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, HTTPException

COOKIE_NAME = "cnc_session"
MAX_AGE = int(os.environ.get("SESSION_MAX_AGE_SECONDS", 60 * 60 * 24 * 7))  # 7 days

# role -> set of capabilities. "*" means everything. A role that is not a
# key here has NO access at all (login is refused).
ROLE_CAPS = {
    "director": {"*"},
    "admin": {"invoices", "documents"},
}
ALL_CAPS = ["transactions", "contacts", "invoices", "assets", "notes", "documents"]

# Known accounts and their roles. Passwords come from DASH_USERS only —
# a user with no configured password cannot log in.
DEFAULT_USERS = [
    ("sashakhoo", "director"),
    ("admin", "admin"),
]

_SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32)
# A fixed record used to burn ~equal CPU when the username is unknown or
# disabled, so response timing doesn't reveal which usernames exist.
_DUMMY = ("00" * 16, "ff" * 32)


def caps_for(role: str) -> list:
    c = ROLE_CAPS.get(role, set())
    return ALL_CAPS[:] if "*" in c else sorted(c)


def has_access(role: str) -> bool:
    return role in ROLE_CAPS


def can(role: str, cap: str) -> bool:
    c = ROLE_CAPS.get(role, set())
    return "*" in c or cap in c


def _hash(password: str, salt_hex: str) -> str:
    dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT)
    return dk.hex()


def _to_record(secret: str) -> tuple[str, str]:
    """Normalise a configured password (plaintext or 'scrypt:salt:hash') to
    a (salt_hex, hash_hex) record."""
    if secret.startswith("scrypt:"):
        _, salt_hex, hash_hex = secret.split(":", 2)
        return salt_hex, hash_hex
    salt_hex = os.urandom(16).hex()
    return salt_hex, _hash(secret, salt_hex)


def _load_users() -> dict:
    roles = {name: role for name, role in DEFAULT_USERS}
    secrets: dict[str, str] = {}

    raw = os.environ.get("DASH_USERS", "").strip()
    if raw:
        for chunk in raw.split(","):
            parts = [p.strip() for p in chunk.split(":")]
            if len(parts) < 2 or not parts[0] or not parts[1]:
                continue
            name = parts[0]
            if parts[1] == "scrypt" and len(parts) >= 4:
                secret = ":".join(parts[1:4])
                role = parts[4] if len(parts) > 4 else roles.get(name, "director")
            else:
                secret = parts[1]
                role = parts[2] if len(parts) > 2 else roles.get(name, "director")
            secrets[name] = secret
            roles[name] = role

    # Back-compat: a lone DASH_USERNAME / DASH_PASSWORD pair.
    u, p = os.environ.get("DASH_USERNAME"), os.environ.get("DASH_PASSWORD")
    if u and p:
        secrets[u] = p
        roles.setdefault(u, "director")

    users = {}
    for name, secret in secrets.items():
        salt_hex, hash_hex = _to_record(secret)
        users[name] = {"salt": salt_hex, "hash": hash_hex, "role": roles.get(name, "director")}

    configured = [n for n in users if has_access(users[n]["role"])]
    if not configured:
        print("WARNING: no usable dashboard accounts. Set DASH_USERS "
              "(e.g. 'sashakhoo:<strong-pass>:director') in the environment.")
    else:
        print(f"Auth: {len(configured)} account(s) configured: {', '.join(sorted(configured))}")
    return users


USERS = _load_users()

SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
if not SESSION_SECRET:
    SESSION_SECRET = os.urandom(32).hex()
    print("WARNING: SESSION_SECRET not set — using an ephemeral one (all sessions drop on restart). "
          "Set SESSION_SECRET to a long random string.")

_serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="cnc-session")


class NoAccess(Exception):
    """Valid credentials, but the role grants no access at all."""


def authenticate(username: str, password: str) -> str | None:
    """Returns the canonical username on success, else None.
    Raises NoAccess if the password is right but the role has no access.
    Constant-ish time whether or not the username exists."""
    username = (username or "").strip()
    user = USERS.get(username)
    salt_hex, expected = (user["salt"], user["hash"]) if user else _DUMMY
    got = _hash(password or "", salt_hex)
    ok = hmac.compare_digest(got, expected)
    if not user or not ok:
        return None
    if not has_access(user["role"]):
        raise NoAccess()
    return username


def issue_token(username: str) -> str:
    return _serializer.dumps({"u": username, "t": int(time.time())})


def _token_user(token: str) -> str | None:
    try:
        data = _serializer.loads(token, max_age=MAX_AGE)
    except (BadSignature, SignatureExpired, Exception):
        return None
    name = data.get("u")
    return name if name in USERS else None


def current_user(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    name = _token_user(token)
    if not name:
        return None
    role = USERS[name]["role"]
    if not has_access(role):
        return None
    return {"username": name, "role": role, "caps": caps_for(role)}


def is_authed(request: Request) -> bool:
    return current_user(request) is not None


def require_auth(request: Request) -> dict:
    """FastAPI dependency — any signed-in user with access."""
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_cap(cap: str):
    """Dependency factory — signed in AND holds a specific capability."""
    def dep(request: Request) -> dict:
        user = require_auth(request)
        if not can(user["role"], cap):
            raise HTTPException(status_code=403, detail=f"Your account can't modify {cap}")
        return user
    return dep


# --- login rate limiting (in-memory, per client IP) -------------------------
_ATTEMPTS: dict[str, list[float]] = {}
_WINDOW = 300      # seconds
_MAX_TRIES = 8     # per window per IP


def register_login_attempt(ip: str) -> bool:
    """Record an attempt; return True if the caller is now over the limit."""
    now = time.time()
    q = [t for t in _ATTEMPTS.get(ip, []) if now - t < _WINDOW]
    q.append(now)
    _ATTEMPTS[ip] = q
    if len(_ATTEMPTS) > 5000:  # crude cap on memory
        for k in [k for k, v in _ATTEMPTS.items() if not v or now - v[-1] > _WINDOW]:
            _ATTEMPTS.pop(k, None)
    return len(q) > _MAX_TRIES


def clear_login_attempts(ip: str) -> None:
    _ATTEMPTS.pop(ip, None)
