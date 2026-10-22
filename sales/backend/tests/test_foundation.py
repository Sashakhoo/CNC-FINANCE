from alembic import command
from sqlalchemy import func, select, update

from app.core.logging import redact
from app.models import Company, Contact, Job, TrainingProgram
from app.models.base import JobStatus, PipelineStatus
from app.services.jobs import JobCancelled, create_job, run_job
from tests.conftest import finance_session


def test_redact_hides_secrets_recursively():
    out = redact({"api_key": "k", "nested": {"Authorization": "Bearer x", "ok": 1}, "list": [{"password": "p"}]})
    assert out == {"api_key": "[REDACTED]", "nested": {"Authorization": "[REDACTED]", "ok": 1},
                   "list": [{"password": "[REDACTED]"}]}


def test_models_match_migrations(migrated):
    command.check(migrated)


async def test_default_training_programs_loaded(db):
    assert await db.scalar(select(func.count()).select_from(TrainingProgram)) == 14


async def _job(db) -> int:
    job = await create_job(db, "test", "Test job")
    await db.commit()
    return job.id


async def test_job_completes_with_counters(db):
    jid = await _job(db)

    async def body(run):
        await run.bump(stage="crawl", processed=3, created=2, companies=2, websites=1)
        await run.bump(companies=1)

    await run_job(db, jid, body)
    job = await db.get(Job, jid)
    await db.refresh(job)
    assert job.status == JobStatus.COMPLETED and job.progress == 100
    assert job.counters == {"companies": 3, "websites": 1}
    assert (job.records_processed, job.records_created) == (3, 2)


async def test_job_failure_is_recorded_not_raised(db):
    jid = await _job(db)

    async def body(run):
        raise RuntimeError("provider exploded")

    await run_job(db, jid, body)
    job = await db.get(Job, jid)
    await db.refresh(job)
    assert job.status == JobStatus.FAILED
    assert "provider exploded" in job.errors[0]["message"]


async def test_job_cancellation(db):
    jid = await _job(db)
    await db.execute(update(Job).where(Job.id == jid).values(cancel_requested=True))
    await db.commit()

    async def body(run):
        await run.check_cancel()
        raise AssertionError("should have been cancelled")

    await run_job(db, jid, body)
    job = await db.get(Job, jid)
    await db.refresh(job)
    assert job.status == JobStatus.CANCELLED


async def test_dashboard_counts_from_database_and_excludes_demo(client, finance, db):
    client.cookies.update(finance_session(finance))
    empty = (await client.get("/api/analytics/summary")).json()
    assert empty["companies"] == 0 and empty["prospects"] == 0 and empty["pipeline_value"] == 0

    real = Company(legal_name="Acme Sdn Bhd", display_name="Acme", normalized_name="acme", deal_value=5000)
    demo = Company(legal_name="Fictional Sdn Bhd", display_name="Fictional", normalized_name="fictional", is_demo=True)
    db.add_all([real, demo])
    await db.flush()
    db.add_all([
        Contact(company_id=real.id, full_name="A", normalized_name="a", status=PipelineStatus.MEETING),
        Contact(company_id=real.id, full_name="B", normalized_name="b", status=PipelineStatus.WON),
        Contact(company_id=demo.id, full_name="C", normalized_name="c", status=PipelineStatus.MEETING, is_demo=True),
    ])
    await db.commit()

    s = (await client.get("/api/analytics/summary")).json()
    assert (s["companies"], s["prospects"], s["meetings"], s["won"]) == (1, 2, 1, 1)
    assert s["pipeline_value"] == 5000
    assert {f["stage"]: f["count"] for f in s["funnel"]}["MEETING"] == 1


async def test_cancel_exception_type_exists():
    assert issubclass(JobCancelled, Exception)
