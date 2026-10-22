"""Hunter Email Verifier (GET /v2/email-verifier). Status mapping: see verification/base.py."""
from __future__ import annotations

import httpx

from app.models.base import VerificationStatus
from app.providers.base import (NOOP_RECORDER, Cache, NotConfigured, ProviderError, ProviderInfo, ProviderKind,
                                ProviderState, ProviderStatus, UsageRecorder)
from app.providers.email.http import send
from app.providers.email.hunter import BASE_URL, check_hunter
from app.providers.verification.base import VerificationResult
from app.providers.verification.common import cached, store, syntax_failure
from app.services.email_intel import validate_syntax

LIKELY_SCORE = 80
_META_FIELDS = ("status", "result", "score", "regexp", "gibberish", "disposable", "webmail", "mx_records",
                "smtp_server", "smtp_check", "accept_all", "block")


def map_hunter_status(status: str | None, score: float | None) -> VerificationStatus:
    s = (status or "").lower()
    if s == "valid":
        return VerificationStatus.VERIFIED
    if s == "accept_all":
        return VerificationStatus.LIKELY if (score or 0) >= LIKELY_SCORE else VerificationStatus.RISKY
    if s == "webmail":
        return VerificationStatus.RISKY
    if s in ("invalid", "disposable"):
        return VerificationStatus.INVALID
    return VerificationStatus.UNKNOWN


class HunterVerifier:
    info = ProviderInfo(
        name="hunter", kind=ProviderKind.EMAIL_VERIFICATION, display_name="Hunter Email Verifier",
        access_method="API", concurrency=2, cost_per_request=None,
        compliance_notes="Checks syntax, MX and SMTP without sending email. HTTP 451 = person opted out.",
        docs_url="https://hunter.io/api-documentation/v2#email-verifier",
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
            raise NotConfigured("Hunter API key is not configured")
        return await send(self._client, "GET", f"{BASE_URL}{path}", provider="hunter",
                          kind=ProviderKind.EMAIL_VERIFICATION, operation=operation, recorder=self._recorder,
                          params=params, headers={"X-API-KEY": self._key},
                          check=lambda r: check_hunter(r, operation))

    async def test_connection(self) -> ProviderStatus:
        if not self.is_configured():
            return ProviderStatus(ProviderState.NOT_CONFIGURED, "Set EMAIL_VERIFICATION_API_KEY")
        try:
            data = await self._get("/account", "account", {})
        except ProviderError as e:
            return ProviderStatus(ProviderState.ERROR, str(e), e.http_status)
        req = data.get("requests") or {}
        pool = req.get("credits") or req.get("verifications") or {}
        remaining = pool.get("remaining", pool.get("available"))
        msg = "Connected" + (f" · {remaining} {'credits' if 'credits' in req else 'verifications'} remaining"
                             if remaining is not None else "")
        return ProviderStatus(ProviderState.CONNECTED, msg, 200)

    async def verify(self, email: str) -> VerificationResult:
        if bad := syntax_failure(email, "hunter"):
            return bad
        email = validate_syntax(email)
        if hit := await cached(self._cache, "hunter", email):
            return hit
        data = await self._get("/email-verifier", "verify", {"email": email})
        score = data.get("score")
        try:
            score = float(score) if score is not None else None
        except (TypeError, ValueError):
            score = None
        result = VerificationResult(
            email=email, status=map_hunter_status(data.get("status"), score),
            confidence=max(0.0, min(1.0, (score or 0) / 100)), provider="hunter",
            meta={k: data[k] for k in _META_FIELDS if k in data},
        )
        await store(self._cache, result)
        return result
