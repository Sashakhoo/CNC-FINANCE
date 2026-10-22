"""Quota, concurrency and retry policy applied around every provider call.

    guard = ProviderGuard(MemoryQuotaStore())        # or RedisQuotaStore(redis)
    results = await guard.call(provider.info, lambda: provider.search("..."))

Local quotas (requests per minute/day/month from ProviderInfo, overridable)
are checked before each attempt; exhausting one raises QuotaExceeded without
calling the provider. RateLimited/TransientError are retried with exponential
backoff + jitter (honouring retry_after); other errors propagate at once.
"""
from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from app.providers.base import ProviderInfo, QuotaExceeded, RateLimited, TransientError

T = TypeVar("T")

WINDOWS = (("minute", 60), ("day", 86_400), ("month", 2_592_000))


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 4
    base_delay: float = 1.0
    max_delay: float = 60.0
    jitter: float = 0.25

    def delay(self, attempt: int, retry_after: float | None = None) -> float:
        backoff = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))
        backoff *= 1 + random.uniform(0, self.jitter)
        if retry_after is not None:
            backoff = max(backoff, min(retry_after, self.max_delay))
        return backoff


class QuotaStore(Protocol):
    async def hit(self, key: str, window_seconds: int) -> int:
        """Counts one request in the current window and returns the new count."""
        ...

    async def undo(self, key: str, window_seconds: int) -> None: ...


class MemoryQuotaStore:
    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._counts: dict[str, int] = {}

    def _bucket(self, key: str, window: int) -> str:
        return f"{key}:{int(self._clock() // window)}"

    async def hit(self, key: str, window_seconds: int) -> int:
        b = self._bucket(key, window_seconds)
        self._counts[b] = self._counts.get(b, 0) + 1
        return self._counts[b]

    async def undo(self, key: str, window_seconds: int) -> None:
        b = self._bucket(key, window_seconds)
        if self._counts.get(b):
            self._counts[b] -= 1


class RedisQuotaStore:
    """Fixed windows shared by every worker: INCR + EXPIRE in one MULTI."""

    def __init__(self, redis: Any, prefix: str = "quota", clock: Callable[[], float] = time.time):
        self._r = redis
        self._prefix = prefix
        self._clock = clock

    def _bucket(self, key: str, window: int) -> str:
        return f"{self._prefix}:{key}:{window}:{int(self._clock() // window)}"

    async def hit(self, key: str, window_seconds: int) -> int:
        b = self._bucket(key, window_seconds)
        async with self._r.pipeline(transaction=True) as pipe:
            pipe.incr(b)
            pipe.expire(b, window_seconds + 60)
            count, _ = await pipe.execute()
        return int(count)

    async def undo(self, key: str, window_seconds: int) -> None:
        await self._r.decr(self._bucket(key, window_seconds))


class ProviderGuard:
    def __init__(self, store: QuotaStore | None = None, policy: RetryPolicy | None = None,
                 limits: dict[str, dict[str, int | None]] | None = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        self._store = store or MemoryQuotaStore()
        self._policy = policy or RetryPolicy()
        self._limits = limits or {}   # {"brave": {"minute": 30, "day": None, "month": 2000}} overrides
        self._sleep = sleep
        self._sems: dict[str, asyncio.Semaphore] = {}

    def _limit(self, info: ProviderInfo, window: str) -> int | None:
        override = self._limits.get(info.name, {})
        if window in override:
            return override[window]
        return {"minute": info.requests_per_minute, "day": info.requests_per_day,
                "month": info.requests_per_month}[window]

    def _sem(self, info: ProviderInfo) -> asyncio.Semaphore:
        if info.name not in self._sems:
            self._sems[info.name] = asyncio.Semaphore(max(1, info.concurrency))
        return self._sems[info.name]

    async def _consume(self, info: ProviderInfo) -> None:
        counted: list[int] = []
        for window, seconds in WINDOWS:
            limit = self._limit(info, window)
            if not limit:
                continue
            n = await self._store.hit(info.name, seconds)
            counted.append(seconds)
            if n > limit:
                for s in counted:
                    await self._store.undo(info.name, s)
                raise QuotaExceeded(f"{info.display_name}: local {window} quota of {limit} requests reached")

    async def call(self, info: ProviderInfo, factory: Callable[[], Awaitable[T]]) -> T:
        attempt = 0
        while True:
            attempt += 1
            await self._consume(info)
            try:
                async with self._sem(info):
                    return await factory()
            except (RateLimited, TransientError) as e:
                if attempt >= self._policy.max_attempts:
                    raise
                await self._sleep(self._policy.delay(attempt, getattr(e, "retry_after", None)))
