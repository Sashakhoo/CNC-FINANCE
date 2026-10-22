from __future__ import annotations

from app.models.base import VerificationStatus
from app.providers.base import Cache
from app.providers.verification.base import VerificationResult, cache_ttl
from app.services.email_intel import validate_syntax


def syntax_failure(email: str, provider: str) -> VerificationResult | None:
    """Reject malformed addresses locally — no paid API call."""
    if validate_syntax(email):
        return None
    return VerificationResult(email=email.strip().lower(), status=VerificationStatus.INVALID, confidence=0.0,
                              provider=provider, meta={"reason": "failed_syntax_check"})


async def cached(cache: Cache | None, provider: str, email: str) -> VerificationResult | None:
    if not cache:
        return None
    hit = await cache.get(f"verify:{provider}:{email}")
    if not hit:
        return None
    res = VerificationResult.model_validate(hit)
    res.cached = True
    return res


async def store(cache: Cache | None, result: VerificationResult) -> None:
    if cache:
        await cache.set(f"verify:{result.provider}:{result.email}", result.model_dump(mode="json"),
                        cache_ttl(result.status))
