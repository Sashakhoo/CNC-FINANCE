import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.models import Company, Contact, ContactEmail, Job, LeadScore, ProspectSearch
from app.models.base import JobStatus, Priority, VerificationStatus
from app.services.jobs import create_job, run_job
from app.services.runtime import build_providers
from app.worker import celery_app

log = logging.getLogger("app.tasks")
LONG = 6 * 3600


async def _execute(job_id: int, body_name: str) -> None:
    from app.services import pipeline
    body = {"discovery": pipeline.run_discovery, "enrich": pipeline.run_enrich, "reverify": _reverify}[body_name]
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    providers = build_providers(sm, job_id)
    try:
        async with sm() as db:
            job = await db.get(Job, job_id)
            if job is None or job.cancel_requested:
                if job and job.status == JobStatus.QUEUED:
                    job.status = JobStatus.CANCELLED
                    await db.commit()
                return
            job.provider = ", ".join(f"{k}:{v}" for k, v in providers.summary().items() if v) or "none configured"
            await db.commit()
            user_id = job.created_by_id
            await run_job(db, job_id, lambda run: body(db, run, providers, user_id))
    finally:
        await providers.aclose()
        await engine.dispose()


async def _reverify(db, run, providers, user_id) -> None:
    from app.services.pipeline import COUNTERS
    await run.bump(stage="Re-verifying stale emails", **{k: 0 for k in COUNTERS})
    verifier = providers.verifier
    if not verifier:
        await run.note("warning", "No email verification provider configured — nothing to re-verify")
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    emails = (await db.execute(select(ContactEmail).where(ContactEmail.verified_at < cutoff).limit(500))).scalars().all()
    for i, e in enumerate(emails):
        await run.check_cancel()
        try:
            r = await providers.call(verifier, lambda e=e: verifier.verify(e.email))
        except Exception as ex:  # one address failing must not stop the batch
            await run.note("warning", f"{e.email}: {getattr(ex, 'error_type', type(ex).__name__)}")
            continue
        e.verification_status, e.verified_at, e.verification_meta = r.status, r.checked_at, r.meta
        await run.bump(processed=1, progress=100 * (i + 1) / max(len(emails), 1),
                       emails_verified=int(r.status == VerificationStatus.VERIFIED))
        await db.commit()


@celery_app.task(name="discovery.run", time_limit=LONG, soft_time_limit=LONG - 60)
def run_discovery_task(job_id: int) -> None:
    asyncio.run(_execute(job_id, "discovery"))


@celery_app.task(name="discovery.enrich", time_limit=LONG, soft_time_limit=LONG - 60)
def run_enrich_task(job_id: int) -> None:
    asyncio.run(_execute(job_id, "enrich"))


@celery_app.task(name="discovery.reverify", time_limit=LONG, soft_time_limit=LONG - 60)
def run_reverify_task(job_id: int) -> None:
    asyncio.run(_execute(job_id, "reverify"))


async def _schedule(kind: str) -> list[int]:
    """Creates the scheduled jobs (rows first, so they show in the Job Monitor) and returns their ids."""
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    ids: list[tuple[str, int]] = []
    try:
        async with sm() as db:
            if kind == "weekly":
                searches = (await db.execute(select(ProspectSearch).where(ProspectSearch.deleted_at.is_(None)))).scalars().all()
                for s in searches:
                    if (s.criteria or {}).get("schedule") == "weekly":
                        j = await create_job(db, "discovery", f"Weekly: {s.name}", search_id=s.id, user_id=s.created_by_id)
                        ids.append(("discovery.run", j.id))
            elif kind == "monthly":
                cutoff = datetime.now(timezone.utc) - timedelta(days=30)
                rows = (await db.execute(
                    select(Company.id, Company.display_name).join(Contact, Contact.company_id == Company.id)
                    .join(LeadScore, LeadScore.contact_id == Contact.id)
                    .where(LeadScore.is_current.is_(True), LeadScore.priority == Priority.HIGH, Company.deleted_at.is_(None),
                           (Company.last_enriched_at.is_(None)) | (Company.last_enriched_at < cutoff))
                    .distinct().limit(20))).all()
                for cid, name in rows:
                    j = await create_job(db, "enrich", f"Monthly refresh: {name}", params={"company_id": cid})
                    ids.append(("discovery.enrich", j.id))
            elif kind == "reverify":
                j = await create_job(db, "reverify", "Re-verify emails older than 90 days")
                ids.append(("discovery.reverify", j.id))
            await db.commit()
    finally:
        await engine.dispose()
    for task, jid in ids:
        r = celery_app.send_task(task, args=[jid])
        async with sm() as db:
            await db.execute(update(Job).where(Job.id == jid).values(celery_task_id=r.id))
            await db.commit()
    return [jid for _, jid in ids]


@celery_app.task(name="schedule.weekly_discovery")
def weekly_discovery() -> list[int]:
    return asyncio.run(_schedule("weekly"))


@celery_app.task(name="schedule.monthly_refresh")
def monthly_refresh() -> list[int]:
    return asyncio.run(_schedule("monthly"))


@celery_app.task(name="schedule.reverify_emails")
def reverify_emails() -> list[int]:
    return asyncio.run(_schedule("reverify"))
