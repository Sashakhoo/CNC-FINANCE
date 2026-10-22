import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def str_enum(e: type[enum.Enum], name: str) -> Enum:
    """Stored as VARCHAR + CHECK so adding a value later is a simple migration."""
    return Enum(e, name=name, native_enum=False, length=40, values_callable=lambda x: [m.value for m in x],
                validate_strings=True)


class IdMixin:
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now(), nullable=False)


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class Provenance(str, enum.Enum):
    DISCOVERED = "DISCOVERED"
    INFERRED = "INFERRED"
    ENRICHED = "ENRICHED"
    VERIFIED = "VERIFIED"
    USER_PROVIDED = "USER_PROVIDED"


class SourceType(str, enum.Enum):
    COMPANY_WEBSITE = "COMPANY_WEBSITE"
    SEARCH_PROVIDER = "SEARCH_PROVIDER"
    DIRECTORY = "DIRECTORY"
    BUSINESS_DATA_PROVIDER = "BUSINESS_DATA_PROVIDER"
    EMAIL_PROVIDER = "EMAIL_PROVIDER"
    VERIFICATION_PROVIDER = "VERIFICATION_PROVIDER"
    USER_IMPORT = "USER_IMPORT"
    USER_ENTRY = "USER_ENTRY"
    LLM = "LLM"
    DEMO = "DEMO"


class PipelineStatus(str, enum.Enum):
    NEW = "NEW"
    REVIEW = "REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CONTACTED = "CONTACTED"
    REPLIED = "REPLIED"
    MEETING = "MEETING"
    PROPOSAL = "PROPOSAL"
    WON = "WON"
    LOST = "LOST"
    DO_NOT_CONTACT = "DO_NOT_CONTACT"


class Department(str, enum.Enum):
    HR = "HR"
    LD = "L&D"
    IT = "IT"
    ENGINEERING = "Engineering"
    OPERATIONS = "Operations"
    MANAGEMENT = "Management"
    OTHER = "Other"


class Seniority(str, enum.Enum):
    INDIVIDUAL = "Individual"
    MANAGER = "Manager"
    HEAD = "Head"
    DIRECTOR = "Director"
    VP = "VP"
    C_LEVEL = "C-Level"
    OWNER = "Owner"


class EmailDiscoveryMethod(str, enum.Enum):
    PUBLIC_WEBSITE = "PUBLIC_WEBSITE"
    PROVIDER = "PROVIDER"
    EMAIL_PATTERN = "EMAIL_PATTERN"
    USER_IMPORT = "USER_IMPORT"
    USER_ENTRY = "USER_ENTRY"


class EmailType(str, enum.Enum):
    PERSONAL_BUSINESS = "PERSONAL_BUSINESS"
    ROLE = "ROLE"
    GENERIC = "GENERIC"


class VerificationStatus(str, enum.Enum):
    VERIFIED = "VERIFIED"
    LIKELY = "LIKELY"
    UNKNOWN = "UNKNOWN"
    INVALID = "INVALID"
    RISKY = "RISKY"
    UNVERIFIED = "UNVERIFIED"


class JobStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Role(str, enum.Enum):
    ADMIN = "ADMIN"
    SALES = "SALES"
    VIEWER = "VIEWER"


class Priority(str, enum.Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


def ts_col(nullable: bool = True) -> Mapped[datetime | None]:
    return mapped_column(DateTime(timezone=True), nullable=nullable)
