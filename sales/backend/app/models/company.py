from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, Provenance, SoftDeleteMixin, SourceType, TimestampMixin, str_enum


class Company(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "companies"

    legal_name: Mapped[str] = mapped_column(String(300))
    display_name: Mapped[str] = mapped_column(String(300))
    # Legal suffixes (Sdn Bhd, Pte Ltd…) stripped, lowercased — for dedup only.
    normalized_name: Mapped[str] = mapped_column(String(300), index=True)
    website: Mapped[str | None] = mapped_column(String(500))
    domain: Mapped[str | None] = mapped_column(String(255), index=True)
    domain_confidence: Mapped[float | None] = mapped_column(Float)
    domain_status: Mapped[str] = mapped_column(String(20), default="UNRESOLVED", server_default="UNRESOLVED")
    industry: Mapped[str | None] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    employee_estimate: Mapped[int | None] = mapped_column(Integer)
    employee_estimate_source: Mapped[str | None] = mapped_column(String(300))
    phone: Mapped[str | None] = mapped_column(String(60))
    general_email: Mapped[str | None] = mapped_column(String(320))
    deal_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    locations: Mapped[list["CompanyLocation"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    sources: Mapped[list["CompanySource"]] = relationship(back_populates="company", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_companies_normalized_name_trgm", "normalized_name", postgresql_using="gin",
              postgresql_ops={"normalized_name": "gin_trgm_ops"}),
        Index("uq_companies_domain_live", "domain", unique=True,
              postgresql_where="domain IS NOT NULL AND deleted_at IS NULL"),
    )


class CompanyLocation(IdMixin, TimestampMixin, Base):
    __tablename__ = "company_locations"

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(120), index=True)
    state: Mapped[str | None] = mapped_column(String(120), index=True)
    postcode: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str] = mapped_column(String(80), default="Malaysia", server_default="Malaysia")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    source_id: Mapped[int | None] = mapped_column(ForeignKey("company_sources.id", ondelete="SET NULL"))

    company: Mapped[Company] = relationship(back_populates="locations")


class CompanySource(IdMixin, Base):
    """Field-level evidence: one row per (field, value, where it came from)."""
    __tablename__ = "company_sources"

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
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

    company: Mapped[Company] = relationship(back_populates="sources")


class CompanySignal(IdMixin, Base):
    __tablename__ = "company_signals"

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    signal_type: Mapped[str] = mapped_column(String(60), index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    evidence_text: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    source_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provenance: Mapped[Provenance] = mapped_column(str_enum(Provenance, "provenance"))
    confidence: Mapped[float | None] = mapped_column(Float)
    crawl_page_id: Mapped[int | None] = mapped_column(ForeignKey("crawl_pages.id", ondelete="SET NULL"))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FinanceInvoice(IdMixin, Base):
    """Invoices raised in CNC Finance when a deal here was marked WON."""
    __tablename__ = "finance_invoices"

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    finance_invoice_id: Mapped[int] = mapped_column(BigInteger)
    invoice_number: Mapped[str] = mapped_column(String(40))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
