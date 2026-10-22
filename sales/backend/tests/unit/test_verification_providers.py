import httpx
import pytest
import respx

from app.models.base import VerificationStatus
from app.providers.base import AuthError, MemoryCache, ProviderState, RateLimited, TransientError
from app.providers.verification.hunter import HunterVerifier, map_hunter_status
from app.providers.verification.zerobounce import ZeroBounceVerifier, map_zerobounce_status

HKEY = "hunter-verify-secret"
ZKEY = "zb-secret-key-987"


class Recorder:
    def __init__(self):
        self.events = []

    async def __call__(self, e):
        self.events.append(e)


@pytest.mark.parametrize("status,score,expected", [
    ("valid", 95, VerificationStatus.VERIFIED), ("accept_all", 85, VerificationStatus.LIKELY),
    ("accept_all", 50, VerificationStatus.RISKY), ("webmail", 90, VerificationStatus.RISKY),
    ("disposable", 10, VerificationStatus.INVALID), ("invalid", 0, VerificationStatus.INVALID),
    ("unknown", None, VerificationStatus.UNKNOWN), ("something_new", 50, VerificationStatus.UNKNOWN),
])
def test_hunter_mapping(status, score, expected):
    assert map_hunter_status(status, score) == expected


@pytest.mark.parametrize("status,expected", [
    ("valid", VerificationStatus.VERIFIED), ("catch-all", VerificationStatus.RISKY),
    ("abuse", VerificationStatus.RISKY), ("invalid", VerificationStatus.INVALID),
    ("spamtrap", VerificationStatus.INVALID), ("do_not_mail", VerificationStatus.INVALID),
    ("unknown", VerificationStatus.UNKNOWN),
])
def test_zerobounce_mapping(status, expected):
    assert map_zerobounce_status(status)[0] == expected


@respx.mock
async def test_hunter_verify_and_cache():
    route = respx.get("https://api.hunter.io/v2/email-verifier").mock(return_value=httpx.Response(200, json={
        "data": {"status": "valid", "score": 97, "email": "jane.tan@acme.example", "smtp_check": True}}))
    rec = Recorder()
    v = HunterVerifier(HKEY, client=httpx.AsyncClient(), recorder=rec, cache=MemoryCache())
    r1 = await v.verify("Jane.Tan@acme.example")
    r2 = await v.verify("jane.tan@acme.example")
    assert r1.status == VerificationStatus.VERIFIED and r1.confidence == 0.97 and not r1.cached
    assert r2.cached and route.call_count == 1 and len(rec.events) == 1
    assert r1.meta == {"status": "valid", "score": 97, "smtp_check": True}


@respx.mock
async def test_hunter_verify_in_progress_is_transient():
    respx.get("https://api.hunter.io/v2/email-verifier").mock(return_value=httpx.Response(202, json={}))
    with pytest.raises(TransientError):
        await HunterVerifier(HKEY, client=httpx.AsyncClient()).verify("jane@acme.example")


async def test_syntax_failure_makes_no_call():
    with respx.mock(assert_all_called=False) as m:
        route = m.get(url__regex=r".*").mock(return_value=httpx.Response(500))
        r = await HunterVerifier(HKEY).verify("broken@@acme")
        assert r.status == VerificationStatus.INVALID and route.call_count == 0


@respx.mock
async def test_zerobounce_verify_maps_and_hides_key():
    route = respx.get("https://api.zerobounce.net/v2/validate").mock(return_value=httpx.Response(200, json={
        "address": "ken@acme.example", "status": "catch-all", "sub_status": "", "free_email": False,
        "firstname": "Ken", "processed_at": "2026-10-22 10:00:00.000"}))
    rec = Recorder()
    r = await ZeroBounceVerifier(ZKEY, client=httpx.AsyncClient(), recorder=rec).verify("ken@acme.example")
    assert r.status == VerificationStatus.RISKY and r.provider == "zerobounce"
    assert "firstname" not in r.meta and r.meta["status"] == "catch-all"
    assert route.calls.last.request.url.params["api_key"] == ZKEY
    assert rec.events[0].success


@respx.mock
async def test_zerobounce_error_body_is_auth_error_without_key():
    respx.get("https://api.zerobounce.net/v2/validate").mock(return_value=httpx.Response(
        200, json={"error": "Invalid API Key or your account ran out of credits"}))
    rec = Recorder()
    with pytest.raises(AuthError) as ei:
        await ZeroBounceVerifier(ZKEY, client=httpx.AsyncClient(), recorder=rec).verify("ken@acme.example")
    assert ZKEY not in str(ei.value) and rec.events[0].success is False


@respx.mock
async def test_zerobounce_429_and_network_error():
    respx.get("https://api.zerobounce.net/v2/validate").mock(side_effect=[
        httpx.Response(429, headers={"retry-after": "30"}),
        httpx.ConnectError("boom"),
    ])
    v = ZeroBounceVerifier(ZKEY, client=httpx.AsyncClient())
    with pytest.raises(RateLimited) as ei:
        await v.verify("a.b@acme.example")
    assert ei.value.retry_after == 30
    with pytest.raises(TransientError) as ei2:
        await v.verify("a.b@acme.example")
    assert ZKEY not in str(ei2.value) and "zerobounce.net" not in str(ei2.value)


@respx.mock
async def test_zerobounce_test_connection_states():
    respx.get("https://api.zerobounce.net/v2/getcredits").mock(side_effect=[
        httpx.Response(200, json={"Credits": 1200}), httpx.Response(200, json={"Credits": -1}),
        httpx.Response(200, json={"Credits": 0}),
    ])
    v = ZeroBounceVerifier(ZKEY, client=httpx.AsyncClient())
    assert (await v.test_connection()).state == ProviderState.CONNECTED
    assert (await v.test_connection()).state == ProviderState.ERROR
    assert "0 credits" in (await v.test_connection()).message
    assert (await ZeroBounceVerifier("").test_connection()).state == ProviderState.NOT_CONFIGURED


@respx.mock
async def test_hunter_verifier_connection():
    respx.get("https://api.hunter.io/v2/account").mock(return_value=httpx.Response(200, json={"data": {
        "requests": {"verifications": {"used": 1, "available": 100, "remaining": 99}}}}))
    st = await HunterVerifier(HKEY, client=httpx.AsyncClient()).test_connection()
    assert st.state == ProviderState.CONNECTED and "99 verifications" in st.message
