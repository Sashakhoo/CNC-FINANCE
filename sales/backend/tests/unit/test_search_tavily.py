import json

import httpx
import pytest
import respx

from app.providers.base import (AuthError, MemoryCache, NotConfigured, ProviderState, QuotaExceeded, RateLimited,
                                TransientError)
from app.providers.search.tavily import ENDPOINT, TavilySearch

KEY = "tvly-test-key-not-real"
PAYLOAD = {"query": "x", "results": [
    {"title": "Fictional Precision Sdn Bhd - Home", "url": "https://fictionalprecision.example/", "content": "Precision machining in Johor", "score": 0.9},
    {"title": "No url", "content": "dropped", "score": 0.5},
    {"title": "Other Co", "url": "https://other.example/about", "content": "", "score": 0.4},
]}


class Recorder:
    def __init__(self):
        self.events = []

    async def __call__(self, e):
        self.events.append(e)


@respx.mock
async def test_search_parses_results_and_sends_key():
    route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=PAYLOAD))
    rec = Recorder()
    p = TavilySearch(KEY, recorder=rec)
    results = await p.search("precision Johor", count=50, country="MY")
    req = route.calls.last.request
    body = json.loads(req.content)
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert body == {"query": "precision Johor", "search_depth": "basic", "topic": "general",
                    "max_results": 20, "country": "malaysia"}
    assert [r.url for r in results] == ["https://fictionalprecision.example/", "https://other.example/about"]
    assert [r.rank for r in results] == [1, 2]
    assert results[0].snippet == "Precision machining in Johor" and results[0].provider == "tavily"
    assert len(rec.events) == 1 and rec.events[0].success and rec.events[0].http_status == 200
    assert KEY not in str(rec.events[0].meta)


@respx.mock
async def test_singapore_and_unknown_country():
    route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json={"results": []}))
    await TavilySearch(KEY).search("q", country="SG")
    assert json.loads(route.calls.last.request.content)["country"] == "singapore"
    await TavilySearch(KEY).search("q2", country="XX")
    assert "country" not in json.loads(route.calls.last.request.content)


@respx.mock
async def test_offset_beyond_first_page_makes_no_request():
    route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=PAYLOAD))
    assert await TavilySearch(KEY).search("q", offset=1) == []
    assert route.call_count == 0


@respx.mock
async def test_results_are_cached():
    route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=PAYLOAD))
    p = TavilySearch(KEY, cache=MemoryCache())
    a = await p.search("q")
    b = await p.search("q")
    assert route.call_count == 1 and a == b


@respx.mock
async def test_429_is_rate_limited_with_retry_after():
    respx.post(ENDPOINT).mock(return_value=httpx.Response(429, headers={"Retry-After": "3"}))
    rec = Recorder()
    with pytest.raises(RateLimited) as e:
        await TavilySearch(KEY, recorder=rec).search("q")
    assert e.value.retry_after == 3.0
    assert rec.events[0].success is False and rec.events[0].error_type == "RATE_LIMITED"


@respx.mock
@pytest.mark.parametrize("status", [432, 433])
async def test_plan_and_payg_limits_are_quota_exceeded(status):
    respx.post(ENDPOINT).mock(return_value=httpx.Response(status))
    with pytest.raises(QuotaExceeded):
        await TavilySearch(KEY).search("q")


@respx.mock
async def test_bad_key_is_auth_error_without_leaking_key():
    respx.post(ENDPOINT).mock(return_value=httpx.Response(401, json={"detail": {"error": "bad"}}))
    with pytest.raises(AuthError) as e:
        await TavilySearch(KEY).search("q")
    assert KEY not in str(e.value)


@respx.mock
async def test_timeout_and_5xx_are_transient():
    respx.post(ENDPOINT).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(TransientError):
        await TavilySearch(KEY).search("q")
    respx.post(ENDPOINT).mock(return_value=httpx.Response(503))
    with pytest.raises(TransientError):
        await TavilySearch(KEY).search("q2")


async def test_not_configured():
    p = TavilySearch("")
    assert not p.is_configured()
    with pytest.raises(NotConfigured):
        await p.search("q")
    assert (await p.test_connection()).state == ProviderState.NOT_CONFIGURED


@respx.mock
async def test_test_connection_states():
    respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json={"results": []}))
    assert (await TavilySearch(KEY).test_connection()).state == ProviderState.CONNECTED
    respx.post(ENDPOINT).mock(return_value=httpx.Response(401))
    s = await TavilySearch(KEY).test_connection()
    assert s.state == ProviderState.ERROR and s.http_status == 401 and KEY not in s.message
