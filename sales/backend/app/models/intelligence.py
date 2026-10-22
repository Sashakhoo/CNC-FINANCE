from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, Priority, TimestampMixin, str_enum
from app.models.contact import JSONVariant


class TrainingProgram(IdMixin, TimestampMixin, Base):
    __tablename__ = "training_programs"

    code: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    target_departments: Mapped[list] = mapped_column(JSONVariant, default=list)
    keywords: Mapped[list] = mapped_column(JSONVariant, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class TrainingOpportunity(IdMixin, Base):
    """TRAINING MATCH — how strongly a company fits a programme. Evidence is a
    list of {source_url, quote} drawn from stored pages, never generated."""
    __tablename__ = "training_opportunities"

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("training_programs.id", ondelete="CASCADE"), index=True)
    match_score: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    target_department: Mapped[str | None] = mapped_column(String(60))
    recommended_decision_maker: Mapped[str | None] = mapped_column(String(120))
    evidence: Mapped[list] = mapped_column(JSONVariant, default=list)
    alternative_program_ids: Mapped[list] = mapped_column(JSONVariant, default=list)
    method: Mapped[str] = mapped_column(String(20), default="RULES")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", index=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContactConfidenceScore(IdMixin, Base):
    """CONTACT CONFIDENCE — how sure we are the contact data is correct."""
    __tablename__ = "contact_confidence_scores"

    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    score: Mapped[int] = mapped_column(Integer)
    breakdown: Mapped[list] = mapped_column(JSONVariant, default=list)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", index=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LeadScore(IdMixin, Base):
    """LEAD SCORE — how valuable this prospect is."""
    __tablename__ = "lead_scores"

    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    score: Mapped[int] = mapped_column(Integer, index=True)
    priority: Mapped[Priority] = mapped_column(str_enum(Priority, "priority"), index=True)
    breakdown: Mapped[list] = mapped_column(JSONVariant, default=list)
    settings_version: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", index=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
