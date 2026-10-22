"""Shared contract for every external provider (search, email discovery,
email verification, AI, business data). Providers return normalized internal
models; they never touch the database. Usage, caching and quotas are applied
by the caller through the hooks below, so providers stay swappable."""
from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderKind(str, enum.Enum):
    SEARCH = "SEARCH"
    COMPANY = "COMPANY"
    EMAIL_DISCOVERY = "EMAIL_DISCOVERY"
    EMAIL_VERIFICATION = "EMAIL_VERIFICATION"
    AI = "AI"
    CRAWLER = "CRAWLER"


class ProviderState(str, enum.Enum):
    CONNECTED = "CONNECTED"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class ProviderInfo:
    """Static description shown on Settings → Providers."""
    name: str                     # stable id, e.g. "brave"
    kind: ProviderKind
    display_name: str
    access_method: str            # "API" | "CRAWL"
    requests_per_minute: int | None = None
    requests_per_day: int | None = None
    requests_per_month: int | None = None
    concurrency: int = 2
    cost_per_request: float | None = None   # None = unknown; never guessed
    compliance_notes: str = ""
    docs_url: str | None = None


@dataclass
class ProviderStatus:
    state: ProviderState
    message: str = ""
    http_status: int | None = None
    checked_at: float = field(default_factory=time.time)


class ProviderError(Exception):
    """Base error. `retryable` tells the caller whether backoff+retry makes sense."""
    error_type = "PROVIDER_ERROR"
    retryable = False

    def __init__(self, message: str, *, http_status: int | None = None):
        super().__init__(message)
        self.http_status = http_status


class NotConfigured(ProviderError):
    error_type = "NOT_CONFIGURED"


class AuthError(ProviderError):
    error_type = "INVALID_CREDENTIALS"


class QuotaExceeded(ProviderError):
    error_type = "QUOTA_EXCEEDED"


class RateLimited(ProviderError):
    error_type = "RATE_LIMITED"
    retryable = True

    def __init__(self, message: str, *, retry_after: float | None = None, http_status: int | None = 429):
        super().__init__(message, http_status=http_status)
        self.retry_after = retry_after


class TransientError(ProviderError):
    """Timeouts, 5xx, connection errors."""
    error_type = "TRANSIENT"
    retryable = True


class BadResponse(ProviderError):
    """Provider answered but the payload couldn't be parsed/validated."""
    error_type = "BAD_RESPONSE"


@dataclass
class UsageEvent:
    provider: str
    kind: ProviderKind
    operation: str
    success: bool
    duration_ms: int
    http_status: int | None = None
    error_type: str | None = None
    cost_estimate: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class UsageRecorder(Protocol):
    async def __call__(self, event: UsageEvent) -> None: ...


async def _noop_recorder(event: UsageEvent) -> None:
    return None


NOOP_RECORDER: UsageRecorder = _noop_recorder


class Cache(Protocol):
    """Key/value cache with expiry (DB-backed in the app, in-memory in tests)."""
    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any, ttl_seconds: int) -> None: ...


class MemoryCache:
    def __init__(self) -> None:
        self._d: dict[str, tuple[float, Any]] = {}

    async def get(self, key: str) -> Any | None:
        hit = self._d.get(key)
        if not hit or hit[0] < time.time():
            return None
        return hit[1]

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._d[key] = (time.time() + ttl_seconds, value)


class Provider(Protocol):
    info: ProviderInfo

    def is_configured(self) -> bool: ...
    async def test_connection(self) -> ProviderStatus: ...
