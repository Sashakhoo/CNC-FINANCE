"""Common machinery for LLM providers: JSON-only prompting, Pydantic validation
with one repair attempt, caching, usage events and HTTP error typing.

LLM output is never authoritative — callers must validate any factual claim
against evidence they supplied (see app.services.training / outreach)."""
from __future__ import annotations

import hashlib
import json
import re
import time
from abc import ABC, abstractmethod
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.providers.base import (NOOP_RECORDER, AuthError, BadResponse, Cache, NotConfigured, ProviderError,
                                ProviderInfo, ProviderKind, ProviderState, ProviderStatus, QuotaExceeded,
                                RateLimited, TransientError, UsageEvent, UsageRecorder)

T = TypeVar("T", bound=BaseModel)

CACHE_TTL_SECONDS = 30 * 24 * 3600
DEFAULT_TIMEOUT = 60.0

_JSON_INSTRUCTIONS = (
    "Respond with a single JSON object only — no prose, no markdown fences. "
    "It must validate against this JSON Schema:\n{schema}"
)


def extract_json(text: str) -> Any:
    """Parses the first JSON object in `text`, tolerating ``` fences and leading prose."""
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.S | re.I)
    if fence:
        t = fence.group(1).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end > start:
            return json.loads(t[start:end + 1])
        raise


class AIProvider(ABC):
    """Subclasses implement `_complete` (one HTTP call) and `_ping`."""

    name: str
    display_name: str
    default_model: str
    base_url: str
    docs_url: str
    compliance_notes = "Output is advisory only; every factual claim is checked against collected evidence."

    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None,
                 recorder: UsageRecorder = NOOP_RECORDER, cache: Cache | None = None, model: str | None = None):
        self.api_key = api_key or ""
        self.model = model or self.default_model
        self.recorder = recorder
        self.cache = cache
        self._client = client
        self.info = ProviderInfo(
            name=self.name, kind=ProviderKind.AI, display_name=self.display_name, access_method="API",
            requests_per_minute=60, concurrency=4, cost_per_request=None,
            compliance_notes=self.compliance_notes, docs_url=self.docs_url,
        )

    # --- plumbing ---------------------------------------------------------

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=DEFAULT_TIMEOUT)
        return self._client

    def is_configured(self) -> bool:
        return bool(self.api_key.strip())

    def _scrub(self, text: str) -> str:
        return text.replace(self.api_key, "[REDACTED]") if self.api_key else text

    def _raise_for(self, resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        try:
            body = resp.json()
            detail = json.dumps(body.get("error", body))[:300]
        except ValueError:
            body, detail = {}, resp.text[:300]
        detail = self._scrub(detail)
        status = resp.status_code
        lowered = detail.lower()
        if status in (401, 403):
            raise AuthError(f"{self.display_name} rejected the API key ({status})", http_status=status)
        if status == 402 or "insufficient_quota" in lowered or "credit balance" in lowered:
            raise QuotaExceeded(f"{self.display_name} quota exhausted: {detail}", http_status=status)
        if status == 429:
            retry_after = resp.headers.get("retry-after")
            try:
                ra = float(retry_after) if retry_after else None
            except ValueError:
                ra = None
            raise RateLimited(f"{self.display_name} rate limit hit", retry_after=ra, http_status=429)
        if status >= 500 or status == 529:
            raise TransientError(f"{self.display_name} server error {status}", http_status=status)
        raise ProviderError(f"{self.display_name} request failed ({status}): {detail}", http_status=status)

    async def _send(self, method: str, url: str, **kw) -> httpx.Response:
        try:
            resp = await self.client.request(method, url, **kw)
        except httpx.TimeoutException as e:
            raise TransientError(f"{self.display_name} timed out") from e
        except httpx.TransportError as e:
            raise TransientError(f"{self.display_name} connection failed: {type(e).__name__}") from e
        self._raise_for(resp)
        return resp

    async def _record(self, operation: str, started: float, *, success: bool, http_status: int | None = None,
                      error_type: str | None = None, meta: dict | None = None) -> None:
        await self.recorder(UsageEvent(
            provider=self.name, kind=ProviderKind.AI, operation=operation, success=success,
            duration_ms=int((time.perf_counter() - started) * 1000), http_status=http_status,
            error_type=error_type, cost_estimate=None, meta={"model": self.model, **(meta or {})}))

    # --- provider-specific ------------------------------------------------

    @abstractmethod
    async def _complete(self, system: str, prompt: str, max_tokens: int) -> tuple[str, dict]:
        """One HTTP call. Returns (text, usage_meta)."""

    @abstractmethod
    async def _ping(self) -> httpx.Response:
        """Cheap authenticated call used by test_connection."""

    # --- public API -------------------------------------------------------

    async def test_connection(self) -> ProviderStatus:
        if not self.is_configured():
            return ProviderStatus(ProviderState.NOT_CONFIGURED, "No API key set")
        started = time.perf_counter()
        try:
            resp = await self._ping()
        except ProviderError as e:
            await self._record("test_connection", started, success=False, http_status=e.http_status,
                               error_type=e.error_type)
            return ProviderStatus(ProviderState.ERROR, str(e), http_status=e.http_status)
        await self._record("test_connection", started, success=True, http_status=resp.status_code)
        return ProviderStatus(ProviderState.CONNECTED, f"{self.display_name} reachable · model {self.model}",
                              http_status=resp.status_code)

    def _cache_key(self, system: str, prompt: str, schema: type[BaseModel]) -> str:
        raw = json.dumps([self.name, self.model, system, prompt, schema.model_json_schema()], sort_keys=True)
        return f"llm:{self.name}:{hashlib.sha256(raw.encode()).hexdigest()}"

    async def _call(self, system: str, prompt: str, max_tokens: int, operation: str) -> str:
        started = time.perf_counter()
        try:
            text, usage = await self._complete(system, prompt, max_tokens)
        except ProviderError as e:
            await self._record(operation, started, success=False, http_status=e.http_status, error_type=e.error_type)
            raise
        await self._record(operation, started, success=True, http_status=200, meta=usage)
        return text

    async def generate_structured(self, system: str, prompt: str, schema: type[T], max_tokens: int = 1500) -> T:
        if not self.is_configured():
            raise NotConfigured(f"{self.display_name} API key is not set")
        key = self._cache_key(system, prompt, schema)
        if self.cache is not None:
            hit = await self.cache.get(key)
            if hit is not None:
                try:
                    return schema.model_validate(hit)
                except ValidationError:
                    pass
        full_system = f"{system}\n\n" + _JSON_INSTRUCTIONS.format(schema=json.dumps(schema.model_json_schema()))
        text = await self._call(full_system, prompt, max_tokens, "generate_structured")
        try:
            result = schema.model_validate(extract_json(text))
        except (ValueError, ValidationError) as first_error:
            repair = (f"{prompt}\n\nYour previous reply was not valid. Error: {str(first_error)[:500]}\n"
                      f"Previous reply:\n{text[:2000]}\n\nReturn only the corrected JSON object.")
            text2 = await self._call(full_system, repair, max_tokens, "generate_structured_repair")
            try:
                result = schema.model_validate(extract_json(text2))
            except (ValueError, ValidationError) as e:
                raise BadResponse(f"{self.display_name} returned output that does not match the schema: "
                                  f"{str(e)[:300]}") from e
        if self.cache is not None:
            await self.cache.set(key, result.model_dump(mode="json"), CACHE_TTL_SECONDS)
        return result
