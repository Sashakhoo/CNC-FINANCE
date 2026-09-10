"""
Minimal single-user auth for the CNC dashboard — replaces the mockup's
hardcoded `zc123` window.prompt() lock.

One username + password (set DASH_USERNAME / DASH_PASSWORD as Railway env
vars), verified with a constant-time compare, then a signed session cookie
(itsdangerous, SESSION_SECRET) that the API and dashboard check on every
request. No database, no user table — right-sized for a one-person business.
"""
import os
import hmac
import time

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, HTTPException

USERNAME = os.environ.get("DASH_USERNAME", "admin")
PASSWORD = os.environ.get("DASH_PASSWORD", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
COOKIE_NAME = "cnc_session"
MAX_AGE = 60 * 60 * 24 * 14  # 14 days

if not SESSION_SECRET:
    # Dev fallback: stable within a process, but sessions drop on restart.
    SESSION_SECRET = os.urandom(32).hex()
    print("⚠️  SESSION_SECRET not set — using an ephemeral one (logins won't survive a restart).")
if not PASSWORD:
    print("⚠️  DASH_PASSWORD not set — the dashboard login will reject every attempt until it is.")

_serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="cnc-session")


def check_credentials(username: str, password: str) -> bool:
    if not PASSWORD:
        return False
    ok_user = hmac.compare_digest((username or "").strip(), USERNAME)
    ok_pass = hmac.compare_digest(password or "", PASSWORD)
    return ok_user and ok_pass


def issue_token(username: str) -> str:
    return _serializer.dumps({"u": username, "t": int(time.time())})


def verify_token(token: str) -> bool:
    try:
        data = _serializer.loads(token, max_age=MAX_AGE)
        return data.get("u") == USERNAME
    except (BadSignature, SignatureExpired, Exception):
        return False


def is_authed(request: Request) -> bool:
    token = request.cookies.get(COOKIE_NAME)
    return bool(token) and verify_token(token)


def require_auth(request: Request):
    """FastAPI dependency — 401s unless a valid session cookie is present."""
    if not is_authed(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
