"""
Multi-user auth for the CNC dashboard — replaces the mockup's hardcoded
`zc123` window.prompt() lock.

Users are a small in-code list (no database). Each has a username, a
password, and a role. Only two roles have any access at all:

  - director : sees everything and can edit everything
  - admin    : sees everything, but can ONLY create invoices and generate
               documents (receipts / vouchers / invoice PDFs)

Any other role has no access — login is refused. The API enforces the
capability split per endpoint (403 otherwise); the dashboard greys out the
controls a user can't use. Add users in DEFAULT_USERS, or override the
whole list at deploy time with DASH_USERS:

    DASH_USERS = sashakhoo:1688:director,accounts:xxxx:admin

Login is verified with a constant-time compare, then a signed session
cookie (itsdangerous, SESSION_SECRET) carries the username on every request.
"""
import os
import hmac
import time

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, HTTPException

COOKIE_NAME = "cnc_session"
MAX_AGE = 60 * 60 * 24 * 14  # 14 days

# role -> set of capabilities. "*" means everything. A role that is not a
# key here has NO access at all (login is refused).
#   transactions / contacts / assets / notes : add & delete in that section
#   invoices                                 : create / mark-paid / delete invoices
#   documents                                : generate receipt / voucher / invoice PDFs
ROLE_CAPS = {
    "director": {"*"},
    "admin": {"invoices", "documents"},
}
ALL_CAPS = ["transactions", "contacts", "invoices", "assets", "notes", "documents"]

# Starting accounts. Add more entries here as they come, or override the
# entire set with the DASH_USERS env var (same "user:pass:role" format).
DEFAULT_USERS = [
    ("sashakhoo", "1688", "director"),
    ("admin", "8888", "admin"),
]


def caps_for(role: str) -> list:
    c = ROLE_CAPS.get(role, set())
    return ALL_CAPS[:] if "*" in c else sorted(c)


def has_access(role: str) -> bool:
    return role in ROLE_CAPS


def can(role: str, cap: str) -> bool:
    c = ROLE_CAPS.get(role, set())
    return "*" in c or cap in c


def _load_users() -> dict:
    raw = os.environ.get("DASH_USERS", "").strip()
    entries = []
    if raw:
        for chunk in raw.split(","):
            parts = [p.strip() for p in chunk.split(":")]
            if len(parts) >= 2 and parts[0] and parts[1]:
                entries.append((parts[0], parts[1], parts[2] if len(parts) > 2 else "director"))
    else:
        entries = list(DEFAULT_USERS)
    # Back-compat: a lone DASH_USERNAME/DASH_PASSWORD pair still works.
    u, p = os.environ.get("DASH_USERNAME"), os.environ.get("DASH_PASSWORD")
    if u and p:
        entries.append((u, p, "director"))
    return {name: {"password": pw, "role": role} for name, pw, role in entries}


USERS = _load_users()

SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
if not SESSION_SECRET:
    SESSION_SECRET = os.urandom(32).hex()
    print("⚠️  SESSION_SECRET not set — using an ephemeral one (logins won't survive a restart).")

_serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="cnc-session")


class NoAccess(Exception):
    """Valid credentials, but the role grants no access at all."""


def authenticate(username: str, password: str) -> str | None:
    """Returns the canonical username on success, else None.
    Raises NoAccess if the password is right but the role has no access."""
    username = (username or "").strip()
    user = USERS.get(username)
    if not user:
        return None
    if not hmac.compare_digest(password or "", user["password"]):
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


def require_write(request: Request) -> dict:
    """FastAPI dependency — signed in AND allowed to change data."""
    user = require_auth(request)
    if user["role"] not in WRITE_ROLES:
        raise HTTPException(status_code=403, detail="Your account is view-only")
    return user
