import csv
import io
import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import contacts as contacts_api
from app.core.security import rate_limit
from app.core.auth import CurrentUser, get_current_user, require_admin, require_editor
from app.core.db import get_session
from app.models import Company, Contact, ContactEmail, DuplicateCandidate, Job
from app.models.base import (Department, JobStatus, PipelineStatus, Priority, Seniority, SourceType, VerificationStatus)
from app.services.audit import audit
from app.services.crm import suppress
from app.services.dataops import (FIELDS, ImportFileError, erase_contact, import_rows, merge_companies, merge_contacts,
                                  parse_table, run_retention, suggest_mapping)
from app.services.scores import load_weights, rescore_company, rescore_contact

router = APIRouter(prefix="/api", tags=["data"])
EXPORT_MAX = 10_000


async def _read(file: UploadFile) -> tuple[str, bytes]:
    data = await file.read(5_000_001)
    return (file.filename or "upload").rsplit("/", 1)[-1][:120], data


# --- import ------------------------------------------------------------------------

@router.post("/import/preview", dependencies=[Depends(rate_limit("import", 20))])
async def import_preview(file: UploadFile = File(...), _: CurrentUser = Depends(require_editor)):
    name, data = await _read(file)
    try:
        headers, rows = parse_table(name, data)
    except ImportFileError as e:
        raise HTTPException(422, str(e))
    return {"filename": name, "headers": headers, "rows": rows[:20], "total": len(rows),
            "mapping": suggest_mapping(headers), "fields": list(FIELDS)}


@router.post("/import/commit", dependencies=[Depends(rate_limit("import", 20))])
async def import_commit(request: Request, file: UploadFile = File(...), mapping: str = Form(...),
                        user: CurrentUser = Depends(require_editor), db: AsyncSession = Depends(get_session)):
    name, data = await _read(file)
    try:
        headers, rows = parse_table(name, data)
        m = json.loads(mapping)
    except ImportFileError as e:
        raise HTTPException(422, str(e))
    except json.JSONDecodeError:
        raise HTTPException(422, "Invalid column mapping")
    if not isinstance(m, dict) or any(k not in FIELDS or (v is not None and v not in headers) for k, v in m.items()):
        raise HTTPException(422, "Column mapping refers to unknown fields or columns")
    if not (m.get("company") or m.get("website") or m.get("domain")):
        raise HTTPException(422, "Map at least a company name or website column")
    started = datetime.now(timezone.utc)
    job = Job(job_type="import", name=f"Import: {name}", status=JobStatus.RUNNING, started_at=started, created_by_id=user.id,
              params={"filename": name, "rows": len(rows), "mapping": m}, counters={}, warnings=[], errors=[])
    db.add(job)
    await db.flush()
    res = await import_rows(db, headers, rows, m, name, user.id)
    weights = await load_weights(db)
    for cid in set(res.contact_ids):
        await rescore_contact(db, cid, weights)
    job.status, job.finished_at, job.progress = JobStatus.COMPLETED, datetime.now(timezone.utc), 100
    job.records_processed, job.records_created = len(rows), res.companies_created + res.contacts_created
    job.counters = {"companies_created": res.companies_created, "companies_updated": res.companies_updated,
                    "contacts_created": res.contacts_created, "contacts_updated": res.contacts_updated,
                    "emails_added": res.emails_added, "duplicates_flagged": res.duplicates_flagged, "skipped": len(res.skipped)}
    job.warnings = [{"at": started.isoformat(), "message": f"Row {s['row']}: {s['reason']}"} for s in res.skipped[:200]]
    audit(db, user.id, "import", "job", job.id, {"filename": name, **job.counters}, request)
    await db.commit()
    return {"job_id": job.id, **job.counters, "skipped_rows": res.skipped[:200]}


# --- export ------------------------------------------------------------------------

def _safe(v) -> str:
    """Neutralise spreadsheet formulas (CSV/Excel injection)."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


COLUMNS = [("Name", "full_name"), ("Title", "original_title"), ("Normalized title", "normalized_title"),
           ("Department", "department"), ("Seniority", "seniority"), ("Company", lambda p: p["company"]["legal_name"]),
           ("Industry", lambda p: p["company"]["industry"]), ("State", lambda p: (p["location"] or {}).get("state")),
           ("City", lambda p: (p["location"] or {}).get("city")), ("Email", "email"), ("Email status", "email_status"),
           ("Email provenance", "email_provenance"), ("Professional profile", "profile_url"), ("Status", "status"),
           ("Lead score", "lead_score"), ("Priority", "priority"), ("Contact confidence", "contact_confidence"),
           ("Training programme", "training_program"), ("Training match", "match_score"), ("Last contacted", "last_contacted_at")]


@router.get("/export/prospects", dependencies=[Depends(rate_limit("export", 10))])
async def export_prospects(
        request: Request, format: Literal["csv", "xlsx"] = "csv", q: str | None = Query(None, max_length=200),
        status: list[PipelineStatus] = Query(default=[]), department: list[Department] = Query(default=[]),
        seniority: list[Seniority] = Query(default=[]), industry: list[str] = Query(default=[]), state: list[str] = Query(default=[]),
        email_status: list[VerificationStatus] = Query(default=[]), priority: list[Priority] = Query(default=[]),
        program: list[str] = Query(default=[]), min_lead_score: int | None = Query(None, ge=0, le=100),
        min_confidence: int | None = Query(None, ge=0, le=100), min_match: int | None = Query(None, ge=0, le=100),
        size_min: int | None = None, size_max: int | None = None, source_type: list[SourceType] = Query(default=[]),
        campaign_id: int | None = None, user: CurrentUser = Depends(require_editor), db: AsyncSession = Depends(get_session)):
    items, page = [], 1
    while len(items) < EXPORT_MAX:
        chunk = await contacts_api.list_prospects(
            q=q, status=status, department=department, seniority=seniority, industry=industry, state=state,
            email_status=email_status, priority=priority, program=program, min_lead_score=min_lead_score,
            min_confidence=min_confidence, min_match=min_match, size_min=size_min, size_max=size_max, source_type=source_type,
            company_id=None, campaign_id=campaign_id, has_email=None, hide_suppressed=True, sort="lead_score", desc=True,
            pg=(page, 200), _=user, db=db)
        items += chunk["items"]
        if page * 200 >= chunk["total"]:
            break
        page += 1
    items = [p for p in items if not p["suppressed"]][:EXPORT_MAX]
    rows = [[_safe(col(p) if callable(col) else p.get(col)) for _, col in COLUMNS] for p in items]
    filters = {k: v for k, v in request.query_params.multi_items() if k != "format"}
    audit(db, user.id, "export", "prospects", None, {"format": format, "rows": len(rows), "filters": filters}, request)
    await db.commit()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([h for h, _ in COLUMNS])
        w.writerows(rows)
        return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="prospects-{stamp}.csv"'})
    from openpyxl import Workbook
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Prospects")
    ws.append([h for h, _ in COLUMNS])
    for r in rows:
        ws.append(r)
    out = io.BytesIO()
    wb.save(out)
    return Response(out.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="prospects-{stamp}.xlsx"'})


# --- duplicates & merge -----------------------------------------------------------------

async def _summary(db: AsyncSession, kind: str, rid: int) -> dict | None:
    if kind == "company":
        c = await db.get(Company, rid)
        if not c or c.deleted_at:
            return None
        n = len((await db.execute(select(Contact.id).where(Contact.company_id == c.id, Contact.deleted_at.is_(None)))).all())
        return {"id": c.id, "name": c.legal_name, "detail": c.domain or c.website or "No website", "contacts": n,
                "created_at": c.created_at.isoformat()}
    c = await db.get(Contact, rid)
    if not c or c.deleted_at:
        return None
    co = await db.get(Company, c.company_id)
    emails = (await db.execute(select(ContactEmail.email).where(ContactEmail.contact_id == c.id))).scalars().all()
    return {"id": c.id, "name": c.full_name, "detail": f"{c.original_title or 'Title unknown'} · {co.display_name}",
            "emails": list(emails), "status": c.status.value, "created_at": c.created_at.isoformat()}


@router.get("/duplicates")
async def list_duplicates(entity_type: Literal["company", "contact"] | None = None, status: str = "OPEN",
                          _: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    q = select(DuplicateCandidate).where(DuplicateCandidate.status == status)
    if entity_type:
        q = q.where(DuplicateCandidate.entity_type == entity_type)
    out = []
    for d in (await db.execute(q.order_by(DuplicateCandidate.similarity.desc()).limit(200))).scalars():
        left, right = await _summary(db, d.entity_type, d.left_id), await _summary(db, d.entity_type, d.right_id)
        if left and right:
            out.append({"id": d.id, "entity_type": d.entity_type, "similarity": d.similarity, "reasons": d.reasons,
                        "left": left, "right": right})
    return out


async def _dup(db: AsyncSession, dup_id: int) -> DuplicateCandidate:
    d = await db.get(DuplicateCandidate, dup_id)
    if not d or d.status != "OPEN":
        raise HTTPException(404, "Duplicate pair not found or already resolved")
    return d


@router.post("/duplicates/{dup_id}/dismiss")
async def dismiss_duplicate(dup_id: int, request: Request, user: CurrentUser = Depends(require_editor),
                            db: AsyncSession = Depends(get_session)):
    d = await _dup(db, dup_id)
    d.status, d.resolved_by_id = "DISMISSED", user.id
    audit(db, user.id, "duplicate_dismissed", d.entity_type, f"{d.left_id},{d.right_id}", {}, request)
    await db.commit()
    return {"ok": True}


class MergeIn(BaseModel):
    keep: Literal["left", "right"]


@router.post("/duplicates/{dup_id}/merge")
async def merge_duplicate(dup_id: int, body: MergeIn, request: Request, user: CurrentUser = Depends(require_editor),
                          db: AsyncSession = Depends(get_session)):
    d = await _dup(db, dup_id)
    keep_id, other_id = (d.left_id, d.right_id) if body.keep == "left" else (d.right_id, d.left_id)
    if d.entity_type == "company":
        keep, other = await db.get(Company, keep_id), await db.get(Company, other_id)
        if not keep or not other or keep.deleted_at or other.deleted_at:
            raise HTTPException(409, "One of these companies no longer exists")
        await merge_companies(db, keep, other)
    else:
        keep, other = await db.get(Contact, keep_id), await db.get(Contact, other_id)
        if not keep or not other or keep.deleted_at or other.deleted_at:
            raise HTTPException(409, "One of these contacts no longer exists")
        await merge_contacts(db, keep, other)
    d.status, d.resolved_by_id = "MERGED", user.id
    audit(db, user.id, "merge", d.entity_type, keep_id, {"merged_from": other_id}, request)
    await db.commit()
    if d.entity_type == "company":
        await rescore_company(db, keep_id)
    else:
        await rescore_contact(db, keep_id)
    await db.commit()
    return {"ok": True, "kept": keep_id, "removed": other_id}


# --- erasure & retention ------------------------------------------------------------------

@router.delete("/contacts/{contact_id}/erase")
async def erase(contact_id: int, request: Request, user: CurrentUser = Depends(require_admin),
                db: AsyncSession = Depends(get_session)):
    c = await db.get(Contact, contact_id)
    if not c:
        raise HTTPException(404, "Contact not found")
    n = await erase_contact(db, c, user.id)
    audit(db, user.id, "contact_erased", "contact", contact_id, {"emails_suppressed": n}, request)
    await db.commit()
    return {"ok": True, "emails_suppressed": n}


@router.delete("/companies/{company_id}/erase")
async def erase_company(company_id: int, request: Request, suppress_domain: bool = True,
                        user: CurrentUser = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    co = await db.get(Company, company_id)
    if not co:
        raise HTTPException(404, "Company not found")
    total = 0
    for c in (await db.execute(select(Contact).where(Contact.company_id == co.id))).scalars().all():
        total += await erase_contact(db, c, user.id)
    if suppress_domain and co.domain:
        await suppress(db, "DOMAIN", co.domain, "Erasure request", user.id)
    from sqlalchemy import delete as sql_delete
    await db.execute(sql_delete(DuplicateCandidate).where(DuplicateCandidate.entity_type == "company",
                                                          (DuplicateCandidate.left_id == co.id) | (DuplicateCandidate.right_id == co.id)))
    await db.delete(co)
    audit(db, user.id, "company_erased", "company", company_id, {"emails_suppressed": total, "domain_suppressed": suppress_domain}, request)
    await db.commit()
    return {"ok": True}


@router.get("/retention/preview")
async def retention_preview(_: CurrentUser = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    return await run_retention(db, dry_run=True)


@router.post("/retention/run")
async def retention_run(request: Request, user: CurrentUser = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    r = await run_retention(db, dry_run=False)
    audit(db, user.id, "retention_run", "settings", "retention", r, request)
    await db.commit()
    return r
