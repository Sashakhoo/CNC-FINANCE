import httpx
import pytest
import respx

from app.models.base import EmailType, Provenance
from app.providers.base import (AuthError, MemoryCache, NotConfigured, ProviderState, QuotaExceeded, RateLimited,
                                TransientError)
from app.providers.email.base import EmailOptedOut
from app.providers.email.hunter import HunterEmailDiscovery

KEY = "hunter-secret-key-123"
API = "https://api.hunter.io/v2"


class Recorder:
    def __init__(self):
        self.events = []

    async def __call__(self, e):
        self.events.append(e)


def provider(cache=None):
    rec = Recorder()
    return HunterEmailDiscovery(KEY, client=httpx.AsyncClient(), recorder=rec, cache=cache), rec


DOMAIN_SEARCH = {"data": {"domain": "acme-automation.example", "pattern": "{first}.{last}", "accept_all": False,
                          "organization": "Acme Automation", "emails": [
    {"value": "jane.tan@acme-automation.example", "type": "personal", "provenance": "found", "confidence": 94,
     "sources": [{"domain": "acme-automation.example", "uri": "https://acme-automation.example/team"}],
     "first_name": "Jane", "last_name": "Tan", "position": "HR Manager", "seniority": "senior",
     "department": "hr", "linkedin": None, "phone_number": None, "verification": {"date": None, "status": "valid"}},
    {"value": "info@acme-automation.example", "type": "generic", "confidence": 90, "sources": []},
    {"value": "ken.lee@acme-automation.example", "type": "personal", "provenance": "inferred", "confidence": 55,
     "sources": []},
    {"value": "not an email", "type": "personal", "confidence": 10},
]}}


@respx.mock
async def test_domain_search_normalizes_and_labels_provenance():
    route = respx.get(f"{API}/domain-search").mock(return_value=httpx.Response(200, json=DOMAIN_SEARCH))
    p, rec = provider()
    res = await p.domain_search("Acme-Automation.example", limit=5)
    assert route.calls.last.request.headers["x-api-key"] == KEY
    assert "api_key" not in str(route.calls.last.request.url)
    assert res.pattern == "{first}.{last}" and len(res.emails) == 3
    jane, info, ken = res.emails
    assert (jane.confidence, jane.email_type, jane.provenance) == (0.94, EmailType.PERSONAL_BUSINESS, Provenance.ENRICHED)
    assert jane.sources == ["https://acme-automation.example/team"]
    assert info.email_type == EmailType.GENERIC
    assert ken.provenance == Provenance.INFERRED
    assert rec.events[0].success and rec.events[0].operation == "domain_search"


@respx.mock
async def test_domain_search_cache_avoids_second_call():
    route = respx.get(f"{API}/domain-search").mock(return_value=httpx.Response(200, json=DOMAIN_SEARCH))
    p, _ = provider(cache=MemoryCache())
    await p.domain_search("acme-automation.example")
    again = await p.domain_search("acme-automation.example")
    assert route.call_count == 1 and len(again.emails) == 3


@respx.mock
async def test_find_email_found_and_not_found():
    respx.get(f"{API}/email-finder").mock(side_effect=[
        httpx.Response(200, json={"data": {"first_name": "Jane", "last_name": "Tan", "email": "jane.tan@acme.example",
                                           "score": 88, "sources": [], "position": "HR Manager"}}),
        httpx.Response(200, json={"data": {"first_name": "No", "last_name": "Body", "email": None, "score": None}}),
    ])
    p, _ = provider()
    found = await p.find_email("Jane", "Tan", "acme.example")
    assert found.email == "jane.tan@acme.example" and found.confidence == 0.88
    assert await p.find_email("No", "Body", "acme.example") is None


@pytest.mark.parametrize("status,exc", [(401, AuthError), (403, RateLimited), (429, QuotaExceeded),
                                        (451, EmailOptedOut), (502, TransientError)])
@respx.mock
async def test_error_mapping_records_failure_and_hides_key(status, exc):
    respx.get(f"{API}/domain-search").mock(return_value=httpx.Response(
        status, json={"errors": [{"id": "x", "code": status, "details": "nope"}]}, headers={"retry-after": "7"}))
    p, rec = provider()
    with pytest.raises(exc) as ei:
        await p.domain_search("acme.example")
    assert KEY not in str(ei.value)
    assert rec.events[-1].success is False and rec.events[-1].http_status == status
    if exc is RateLimited:
        assert ei.value.retry_after == 7.0 and ei.value.retryable


@respx.mock
async def test_timeout_is_transient_without_url():
    respx.get(f"{API}/domain-search").mock(side_effect=httpx.ReadTimeout("timed out", request=None))
    p, rec = provider()
    with pytest.raises(TransientError) as ei:
        await p.domain_search("acme.example")
    assert "hunter.io" not in str(ei.value) and KEY not in str(ei.value)
    assert rec.events[-1].error_type == "TRANSIENT"


@respx.mock
async def test_test_connection():
    respx.get(f"{API}/account").mock(return_value=httpx.Response(200, json={"data": {
        "plan_name": "Starter", "reset_date": "2026-11-01",
        "requests": {"searches": {"used": 10, "available": 500, "remaining": 490}}}}))
    p, _ = provider()
    st = await p.test_connection()
    assert st.state == ProviderState.CONNECTED and "490 searches remaining" in st.message
    assert (await HunterEmailDiscovery("").test_connection()).state == ProviderState.NOT_CONFIGURED


async def test_unconfigured_call_raises():
    with pytest.raises(NotConfigured):
        await HunterEmailDiscovery("").domain_search("acme.example")
