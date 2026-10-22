import httpx
import pytest
import respx

from app.providers.base import (AuthError, MemoryCache, NotConfigured, ProviderState, QuotaExceeded, RateLimited,
                                TransientError)
from app.providers.search.brave import ENDPOINT, BraveSearch, parse_reset

KEY = "test-key-not-real"
PAYLOAD = {"query": {"original": "x", "more_results_available": False}, "web": {"results": [
    {"title": "Fictional Precision Sdn Bhd - Home", "url": "https://fictionalprecision.example/", "description": "Precision machining in Johor"},
    {"title": "No url", "description": "dropped"},
    {"title": "Other Co", "url": "https://other.example/about", "description": ""},
]}}


class Recorder:
    def __init__(self):
        self.events = []

    async def __call__(self, e):
        self.events.append(e)


def test_parse_reset_takes_shortest_window():
    assert parse_reset("1, 1419704") == 1.0
    assert parse_reset(None) is None
    assert parse_reset("abc") is None


@respx.mock
async def test_search_parses_results_and_sends_key():
    route = respx.get(ENDPOINT).mock(return_value=httpx.Response(200, json=PAYLOAD))
    rec = Recorder()
    p = BraveSearch(KEY, recorder=rec)
    results = await p.search("precision Johor", count=50, offset=3)
    req = route.calls.last.request
    assert req.headers["x-subscription-token"] == KEY
    assert req.url.params["count"] == "20" and req.url.params["offset"] == "3" and req.url.params["country"] == "MY"
    assert [r.url for r in results] == ["https://fictionalprecision.example/", "https://other.example/about"]
    assert results[0].rank == 61 and results[0].provider == "brave" and results[0].query == "precision Johor"
    assert len(rec.events) == 1 and rec.events[0].success and rec.events[0].http_status == 200
    assert KEY not in str(rec.events[0].meta)


@respx.mock
async def test_results_are_cached():
    route = respx.get(ENDPOINT).mock(return_value=httpx.Response(200, json=PAYLOAD))
    p = BraveSearch(KEY, cache=MemoryCache())
    a = await p.search("q")
    b = await p.search("q")
    assert route.call_count == 1 and a == b


@respx.mock
async def test_429_is_rate_limited_with_retry_after():
    respx.get(ENDPOINT).mock(return_value=httpx.Response(
        429, headers={"X-RateLimit-Reset": "2, 99999", "X-RateLimit-Remaining": "0, 500"}))
    rec = Recorder()
    with pytest.raises(RateLimited) as e:
        await BraveSearch(KEY, recorder=rec).search("q")
    assert e.value.retry_after == 2.0
    assert rec.events[0].success is False and rec.events[0].error_type == "RATE_LIMITED"


@respx.mock
async def test_429_with_monthly_quota_gone_is_quota_exceeded():
    respx.get(ENDPOINT).mock(return_value=httpx.Response(
        429, headers={"X-RateLimit-Reset": "1, 99999", "X-RateLimit-Remaining": "1, 0"}))
    with pytest.raises(QuotaExceeded):
        await BraveSearch(KEY).search("q")


@respx.mock
async def test_bad_key_is_auth_error_without_leaking_key():
    respx.get(ENDPOINT).mock(return_value=httpx.Response(401, json={"error": "bad"}))
    with pytest.raises(AuthError) as e:
        await BraveSearch(KEY).search("q")
    assert KEY not in str(e.value)


@respx.mock
async def test_timeout_and_5xx_are_transient():
    respx.get(ENDPOINT).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(TransientError):
        await BraveSearch(KEY).search("q")
    respx.get(ENDPOINT).mock(return_value=httpx.Response(503))
    with pytest.raises(TransientError):
        await BraveSearch(KEY).search("q2")


async def test_not_configured():
    p = BraveSearch("")
    assert not p.is_configured()
    with pytest.raises(NotConfigured):
        await p.search("q")
    assert (await p.test_connection()).state == ProviderState.NOT_CONFIGURED


@respx.mock
async def test_test_connection_states():
    respx.get(ENDPOINT).mock(return_value=httpx.Response(200, json={"web": {"results": []}}))
    assert (await BraveSearch(KEY).test_connection()).state == ProviderState.CONNECTED
    respx.get(ENDPOINT).mock(return_value=httpx.Response(403))
    s = await BraveSearch(KEY).test_connection()
    assert s.state == ProviderState.ERROR and s.http_status == 403 and KEY not in s.message
