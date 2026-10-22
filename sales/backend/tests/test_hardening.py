import re

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.main import app
from app.models import Company
from tests.conftest import finance_session

PUBLIC = {("GET", "/api/auth/setup"), ("POST", "/api/auth/login"), ("POST", "/api/auth/logout"),
          ("GET", "/api/docs"), ("GET", "/api/openapi.json"), ("GET", "/api/docs/oauth2-redirect")}


async def test_every_api_route_requires_sign_in(client, finance):
    """No /api route (other than sign-in itself) may succeed without a session."""
    checked = 0
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/"):
            continue
        for method in getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}:
            if (method, path) in PUBLIC:
                continue
            url = re.sub(r"\{[^}]+\}", "1", path).replace("/api/providers/1/", "/api/providers/SEARCH/")
            r = await client.request(method, url, json={} if method != "GET" else None)
            assert r.status_code in (401, 403, 422), f"{method} {path} returned {r.status_code} without a session"
            checked += 1
    assert checked > 60


async def test_cross_site_writes_are_blocked(client, finance):
    client.cookies.update(finance_session(finance))
    await client.get("/api/auth/me")
    evil = await client.post("/api/companies", json={"legal_name": "Evil Sdn Bhd"}, headers={"origin": "https://evil.example"})
    assert evil.status_code == 403 and "blocked" in evil.json()["detail"]
    fetch_site = await client.post("/api/companies", json={"legal_name": "Evil Sdn Bhd"}, headers={"sec-fetch-site": "cross-site"})
    assert fetch_site.status_code == 403
    same = await client.post("/api/companies", json={"legal_name": "Good Sdn Bhd"}, headers={"origin": "http://sales.test"})
    assert same.status_code == 201
    read = await client.get("/api/companies", headers={"origin": "https://evil.example"})
    assert read.status_code == 200


async def test_rate_limit_on_provider_test(client, finance):
    client.cookies.update(finance_session(finance))
    await client.get("/api/auth/me")
    codes = [(await client.post("/api/providers/SEARCH/test")).status_code for _ in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429


def test_provider_limit_overrides(monkeypatch):
    from app.services.runtime import provider_limits
    monkeypatch.setenv("PROVIDER_LIMITS", '{"brave": {"minute": 5, "month": 1000, "bogus": 1}}')
    get_settings.cache_clear()
    try:
        assert provider_limits(get_settings()) == {"brave": {"minute": 5, "month": 1000}}
        monkeypatch.setenv("PROVIDER_LIMITS", "not json")
        get_settings.cache_clear()
        assert provider_limits(get_settings()) == {}
    finally:
        get_settings.cache_clear()


async def test_demo_seed_refuses_without_demo_mode_and_stays_isolated(client, finance, db, monkeypatch):
    from app.scripts.seed_demo import seed
    assert await seed() == 1
    monkeypatch.setenv("DEMO_MODE", "true")
    get_settings.cache_clear()
    try:
        assert await seed() == 0
        assert await db.scalar(select(func.count()).select_from(Company).where(Company.is_demo.is_(True))) == 3
        client.cookies.update(finance_session(finance))
        demo_view = (await client.get("/api/analytics/summary")).json()
        assert demo_view["demo_mode"] is True and demo_view["companies"] == 3
    finally:
        monkeypatch.setenv("DEMO_MODE", "false")
        get_settings.cache_clear()
    prod_view = (await client.get("/api/analytics/summary")).json()
    assert prod_view["companies"] == 0                       # demo records never appear in production views


@pytest.mark.parametrize("path", ["/health"])
async def test_health(client, path):
    r = (await client.get(path)).json()
    assert r["status"] == "ok" and r["database"] is True
