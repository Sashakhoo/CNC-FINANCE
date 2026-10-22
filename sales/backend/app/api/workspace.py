from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics import live_companies
from app.api.common import activity_out, iso, note_out, paging
from app.core.auth import CurrentUser, get_current_user, require_admin, require_editor
from app.core.db import get_session
from app.models import (Activity, AuditLog, Company, CompanyLocation, Contact, Note, Setting, Suppression,
                        TrainingProgram, User)
from app.models.base import (Department, PipelineStatus, Priority, Provenance, Role, Seniority, SourceType,
                             VerificationStatus)
from app.services.audit import audit
from app.services.crm import ACTIVITY_TYPES, log_activity, suppress
from app.services.defaults import LEAD_SCORING

router = APIRouter(prefix="/api", tags=["workspace"])


# --- notes ------------------------------------------------------------------

class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)
    contact_id: int | None = None
    company_id: int | None = None

    @model_validator(mode="after")
    def _target(self):
        if not self.contact_id and not self.company_id:
            raise ValueError("A note needs a contact_id or company_id")
        return self


async def _resolve_target(db: AsyncSession, contact_id: int | None, company_id: int | None) -> tuple[int | None, int]:
    if contact_id:
        c = await db.get(Contact, contact_id)
        if not c or c.deleted_at:
            raise HTTPException(404, "Contact not found")
        return c.id, c.company_id
    co = await db.get(Company, company_id)
    if not co or co.deleted_at:
        raise HTTPException(404, "Company not found")
    return None, co.id


@router.post("/notes", status_code=201)
async def create_note(body: NoteIn, user: CurrentUser = Depends(require_editor), db: AsyncSession = Depends(get_session)):
    contact_id, company_id = await _resolve_target(db, body.contact_id, body.company_id)
    n = Note(body=body.body.strip(), contact_id=contact_id, company_id=company_id, user_id=user.id)
    db.add(n)
    await db.commit()
    return note_out(n, user.username)


class NotePatch(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)


async def _own_note(db: AsyncSession, note_id: int, user: CurrentUser) -> Note:
    n = await db.get(Note, note_id)
    if not n or n.deleted_at:
        raise HTTPException(404, "Note not found")
    if n.user_id != user.id and user.role != Role.ADMIN:
        raise HTTPException(403, "You can only change your own notes")
    return n


@router.patch("/notes/{note_id}")
async def edit_note(note_id: int, body: NotePatch, user: CurrentUser = Depends(require_editor),
                    db: AsyncSession = Depends(get_session)):
    n = await _own_note(db, note_id, user)
    n.body = body.body.strip()
    await db.commit()
    return note_out(n, user.username)


@router.delete("/notes/{note_id}")
async def delete_note(note_id: int, request: Request, user: CurrentUser = Depends(require_editor),
                      db: AsyncSession = Depends(get_session)):
    n = await _own_note(db, note_id, user)
    n.deleted_at = datetime.now(timezone.utc)
    audit(db, user.id, "note_deleted", "note", n.id, {}, request)
    await db.commit()
    return {"ok": True}


# --- activities ---------------------------------------------------------------

class ActivityIn(BaseModel):
    activity_type: str = Field(pattern="^(note|call|meeting|email|linkedin|other)$")
    text: str = Field(min_length=1, max_length=2000)
    contact_id: int | None = None
    company_id: int | None = None

    @model_validator(mode="after")
    def _target(self):
        if not self.contact_id and not self.company_id:
            raise ValueError("An activity needs a contact_id or company_id")
        return self


@router.post("/activities", status_code=201)
async def log_manual_activity(body: ActivityIn, user: CurrentUser = Depends(require_editor),
                              db: AsyncSession = Depends(get_session)):
    assert body.activity_type in ACTIVITY_TYPES
    contact_id, company_id = await _resolve_target(db, body.contact_id, body.company_id)
    a = log_activity(db, body.activity_type, body.text.strip(), contact_id=contact_id, company_id=company_id,
                     user_id=user.id, meta={"manual": True})
    if contact_id and body.activity_type in ("call", "meeting", "email", "linkedin"):
        c = await db.get(Contact, contact_id)
        c.last_contacted_at = datetime.now(timezone.utc)
    await db.commit()
    return activity_out(a, user.username)


@router.get("/activities")
async def list_activities(contact_id: int | None = None, company_id: int | None = None,
                          pg: tuple[int, int] = Depends(paging), _: CurrentUser = Depends(get_current_user),
                          db: AsyncSession = Depends(get_session)):
    page, size = pg
    q = select(Activity, User.finance_username).outerjoin(User, User.id == Activity.user_id)
    if contact_id:
        q = q.where(Activity.contact_id == contact_id)
    if company_id:
        q = q.where(Activity.company_id == company_id)
    total = await db.scalar(select(func.count()).select_from(q.subquery()))
    rows = (await db.execute(q.order_by(Activity.created_at.desc()).offset((page - 1) * size).limit(size))).all()
    return {"items": [activity_out(a, u) for a, u in rows], "total": total, "page": page, "page_size": size}


# --- metadata for filters / forms ------------------------------------------------

@router.get("/meta")
async def meta(_: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    programs = (await db.execute(select(TrainingProgram).order_by(TrainingProgram.name))).scalars().all()
    industries = sorted({i for i in (await db.execute(select(distinct(Company.industry)).where(live_companies()))).scalars() if i}
                        | set(LEAD_SCORING["target_industries"]))
    states = sorted({s for s in (await db.execute(select(distinct(CompanyLocation.state)))).scalars() if s}
                    | set(LEAD_SCORING["locations"]))
    return {
        "statuses": [s.value for s in PipelineStatus], "departments": [d.value for d in Department],
        "seniorities": [s.value for s in Seniority], "email_statuses": [v.value for v in VerificationStatus],
        "priorities": [p.value for p in Priority], "provenances": [p.value for p in Provenance],
        "source_types": [s.value for s in SourceType], "industries": industries, "states": states,
        "programs": [{"id": p.id, "code": p.code, "name": p.name, "enabled": p.enabled} for p in programs],
    }


# --- settings -------------------------------------------------------------------

@router.get("/settings")
async def get_settings_all(_: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    rows = (await db.execute(select(Setting))).scalars().all()
    return {s.key: {"value": s.value, "version": s.version, "updated_at": iso(s.updated_at)} for s in rows}


class GeneralSettings(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    sender_name: str = Field(default="", max_length=120)
    sender_title: str = Field(default="", max_length=120)
    currency: str = Field(default="RM", max_length=8)


class RetentionSettings(BaseModel):
    activity_days: int = Field(ge=30, le=3650)
    crawl_page_days: int = Field(ge=30, le=3650)
    rejected_contact_days: int = Field(ge=30, le=3650)


VALIDATORS: dict[str, type[BaseModel]] = {"general": GeneralSettings, "retention": RetentionSettings}


async def put_setting(db: AsyncSession, key: str, value: dict, user: CurrentUser, request: Request) -> dict:
    row = await db.get(Setting, key)
    old = row.value if row else None
    if row:
        row.value, row.version, row.updated_by_id = value, row.version + 1, user.id
    else:
        row = Setting(key=key, value=value, version=1, updated_by_id=user.id)
        db.add(row)
    audit(db, user.id, "settings_changed", "setting", key, {"from": old, "to": value}, request)
    await db.commit()
    return {"key": key, "value": row.value, "version": row.version}


@router.put("/settings/{key}")
async def update_setting(key: str, body: dict, request: Request, user: CurrentUser = Depends(require_admin),
                         db: AsyncSession = Depends(get_session)):
    model = VALIDATORS.get(key)
    if model is None:
        from app.services import scoring
        if key == "lead_scoring":
            model = scoring.LeadWeights
        elif key == "contact_confidence":
            model = scoring.ConfidenceWeights
        else:
            raise HTTPException(404, "Unknown setting")
    try:
        value = model.model_validate(body).model_dump()
    except ValueError as e:
        raise HTTPException(422, str(e))
    return await put_setting(db, key, value, user, request)


# --- training programmes ----------------------------------------------------------

class ProgramPatch(BaseModel):
    enabled: bool | None = None
    description: str | None = Field(default=None, max_length=2000)
    keywords: list[str] | None = Field(default=None, max_length=60)


@router.get("/programs")
async def list_programs(_: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    rows = (await db.execute(select(TrainingProgram).order_by(TrainingProgram.name))).scalars().all()
    return [{"id": p.id, "code": p.code, "name": p.name, "description": p.description, "enabled": p.enabled,
             "keywords": p.keywords, "target_departments": p.target_departments} for p in rows]


@router.patch("/programs/{program_id}")
async def update_program(program_id: int, body: ProgramPatch, request: Request, user: CurrentUser = Depends(require_admin),
                         db: AsyncSession = Depends(get_session)):
    p = await db.get(TrainingProgram, program_id)
    if not p:
        raise HTTPException(404, "Programme not found")
    data = body.model_dump(exclude_unset=True)
    if "keywords" in data and data["keywords"] is not None:
        data["keywords"] = sorted({k.strip().lower() for k in data["keywords"] if k.strip()})
    for k, v in data.items():
        if v is not None:
            setattr(p, k, v)
    audit(db, user.id, "program_changed", "training_program", p.id, data, request)
    await db.commit()
    return {"ok": True}


# --- suppression (Do Not Contact) ---------------------------------------------------

class SuppressionIn(BaseModel):
    kind: str = Field(pattern="^(EMAIL|DOMAIN)$")
    value: str = Field(min_length=3, max_length=320)
    reason: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _shape(self):
        if self.kind == "EMAIL":
            EmailIn.model_validate({"email": self.value})
        elif "." not in self.value or "@" in self.value or "/" in self.value:
            raise ValueError("Enter a bare domain like example.com")
        return self


class EmailIn(BaseModel):
    email: EmailStr


@router.get("/suppression")
async def list_suppression(pg: tuple[int, int] = Depends(paging), _: CurrentUser = Depends(get_current_user),
                           db: AsyncSession = Depends(get_session)):
    page, size = pg
    total = await db.scalar(select(func.count()).select_from(Suppression))
    rows = (await db.execute(select(Suppression, User.finance_username).outerjoin(User, User.id == Suppression.created_by_id)
                             .order_by(Suppression.created_at.desc()).offset((page - 1) * size).limit(size))).all()
    return {"items": [{"id": s.id, "kind": s.kind, "value": s.value, "reason": s.reason, "user": u,
                       "created_at": iso(s.created_at)} for s, u in rows], "total": total, "page": page, "page_size": size}


@router.post("/suppression", status_code=201)
async def add_suppression(body: SuppressionIn, request: Request, user: CurrentUser = Depends(require_editor),
                          db: AsyncSession = Depends(get_session)):
    await suppress(db, body.kind, body.value, body.reason, user.id)
    audit(db, user.id, "suppression_added", "suppression", body.value.lower(), {"kind": body.kind}, request)
    await db.commit()
    return {"ok": True}


@router.delete("/suppression/{suppression_id}")
async def remove_suppression(suppression_id: int, request: Request, user: CurrentUser = Depends(require_admin),
                             db: AsyncSession = Depends(get_session)):
    s = await db.get(Suppression, suppression_id)
    if not s:
        raise HTTPException(404, "Entry not found")
    if s.kind == "CONTACT":
        raise HTTPException(409, "Take the contact off Do Not Contact from the contact's page instead")
    await db.delete(s)
    audit(db, user.id, "suppression_removed", "suppression", s.value, {"kind": s.kind}, request)
    await db.commit()
    return {"ok": True}


# --- audit log --------------------------------------------------------------------

@router.get("/audit")
async def list_audit(action: str | None = Query(None, max_length=60), entity_type: str | None = Query(None, max_length=40),
                     pg: tuple[int, int] = Depends(paging), _: CurrentUser = Depends(require_admin),
                     db: AsyncSession = Depends(get_session)):
    page, size = pg
    q = select(AuditLog, User.finance_username).outerjoin(User, User.id == AuditLog.user_id)
    if action:
        q = q.where(AuditLog.action == action)
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    total = await db.scalar(select(func.count()).select_from(q.subquery()))
    rows = (await db.execute(q.order_by(AuditLog.created_at.desc()).offset((page - 1) * size).limit(size))).all()
    actions = (await db.execute(select(distinct(AuditLog.action)).order_by(AuditLog.action))).scalars().all()
    return {"items": [{"id": a.id, "action": a.action, "entity_type": a.entity_type, "entity_id": a.entity_id,
                       "meta": a.meta, "ip": a.ip, "user": u, "created_at": iso(a.created_at)} for a, u in rows],
            "total": total, "page": page, "page_size": size, "actions": actions}
