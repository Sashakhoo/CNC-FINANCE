"""Sign-in is owned by CNC Finance. A request is authenticated when its
Finance session cookie is accepted by Finance's /api/me; the answer is
cached briefly so every API call doesn't hit Finance."""
import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.models import User
from app.models.base import Role

FINANCE_ROLE_DEFAULTS = {"director": Role.ADMIN, "admin": Role.SALES}
_cache: dict[str, tuple[float, dict | None]] = {}
_client: httpx.AsyncClient | None = None


def finance_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=get_settings().finance_internal_url, timeout=10.0)
    return _client


def _key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def forget_session(token: str | None) -> None:
    if token:
        _cache.pop(_key(token), None)


async def finance_me(token: str) -> dict | None:
    """Finance's view of this session, or None if it isn't a valid session."""
    s = get_settings()
    k = _key(token)
    hit = _cache.get(k)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    try:
        r = await finance_client().get("/api/me", cookies={s.finance_session_cookie: token})
    except httpx.HTTPError as e:
        raise HTTPException(503, "Sign-in service (Finance) is unreachable") from e
    if r.status_code == 401:
        me = None
    elif r.status_code != 200:
        raise HTTPException(503, f"Sign-in service (Finance) returned {r.status_code}")
    else:
        me = r.json()
    if len(_cache) > 2000:
        _cache.clear()
    _cache[k] = (time.monotonic() + s.session_cache_seconds, me)
    return me


@dataclass
class CurrentUser:
    id: int
    username: str
    role: Role
    finance_role: str

    def can_edit(self) -> bool:
        return self.role in (Role.ADMIN, Role.SALES)


async def get_current_user(request: Request, db: AsyncSession = Depends(get_session)) -> CurrentUser:
    token = request.cookies.get(get_settings().finance_session_cookie)
    if not token:
        raise HTTPException(401, "Not signed in")
    me = await finance_me(token)
    if not me:
        raise HTTPException(401, "Session expired — sign in again")
    if "crm" not in me.get("caps", []):
        raise HTTPException(403, "This account doesn't have access to the Sales CRM")
    user = (await db.execute(select(User).where(User.finance_username == me["username"]))).scalar_one_or_none()
    if user is None:
        user = User(finance_username=me["username"], finance_role=me["role"],
                    role=FINANCE_ROLE_DEFAULTS.get(me["role"], Role.VIEWER),
                    last_login_at=datetime.now(timezone.utc))
        db.add(user)
        await db.commit()
    elif user.finance_role != me["role"]:
        user.finance_role = me["role"]
        await db.commit()
    request.state.user_id = user.id
    return CurrentUser(id=user.id, username=user.finance_username, role=user.role, finance_role=user.finance_role)


def require_role(*roles: Role):
    async def dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(403, f"Requires role: {', '.join(r.value for r in roles)}")
        return user
    return dep


require_editor = require_role(Role.ADMIN, Role.SALES)
require_admin = require_role(Role.ADMIN)
