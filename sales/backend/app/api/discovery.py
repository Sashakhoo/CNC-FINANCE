from datetime import datetime, timezone
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics import live_companies
from app.api.common import iso, paging, signal_out
from app.core.security import rate_limit
from app.core.auth import CurrentUser, get_current_user, require_admin, require_editor
from app.core.config import get_settings
from app.core.db import get_session, sessionmaker
from app.models import (Company, CompanySignal, CrawlJob, Job, ProspectSearch, ProviderUsage, TrainingOpportunity,
                        TrainingProgram, User)
from app.models.base import JobStatus
from app.providers.base import ProviderKind, ProviderState
from app.providers.registry import build_provider, describe_providers
from app.services.audit import audit
from app.services.jobs import create_job
from app.services.normalize import normalize_website
from app.services.runtime import DbCache, DbRecorder, usage_stats

router = APIRouter(prefix="/api", tags=["discovery"])


def enqueue(task: str, job_id: int) -> str | None:
    from app.worker import celery_app
    return celery_app.send_task(task, args=[job_id]).id


# --- searches ------------------------------------------------------------------

class Criteria(BaseModel):
    country: str = Field(default="Malaysia", max_length=60)
    state: str | None = Field(default=None, max_length=60)
    city: str | None = Field(default=None, max_length=80)
    industries: list[str] = Field(default_factory=list, max_length=20)
    size_min: int | None = Field(default=None, ge=0, le=1_000_000)
    size_max: int | None = Field(default=None, ge=0, le=1_000_000)
    departments: list[str] = Field(default_factory=list, max_length=10)
    titles: list[str] = Field(default_factory=list, max_length=40)
    min_lead_score: int = Field(default=0, ge=0, le=100)
    max_companies: int = Field(default=20, ge=1, le=500)
    seed_websites: list[str] = Field(default_factory=list, max_length=100)
    find_profiles: bool = True
    schedule: Literal["weekly"] | None = None

    @field_validator("seed_websites")
    @classmethod
    def _sites(cls, v: list[str]) -> list[str]:
        out = []
        for s in v:
            s = s.strip()
            if s:
                try:
                    out.append(normalize_website(s))
                except ValueError:
                    raise ValueError(f"Not a website: {s[:80]}")
        return out


class SearchIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    criteria: Criteria


def _job_out(j: Job, username: str | None = None) -> dict:
    duration = None
    if j.started_at:
        duration = round(((j.finished_at or datetime.now(timezone.utc)) - j.started_at).total_seconds())
    return {"id": j.id, "name": j.name, "job_type": j.job_type, "status": j.status.value, "search_id": j.search_id,
            "provider": j.provider, "params": j.params, "counters": j.counters, "progress": j.progress, "stage": j.stage,
            "records_processed": j.records_processed, "records_created": j.records_created,
            "warnings": j.warnings, "errors": j.errors, "warning_count": len(j.warnings or []),
            "error_count": len(j.errors or []), "cancel_requested": j.cancel_requested,
            "started_at": iso(j.started_at), "finished_at": iso(j.finished_at), "created_at": iso(j.created_at),
            "duration_seconds": duration, "user": username}


def _search_out(s: ProspectSearch, last: Job | None) -> dict:
    return {"id": s.id, "name": s.name, "criteria": s.criteria, "created_at": iso(s.created_at),
            "last_job": _job_out(last) if last else None}


@router.post("/searches", status_code=201)
async def create_search(body: SearchIn, request: Request, user: CurrentUser = Depends(require_editor),
                        db: AsyncSession = Depends(get_session)):
    s = ProspectSearch(name=body.name.strip(), criteria=body.criteria.model_dump(), created_by_id=user.id)
    db.add(s)
    await db.flush()
    audit(db, user.id, "search_created", "search", s.id, {"name": s.name}, request)
    await db.commit()
    return _search_out(s, None)


@router.get("/searches")
async def list_searches(_: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    rows = (await db.execute(select(ProspectSearch).where(ProspectSearch.deleted_at.is_(None))
                             .order_by(ProspectSearch.created_at.desc()).limit(100))).scalars().all()
    out = []
    for s in rows:
        last = (await db.execute(select(Job).where(Job.search_id == s.id).order_by(Job.id.desc()).limit(1))).scalar_one_or_none()
        out.append(_search_out(s, last))
    return out


@router.patch("/searches/{search_id}")
async def update_search(search_id: int, body: SearchIn, request: Request, user: CurrentUser = Depends(require_editor),
                        db: AsyncSession = Depends(get_session)):
    s = await db.get(ProspectSearch, search_id)
    if not s or s.deleted_at:
        raise HTTPException(404, "Search not found")
    s.name, s.criteria = body.name.strip(), body.criteria.model_dump()
    audit(db, user.id, "search_updated", "search", s.id, {"name": s.name}, request)
    await db.commit()
    return _search_out(s, None)


@router.delete("/searches/{search_id}")
async def delete_search(search_id: int, request: Request, user: CurrentUser = Depends(require_editor),
                        db: AsyncSession = Depends(get_session)):
    s = await db.get(ProspectSearch, search_id)
    if not s or s.deleted_at:
        raise HTTPException(404, "Search not found")
    s.deleted_at = datetime.now(timezone.utc)
    audit(db, user.id, "search_deleted", "search", s.id, {"name": s.name}, request)
    await db.commit()
    return {"ok": True}


@router.post("/searches/{search_id}/run", status_code=202, dependencies=[Depends(rate_limit("discovery_run", 10))])
async def run_search(search_id: int, request: Request, user: CurrentUser = Depends(require_editor),
                     db: AsyncSession = Depends(get_session)):
    s = await db.get(ProspectSearch, search_id)
    if not s or s.deleted_at:
        raise HTTPException(404, "Search not found")
    running = await db.scalar(select(Job.id).where(Job.search_id == s.id, Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING])))
    if running:
        raise HTTPException(409, {"message": "This search is already running", "job_id": running})
    job = await create_job(db, "discovery", s.name, search_id=s.id, user_id=user.id, params={"criteria": s.criteria})
    audit(db, user.id, "discovery_started", "job", job.id, {"search": s.name}, request)
    await db.commit()
    job.celery_task_id = enqueue("discovery.run", job.id)
    await db.commit()
    return _job_out(job, user.username)


# --- company enrichment -------------------------------------------------------------

class EnrichIn(BaseModel):
    steps: dict[str, bool] = Field(default_factory=dict)
    titles: list[str] = Field(default_factory=list, max_length=40)
    departments: list[str] = Field(default_factory=list, max_length=10)


ACTION_STEPS = {
    "reenrich": {},
    "find_contacts": {"training": False},
    "analyze": {"crawl": False, "people": False, "profiles": False, "emails": False, "verify": False},
}


@router.post("/companies/{company_id}/enrich", status_code=202, dependencies=[Depends(rate_limit("enrich", 30))])
async def enrich(company_id: int, request: Request, action: Literal["reenrich", "find_contacts", "analyze"] = "reenrich",
                 user: CurrentUser = Depends(require_editor), db: AsyncSession = Depends(get_session)):
    c = await db.get(Company, company_id)
    if not c or c.deleted_at:
        raise HTTPException(404, "Company not found")
    if action != "analyze" and not c.website:
        raise HTTPException(422, "Add the company's website first")
    label = {"reenrich": "Re-enrich", "find_contacts": "Find contacts", "analyze": "Analyze opportunity"}[action]
    job = await create_job(db, "enrich", f"{label}: {c.display_name}", user_id=user.id,
                           params={"company_id": c.id, "action": action, "steps": ACTION_STEPS[action]})
    audit(db, user.id, "enrich_started", "company", c.id, {"action": action}, request)
    await db.commit()
    job.celery_task_id = enqueue("discovery.enrich", job.id)
    await db.commit()
    return _job_out(job, user.username)


# --- jobs ---------------------------------------------------------------------------

@router.get("/jobs")
async def list_jobs(status: JobStatus | None = None, job_type: str | None = Query(None, max_length=40),
                    pg: tuple[int, int] = Depends(paging), _: CurrentUser = Depends(get_current_user),
                    db: AsyncSession = Depends(get_session)):
    page, size = pg
    q = select(Job, User.finance_username).outerjoin(User, User.id == Job.created_by_id)
    if status:
        q = q.where(Job.status == status)
    if job_type:
        q = q.where(Job.job_type == job_type)
    total = await db.scalar(select(func.count()).select_from(q.subquery()))
    rows = (await db.execute(q.order_by(Job.id.desc()).offset((page - 1) * size).limit(size))).all()
    items = []
    for j, u in rows:
        d = _job_out(j, u)
        d.pop("warnings"), d.pop("errors")
        items.append(d)
    return {"items": items, "total": total, "page": page, "page_size": size}


@router.get("/jobs/{job_id}")
async def get_job(job_id: int, _: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    j = await db.get(Job, job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    user = await db.get(User, j.created_by_id) if j.created_by_id else None
    crawls = (await db.execute(select(CrawlJob, Company.display_name).join(Company, Company.id == CrawlJob.company_id)
                               .where(CrawlJob.job_id == j.id).order_by(CrawlJob.id))).all()
    usage = (await db.execute(select(ProviderUsage.provider, func.count(), func.count().filter(ProviderUsage.success.is_(False)))
                              .where(ProviderUsage.job_id == j.id).group_by(ProviderUsage.provider))).all()
    out = _job_out(j, user.finance_username if user else None)
    out["crawls"] = [{"company_id": c.company_id, "company": name, "domain": c.domain, "status": c.status.value,
                      "pages_fetched": c.pages_fetched, "pages_skipped": c.pages_skipped, "robots_allowed": c.robots_allowed,
                      "error": c.error} for c, name in crawls]
    out["provider_calls"] = [{"provider": p, "calls": n, "errors": e} for p, n, e in usage]
    return out


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: int, request: Request, user: CurrentUser = Depends(require_editor),
                     db: AsyncSession = Depends(get_session)):
    j = await db.get(Job, job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    if j.status not in (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.PAUSED):
        raise HTTPException(409, "Only queued or running jobs can be cancelled")
    j.cancel_requested = True
    if j.status == JobStatus.QUEUED:
        j.status, j.finished_at = JobStatus.CANCELLED, datetime.now(timezone.utc)
    audit(db, user.id, "job_cancelled", "job", j.id, {}, request)
    await db.commit()
    return _job_out(j)


@router.post("/jobs/{job_id}/retry", status_code=202, dependencies=[Depends(rate_limit("job_retry", 20))])
async def retry_job(job_id: int, request: Request, user: CurrentUser = Depends(require_editor),
                    db: AsyncSession = Depends(get_session)):
    j = await db.get(Job, job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    if j.status not in (JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.COMPLETED):
        raise HTTPException(409, "Only finished jobs can be retried")
    task = {"discovery": "discovery.run", "enrich": "discovery.enrich", "reverify": "discovery.reverify"}.get(j.job_type)
    if not task:
        raise HTTPException(422, "This job type can't be retried")
    new = await create_job(db, j.job_type, f"Retry: {j.name}"[:200], search_id=j.search_id, user_id=user.id, params=j.params)
    audit(db, user.id, "job_retried", "job", new.id, {"from": j.id}, request)
    await db.commit()
    new.celery_task_id = enqueue(task, new.id)
    await db.commit()
    return _job_out(new, user.username)


# --- providers ---------------------------------------------------------------------

@router.get("/providers")
async def providers(_: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    return {"providers": describe_providers(get_settings()), "usage": await usage_stats(db)}


@router.post("/providers/{kind}/test", dependencies=[Depends(rate_limit("provider_test", 10))])
async def test_provider(kind: ProviderKind, request: Request, user: CurrentUser = Depends(require_admin),
                        db: AsyncSession = Depends(get_session)):
    async with httpx.AsyncClient(timeout=20.0) as client:
        p = build_provider(kind, get_settings(), client, DbRecorder(sessionmaker()), DbCache(sessionmaker()))
        if p is None:
            result = {"state": ProviderState.NOT_CONFIGURED.value, "message": "No provider/key configured for this kind",
                      "http_status": None}
        else:
            st = await p.test_connection()
            result = {"state": st.state.value, "message": st.message, "http_status": st.http_status,
                      "provider": p.info.name}
    audit(db, user.id, "provider_tested", "provider", kind.value, {"state": result["state"]}, request)
    await db.commit()
    return result


# --- signals & opportunities -------------------------------------------------------

@router.get("/signals")
async def list_signals(signal_type: str | None = Query(None, max_length=60), company_id: int | None = None,
                       pg: tuple[int, int] = Depends(paging), _: CurrentUser = Depends(get_current_user),
                       db: AsyncSession = Depends(get_session)):
    page, size = pg
    q = select(CompanySignal, Company.id, Company.display_name).join(Company, Company.id == CompanySignal.company_id).where(live_companies())
    if signal_type:
        q = q.where(CompanySignal.signal_type == signal_type)
    if company_id:
        q = q.where(CompanySignal.company_id == company_id)
    total = await db.scalar(select(func.count()).select_from(q.subquery()))
    rows = (await db.execute(q.order_by(CompanySignal.discovered_at.desc()).offset((page - 1) * size).limit(size))).all()
    types = (await db.execute(select(CompanySignal.signal_type, func.count()).group_by(CompanySignal.signal_type)
                              .order_by(func.count().desc()))).all()
    return {"items": [{**signal_out(s), "company": {"id": cid, "name": name}} for s, cid, name in rows],
            "total": total, "page": page, "page_size": size, "types": [{"type": t, "count": n} for t, n in types]}


@router.get("/opportunities")
async def list_opportunities(program: str | None = Query(None, max_length=120), min_match: int = Query(0, ge=0, le=100),
                             pg: tuple[int, int] = Depends(paging), _: CurrentUser = Depends(get_current_user),
                             db: AsyncSession = Depends(get_session)):
    page, size = pg
    q = (select(TrainingOpportunity, TrainingProgram.name, Company.id, Company.display_name, Company.industry)
         .join(TrainingProgram, TrainingProgram.id == TrainingOpportunity.program_id)
         .join(Company, Company.id == TrainingOpportunity.company_id)
         .where(live_companies(), TrainingOpportunity.is_current.is_(True), TrainingOpportunity.match_score >= min_match))
    if program:
        q = q.where(TrainingProgram.name == program)
    total = await db.scalar(select(func.count()).select_from(q.subquery()))
    rows = (await db.execute(q.order_by(TrainingOpportunity.match_score.desc()).offset((page - 1) * size).limit(size))).all()
    return {"items": [{"id": o.id, "program": pname, "match_score": o.match_score, "reason": o.reason,
                       "target_department": o.target_department, "recommended_decision_maker": o.recommended_decision_maker,
                       "evidence": o.evidence, "method": o.method, "computed_at": iso(o.computed_at),
                       "company": {"id": cid, "name": cname, "industry": ind}} for o, pname, cid, cname, ind in rows],
            "total": total, "page": page, "page_size": size}
