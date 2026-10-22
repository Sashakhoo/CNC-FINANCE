"""Request-level protections: cross-site write blocking and rate limits."""
import time
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _allowed_origins() -> set[str]:
    s = get_settings()
    extra = [o.strip().rstrip("/") for o in s.allowed_origins.split(",") if o.strip()]
    return {s.frontend_url.rstrip("/"), *extra}


def cross_site_violation(request: Request) -> str | None:
    """Cookie-authenticated writes must come from our own pages. Returns a reason to block, or None."""
    if request.method in SAFE_METHODS or not request.url.path.startswith("/api/"):
        return None
    if request.headers.get("sec-fetch-site") == "cross-site":
        return "cross-site request"
    origin = request.headers.get("origin")
    if not origin:
        return None  # non-browser clients (curl, server-to-server) don't send Origin and carry no ambient cookie risk
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    if urlsplit(origin).netloc.lower() == host.lower() or origin.rstrip("/") in _allowed_origins():
        return None
    return f"origin {origin} not allowed"


async def origin_guard(request: Request, call_next):
    reason = cross_site_violation(request)
    if reason:
        return JSONResponse({"detail": "Request blocked: " + reason}, status_code=403)
    return await call_next(request)


class _Window:
    """Fixed-window counter: Redis in production (shared by all workers), memory in tests."""

    def __init__(self):
        self._mem: dict[str, tuple[int, int]] = {}
        self._redis = None

    def _client(self):
        s = get_settings()
        if s.app_env == "test":
            return None
        if self._redis is None:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(s.redis_url)
        return self._redis

    async def hit(self, key: str, window: int) -> int:
        bucket = int(time.time() // window)
        r = self._client()
        if r is None:
            b, n = self._mem.get(key, (bucket, 0))
            n = n + 1 if b == bucket else 1
            self._mem[key] = (bucket, n)
            if len(self._mem) > 10000:
                self._mem.clear()
            return n
        k = f"rl:{key}:{bucket}"
        async with r.pipeline(transaction=True) as p:
            p.incr(k)
            p.expire(k, window + 5)
            n, _ = await p.execute()
        return int(n)

    def reset(self) -> None:
        self._mem.clear()


window = _Window()


def rate_limit(name: str, per_minute: int):
    async def dep(request: Request) -> None:
        fwd = request.headers.get("x-forwarded-for", "")
        ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")
        try:
            n = await window.hit(f"{name}:{ip}", 60)
        except Exception:
            return  # a Redis outage must not take the API down
        if n > per_minute:
            raise HTTPException(429, f"Too many requests — try again in a minute ({name})")
    return dep
