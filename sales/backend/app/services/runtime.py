"""Runtime wiring for providers: DB-backed usage log and cache, Redis quotas,
and one bundle of configured providers per job."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, TypeVar

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.models import ProviderCache, ProviderUsage
from app.providers.base import ProviderInfo, ProviderKind, UsageEvent
from app.providers.ratelimit import MemoryQuotaStore, ProviderGuard, RedisQuotaStore
from app.providers.registry import build_provider

log = logging.getLogger("app.providers")
T = TypeVar("T")


class DbCache:
    """`Cache` protocol on the provider_cache table. JSON-serialisable values only."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], provider: str = "shared"):
        self._sessions = sessions
        self._provider = provider

    async def get(self, key: str) -> Any | None:
        async with self._sessions() as db:
            row = await db.get(ProviderCache, key[:300])
            if not row or row.expires_at < datetime.now(timezone.utc):
                return None
            return row.value.get("v") if isinstance(row.value, dict) else row.value

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        payload = {"v": json.loads(json.dumps(value, default=str))}
        expires = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        async with self._sessions() as db:
            stmt = insert(ProviderCache).values(cache_key=key[:300], provider=self._provider, value=payload, expires_at=expires)
            await db.execute(stmt.on_conflict_do_update(index_elements=["cache_key"],
                                                        set_={"value": payload, "expires_at": expires}))
            await db.commit()


@dataclass
class DbRecorder:
    sessions: async_sessionmaker[AsyncSession]
    job_id: int | None = None
    events: list[UsageEvent] = field(default_factory=list)

    async def __call__(self, event: UsageEvent) -> None:
        self.events.append(event)
        try:
            async with self.sessions() as db:
                db.add(ProviderUsage(provider=event.provider, kind=event.kind.value, operation=event.operation,
                                     success=event.success, http_status=event.http_status, duration_ms=event.duration_ms,
                                     error_type=event.error_type, cost_estimate=event.cost_estimate, job_id=self.job_id))
                await db.commit()
        except Exception:  # usage logging must never break the provider call
            log.exception("could not record provider usage", extra={"provider": event.provider})


def provider_limits(s: Settings) -> dict:
    if not s.provider_limits.strip():
        return {}
    try:
        data = json.loads(s.provider_limits)
        return {str(k): {w: (int(v) if v is not None else None) for w, v in d.items() if w in ("minute", "day", "month")}
                for k, d in data.items() if isinstance(d, dict)}
    except (ValueError, TypeError, AttributeError):
        log.warning("PROVIDER_LIMITS is not valid JSON; using provider defaults")
        return {}


def make_guard(settings: Settings | None = None) -> ProviderGuard:
    s = settings or get_settings()
    if s.app_env == "test":
        return ProviderGuard(MemoryQuotaStore(), limits=provider_limits(s))
    import redis.asyncio as aioredis
    return ProviderGuard(RedisQuotaStore(aioredis.from_url(s.redis_url)), limits=provider_limits(s))


@dataclass
class Providers:
    """Configured providers for one job; any of them may be None (NOT CONFIGURED)."""
    client: httpx.AsyncClient
    guard: ProviderGuard
    recorder: DbRecorder
    search: Any = None
    email: Any = None
    verifier: Any = None
    ai: Any = None

    async def call(self, provider: Any, fn: Callable[[], Awaitable[T]]) -> T:
        info: ProviderInfo = provider.info
        return await self.guard.call(info, fn)

    def summary(self) -> dict[str, str | None]:
        return {k: (getattr(getattr(self, k), "info", None).name if getattr(self, k) else None)
                for k in ("search", "email", "verifier", "ai")}

    async def aclose(self) -> None:
        await self.client.aclose()


def build_providers(sessions: async_sessionmaker[AsyncSession], job_id: int | None = None,
                    settings: Settings | None = None, guard: ProviderGuard | None = None) -> Providers:
    s = settings or get_settings()
    client = httpx.AsyncClient(timeout=30.0)
    recorder = DbRecorder(sessions, job_id)
    cache = DbCache(sessions)
    p = Providers(client=client, guard=guard or make_guard(s), recorder=recorder)
    p.search = build_provider(ProviderKind.SEARCH, s, client, recorder, cache)
    p.email = build_provider(ProviderKind.EMAIL_DISCOVERY, s, client, recorder, cache)
    p.verifier = build_provider(ProviderKind.EMAIL_VERIFICATION, s, client, recorder, cache)
    p.ai = build_provider(ProviderKind.AI, s, client, recorder, cache)
    return p


async def usage_stats(db: AsyncSession) -> list[dict]:
    """Per-provider request counts, success rate and latency for Provider Usage."""
    from sqlalchemy import Integer, case, func
    now = datetime.now(timezone.utc)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    rows = (await db.execute(select(
        ProviderUsage.provider, ProviderUsage.kind,
        func.count().filter(ProviderUsage.created_at >= day).label("today"),
        func.count().filter(ProviderUsage.created_at >= month).label("month"),
        func.sum(case((ProviderUsage.success.is_(True), 1), else_=0).cast(Integer)).filter(ProviderUsage.created_at >= month).label("ok_month"),
        func.count().filter((ProviderUsage.success.is_(False)) & (ProviderUsage.created_at >= month)).label("errors_month"),
        func.avg(ProviderUsage.duration_ms).filter(ProviderUsage.created_at >= month).label("avg_ms"),
        func.sum(ProviderUsage.cost_estimate).filter(ProviderUsage.created_at >= month).label("cost"),
        func.max(ProviderUsage.created_at).label("last_used"),
    ).group_by(ProviderUsage.provider, ProviderUsage.kind))).all()
    out = []
    for r in rows:
        out.append({"provider": r.provider, "kind": r.kind, "requests_today": r.today, "requests_month": r.month,
                    "success_rate": round((r.ok_month or 0) / r.month * 100, 1) if r.month else None,
                    "errors_month": r.errors_month, "avg_ms": round(float(r.avg_ms)) if r.avg_ms is not None else None,
                    "estimated_cost": float(r.cost) if r.cost is not None else None,
                    "last_used": r.last_used.isoformat() if r.last_used else None})
    recent_errors = (await db.execute(select(ProviderUsage).where(ProviderUsage.success.is_(False))
                                      .order_by(ProviderUsage.created_at.desc()).limit(20))).scalars().all()
    for row in out:
        row["recent_errors"] = [{"at": e.created_at.isoformat(), "operation": e.operation, "error_type": e.error_type,
                                 "http_status": e.http_status} for e in recent_errors if e.provider == row["provider"]][:5]
    return out
