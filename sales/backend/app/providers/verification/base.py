"""Email-verification provider contract.

Status mapping to app.models.base.VerificationStatus:

| Provider   | Provider value                     | Ours      | confidence            |
|------------|------------------------------------|-----------|-----------------------|
| Hunter     | valid                              | VERIFIED  | score/100             |
| Hunter     | accept_all, score >= 80            | LIKELY    | score/100             |
| Hunter     | accept_all, score < 80             | RISKY     | score/100             |
| Hunter     | webmail (not a business address)   | RISKY     | score/100             |
| Hunter     | disposable, invalid                | INVALID   | score/100             |
| Hunter     | unknown / anything else            | UNKNOWN   | score/100             |
| ZeroBounce | valid                              | VERIFIED  | 0.95                  |
| ZeroBounce | catch-all                          | RISKY     | 0.40                  |
| ZeroBounce | abuse                              | RISKY     | 0.40                  |
| ZeroBounce | invalid, spamtrap, do_not_mail     | INVALID   | 0.0                   |
| ZeroBounce | unknown / anything else            | UNKNOWN   | 0.20                  |
| Reoon      | safe                               | VERIFIED  | 0.95                  |
| Reoon      | role_account                       | RISKY     | 0.50                  |
| Reoon      | catch_all                          | RISKY     | 0.40                  |
| Reoon      | inbox_full                         | RISKY     | 0.30                  |
| Reoon      | invalid, disabled, disposable, spamtrap | INVALID | 0.0               |
| Reoon      | unknown / anything else            | UNKNOWN   | 0.20                  |
| (any)      | fails local syntax check           | INVALID   | 0.0 (no API call)     |

Verification never sends an email to the address (spec §20)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from pydantic import BaseModel, Field

from app.models.base import VerificationStatus
from app.providers.base import ProviderInfo, ProviderStatus

VERIFIED_TTL = 30 * 24 * 3600
UNKNOWN_TTL = 24 * 3600   # inconclusive results are worth re-checking sooner


class VerificationResult(BaseModel):
    email: str
    status: VerificationStatus
    confidence: float = Field(ge=0, le=1)
    provider: str
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    meta: dict = Field(default_factory=dict)   # non-secret provider fields only
    cached: bool = False


def cache_ttl(status: VerificationStatus) -> int:
    return UNKNOWN_TTL if status == VerificationStatus.UNKNOWN else VERIFIED_TTL


class Verifier(Protocol):
    info: ProviderInfo

    def is_configured(self) -> bool: ...
    async def test_connection(self) -> ProviderStatus: ...
    async def verify(self, email: str) -> VerificationResult: ...
