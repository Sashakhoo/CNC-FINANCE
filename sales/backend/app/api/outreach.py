"""Outreach drafts and campaigns. Nothing is ever sent from here (V1):
drafts are generated, edited and approved; 'mark sent' records that a person
sent it themselves."""
from datetime import date, datetime, timezone
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics import live_contacts
from app.api.common import iso
from app.core.security import rate_limit
from app.core.auth import CurrentUser, get_current_user, require_editor
from app.core.config import get_settings
from app.core.db import get_session, sessionmaker
from app.models import (Campaign, CampaignContact, Company, CompanySignal, Contact, ContactEmail, FinanceInvoice,
                        OutreachDraft, Setting, TrainingOpportunity, TrainingProgram, User)
from app.models.base import PipelineStatus
from app.providers.base import ProviderError, ProviderKind
from app.providers.registry import build_provider
from app.services.audit import audit
from app.services.crm import log_activity, suppressed_reasons
from app.services.outreach import (OutreachContact, OutreachOpportunity, Sender, generate_draft, generate_draft_llm)
from app.services.runtime import DbCache, DbRecorder, make_guard
from app.services.scores import rescore_contact
from app.services.training import SignalFact

router = APIRouter(prefix="/api", tags=["outreach"])

EARLY = {PipelineStatus.NEW, PipelineStatus.REVIEW, PipelineStatus.APPROVED}
ACTIVE = [PipelineStatus.CONTACTED, PipelineStatus.REPLIED, PipelineStatus.MEETING, PipelineStatus.PROPOSAL]


def draft_out(d: OutreachDraft) -> dict:
    return {"id": d.id, "contact_id": d.contact_id, "campaign_id": d.campaign_id, "channel": d.channel, "tone": d.tone,
            "subject": d.subject, "body": d.body, "evidence": d.evidence, "generated_by": d.generated_by,
            "status": d.status, "created_at": iso(d.created_at), "updated_at": iso(d.updated_at)}


async def _contact(db: AsyncSession, contact_id: int) -> Contact:
    c = await db.get(Contact, contact_id)
    if not c or c.deleted_at or c.is_demo != get_settings().demo_mode:
        raise HTTPException(404, "Contact not found")
    return c


async def _blocked(db: AsyncSession, c: Contact) -> list[str]:
    emails = (await db.execute(select(ContactEmail.email).where(ContactEmail.contact_id == c.id))).scalars().all()
    reasons = await suppressed_reasons(db, contact_id=c.id, company_id=c.company_id, emails=list(emails))
    if c.status == PipelineStatus.DO_NOT_CONTACT and not reasons:
        reasons = [f"CONTACT:{c.id}"]
    return reasons


# --- drafts -------------------------------------------------------------------------

class DraftIn(BaseModel):
    channel: Literal["EMAIL", "LINKEDIN", "FOLLOWUP"] = "EMAIL"
    tone: Literal["Professional", "Friendly", "Concise", "Consultative"] = "Professional"
    campaign_id: int | None = None
    use_ai: bool = False


@router.post("/contacts/{contact_id}/drafts", status_code=201, dependencies=[Depends(rate_limit("draft", 30))])
async def create_draft(contact_id: int, body: DraftIn, user: CurrentUser = Depends(require_editor),
                       db: AsyncSession = Depends(get_session)):
    c = await _contact(db, contact_id)
    if await _blocked(db, c):
        raise HTTPException(409, "This contact is on the Do Not Contact list")
    company = await db.get(Company, c.company_id)
    opp_row = (await db.execute(
        select(TrainingOpportunity, TrainingProgram.name).join(TrainingProgram, TrainingProgram.id == TrainingOpportunity.program_id)
        .where(TrainingOpportunity.company_id == company.id, TrainingOpportunity.is_current.is_(True))
        .order_by(TrainingOpportunity.match_score.desc()).limit(1))).first()
    if body.campaign_id:
        camp = await db.get(Campaign, body.campaign_id)
        if camp and camp.program_id:
            pref = (await db.execute(
                select(TrainingOpportunity, TrainingProgram.name).join(TrainingProgram, TrainingProgram.id == TrainingOpportunity.program_id)
                .where(TrainingOpportunity.company_id == company.id, TrainingOpportunity.is_current.is_(True),
                       TrainingOpportunity.program_id == camp.program_id))).first()
            opp_row = pref or opp_row
    opp = OutreachOpportunity(program_name=opp_row[1], reason=opp_row[0].reason, evidence=opp_row[0].evidence) if opp_row else None
    signals = [SignalFact(signal_type=s.signal_type, title=s.title, quote=s.evidence_text or "", source_url=s.source_url)
               for s in (await db.execute(select(CompanySignal).where(CompanySignal.company_id == company.id)
                                          .order_by(CompanySignal.confidence.desc().nulls_last()).limit(5))).scalars()]
    general = (await db.get(Setting, "general"))
    g = general.value if general else {}
    sender = Sender(name=g.get("sender_name") or user.username, title=g.get("sender_title") or "Corporate Training",
                    company=g.get("company_name") or "Codencode Academy")
    contact = OutreachContact(name=c.full_name, original_title=c.original_title, company_name=company.display_name,
                              industry=company.industry)
    draft = None
    if body.use_ai:
        async with httpx.AsyncClient(timeout=60.0) as client:
            ai = build_provider(ProviderKind.AI, get_settings(), client, DbRecorder(sessionmaker()), DbCache(sessionmaker()))
            if ai is None:
                raise HTTPException(422, "No LLM provider is configured — generate a template draft instead")
            try:
                draft = await make_guard().call(ai.info, lambda: generate_draft_llm(ai, contact, opp, signals, sender,
                                                                                    body.channel, body.tone))
            except ProviderError as e:
                raise HTTPException(502, f"AI provider error ({e.error_type}) — try a template draft")
    if draft is None:
        draft = generate_draft(contact, opp, signals, sender, body.channel, body.tone)
    d = OutreachDraft(contact_id=c.id, campaign_id=body.campaign_id, channel=body.channel, tone=body.tone,
                      subject=draft.subject[:300], body=draft.body, evidence=draft.evidence_used,
                      generated_by=draft.generated_by, created_by_id=user.id)
    db.add(d)
    log_activity(db, "drafted", f"{body.channel.title()} draft created ({body.tone}, {draft.generated_by.lower()})",
                 contact_id=c.id, company_id=c.company_id, user_id=user.id)
    await db.commit()
    await db.refresh(d)
    out = draft_out(d)
    out["note"] = draft.note
    return out


@router.get("/contacts/{contact_id}/drafts")
async def list_drafts(contact_id: int, _: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    await _contact(db, contact_id)
    rows = (await db.execute(select(OutreachDraft).where(OutreachDraft.contact_id == contact_id)
                             .order_by(OutreachDraft.created_at.desc()))).scalars().all()
    return [draft_out(d) for d in rows]


class DraftPatch(BaseModel):
    subject: str | None = Field(default=None, max_length=300)
    body: str | None = Field(default=None, min_length=1, max_length=5000)


async def _draft(db: AsyncSession, draft_id: int) -> OutreachDraft:
    d = await db.get(OutreachDraft, draft_id)
    if not d:
        raise HTTPException(404, "Draft not found")
    await _contact(db, d.contact_id)
    return d


@router.patch("/drafts/{draft_id}")
async def edit_draft(draft_id: int, body: DraftPatch, user: CurrentUser = Depends(require_editor),
                     db: AsyncSession = Depends(get_session)):
    d = await _draft(db, draft_id)
    if d.status == "SENT":
        raise HTTPException(409, "A sent draft can't be edited")
    if body.subject is not None:
        d.subject = body.subject
    if body.body is not None:
        d.body = body.body
    d.status = "DRAFT"
    await db.commit()
    await db.refresh(d)
    return draft_out(d)


@router.post("/drafts/{draft_id}/approve")
async def approve_draft(draft_id: int, request: Request, user: CurrentUser = Depends(require_editor),
                        db: AsyncSession = Depends(get_session)):
    d = await _draft(db, draft_id)
    c = await _contact(db, d.contact_id)
    if await _blocked(db, c):
        raise HTTPException(409, "This contact is on the Do Not Contact list")
    d.status = "APPROVED"
    audit(db, user.id, "draft_approved", "draft", d.id, {"contact_id": c.id}, request)
    await db.commit()
    await db.refresh(d)
    return draft_out(d)


@router.post("/drafts/{draft_id}/mark-sent")
async def mark_sent(draft_id: int, request: Request, user: CurrentUser = Depends(require_editor),
                    db: AsyncSession = Depends(get_session)):
    """The user sent this themselves (email client / LinkedIn). Records it; sends nothing."""
    d = await _draft(db, draft_id)
    c = await _contact(db, d.contact_id)
    if await _blocked(db, c):
        raise HTTPException(409, "This contact is on the Do Not Contact list")
    if d.status != "APPROVED":
        raise HTTPException(409, "Approve the draft before marking it sent")
    now = datetime.now(timezone.utc)
    d.status = "SENT"
    c.last_contacted_at = now
    if c.status in EARLY:
        old = c.status
        c.status, c.status_changed_at = PipelineStatus.CONTACTED, now
        log_activity(db, "status", "Status changed to CONTACTED", contact_id=c.id, company_id=c.company_id,
                     user_id=user.id, meta={"from": old.value, "to": "CONTACTED"})
    kind = "linkedin" if d.channel == "LINKEDIN" else "email"
    log_activity(db, kind, f"{d.channel.title()} sent by {user.username}" + (f" — “{d.subject}”" if d.subject else ""),
                 contact_id=c.id, company_id=c.company_id, user_id=user.id, meta={"draft_id": d.id})
    audit(db, user.id, "draft_marked_sent", "draft", d.id, {"contact_id": c.id}, request)
    await db.commit()
    await rescore_contact(db, c.id)
    await db.commit()
    await db.refresh(d)
    return draft_out(d)


@router.delete("/drafts/{draft_id}")
async def delete_draft(draft_id: int, user: CurrentUser = Depends(require_editor), db: AsyncSession = Depends(get_session)):
    d = await _draft(db, draft_id)
    await db.delete(d)
    await db.commit()
    return {"ok": True}


# --- campaigns -------------------------------------------------------------------------

class CampaignIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    program_id: int | None = None
    description: str = Field(default="", max_length=5000)
    owner_id: int | None = None
    target_filters: dict = Field(default_factory=dict)
    start_date: date | None = None
    status: Literal["DRAFT", "ACTIVE", "PAUSED", "COMPLETED"] = "DRAFT"


async def _metrics(db: AsyncSession, campaign_ids: list[int]) -> dict[int, dict]:
    out = {cid: {"prospects": 0, **{s.value.lower(): 0 for s in PipelineStatus}, "pipeline_value": 0.0, "won_value": 0.0}
           for cid in campaign_ids}
    if not campaign_ids:
        return out
    rows = (await db.execute(select(CampaignContact.campaign_id, Contact.status, func.count())
                             .join(Contact, Contact.id == CampaignContact.contact_id)
                             .where(CampaignContact.campaign_id.in_(campaign_ids), live_contacts())
                             .group_by(CampaignContact.campaign_id, Contact.status))).all()
    for cid, status, n in rows:
        out[cid][status.value.lower()] += n
        out[cid]["prospects"] += n
    for cid in campaign_ids:
        active_cos = select(distinct(Contact.company_id)).join(CampaignContact, CampaignContact.contact_id == Contact.id).where(
            CampaignContact.campaign_id == cid, live_contacts(), Contact.status.in_(ACTIVE))
        out[cid]["pipeline_value"] = float(await db.scalar(select(func.coalesce(func.sum(Company.deal_value), 0))
                                                           .where(Company.id.in_(active_cos))) or 0)
        won_cos = select(distinct(Contact.company_id)).join(CampaignContact, CampaignContact.contact_id == Contact.id).where(
            CampaignContact.campaign_id == cid, live_contacts(), Contact.status == PipelineStatus.WON)
        out[cid]["won_value"] = float(await db.scalar(select(func.coalesce(func.sum(FinanceInvoice.amount), 0))
                                                      .where(FinanceInvoice.company_id.in_(won_cos))) or 0)
        m = out[cid]
        reached = m["contacted"] + m["replied"] + m["meeting"] + m["proposal"] + m["won"] + m["lost"]
        m["response_rate"] = round((m["replied"] + m["meeting"] + m["proposal"] + m["won"]) / reached * 100, 1) if reached else None
    return out


def campaign_out(c: Campaign, program: str | None, owner: str | None, metrics: dict) -> dict:
    return {"id": c.id, "name": c.name, "program_id": c.program_id, "program": program, "description": c.description,
            "owner_id": c.owner_id, "owner": owner, "target_filters": c.target_filters, "start_date": c.start_date.isoformat() if c.start_date else None,
            "status": c.status, "created_at": iso(c.created_at), "metrics": metrics}


async def _campaign(db: AsyncSession, campaign_id: int) -> Campaign:
    c = await db.get(Campaign, campaign_id)
    if not c or c.deleted_at:
        raise HTTPException(404, "Campaign not found")
    return c


@router.get("/campaigns")
async def list_campaigns(_: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    rows = (await db.execute(select(Campaign, TrainingProgram.name, User.finance_username)
                             .outerjoin(TrainingProgram, TrainingProgram.id == Campaign.program_id)
                             .outerjoin(User, User.id == Campaign.owner_id)
                             .where(Campaign.deleted_at.is_(None)).order_by(Campaign.created_at.desc()))).all()
    metrics = await _metrics(db, [c.id for c, _, _ in rows])
    return [campaign_out(c, p, o, metrics[c.id]) for c, p, o in rows]


@router.post("/campaigns", status_code=201)
async def create_campaign(body: CampaignIn, request: Request, user: CurrentUser = Depends(require_editor),
                          db: AsyncSession = Depends(get_session)):
    c = Campaign(**body.model_dump(exclude={"owner_id"}), owner_id=body.owner_id or user.id)
    db.add(c)
    await db.flush()
    audit(db, user.id, "campaign_created", "campaign", c.id, {"name": c.name}, request)
    await db.commit()
    return await get_campaign(c.id, user, db)


@router.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: int, _: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    c = await _campaign(db, campaign_id)
    program = (await db.get(TrainingProgram, c.program_id)).name if c.program_id else None
    owner = (await db.get(User, c.owner_id)).finance_username if c.owner_id else None
    return campaign_out(c, program, owner, (await _metrics(db, [c.id]))[c.id])


@router.patch("/campaigns/{campaign_id}")
async def update_campaign(campaign_id: int, body: CampaignIn, request: Request, user: CurrentUser = Depends(require_editor),
                          db: AsyncSession = Depends(get_session)):
    c = await _campaign(db, campaign_id)
    for k, v in body.model_dump().items():
        if k == "owner_id" and v is None:
            continue
        setattr(c, k, v)
    audit(db, user.id, "campaign_updated", "campaign", c.id, {"name": c.name, "status": c.status}, request)
    await db.commit()
    return await get_campaign(c.id, user, db)


@router.delete("/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: int, request: Request, user: CurrentUser = Depends(require_editor),
                          db: AsyncSession = Depends(get_session)):
    c = await _campaign(db, campaign_id)
    c.deleted_at = datetime.now(timezone.utc)
    audit(db, user.id, "campaign_deleted", "campaign", c.id, {"name": c.name}, request)
    await db.commit()
    return {"ok": True}


class MembersIn(BaseModel):
    contact_ids: list[int] = Field(min_length=1, max_length=1000)


@router.post("/campaigns/{campaign_id}/contacts")
async def add_members(campaign_id: int, body: MembersIn, request: Request, user: CurrentUser = Depends(require_editor),
                      db: AsyncSession = Depends(get_session)):
    camp = await _campaign(db, campaign_id)
    existing = set((await db.execute(select(CampaignContact.contact_id).where(CampaignContact.campaign_id == camp.id))).scalars())
    contacts = (await db.execute(select(Contact).where(Contact.id.in_(body.contact_ids), live_contacts()))).scalars().all()
    added, skipped = [], []
    for c in contacts:
        if c.id in existing:
            skipped.append({"id": c.id, "reason": "Already in campaign"})
            continue
        if await _blocked(db, c):
            skipped.append({"id": c.id, "reason": "Do Not Contact"})
            continue
        db.add(CampaignContact(campaign_id=camp.id, contact_id=c.id, added_by_id=user.id))
        log_activity(db, "campaign", f"Added to campaign “{camp.name}”", contact_id=c.id, company_id=c.company_id, user_id=user.id)
        added.append(c.id)
    missing = sorted(set(body.contact_ids) - {c.id for c in contacts})
    skipped += [{"id": i, "reason": "Not found"} for i in missing]
    audit(db, user.id, "campaign_members_added", "campaign", camp.id, {"added": len(added), "skipped": len(skipped)}, request)
    await db.commit()
    return {"added": len(added), "skipped": skipped}


@router.post("/campaigns/{campaign_id}/contacts/remove")
async def remove_members(campaign_id: int, body: MembersIn, user: CurrentUser = Depends(require_editor),
                         db: AsyncSession = Depends(get_session)):
    camp = await _campaign(db, campaign_id)
    await db.execute(delete(CampaignContact).where(CampaignContact.campaign_id == camp.id,
                                                   CampaignContact.contact_id.in_(body.contact_ids)))
    await db.commit()
    return {"ok": True}

