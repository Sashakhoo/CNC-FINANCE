from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from app.providers.base import ProviderInfo, ProviderStatus


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    rank: int
    provider: str
    query: str
    retrieved_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> SearchResult:
        return cls(**{k: d[k] for k in ("title", "url", "snippet", "rank", "provider", "query", "retrieved_at")})


class SearchProvider(Protocol):
    info: ProviderInfo

    def is_configured(self) -> bool: ...
    async def test_connection(self) -> ProviderStatus: ...
    async def search(self, query: str, count: int = 10, country: str = "MY", offset: int = 0) -> list[SearchResult]: ...
