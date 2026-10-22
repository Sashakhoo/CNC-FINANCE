import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import rate_limit
from app.core.auth import CurrentUser, finance_client, forget_session, get_current_user, require_admin
from app.core.config import get_settings
from app.core.db import get_session
from app.models import User
from app.models.base import Role
from app.services.audit import audit, client_ip

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


def _relay_cookies(src: httpx.Response, dst: Response) -> None:
    for value in src.headers.get_list("set-cookie"):
        dst.headers.append("set-cookie", value)


@router.get("/setup")
async def setup_status():
    """Whether Finance still needs its first account created."""
    try:
        r = await finance_client().get("/api/setup")
        return {"needs_setup": bool(r.json().get("needs_setup")), "finance_url": get_settings().finance_public_url}
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "Sign-in service (Finance) is unreachable")


@router.post("/login", dependencies=[Depends(rate_limit("login", 10))])
async def login(body: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_session)):
    ip = client_ip(request) or ""
    try:
        r = await finance_client().post("/api/login", json=body.model_dump(), headers={"x-forwarded-for": ip})
    except httpx.HTTPError:
        raise HTTPException(503, "Sign-in service (Finance) is unreachable")
    if r.status_code != 200:
        detail = "Sign-in failed"
        try:
            detail = r.json().get("detail", detail)
        except ValueError:
            pass
        audit(db, None, "login_failed", "user", body.username, {"status": r.status_code}, request)
        await db.commit()
        raise HTTPException(r.status_code if r.status_code in (401, 403, 429) else 502, detail)
    _relay_cookies(r, response)
    data = r.json()
    if "crm" not in data.get("caps", []):
        raise HTTPException(403, "This account doesn't have access to the Sales CRM. Ask the director.")
    user = (await db.execute(select(User).where(User.finance_username == data["username"]))).scalar_one_or_none()
    audit(db, user.id if user else None, "login", "user", data["username"], {}, request)
    await db.commit()
    return {"ok": True}


@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(get_settings().finance_session_cookie)
    forget_session(token)
    try:
        r = await finance_client().post("/api/logout")
        _relay_cookies(r, response)
    except httpx.HTTPError:
        pass
    response.delete_cookie(get_settings().finance_session_cookie, path="/")
    return {"ok": True}


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)):
    return {"id": user.id, "username": user.username, "role": user.role.value, "finance_role": user.finance_role,
            "can_edit": user.can_edit(), "finance_url": get_settings().finance_public_url}


@router.get("/users")
async def list_users(_: CurrentUser = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    rows = (await db.execute(select(User).order_by(User.finance_username))).scalars().all()
    return [{"id": u.id, "username": u.finance_username, "role": u.role.value, "finance_role": u.finance_role,
             "last_login_at": u.last_login_at} for u in rows]


class RoleIn(BaseModel):
    role: Role


@router.patch("/users/{user_id}")
async def set_role(user_id: int, body: RoleIn, request: Request, admin: CurrentUser = Depends(require_admin),
                   db: AsyncSession = Depends(get_session)):
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    if target.id == admin.id and body.role != Role.ADMIN:
        raise HTTPException(400, "You can't remove your own admin role")
    old = target.role
    await db.execute(update(User).where(User.id == user_id).values(role=body.role))
    audit(db, admin.id, "user_role_changed", "user", user_id, {"from": old.value, "to": body.role.value}, request)
    await db.commit()
    return {"ok": True}
