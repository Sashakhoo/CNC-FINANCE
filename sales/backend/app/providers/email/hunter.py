"""Hunter.io email discovery (API v2).

Docs: https://hunter.io/api-documentation/v2 — Domain Search, Email Finder,
Account. The key is sent in the X-API-KEY header so it never appears in URLs.

Hunter's documented status codes differ from the usual meaning:
401 = no valid key, 403 = rate limit, 429 = usage limit (plan quota),
451 = the person asked not to be processed."""
from __future__ import annotations

import httpx

from app.models.base import EmailType, Provenance
from app.providers.base import (NOOP_RECORDER, AuthError, BadResponse, Cache, NotConfigured, ProviderError,
                                ProviderInfo, ProviderKind, ProviderState, ProviderStatus, QuotaExceeded, RateLimited,
                                TransientError, UsageRecorder)
from app.providers.email.base import DiscoveredEmail, DomainSearchResult, EmailOptedOut
from app.providers.email.http import json_body, retry_after_seconds, send
from app.services.email_intel import classify_email, validate_syntax

BASE_URL = "https://api.hunter.io/v2"
SEARCH_CACHE_TTL = 7 * 24 * 3600


def check_hunter(resp: httpx.Response, operation: str) -> dict:
    """Map Hunter HTTP statuses to typed errors; return `data` on success."""
    name = "hunter"
    code = resp.status_code
    if code == 401:
        raise AuthError("Hunter rejected the API key", http_status=code)
    if code == 403:
        raise RateLimited("Hunter rate limit reached", retry_after=retry_after_seconds(resp), http_status=code)
    if code == 429:
        raise QuotaExceeded("Hunter usage limit for this billing period reached", http_status=code)
    if code == 451:
        raise EmailOptedOut("This person asked Hunter not to process their data", http_status=code)
    if code == 202:
        raise TransientError("Hunter verification still in progress — retry later", http_status=code)
    if code == 222:
        raise TransientError("Hunter got an unexpected SMTP response — retry later", http_status=code)
    if code >= 500:
        raise TransientError(f"Hunter server error ({code})", http_status=code)
    body = json_body(resp, name, operation)
    if code != 200:
        details = ""
        if isinstance(body, dict) and isinstance(body.get("errors"), list) and body["errors"]:
            details = str(body["errors"][0].get("details") or body["errors"][0].get("id") or "")[:200]
        raise BadResponse(f"Hunter {operation} failed ({code}){': ' + details if details else ''}", http_status=code)
    if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
        raise BadResponse(f"Hunter {operation}: unexpected response shape", http_status=code)
    return body["data"]


def _email_type(hunter_type: str | None, email: str) -> EmailType:
    local_class = classify_email(email)
    if local_class != EmailType.PERSONAL_BUSINESS:
        return local_class
    return EmailType.ROLE if hunter_type == "generic" else EmailType.PERSONAL_BUSINESS


def _sources(items) -> list[str]:
    out = []
    for s in items or []:
        uri = s.get("uri") if isinstance(s, dict) else None
        if isinstance(uri, str) and uri.startswith(("http://", "https://")):
            out.append(uri[:1000])
    return out


def _confidence(raw) -> float:
    try:
        return max(0.0, min(1.0, float(raw) / 100))
    except (TypeError, ValueError):
        return 0.0


class HunterEmailDiscovery:
    info = ProviderInfo(
        name="hunter", kind=ProviderKind.EMAIL_DISCOVERY, display_name="Hunter.io", access_method="API",
        requests_per_minute=None, concurrency=2, cost_per_request=None,
        compliance_notes=("Returns business emails Hunter found published on the web (with source URLs) or "
                          "inferred from patterns. Inferred results are labelled INFERRED. HTTP 451 means the "
                          "person opted out — suppress them."),
        docs_url="https://hunter.io/api-documentation/v2",
    )

    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None,
                 recorder: UsageRecorder = NOOP_RECORDER, cache: Cache | None = None):
        self._key = api_key or ""
        self._client = client or httpx.AsyncClient()
        self._recorder = recorder
        self._cache = cache

    def is_configured(self) -> bool:
        return bool(self._key)

    def _headers(self) -> dict[str, str]:
        if not self._key:
            raise NotConfigured("Hunter API key is not configured")
        return {"X-API-KEY": self._key}

    async def _get(self, path: str, operation: str, params: dict) -> dict:
        return await send(self._client, "GET", f"{BASE_URL}{path}", provider="hunter",
                          kind=ProviderKind.EMAIL_DISCOVERY, operation=operation, recorder=self._recorder,
                          params=params, headers=self._headers(), check=lambda r: check_hunter(r, operation))

    async def test_connection(self) -> ProviderStatus:
        if not self.is_configured():
            return ProviderStatus(ProviderState.NOT_CONFIGURED, "Set EMAIL_DISCOVERY_API_KEY")
        try:
            data = await self._get("/account", "account", {})
        except ProviderError as e:
            return ProviderStatus(ProviderState.ERROR, str(e), e.http_status)
        req = (data.get("requests") or {})
        pool = req.get("credits") or req.get("searches") or {}
        remaining = pool.get("remaining", pool.get("available"))
        msg = f"Plan {data.get('plan_name', '?')}"
        if remaining is not None:
            msg += f" · {remaining} {'credits' if 'credits' in req else 'searches'} remaining"
        if data.get("reset_date"):
            msg += f" · resets {data['reset_date']}"
        return ProviderStatus(ProviderState.CONNECTED, msg, 200)

    def _to_email(self, item: dict, domain: str) -> DiscoveredEmail | None:
        email = validate_syntax(str(item.get("value") or item.get("email") or ""))
        if not email:
            return None
        verification = item.get("verification") if isinstance(item.get("verification"), dict) else {}
        return DiscoveredEmail(
            email=email, first_name=item.get("first_name"), last_name=item.get("last_name"),
            position=item.get("position") or item.get("position_raw"), department=item.get("department"),
            seniority=item.get("seniority"), linkedin_url=item.get("linkedin") or item.get("linkedin_url"),
            phone=item.get("phone_number"),
            confidence=_confidence(item.get("confidence", item.get("score"))),
            email_type=_email_type(item.get("type"), email), sources=_sources(item.get("sources")),
            provider="hunter",
            provenance=Provenance.INFERRED if item.get("provenance") == "inferred" else Provenance.ENRICHED,
            provider_verification_status=verification.get("status"),
        )

    async def domain_search(self, domain: str, limit: int = 10) -> DomainSearchResult:
        domain = domain.lower().strip()
        limit = max(1, min(100, int(limit)))
        key = f"hunter:domain_search:{domain}:{limit}"
        if self._cache and (hit := await self._cache.get(key)):
            return DomainSearchResult.model_validate(hit)
        data = await self._get("/domain-search", "domain_search", {"domain": domain, "limit": limit})
        emails = [e for e in (self._to_email(i, domain) for i in data.get("emails") or [] if isinstance(i, dict)) if e]
        result = DomainSearchResult(domain=domain, pattern=data.get("pattern"), accept_all=data.get("accept_all"),
                                    organization=data.get("organization"), emails=emails)
        if self._cache:
            await self._cache.set(key, result.model_dump(mode="json"), SEARCH_CACHE_TTL)
        return result

    async def find_email(self, first_name: str, last_name: str, domain: str) -> DiscoveredEmail | None:
        domain = domain.lower().strip()
        key = f"hunter:find:{domain}:{first_name.lower().strip()}:{last_name.lower().strip()}"
        if self._cache and (hit := await self._cache.get(key)) is not None:
            return DiscoveredEmail.model_validate(hit["email"]) if hit.get("email") else None
        data = await self._get("/email-finder", "find_email",
                               {"domain": domain, "first_name": first_name, "last_name": last_name})
        found = self._to_email({**data, "confidence": data.get("score")}, domain) if data.get("email") else None
        if self._cache:
            await self._cache.set(key, {"email": found.model_dump(mode="json") if found else None}, SEARCH_CACHE_TTL)
        return found
