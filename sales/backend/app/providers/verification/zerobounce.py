"""ZeroBounce single validation (API v2).

Docs: https://www.zerobounce.net/docs/email-validation-api-quickstart/v2-validate-emails
      https://www.zerobounce.net/docs/email-validation-api-quickstart/v2-credit-balance
ZeroBounce only accepts the key as a query parameter, so error messages here
are fixed strings and never include the request URL.
Status mapping: see verification/base.py."""
from __future__ import annotations

import httpx

from app.models.base import VerificationStatus
from app.providers.base import (NOOP_RECORDER, AuthError, BadResponse, Cache, NotConfigured, ProviderError,
                                ProviderInfo, ProviderKind, ProviderState, ProviderStatus, RateLimited,
                                TransientError, UsageRecorder)
from app.providers.email.http import json_body, retry_after_seconds, send
from app.providers.verification.base import VerificationResult
from app.providers.verification.common import cached, store, syntax_failure
from app.services.email_intel import validate_syntax

BASE_URL = "https://api.zerobounce.net/v2"
_STATUS = {
    "valid": (VerificationStatus.VERIFIED, 0.95),
    "catch-all": (VerificationStatus.RISKY, 0.40),
    "abuse": (VerificationStatus.RISKY, 0.40),
    "invalid": (VerificationStatus.INVALID, 0.0),
    "spamtrap": (VerificationStatus.INVALID, 0.0),
    "do_not_mail": (VerificationStatus.INVALID, 0.0),
}
_META_FIELDS = ("status", "sub_status", "free_email", "did_you_mean", "domain", "domain_age_days", "smtp_provider",
                "mx_found", "mx_record", "processed_at")


def map_zerobounce_status(status: str | None) -> tuple[VerificationStatus, float]:
    return _STATUS.get((status or "").lower(), (VerificationStatus.UNKNOWN, 0.20))


def _check(resp: httpx.Response, operation: str) -> dict:
    code = resp.status_code
    if code == 429:
        raise RateLimited("ZeroBounce rate limit reached", retry_after=retry_after_seconds(resp), http_status=code)
    if code in (401, 403):
        raise AuthError("ZeroBounce rejected the API key", http_status=code)
    if code >= 500:
        raise TransientError(f"ZeroBounce server error ({code})", http_status=code)
    body = json_body(resp, "zerobounce", operation)
    if code != 200 or not isinstance(body, dict):
        raise BadResponse(f"ZeroBounce {operation} failed ({code})", http_status=code)
    if body.get("error"):
        # ZeroBounce uses one message for "bad key" and "no credits left".
        raise AuthError("ZeroBounce: invalid API key or no credits remaining", http_status=code)
    return body


class ZeroBounceVerifier:
    info = ProviderInfo(
        name="zerobounce", kind=ProviderKind.EMAIL_VERIFICATION, display_name="ZeroBounce",
        access_method="API", concurrency=2, cost_per_request=None,
        compliance_notes="Validates via DNS/SMTP without sending email. 200 bad-key calls/hour triggers a 1-hour block.",
        docs_url="https://www.zerobounce.net/docs/email-validation-api-quickstart/",
    )

    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None,
                 recorder: UsageRecorder = NOOP_RECORDER, cache: Cache | None = None):
        self._key = api_key or ""
        self._client = client or httpx.AsyncClient()
        self._recorder = recorder
        self._cache = cache

    def is_configured(self) -> bool:
        return bool(self._key)

    async def _get(self, path: str, operation: str, params: dict) -> dict:
        if not self._key:
            raise NotConfigured("ZeroBounce API key is not configured")
        return await send(self._client, "GET", f"{BASE_URL}{path}", provider="zerobounce",
                          kind=ProviderKind.EMAIL_VERIFICATION, operation=operation, recorder=self._recorder,
                          params={**params, "api_key": self._key}, check=lambda r: _check(r, operation))

    async def test_connection(self) -> ProviderStatus:
        if not self.is_configured():
            return ProviderStatus(ProviderState.NOT_CONFIGURED, "Set EMAIL_VERIFICATION_API_KEY")
        try:
            data = await self._get("/getcredits", "credits", {})
        except ProviderError as e:
            return ProviderStatus(ProviderState.ERROR, str(e), e.http_status)
        try:
            credits = int(data.get("Credits"))
        except (TypeError, ValueError):
            return ProviderStatus(ProviderState.ERROR, "Unexpected credit-balance response", 200)
        if credits < 0:
            return ProviderStatus(ProviderState.ERROR, "ZeroBounce rejected the API key", 200)
        if credits == 0:
            return ProviderStatus(ProviderState.ERROR, "Connected, but 0 credits remaining", 200)
        return ProviderStatus(ProviderState.CONNECTED, f"{credits} credits remaining", 200)

    async def verify(self, email: str) -> VerificationResult:
        if bad := syntax_failure(email, "zerobounce"):
            return bad
        email = validate_syntax(email)
        if hit := await cached(self._cache, "zerobounce", email):
            return hit
        data = await self._get("/validate", "verify", {"email": email})
        status, confidence = map_zerobounce_status(data.get("status"))
        result = VerificationResult(email=email, status=status, confidence=confidence, provider="zerobounce",
                                    meta={k: data[k] for k in _META_FIELDS if k in data})
        await store(self._cache, result)
        return result
