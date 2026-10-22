"""Brave Search API (web search).

Docs: https://api-dashboard.search.brave.com/app/documentation/web-search/get-started
Rate limits: https://api-dashboard.search.brave.com/documentation/guides/rate-limiting
"""
from __future__ import annotations

import hashlib
import json
import time

import httpx

from app.providers.base import (NOOP_RECORDER, AuthError, BadResponse, Cache, NotConfigured, ProviderError,
                                ProviderInfo, ProviderKind, ProviderState, ProviderStatus, QuotaExceeded, RateLimited,
                                TransientError, UsageEvent, UsageRecorder)
from app.providers.search.base import SearchResult

ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
CACHE_TTL_SECONDS = 7 * 24 * 3600
MAX_COUNT = 20
MAX_OFFSET = 9


def parse_reset(header: str | None) -> float | None:
    """`X-RateLimit-Reset: 1, 1419704` — seconds until each window resets.
    The shortest window is what blocks us right now."""
    if not header:
        return None
    vals = []
    for part in header.split(","):
        try:
            vals.append(float(part.strip()))
        except ValueError:
            continue
    return min(vals) if vals else None


def _monthly_exhausted(remaining: str | None) -> bool:
    if not remaining:
        return False
    parts = [p.strip() for p in remaining.split(",")]
    return len(parts) > 1 and parts[-1] == "0"


class BraveSearch:
    info = ProviderInfo(
        name="brave", kind=ProviderKind.SEARCH, display_name="Brave Search API", access_method="API",
        requests_per_minute=60, concurrency=1, cost_per_request=None,
        compliance_notes="Official API; results used only to identify companies and public professional "
                         "references. Result pages are not fetched by this provider.",
        docs_url="https://api-dashboard.search.brave.com/app/documentation/web-search/get-started",
    )

    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None,
                 recorder: UsageRecorder = NOOP_RECORDER, cache: Cache | None = None):
        self._key = api_key or ""
        self._client = client
        self._recorder = recorder
        self._cache = cache

    def is_configured(self) -> bool:
        return bool(self._key)

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    @staticmethod
    def _cache_key(params: dict) -> str:
        digest = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:32]
        return f"search:brave:{digest}"

    async def _request(self, params: dict, operation: str) -> dict:
        if not self.is_configured():
            raise NotConfigured("Brave Search API key is not set")
        start = time.perf_counter()
        status: int | None = None
        error: ProviderError | None = None
        try:
            try:
                r = await self._http().get(ENDPOINT, params=params, headers={
                    "X-Subscription-Token": self._key, "Accept": "application/json"})
            except httpx.TimeoutException as e:
                raise TransientError("Brave Search timed out") from e
            except httpx.HTTPError as e:
                raise TransientError(f"Brave Search connection error: {type(e).__name__}") from e
            status = r.status_code
            if status == 429:
                if _monthly_exhausted(r.headers.get("x-ratelimit-remaining")):
                    raise QuotaExceeded("Brave Search monthly quota exhausted", http_status=429)
                raise RateLimited("Brave Search rate limit hit",
                                  retry_after=parse_reset(r.headers.get("x-ratelimit-reset")))
            if status in (401, 403):
                raise AuthError("Brave Search rejected the API key", http_status=status)
            if status == 402:
                raise QuotaExceeded("Brave Search plan quota exhausted", http_status=status)
            if status >= 500:
                raise TransientError(f"Brave Search server error {status}", http_status=status)
            if status != 200:
                raise BadResponse(f"Brave Search returned {status}", http_status=status)
            try:
                return r.json()
            except ValueError as e:
                raise BadResponse("Brave Search returned invalid JSON", http_status=status) from e
        except ProviderError as e:
            error = e
            raise
        finally:
            await self._recorder(UsageEvent(
                provider=self.info.name, kind=self.info.kind, operation=operation, success=error is None,
                duration_ms=round((time.perf_counter() - start) * 1000), http_status=status,
                error_type=error.error_type if error else None,
                meta={"q": params.get("q", "")[:200]},
            ))

    async def search(self, query: str, count: int = 10, country: str = "MY", offset: int = 0) -> list[SearchResult]:
        params = {"q": query, "count": max(1, min(count, MAX_COUNT)), "offset": max(0, min(offset, MAX_OFFSET)),
                  "country": country.upper()}
        key = self._cache_key(params)
        if self._cache is not None:
            hit = await self._cache.get(key)
            if hit is not None:
                return [SearchResult.from_dict(d) for d in hit]
        data = await self._request(params, "web_search")
        web = data.get("web") or {}
        raw = web.get("results") or []
        if not isinstance(raw, list):
            raise BadResponse("Brave Search response missing web.results")
        results = []
        for i, item in enumerate(raw):
            url = (item or {}).get("url")
            if not url:
                continue
            results.append(SearchResult(
                title=item.get("title") or "", url=url, snippet=item.get("description") or "",
                rank=params["offset"] * params["count"] + i + 1, provider=self.info.name, query=query))
        if self._cache is not None:
            await self._cache.set(key, [r.to_dict() for r in results], CACHE_TTL_SECONDS)
        return results

    async def test_connection(self) -> ProviderStatus:
        if not self.is_configured():
            return ProviderStatus(ProviderState.NOT_CONFIGURED, "No API key configured")
        try:
            await self._request({"q": "codencode", "count": 1, "offset": 0, "country": "MY"}, "test_connection")
        except ProviderError as e:
            return ProviderStatus(ProviderState.ERROR, f"{e.error_type}: {e}", e.http_status)
        return ProviderStatus(ProviderState.CONNECTED, "Search request succeeded", 200)
