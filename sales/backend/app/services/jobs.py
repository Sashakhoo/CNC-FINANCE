"""Job lifecycle helpers shared by every background task. Counters are the
single source of truth the Job Monitor and Discovery screens display."""
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job
from app.models.base import JobStatus

log = logging.getLogger("app.jobs")
MAX_MESSAGES = 200


class JobCancelled(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def create_job(db: AsyncSession, job_type: str, name: str, *, params: dict | None = None,
                     search_id: int | None = None, user_id: int | None = None, provider: str | None = None) -> Job:
    job = Job(job_type=job_type, name=name, params=params or {}, search_id=search_id, created_by_id=user_id,
              provider=provider, counters={}, warnings=[], errors=[])
    db.add(job)
    await db.flush()
    return job


class JobRun:
    """Wraps one execution of a Job inside a worker."""

    def __init__(self, db: AsyncSession, job_id: int):
        self.db = db
        self.job_id = job_id

    async def start(self, stage: str | None = None) -> Job:
        await self.db.execute(update(Job).where(Job.id == self.job_id).values(
            status=JobStatus.RUNNING, started_at=_now(), finished_at=None, stage=stage))
        await self.db.commit()
        return await self.db.get(Job, self.job_id)

    async def _job(self) -> Job:
        job = await self.db.get(Job, self.job_id)
        await self.db.refresh(job)
        return job

    async def check_cancel(self) -> None:
        cancelled = (await self.db.execute(select(Job.cancel_requested).where(Job.id == self.job_id))).scalar_one()
        if cancelled:
            raise JobCancelled()

    async def bump(self, stage: str | None = None, progress: float | None = None, processed: int = 0,
                   created: int = 0, **counters: int) -> None:
        job = await self._job()
        merged = dict(job.counters or {})
        for k, v in counters.items():
            merged[k] = merged.get(k, 0) + v
        job.counters = merged
        job.records_processed += processed
        job.records_created += created
        if stage is not None:
            job.stage = stage
        if progress is not None:
            job.progress = max(0.0, min(100.0, progress))
        await self.db.commit()

    async def note(self, level: str, message: str, **context) -> None:
        job = await self._job()
        entry = {"at": _now().isoformat(), "message": message[:500], **{k: str(v)[:200] for k, v in context.items()}}
        if level == "error":
            job.errors = (list(job.errors or []) + [entry])[-MAX_MESSAGES:]
        else:
            job.warnings = (list(job.warnings or []) + [entry])[-MAX_MESSAGES:]
        await self.db.commit()
        getattr(log, "error" if level == "error" else "warning")(message, extra={"job_id": self.job_id, "data": context})

    async def finish(self, status: JobStatus = JobStatus.COMPLETED) -> None:
        values = {"status": status, "finished_at": _now()}
        if status == JobStatus.COMPLETED:
            values["progress"] = 100.0
        await self.db.execute(update(Job).where(Job.id == self.job_id).values(**values))
        await self.db.commit()


async def run_job(db: AsyncSession, job_id: int, body) -> None:
    """Runs `body(run)`, translating cancellation and crashes into job status."""
    run = JobRun(db, job_id)
    await run.start()
    try:
        await body(run)
    except JobCancelled:
        await db.rollback()
        await run.finish(JobStatus.CANCELLED)
        return
    except Exception as e:  # one job's failure must never take the worker down
        await db.rollback()
        log.exception("job failed", extra={"job_id": job_id, "error_type": type(e).__name__})
        await run.note("error", f"{type(e).__name__}: {e}")
        await run.finish(JobStatus.FAILED)
        return
    await run.finish(JobStatus.COMPLETED)
