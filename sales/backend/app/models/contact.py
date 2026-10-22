from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (Base, Department, EmailDiscoveryMethod, EmailType, IdMixin, PipelineStatus, Provenance,
                             Seniority, SoftDeleteMixin, SourceType, TimestampMixin, VerificationStatus, str_enum)

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class Contact(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "contacts"

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(200), index=True)
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    original_title: Mapped[str | None] = mapped_column(String(200))
    normalized_title: Mapped[str | None] = mapped_column(String(120))
    department: Mapped[Department | None] = mapped_column(str_enum(Department, "department"), index=True)
    seniority: Mapped[Seniority | None] = mapped_column(str_enum(Seniority, "seniority"))
    phone: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[PipelineStatus] = mapped_column(str_enum(PipelineStatus, "pipeline_status"),
                                                   default=PipelineStatus.REVIEW, server_default="REVIEW", index=True)
    status_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)

    emails: Mapped[list["ContactEmail"]] = relationship(back_populates="contact", cascade="all, delete-orphan")
    profiles: Mapped[list["ContactProfile"]] = relationship(back_populates="contact", cascade="all, delete-orphan")
    sources: Mapped[list["ContactSource"]] = relationship(back_populates="contact", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_contacts_normalized_name_trgm", "normalized_name", postgresql_using="gin",
              postgresql_ops={"normalized_name": "gin_trgm_ops"}),
    )


class ContactSource(IdMixin, Base):
    """Evidence that a person exists / holds a title (every contact needs ≥1)."""
    __tablename__ = "contact_sources"

    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    field_name: Mapped[str] = mapped_column(String(60))
    value: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[Provenance] = mapped_column(str_enum(Provenance, "provenance"))
    source_type: Mapped[SourceType] = mapped_column(str_enum(SourceType, "source_type"))
    provider: Mapped[str | None] = mapped_column(String(80))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    evidence_text: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    crawl_page_id: Mapped[int | None] = mapped_column(ForeignKey("crawl_pages.id", ondelete="SET NULL"))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    contact: Mapped[Contact] = relationship(back_populates="sources")


class ContactEmail(IdMixin, TimestampMixin, Base):
    __tablename__ = "contact_emails"

    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    email_type: Mapped[EmailType] = mapped_column(str_enum(EmailType, "email_type"))
    discovery_method: Mapped[EmailDiscoveryMethod] = mapped_column(str_enum(EmailDiscoveryMethod, "email_discovery_method"))
    provenance: Mapped[Provenance] = mapped_column(str_enum(Provenance, "provenance"))
    source: Mapped[str | None] = mapped_column(String(120))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    confidence: Mapped[float | None] = mapped_column(Float)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        str_enum(VerificationStatus, "verification_status"), default=VerificationStatus.UNVERIFIED,
        server_default="UNVERIFIED", index=True)
    verification_provider: Mapped[str | None] = mapped_column(String(80))
    verification_confidence: Mapped[float | None] = mapped_column(Float)
    verification_meta: Mapped[dict | None] = mapped_column(JSONVariant)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    contact: Mapped[Contact] = relationship(back_populates="emails")

    __table_args__ = (UniqueConstraint("contact_id", "email", name="uq_contact_emails_contact_email"),)


class ContactProfile(IdMixin, Base):
    """A professional profile URL found via a permitted source — stored as a reference only."""
    __tablename__ = "contact_profiles"

    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(40))
    url: Mapped[str] = mapped_column(String(1000), index=True)
    source_type: Mapped[SourceType] = mapped_column(str_enum(SourceType, "source_type"))
    provider: Mapped[str | None] = mapped_column(String(80))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    confidence: Mapped[float | None] = mapped_column(Float)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    contact: Mapped[Contact] = relationship(back_populates="profiles")

    __table_args__ = (UniqueConstraint("contact_id", "url", name="uq_contact_profiles_contact_url"),)
