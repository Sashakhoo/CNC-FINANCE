from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, Role, TimestampMixin, str_enum
from app.models.contact import JSONVariant


class User(IdMixin, TimestampMixin, Base):
    """CRM-side profile for a CNC Finance account. Passwords live in Finance;
    this row holds the CRM role and is created on first sign-in."""
    __tablename__ = "users"

    finance_username: Mapped[str] = mapped_column(String(80), unique=True)
    finance_role: Mapped[str] = mapped_column(String(40))
    role: Mapped[Role] = mapped_column(str_enum(Role, "role"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Activity(IdMixin, Base):
    __tablename__ = "activities"

    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    activity_type: Mapped[str] = mapped_column(String(40), index=True)
    text: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Note(IdMixin, TimestampMixin, Base):
    __tablename__ = "notes"

    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    body: Mapped[str] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(IdMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(300))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class ProviderUsage(IdMixin, Base):
    __tablename__ = "provider_usage"

    provider: Mapped[str] = mapped_column(String(80), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    operation: Mapped[str] = mapped_column(String(80))
    success: Mapped[bool] = mapped_column(default=True)
    http_status: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_type: Mapped[str | None] = mapped_column(String(80))
    cost_estimate: Mapped[float | None] = mapped_column(Float)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class ProviderCache(Base):
    __tablename__ = "provider_cache"

    cache_key: Mapped[str] = mapped_column(String(300), primary_key=True)
    provider: Mapped[str] = mapped_column(String(80), index=True)
    value: Mapped[dict] = mapped_column(JSONVariant)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(IdMixin, Base):
    __tablename__ = "audit_logs"

    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(60))
    meta: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Suppression(IdMixin, Base):
    """DO NOT CONTACT list. kind: EMAIL | DOMAIN | CONTACT | COMPANY."""
    __tablename__ = "suppression_list"

    kind: Mapped[str] = mapped_column(String(20))
    value: Mapped[str] = mapped_column(String(320))
    reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("kind", "value", name="uq_suppression_kind_value"),)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONVariant)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DuplicateCandidate(IdMixin, Base):
    """Possible duplicates flagged for human review — never merged automatically."""
    __tablename__ = "duplicate_candidates"

    entity_type: Mapped[str] = mapped_column(String(20))
    left_id: Mapped[int] = mapped_column(Integer, index=True)
    right_id: Mapped[int] = mapped_column(Integer, index=True)
    similarity: Mapped[float] = mapped_column(Float)
    reasons: Mapped[list] = mapped_column(JSONVariant, default=list)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", server_default="OPEN", index=True)
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("entity_type", "left_id", "right_id", name="uq_duplicate_pair"),)
