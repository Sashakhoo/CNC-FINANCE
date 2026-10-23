"""Tavily Search API (web search).

Docs: https://docs.tavily.com/documentation/api-reference/endpoint/search
Credits: https://docs.tavily.com/guides/api-credits  (a "basic" search costs 1 credit)
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

ENDPOINT = "https://api.tavily.com/search"
CACHE_TTL_SECONDS = 7 * 24 * 3600
MAX_COUNT = 20
# Tavily takes lowercase English country names, not ISO codes.
COUNTRY_NAMES = {"MY": "malaysia", "SG": "singapore"}


def _retry_after(header: str | None) -> float | None:
    try:
        return float(header) if header else None
    except ValueError:
        return None


class TavilySearch:
    info = ProviderInfo(
        name="tavily", kind=ProviderKind.SEARCH, display_name="Tavily Search API", access_method="API",
        requests_per_minute=60, concurrency=1, cost_per_request=None,
        compliance_notes="Official API; results used only to identify companies and public professional "
                         "references. Result pages are not fetched by this provider (raw content is not requested).",
        docs_url="https://docs.tavily.com/documentation/api-reference/endpoint/search",
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
            self._client = httpx.AsyncClient(timeout=20.0)
        return self._client

    @staticmethod
    def _cache_key(body: dict) -> str:
        digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:32]
        return f"search:tavily:{digest}"

    async def _request(self, body: dict, operation: str) -> dict:
        if not self.is_configured():
            raise NotConfigured("Tavily API key is not set")
        start = time.perf_counter()
        status: int | None = None
        error: ProviderError | None = None
        try:
            try:
                r = await self._http().post(ENDPOINT, json=body, headers={
                    "Authorization": f"Bearer {self._key}", "Accept": "application/json"})
            except httpx.TimeoutException as e:
                raise TransientError("Tavily timed out") from e
            except httpx.HTTPError as e:
                raise TransientError(f"Tavily connection error: {type(e).__name__}") from e
            status = r.status_code
            if status == 429:
                raise RateLimited("Tavily rate limit hit", retry_after=_retry_after(r.headers.get("retry-after")))
            if status == 401:
                raise AuthError("Tavily rejected the API key", http_status=status)
            if status == 432:
                raise QuotaExceeded("Tavily plan credits exhausted", http_status=status)
            if status == 433:
                raise QuotaExceeded("Tavily pay-as-you-go limit reached", http_status=status)
            if status >= 500:
                raise TransientError(f"Tavily server error {status}", http_status=status)
            if status != 200:
                raise BadResponse(f"Tavily returned {status}", http_status=status)
            try:
                return r.json()
            except ValueError as e:
                raise BadResponse("Tavily returned invalid JSON", http_status=status) from e
        except ProviderError as e:
            error = e
            raise
        finally:
            await self._recorder(UsageEvent(
                provider=self.info.name, kind=self.info.kind, operation=operation, success=error is None,
                duration_ms=round((time.perf_counter() - start) * 1000), http_status=status,
                error_type=error.error_type if error else None,
                meta={"q": body.get("query", "")[:200]},
            ))

    async def search(self, query: str, count: int = 10, country: str = "MY", offset: int = 0) -> list[SearchResult]:
        # Tavily has no paging: a page beyond the first has nothing new to give.
        if offset > 0:
            return []
        body = {"query": query, "search_depth": "basic", "topic": "general",
                "max_results": max(1, min(count, MAX_COUNT))}
        name = COUNTRY_NAMES.get(country.upper())
        if name:
            body["country"] = name
        key = self._cache_key(body)
        if self._cache is not None:
            hit = await self._cache.get(key)
            if hit is not None:
                return [SearchResult.from_dict(d) for d in hit]
        data = await self._request(body, "web_search")
        raw = data.get("results")
        if not isinstance(raw, list):
            raise BadResponse("Tavily response missing results")
        results = []
        for item in raw:
            url = (item or {}).get("url")
            if not url:
                continue
            results.append(SearchResult(
                title=item.get("title") or "", url=url, snippet=item.get("content") or "",
                rank=len(results) + 1, provider=self.info.name, query=query))
        if self._cache is not None:
            await self._cache.set(key, [r.to_dict() for r in results], CACHE_TTL_SECONDS)
        return results

    async def test_connection(self) -> ProviderStatus:
        if not self.is_configured():
            return ProviderStatus(ProviderState.NOT_CONFIGURED, "No API key configured")
        try:
            await self._request({"query": "codencode", "search_depth": "basic", "max_results": 1}, "test_connection")
        except ProviderError as e:
            return ProviderStatus(ProviderState.ERROR, f"{e.error_type}: {e}", e.http_status)
        return ProviderStatus(ProviderState.CONNECTED, "Search request succeeded", 200)
