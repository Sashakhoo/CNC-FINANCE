from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JobStatus, SoftDeleteMixin, TimestampMixin, str_enum
from app.models.contact import JSONVariant


class ProspectSearch(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "prospect_searches"

    name: Mapped[str] = mapped_column(String(200))
    criteria: Mapped[dict] = mapped_column(JSONVariant)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Job(IdMixin, TimestampMixin, Base):
    """Every background run (discovery, crawl, verification, import, export…).
    Counters are written by the worker as it goes — the UI only reads them."""
    __tablename__ = "jobs"

    job_type: Mapped[str] = mapped_column(String(60), index=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[JobStatus] = mapped_column(str_enum(JobStatus, "job_status"), default=JobStatus.QUEUED,
                                              server_default="QUEUED", index=True)
    search_id: Mapped[int | None] = mapped_column(ForeignKey("prospect_searches.id", ondelete="SET NULL"))
    provider: Mapped[str | None] = mapped_column(String(80))
    celery_task_id: Mapped[str | None] = mapped_column(String(80))
    params: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    counters: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    progress: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    stage: Mapped[str | None] = mapped_column(String(80))
    records_processed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    records_created: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    warnings: Mapped[list] = mapped_column(JSONVariant, default=list)
    errors: Mapped[list] = mapped_column(JSONVariant, default=list)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class CrawlJob(IdMixin, Base):
    """One company website crawl inside a Job."""
    __tablename__ = "crawl_jobs"

    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    domain: Mapped[str] = mapped_column(String(255))
    status: Mapped[JobStatus] = mapped_column(str_enum(JobStatus, "job_status"), default=JobStatus.QUEUED)
    robots_allowed: Mapped[bool | None] = mapped_column(Boolean)
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0)
    pages_skipped: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CrawlPage(IdMixin, Base):
    __tablename__ = "crawl_pages"

    crawl_job_id: Mapped[int | None] = mapped_column(ForeignKey("crawl_jobs.id", ondelete="SET NULL"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(1000))
    canonical_url: Mapped[str | None] = mapped_column(String(1000))
    page_type: Mapped[str | None] = mapped_column(String(40))
    status_code: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(120))
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    title: Mapped[str | None] = mapped_column(String(500))
    text: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EnrichmentJob(IdMixin, Base):
    """One enrichment step for one company/contact (provider call, LLM analysis…)."""
    __tablename__ = "enrichment_jobs"

    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    step: Mapped[str] = mapped_column(String(60))
    provider: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[JobStatus] = mapped_column(str_enum(JobStatus, "job_status"), default=JobStatus.QUEUED)
    result: Mapped[dict | None] = mapped_column(JSONVariant)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
