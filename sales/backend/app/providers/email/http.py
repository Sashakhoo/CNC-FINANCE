"""One timed, recorded HTTP attempt for email/verification providers.

Error messages are built here from fixed text only — never from the request
URL or exception string — because some providers take the API key as a query
parameter and httpx includes the full URL in its exception messages."""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from app.providers.base import ProviderError, ProviderKind, TransientError, UsageEvent, UsageRecorder

DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def retry_after_seconds(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


async def send(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    provider: str,
    kind: ProviderKind,
    operation: str,
    recorder: UsageRecorder,
    check: Callable[[httpx.Response], Any],
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    cost_estimate: float | None = None,
) -> Any:
    """Makes exactly one request. `check(resp)` returns the parsed payload or
    raises a ProviderError; either way a UsageEvent is recorded."""
    start = time.perf_counter()

    async def record(success: bool, http_status: int | None, error_type: str | None) -> None:
        await recorder(UsageEvent(
            provider=provider, kind=kind, operation=operation, success=success,
            duration_ms=round((time.perf_counter() - start) * 1000), http_status=http_status,
            error_type=error_type, cost_estimate=cost_estimate if success else None,
        ))

    try:
        resp = await client.request(method, url, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
    except httpx.TimeoutException:
        await record(False, None, TransientError.error_type)
        raise TransientError(f"{provider} {operation}: request timed out") from None
    except httpx.HTTPError as e:
        await record(False, None, TransientError.error_type)
        raise TransientError(f"{provider} {operation}: network error ({type(e).__name__})") from None

    try:
        payload = check(resp)
    except ProviderError as e:
        await record(False, resp.status_code, e.error_type)
        raise
    await record(True, resp.status_code, None)
    return payload


def json_body(resp: httpx.Response, provider: str, operation: str) -> Any:
    from app.providers.base import BadResponse
    try:
        return resp.json()
    except ValueError:
        raise BadResponse(f"{provider} {operation}: response was not JSON", http_status=resp.status_code) from None
