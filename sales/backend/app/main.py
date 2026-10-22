import logging
import time

from fastapi import FastAPI, Request
from sqlalchemy import text

from app.api import analytics, auth, companies, contacts, dataops, discovery, outreach, workspace
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.logging import setup_logging
from app.core.security import origin_guard

setup_logging(get_settings().log_level)
log = logging.getLogger("app")

app = FastAPI(title="Codencode Lead Intelligence API", version="1.0.0",
              docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")


app.middleware("http")(origin_guard)


@app.middleware("http")
async def access_log_and_headers(request: Request, call_next):
    start = time.perf_counter()
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.url.path not in ("/health",):
        log.info("request", extra={"operation": f"{request.method} {request.url.path}", "status": resp.status_code,
                                   "duration_ms": round((time.perf_counter() - start) * 1000),
                                   "user": getattr(request.state, "user_id", None)})
    return resp


@app.get("/health", include_in_schema=False)
async def health():
    """Liveness: the database must answer. Redis is reported but not fatal (the API works without it)."""
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))
    redis_ok = None
    if get_settings().app_env != "test":
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(get_settings().redis_url, socket_timeout=2)
            redis_ok = bool(await r.ping())
            await r.aclose()
        except Exception:
            redis_ok = False
    return {"status": "ok", "database": True, "redis": redis_ok}


app.include_router(auth.router)
app.include_router(analytics.router)
app.include_router(companies.router)
app.include_router(contacts.router)
app.include_router(workspace.router)
app.include_router(discovery.router)
app.include_router(outreach.router)
app.include_router(dataops.router)
