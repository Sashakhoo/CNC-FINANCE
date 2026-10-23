"""Reoon Email Verifier, single verification in "power" mode.

Docs: https://www.reoon.com/articles/api-documentation-of-reoon-email-verifier/
"quick" mode only checks the domain (a made-up mailbox at a real company still
passes), so this adapter always uses "power", which checks the mailbox itself
and can take up to a minute. Reoon asks for no more than 5 parallel requests.
Reoon only accepts the key as a query parameter, so error messages here are
fixed strings and never include the request URL. Error responses are not
documented; they come back as {"status": "error", "reason": "..."}.
Status mapping: see verification/base.py."""
from __future__ import annotations

import httpx

from app.models.base import VerificationStatus
from app.providers.base import (NOOP_RECORDER, AuthError, BadResponse, Cache, NotConfigured, ProviderError,
                                ProviderInfo, ProviderKind, ProviderState, ProviderStatus, QuotaExceeded,
                                RateLimited, TransientError, UsageRecorder)
from app.providers.email.http import json_body, retry_after_seconds, send
from app.providers.verification.base import VerificationResult
from app.providers.verification.common import cached, store, syntax_failure
from app.services.email_intel import validate_syntax

BASE_URL = "https://emailverifier.reoon.com/api/v1"
POWER_TIMEOUT = httpx.Timeout(90.0, connect=10.0)
_STATUS = {
    "safe": (VerificationStatus.VERIFIED, 0.95),
    "role_account": (VerificationStatus.RISKY, 0.50),
    "catch_all": (VerificationStatus.RISKY, 0.40),
    "inbox_full": (VerificationStatus.RISKY, 0.30),
    "invalid": (VerificationStatus.INVALID, 0.0),
    "disabled": (VerificationStatus.INVALID, 0.0),
    "disposable": (VerificationStatus.INVALID, 0.0),
    "spamtrap": (VerificationStatus.INVALID, 0.0),
}
_META_FIELDS = ("status", "overall_score", "is_safe_to_send", "is_deliverable", "is_catch_all", "is_role_account",
                "is_disposable", "is_disabled", "has_inbox_full", "is_free_email", "can_connect_smtp",
                "mx_accepts_mail", "domain", "verification_mode")


def map_reoon_status(status: str | None) -> tuple[VerificationStatus, float]:
    return _STATUS.get((status or "").lower(), (VerificationStatus.UNKNOWN, 0.20))


def _check(resp: httpx.Response, operation: str) -> dict:
    code = resp.status_code
    if code == 429:
        raise RateLimited("Reoon rate limit reached", retry_after=retry_after_seconds(resp), http_status=code)
    if code >= 500:
        raise TransientError(f"Reoon server error ({code})", http_status=code)
    body = json_body(resp, "reoon", operation)
    if not isinstance(body, dict):
        raise BadResponse(f"Reoon {operation} failed ({code})", http_status=code)
    if body.get("status") == "error" or code in (401, 402, 403):
        reason = str(body.get("reason") or "").lower()
        if "credit" in reason or "balance" in reason or code == 402:
            raise QuotaExceeded("Reoon: no verification credits remaining", http_status=code)
        if "key" in reason or code in (401, 403):
            raise AuthError("Reoon rejected the API key", http_status=code)
        raise BadResponse(f"Reoon {operation} returned an error", http_status=code)
    if code != 200:
        raise BadResponse(f"Reoon {operation} failed ({code})", http_status=code)
    return body


class ReoonVerifier:
    info = ProviderInfo(
        name="reoon", kind=ProviderKind.EMAIL_VERIFICATION, display_name="Reoon Email Verifier",
        access_method="API", concurrency=2, cost_per_request=None,
        compliance_notes="Validates via DNS/SMTP without sending email (power mode checks the mailbox itself).",
        docs_url="https://www.reoon.com/articles/api-documentation-of-reoon-email-verifier/",
    )

    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None,
                 recorder: UsageRecorder = NOOP_RECORDER, cache: Cache | None = None):
        self._key = api_key or ""
        self._client = client or httpx.AsyncClient()
        self._recorder = recorder
        self._cache = cache

    def is_configured(self) -> bool:
        return bool(self._key)

    async def _get(self, path: str, operation: str, params: dict, timeout: httpx.Timeout | None = None) -> dict:
        if not self._key:
            raise NotConfigured("Reoon API key is not configured")
        kwargs = {"timeout": timeout} if timeout else {}
        return await send(self._client, "GET", f"{BASE_URL}{path}", provider="reoon",
                          kind=ProviderKind.EMAIL_VERIFICATION, operation=operation, recorder=self._recorder,
                          params={**params, "key": self._key}, check=lambda r: _check(r, operation), **kwargs)

    async def test_connection(self) -> ProviderStatus:
        if not self.is_configured():
            return ProviderStatus(ProviderState.NOT_CONFIGURED, "Set EMAIL_VERIFICATION_API_KEY")
        try:
            data = await self._get("/check-account-balance/", "credits", {})
        except ProviderError as e:
            return ProviderStatus(ProviderState.ERROR, str(e), e.http_status)
        try:
            daily = int(data.get("remaining_daily_credits") or 0)
            instant = int(data.get("remaining_instant_credits") or 0)
        except (TypeError, ValueError):
            return ProviderStatus(ProviderState.ERROR, "Unexpected credit-balance response", 200)
        if daily + instant <= 0:
            return ProviderStatus(ProviderState.ERROR, "Connected, but 0 credits remaining", 200)
        return ProviderStatus(ProviderState.CONNECTED,
                              f"{daily} daily + {instant} instant credits remaining", 200)

    async def verify(self, email: str) -> VerificationResult:
        if bad := syntax_failure(email, "reoon"):
            return bad
        email = validate_syntax(email)
        if hit := await cached(self._cache, "reoon", email):
            return hit
        data = await self._get("/verify", "verify", {"email": email, "mode": "power"}, POWER_TIMEOUT)
        status, confidence = map_reoon_status(data.get("status"))
        result = VerificationResult(email=email, status=status, confidence=confidence, provider="reoon",
                                    meta={k: data[k] for k in _META_FIELDS if k in data})
        await store(self._cache, result)
        return result
