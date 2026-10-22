"""Email-discovery provider contract and the normalized models every provider returns."""
from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from app.models.base import EmailDiscoveryMethod, EmailType, Provenance
from app.providers.base import ProviderError, ProviderInfo, ProviderStatus


class EmailOptedOut(ProviderError):
    """The person asked the provider not to process their data (Hunter HTTP 451).
    Callers should add the address/person to the suppression list."""
    error_type = "OPTED_OUT"


class DiscoveredEmail(BaseModel):
    email: str
    first_name: str | None = None
    last_name: str | None = None
    position: str | None = None
    department: str | None = None
    seniority: str | None = None
    linkedin_url: str | None = None
    phone: str | None = None
    confidence: float = Field(ge=0, le=1)
    email_type: EmailType
    sources: list[str] = Field(default_factory=list)
    provider: str
    discovery_method: EmailDiscoveryMethod = EmailDiscoveryMethod.PROVIDER
    # ENRICHED = the provider found it published somewhere; INFERRED = the
    # provider guessed it from a pattern (must stay unverified until checked).
    provenance: Provenance = Provenance.ENRICHED
    provider_verification_status: str | None = None


class DomainSearchResult(BaseModel):
    domain: str
    pattern: str | None = None          # provider-reported, e.g. "{first}.{last}"
    accept_all: bool | None = None
    organization: str | None = None
    emails: list[DiscoveredEmail] = Field(default_factory=list)
    total_results: int | None = None


class EmailDiscoveryProvider(Protocol):
    info: ProviderInfo

    def is_configured(self) -> bool: ...
    async def test_connection(self) -> ProviderStatus: ...
    async def domain_search(self, domain: str, limit: int = 10) -> DomainSearchResult: ...
    async def find_email(self, first_name: str, last_name: str, domain: str) -> DiscoveredEmail | None: ...
