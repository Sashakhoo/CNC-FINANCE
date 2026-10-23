import httpx
import pytest
import respx

from app.models.base import VerificationStatus
from app.providers.base import AuthError, BadResponse, MemoryCache, ProviderState, QuotaExceeded, RateLimited, TransientError
from app.providers.verification.reoon import BASE_URL, ReoonVerifier, map_reoon_status

RKEY = "reoon-secret-key-123"
VERIFY = f"{BASE_URL}/verify"
BALANCE = f"{BASE_URL}/check-account-balance/"


class Recorder:
    def __init__(self):
        self.events = []

    async def __call__(self, e):
        self.events.append(e)


@pytest.mark.parametrize("status,expected", [
    ("safe", VerificationStatus.VERIFIED), ("role_account", VerificationStatus.RISKY),
    ("catch_all", VerificationStatus.RISKY), ("inbox_full", VerificationStatus.RISKY),
    ("invalid", VerificationStatus.INVALID), ("disabled", VerificationStatus.INVALID),
    ("disposable", VerificationStatus.INVALID), ("spamtrap", VerificationStatus.INVALID),
    ("unknown", VerificationStatus.UNKNOWN), ("something_new", VerificationStatus.UNKNOWN), (None, VerificationStatus.UNKNOWN),
])
def test_reoon_mapping(status, expected):
    assert map_reoon_status(status)[0] == expected


@respx.mock
async def test_verify_uses_power_mode_maps_and_caches():
    route = respx.get(VERIFY).mock(return_value=httpx.Response(200, json={
        "email": "jane.tan@acme.example", "status": "safe", "overall_score": 98, "username": "jane.tan",
        "domain": "acme.example", "is_safe_to_send": True, "is_deliverable": True, "is_catch_all": False,
        "verification_mode": "power"}))
    rec = Recorder()
    v = ReoonVerifier(RKEY, client=httpx.AsyncClient(), recorder=rec, cache=MemoryCache())
    r1 = await v.verify("Jane.Tan@acme.example")
    r2 = await v.verify("jane.tan@acme.example")
    params = route.calls.last.request.url.params
    assert params["mode"] == "power" and params["key"] == RKEY and params["email"] == "jane.tan@acme.example"
    assert r1.status == VerificationStatus.VERIFIED and r1.confidence == 0.95 and r1.provider == "reoon"
    assert "username" not in r1.meta and r1.meta["overall_score"] == 98
    assert r2.cached and route.call_count == 1 and len(rec.events) == 1 and rec.events[0].success


async def test_syntax_failure_makes_no_call():
    with respx.mock(assert_all_called=False) as m:
        route = m.get(url__regex=r".*").mock(return_value=httpx.Response(500))
        r = await ReoonVerifier(RKEY).verify("broken@@acme")
        assert r.status == VerificationStatus.INVALID and route.call_count == 0


@respx.mock
@pytest.mark.parametrize("reason,code,exc", [
    ("Invalid API key", 200, AuthError),
    ("Not enough credits", 200, QuotaExceeded),
    ("Insufficient balance", 200, QuotaExceeded),
    ("Something else went wrong", 200, BadResponse),
    ("", 401, AuthError),
    ("", 402, QuotaExceeded),
])
async def test_error_bodies_map_without_leaking_key(reason, code, exc):
    respx.get(VERIFY).mock(return_value=httpx.Response(code, json={"status": "error", "reason": reason}))
    rec = Recorder()
    with pytest.raises(exc) as ei:
        await ReoonVerifier(RKEY, client=httpx.AsyncClient(), recorder=rec).verify("ken@acme.example")
    assert RKEY not in str(ei.value) and rec.events[0].success is False


@respx.mock
async def test_429_and_network_error():
    respx.get(VERIFY).mock(side_effect=[
        httpx.Response(429, headers={"retry-after": "30"}),
        httpx.ConnectError("boom"),
        httpx.Response(503),
    ])
    v = ReoonVerifier(RKEY, client=httpx.AsyncClient())
    with pytest.raises(RateLimited) as ei:
        await v.verify("a.b@acme.example")
    assert ei.value.retry_after == 30
    with pytest.raises(TransientError) as ei2:
        await v.verify("a.b@acme.example")
    assert RKEY not in str(ei2.value) and "reoon.com" not in str(ei2.value)
    with pytest.raises(TransientError):
        await v.verify("a.b@acme.example")


@respx.mock
async def test_test_connection_states():
    respx.get(BALANCE).mock(side_effect=[
        httpx.Response(200, json={"api_status": "active", "remaining_daily_credits": 20,
                                  "remaining_instant_credits": 580, "status": "success"}),
        httpx.Response(200, json={"api_status": "active", "remaining_daily_credits": 0,
                                  "remaining_instant_credits": 0, "status": "success"}),
        httpx.Response(200, json={"status": "error", "reason": "Invalid API key"}),
    ])
    v = ReoonVerifier(RKEY, client=httpx.AsyncClient())
    ok = await v.test_connection()
    assert ok.state == ProviderState.CONNECTED and "20 daily + 580 instant" in ok.message
    assert "0 credits" in (await v.test_connection()).message
    bad = await v.test_connection()
    assert bad.state == ProviderState.ERROR and RKEY not in bad.message
    assert (await ReoonVerifier("").test_connection()).state == ProviderState.NOT_CONFIGURED
