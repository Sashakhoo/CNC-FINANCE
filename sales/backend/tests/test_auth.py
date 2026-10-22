import httpx
from httpx import Response
from sqlalchemy import select

from app.models import AuditLog, User
from app.models.base import Role
from tests.conftest import finance_session


async def test_no_cookie_is_401(client, finance):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


async def test_finance_rejects_session(client, finance):
    finance_session(finance)
    client.cookies.set("cnc_session", "forged")
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


async def test_account_without_crm_cap_is_403(client, finance):
    client.cookies.update(finance_session(finance, caps=("invoices",)))
    r = await client.get("/api/auth/me")
    assert r.status_code == 403


async def test_director_becomes_admin_on_first_sign_in(client, finance, db):
    client.cookies.update(finance_session(finance, username="owner", role="director"))
    r = await client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["role"] == "ADMIN" and r.json()["can_edit"] is True
    user = (await db.execute(select(User))).scalar_one()
    assert user.finance_username == "owner" and user.role == Role.ADMIN


async def test_finance_admin_becomes_sales(client, finance):
    client.cookies.update(finance_session(finance, username="sam", role="admin"))
    assert (await client.get("/api/auth/me")).json()["role"] == "SALES"


async def test_session_check_is_cached(client, finance):
    client.cookies.update(finance_session(finance))
    await client.get("/api/auth/me")
    await client.get("/api/auth/me")
    assert finance.routes[0].call_count == 1


async def test_finance_unreachable_is_503(client, finance):
    finance.get("/api/me").mock(side_effect=httpx.ConnectError("down"))
    client.cookies.set("cnc_session", "tok")
    assert (await client.get("/api/auth/me")).status_code == 503


async def test_login_relays_finance_cookie_and_audits(client, finance, db):
    finance.post("/api/login").mock(return_value=Response(
        200, json={"ok": True, "username": "owner", "role": "director", "caps": ["crm"]},
        headers={"set-cookie": "cnc_session=abc; HttpOnly; Path=/; SameSite=lax"}))
    r = await client.post("/api/auth/login", json={"username": "owner", "password": "pw"})
    assert r.status_code == 200
    assert "cnc_session=abc" in r.headers["set-cookie"]
    sent = finance.calls.last.request
    assert sent.headers["x-forwarded-for"]
    assert [a.action for a in (await db.execute(select(AuditLog))).scalars()] == ["login"]


async def test_failed_login_passes_status_and_is_audited(client, finance, db):
    finance.post("/api/login").mock(return_value=Response(401, json={"detail": "Invalid username or password"}))
    r = await client.post("/api/auth/login", json={"username": "owner", "password": "wrong"})
    assert r.status_code == 401 and r.json()["detail"] == "Invalid username or password"
    log = (await db.execute(select(AuditLog))).scalar_one()
    assert log.action == "login_failed" and "password" not in str(log.meta)


async def test_login_validates_input(client, finance):
    assert (await client.post("/api/auth/login", json={"username": "", "password": "x"})).status_code == 422


async def test_admin_can_change_roles_but_not_demote_self(client, finance, db):
    client.cookies.update(finance_session(finance, username="owner", role="director"))
    me = (await client.get("/api/auth/me")).json()
    db.add(User(finance_username="sam", finance_role="admin", role=Role.SALES))
    await db.commit()
    sam = (await db.execute(select(User).where(User.finance_username == "sam"))).scalar_one()

    assert (await client.patch(f"/api/auth/users/{sam.id}", json={"role": "VIEWER"})).status_code == 200
    assert (await client.patch(f"/api/auth/users/{me['id']}", json={"role": "SALES"})).status_code == 400
    await db.refresh(sam)
    assert sam.role == Role.VIEWER


async def test_non_admin_cannot_list_users(client, finance):
    client.cookies.update(finance_session(finance, username="sam", role="admin"))
    assert (await client.get("/api/auth/users")).status_code == 403
