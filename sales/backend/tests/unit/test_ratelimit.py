import asyncio

import pytest

from app.providers.base import AuthError, ProviderInfo, ProviderKind, QuotaExceeded, RateLimited, TransientError
from app.providers.ratelimit import MemoryQuotaStore, ProviderGuard, RedisQuotaStore, RetryPolicy

INFO = ProviderInfo(name="fake", kind=ProviderKind.SEARCH, display_name="Fake", access_method="API",
                    requests_per_minute=3, requests_per_day=100, concurrency=2)


class Sleeps:
    def __init__(self):
        self.calls = []

    async def __call__(self, s):
        self.calls.append(s)


def guard(**kw):
    sleeps = Sleeps()
    return ProviderGuard(MemoryQuotaStore(clock=lambda: 1000.0), policy=RetryPolicy(jitter=0), sleep=sleeps, **kw), sleeps


async def ok():
    return "ok"


async def test_minute_quota_exhausts_without_calling_provider():
    g, _ = guard()
    for _ in range(3):
        assert await g.call(INFO, ok) == "ok"
    called = []

    async def tracked():
        called.append(1)
        return "x"

    with pytest.raises(QuotaExceeded):
        await g.call(INFO, tracked)
    assert called == []


async def test_override_limits():
    g, _ = guard(limits={"fake": {"minute": 1}})
    await g.call(INFO, ok)
    with pytest.raises(QuotaExceeded):
        await g.call(INFO, ok)


async def test_retries_rate_limited_honouring_retry_after():
    g, sleeps = guard()
    attempts = []

    async def flaky():
        attempts.append(1)
        if len(attempts) < 2:
            raise RateLimited("slow down", retry_after=7)
        return "done"

    assert await g.call(INFO, flaky) == "done"
    assert sleeps.calls == [7]


async def test_transient_backoff_then_gives_up():
    g, sleeps = guard(limits={"fake": {"minute": 100}})

    async def always():
        raise TransientError("503")

    with pytest.raises(TransientError):
        await g.call(INFO, always)
    assert sleeps.calls == [1.0, 2.0, 4.0]


async def test_non_retryable_errors_propagate_immediately():
    g, sleeps = guard()

    async def bad():
        raise AuthError("bad key")

    with pytest.raises(AuthError):
        await g.call(INFO, bad)
    assert sleeps.calls == []


async def test_concurrency_limit():
    g, _ = guard(limits={"fake": {"minute": 100}})
    live, peak = 0, 0

    async def work():
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.01)
        live -= 1
        return 1

    await asyncio.gather(*(g.call(INFO, work) for _ in range(6)))
    assert peak == 2


class FakePipe:
    def __init__(self, redis):
        self.r, self.ops = redis, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def incr(self, k):
        self.ops.append(("incr", k))

    def expire(self, k, s):
        self.ops.append(("expire", k, s))

    async def execute(self):
        out = []
        for op in self.ops:
            if op[0] == "incr":
                self.r.d[op[1]] = self.r.d.get(op[1], 0) + 1
                out.append(self.r.d[op[1]])
            else:
                self.r.ttl[op[1]] = op[2]
                out.append(True)
        return out


class FakeRedis:
    def __init__(self):
        self.d, self.ttl = {}, {}

    def pipeline(self, transaction=True):
        assert transaction
        return FakePipe(self)

    async def decr(self, k):
        self.d[k] -= 1


async def test_redis_store_windows_and_expiry():
    r = FakeRedis()
    g = ProviderGuard(RedisQuotaStore(r, clock=lambda: 120.0), policy=RetryPolicy(jitter=0), sleep=Sleeps())
    for _ in range(3):
        await g.call(INFO, ok)
    with pytest.raises(QuotaExceeded):
        await g.call(INFO, ok)
    minute_key = "quota:fake:60:2"
    assert r.d[minute_key] == 3 and r.ttl[minute_key] == 120
    assert r.d["quota:fake:86400:0"] == 3
