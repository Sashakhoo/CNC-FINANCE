from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, SoftDeleteMixin, TimestampMixin
from app.models.contact import JSONVariant


class Campaign(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "campaigns"

    name: Mapped[str] = mapped_column(String(200))
    program_id: Mapped[int | None] = mapped_column(ForeignKey("training_programs.id", ondelete="SET NULL"))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    target_filters: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    start_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", server_default="DRAFT")


class CampaignContact(Base):
    __tablename__ = "campaign_contacts"

    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), primary_key=True, index=True)
    added_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutreachDraft(IdMixin, TimestampMixin, Base):
    __tablename__ = "outreach_drafts"

    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"))
    channel: Mapped[str] = mapped_column(String(20))
    tone: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSONVariant, default=list)
    generated_by: Mapped[str] = mapped_column(String(20), default="TEMPLATE")
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", server_default="DRAFT")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
