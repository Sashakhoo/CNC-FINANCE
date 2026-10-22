import pytest
from sqlalchemy import select

from app.api import discovery as discovery_api
from app.core.config import get_settings
from app.models import AuditLog, Job
from app.models.base import JobStatus
from tests.conftest import finance_session


@pytest.fixture
def queued(monkeypatch):
    sent = []
    monkeypatch.setattr(discovery_api, "enqueue", lambda task, job_id: sent.append((task, job_id)) or f"task-{job_id}")
    return sent


async def _admin(client, finance):
    client.cookies.update(finance_session(finance))
    await client.get("/api/auth/me")


SEARCH = {"name": "Johor Engineering Prospects", "criteria": {"state": "Johor", "industries": ["Manufacturing", "Engineering"],
                                                             "size_min": 30, "size_max": 1000, "max_companies": 20,
                                                             "seed_websites": ["southern-precision.example.my"]}}


async def test_search_validation(client, finance):
    await _admin(client, finance)
    bad = {"name": "x" * 3, "criteria": {"max_companies": 501}}
    assert (await client.post("/api/searches", json=bad)).status_code == 422
    bad = {"name": "Seeds", "criteria": {"seed_websites": ["javascript:alert(1)"]}}
    assert (await client.post("/api/searches", json=bad)).status_code == 422
    r = await client.post("/api/searches", json=SEARCH)
    assert r.status_code == 201 and r.json()["criteria"]["seed_websites"] == ["https://southern-precision.example.my"]


async def test_run_search_enqueues_once(client, finance, queued, db):
    await _admin(client, finance)
    s = (await client.post("/api/searches", json=SEARCH)).json()
    r = await client.post(f"/api/searches/{s['id']}/run")
    assert r.status_code == 202 and r.json()["status"] == "QUEUED"
    assert queued == [("discovery.run", r.json()["id"])]
    assert (await client.post(f"/api/searches/{s['id']}/run")).status_code == 409
    listed = (await client.get("/api/searches")).json()
    assert listed[0]["last_job"]["id"] == r.json()["id"]
    assert "discovery_started" in [a.action for a in (await db.execute(select(AuditLog))).scalars()]


async def test_cancel_and_retry(client, finance, queued, db):
    await _admin(client, finance)
    s = (await client.post("/api/searches", json=SEARCH)).json()
    job = (await client.post(f"/api/searches/{s['id']}/run")).json()
    assert (await client.post(f"/api/jobs/{job['id']}/retry")).status_code == 409
    r = (await client.post(f"/api/jobs/{job['id']}/cancel")).json()
    assert r["status"] == "CANCELLED" and r["cancel_requested"] is True
    retry = await client.post(f"/api/jobs/{job['id']}/retry")
    assert retry.status_code == 202 and retry.json()["name"].startswith("Retry:")
    detail = (await client.get(f"/api/jobs/{retry.json()['id']}")).json()
    assert detail["crawls"] == [] and detail["provider_calls"] == []
    jobs = (await client.get("/api/jobs", params={"status": "CANCELLED"})).json()
    assert [j["id"] for j in jobs["items"]] == [job["id"]]


async def test_providers_status_never_leaks_keys(client, finance, monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER", "brave")
    monkeypatch.setenv("SEARCH_API_KEY", "super-secret-value")
    get_settings.cache_clear()
    try:
        await _admin(client, finance)
        r = await client.get("/api/providers")
        assert "super-secret-value" not in r.text
        brave = next(p for p in r.json()["providers"] if p["name"] == "brave")
        assert brave["state"] == "CONFIGURED"
        t = (await client.post("/api/providers/EMAIL_VERIFICATION/test")).json()
        assert t["state"] == "NOT_CONFIGURED"
    finally:
        get_settings.cache_clear()


async def test_provider_test_admin_only(client, finance):
    client.cookies.update(finance_session(finance, username="sam", role="admin"))
    assert (await client.post("/api/providers/SEARCH/test")).status_code == 403


async def test_enrich_requires_website(client, finance, queued):
    await _admin(client, finance)
    co = (await client.post("/api/companies", json={"legal_name": "No Site Sdn Bhd"})).json()
    assert (await client.post(f"/api/companies/{co['id']}/enrich?action=reenrich")).status_code == 422
    r = await client.post(f"/api/companies/{co['id']}/enrich?action=analyze")
    assert r.status_code == 202 and queued[-1][0] == "discovery.enrich"


async def test_signals_and_opportunities_empty(client, finance):
    await _admin(client, finance)
    assert (await client.get("/api/signals")).json()["total"] == 0
    assert (await client.get("/api/opportunities", params={"min_match": 60})).json()["total"] == 0
