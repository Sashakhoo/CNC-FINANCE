import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import delete

from app.core.db import task_session
from app.models import ProviderCache
from app.worker import celery_app

log = logging.getLogger("app.tasks")


async def _purge() -> int:
    async with task_session() as db:
        res = await db.execute(delete(ProviderCache).where(ProviderCache.expires_at < datetime.now(timezone.utc)))
        await db.commit()
        return res.rowcount or 0


@celery_app.task(name="maintenance.purge_expired_cache")
def purge_expired_cache() -> int:
    n = asyncio.run(_purge())
    log.info("purged expired provider cache", extra={"operation": "purge_cache", "data": {"rows": n}})
    return n


@celery_app.task(name="maintenance.ping")
def ping() -> str:
    return "pong"


async def _retention() -> dict:
    from app.services.dataops import run_retention
    async with task_session() as db:
        r = await run_retention(db, dry_run=False)
        await db.commit()
        return r


@celery_app.task(name="maintenance.retention")
def retention() -> dict:
    r = asyncio.run(_retention())
    log.info("retention run", extra={"operation": "retention", "data": r})
    return r
