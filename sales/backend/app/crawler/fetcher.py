"""SafeFetcher — the only way the crawler touches the network.

Every request (and every redirect hop) is SSRF-checked, throttled per host
(one request at a time, min delay = max(config delay, robots Crawl-delay)),
bounded globally, size-limited, and retried with backoff on 429/5xx/timeouts.
Failures come back as values (error_type), never as exceptions."""
from __future__ import annotations

import asyncio
import email.utils
import random
import re
import ssl
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

import httpx

from app.crawler.html import Link, content_hash, parse_html
from app.crawler.url_safety import DNSResolutionError, Resolver, UnsafeURL, resolve_and_check, validate_url

if TYPE_CHECKING:
    from app.crawler.robots import RobotsCache


class FetchError:
    UNSAFE_URL = "UNSAFE_URL"
    DNS_ERROR = "DNS_ERROR"
    ROBOTS_DISALLOWED = "ROBOTS_DISALLOWED"
    TIMEOUT = "TIMEOUT"
    SSL_ERROR = "SSL_ERROR"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    HTTP_403 = "HTTP_403"
    HTTP_404 = "HTTP_404"
    HTTP_429 = "HTTP_429"
    HTTP_4XX = "HTTP_4XX"
    HTTP_5XX = "HTTP_5XX"
    NOT_HTML = "NOT_HTML"
    TOO_LARGE = "TOO_LARGE"
    TOO_MANY_REDIRECTS = "TOO_MANY_REDIRECTS"
    BAD_REDIRECT = "BAD_REDIRECT"
    INVALID_HTML = "INVALID_HTML"


RETRY_STATUSES = {429, 500, 502, 503, 504}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
HTML_TYPES = ("text/html", "application/xhtml+xml")


@dataclass
class RawResponse:
    url: str
    final_url: str
    status_code: int | None
    headers: dict[str, str]
    body: bytes
    redirects: list[str] = field(default_factory=list)
    error_type: str | None = None
    error: str | None = None


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int | None
    content_type: str | None
    html: str | None
    text: str | None
    title: str | None
    canonical_url: str | None
    content_hash: str | None
    fetched_at: datetime
    error_type: str | None = None
    error: str | None = None
    redirects: list[str] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error_type is None


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _status_error(status: int) -> str:
    if status == 403:
        return FetchError.HTTP_403
    if status == 404 or status == 410:
        return FetchError.HTTP_404
    if status == 429:
        return FetchError.HTTP_429
    if status >= 500:
        return FetchError.HTTP_5XX
    return FetchError.HTTP_4XX


def _classify_exception(e: Exception) -> tuple[str, str]:
    if isinstance(e, httpx.TimeoutException):
        return FetchError.TIMEOUT, "request timed out"
    cur: BaseException | None = e
    while cur is not None:
        if isinstance(cur, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in str(cur) or "SSL" in type(cur).__name__:
            return FetchError.SSL_ERROR, f"TLS error: {str(cur)[:200]}"
        cur = cur.__cause__ or cur.__context__
    return FetchError.CONNECTION_ERROR, f"{type(e).__name__}: {str(e)[:200]}"


def parse_retry_after(value: str | None, now: float | None = None) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        dt = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    return max(0.0, dt.timestamp() - (now if now is not None else time.time()))


def _charset(content_type: str | None, body: bytes) -> str:
    if content_type:
        m = re.search(r"charset=[\"']?([\w-]+)", content_type, re.I)
        if m:
            return m.group(1)
    m = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", body[:4096], re.I)
    return m.group(1).decode("ascii", "ignore") if m else "utf-8"


def _looks_like_html(content_type: str | None, body: bytes) -> bool:
    if content_type:
        return content_type.split(";", 1)[0].strip().lower() in HTML_TYPES
    head = body[:1024].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<html" in head


class SafeFetcher:
    def __init__(self, *, user_agent: str, timeout: float = 15.0, min_delay: float = 2.0,
                 max_bytes: int = 2_000_000, max_redirects: int = 5, max_retries: int = 3,
                 backoff_base: float = 1.0, max_backoff: float = 30.0, max_retry_after: float = 120.0,
                 global_concurrency: int = 8, robots: RobotsCache | None = None,
                 resolver: Resolver | None = None, client: httpx.AsyncClient | None = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 clock: Callable[[], float] = time.monotonic, pin_dns: bool = False):
        self.user_agent = user_agent
        # Connect to the exact IP that passed the SSRF check (closes the DNS-rebinding
        # window between check and connect). Host header + TLS SNI keep the real name,
        # so certificates are still verified against the hostname.
        self.pin_dns = pin_dns
        self.min_delay = min_delay
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.max_backoff = max_backoff
        self.max_retry_after = max_retry_after
        self.robots = robots
        self._resolver = resolver
        self._sleep = sleep
        self._clock = clock
        self._own_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout), follow_redirects=False, trust_env=False,
            headers={"User-Agent": user_agent, "Accept-Language": "en;q=0.9, ms;q=0.5"})
        self._global = asyncio.Semaphore(global_concurrency)
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._host_last: dict[str, float] = {}
        self._host_delay: dict[str, float] = {}

    async def aclose(self) -> None:
        if self._own_client:
            await self._client.aclose()

    async def __aenter__(self) -> SafeFetcher:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    def set_host_delay(self, host: str, delay: float | None) -> None:
        self._host_delay[host.lower()] = max(self.min_delay, delay or 0.0)

    @asynccontextmanager
    async def _throttle(self, host: str):
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            delay = self._host_delay.get(host, self.min_delay)
            last = self._host_last.get(host)
            if last is not None:
                wait = last + delay - self._clock()
                if wait > 0:
                    await self._sleep(wait)
            async with self._global:
                try:
                    yield
                finally:
                    self._host_last[host] = self._clock()

    def _backoff(self, attempt: int) -> float:
        return min(self.max_backoff, self.backoff_base * (2 ** attempt)) + random.uniform(0, self.backoff_base)

    def _pinned(self, url: str, ip: str | None) -> tuple[str, dict, dict]:
        if not (self.pin_dns and ip):
            return url, {}, {}
        parts = urlsplit(url)
        host = parts.hostname or ""
        literal = f"[{ip}]" if ":" in ip else ip
        netloc = literal + (f":{parts.port}" if parts.port else "")
        headers = {"Host": host + (f":{parts.port}" if parts.port else "")}
        ext = {"sni_hostname": host} if parts.scheme == "https" else {}
        return parts._replace(netloc=netloc).geturl(), headers, ext

    async def _send_once(self, url: str, accept: str, ip: str | None = None) -> RawResponse:
        """One HTTP request (no redirects), throttled for its host, body capped."""
        target, extra_headers, ext = self._pinned(url, ip)
        async with self._throttle(_host(url)):
            async with self._client.stream("GET", target, headers={"Accept": accept, **extra_headers},
                                           extensions=ext) as resp:
                headers = {k.lower(): v for k, v in resp.headers.items()}
                declared = headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > self.max_bytes:
                    return RawResponse(url, url, resp.status_code, headers, b"", error_type=FetchError.TOO_LARGE,
                                       error=f"Content-Length {declared} exceeds {self.max_bytes} bytes")
                chunks, size = [], 0
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    if size > self.max_bytes:
                        return RawResponse(url, url, resp.status_code, headers, b"", error_type=FetchError.TOO_LARGE,
                                           error=f"body exceeds {self.max_bytes} bytes")
                    chunks.append(chunk)
                return RawResponse(url, url, resp.status_code, headers, b"".join(chunks))

    async def _send_with_retries(self, url: str, accept: str, ip: str | None = None) -> RawResponse:
        attempt = 0
        while True:
            try:
                raw = await self._send_once(url, accept, ip)
            except httpx.HTTPError as e:
                etype, msg = _classify_exception(e)
                if etype == FetchError.SSL_ERROR or attempt >= self.max_retries:
                    return RawResponse(url, url, None, {}, b"", error_type=etype, error=msg)
                await self._sleep(self._backoff(attempt))
                attempt += 1
                continue
            if raw.error_type or raw.status_code not in RETRY_STATUSES or attempt >= self.max_retries:
                return raw
            wait = parse_retry_after(raw.headers.get("retry-after"))
            if wait is not None and wait > self.max_retry_after:
                return raw
            await self._sleep(wait if wait is not None else self._backoff(attempt))
            attempt += 1

    async def fetch_raw(self, url: str, *, accept: str = "*/*",
                        hop_check: Callable[[str], Awaitable[str | None]] | None = None) -> RawResponse:
        """SSRF-safe GET following up to max_redirects validated hops. No robots
        check (used for robots.txt itself); `hop_check` may veto a hop by
        returning an error type."""
        redirects: list[str] = []
        current = url
        for _ in range(self.max_redirects + 1):
            try:
                current = validate_url(current)
                parts = urlsplit(current)
                ips = await resolve_and_check(parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80),
                                              self._resolver)
            except UnsafeURL as e:
                return RawResponse(url, current, None, {}, b"", redirects, FetchError.UNSAFE_URL, e.reason)
            except DNSResolutionError as e:
                return RawResponse(url, current, None, {}, b"", redirects, FetchError.DNS_ERROR, str(e))
            if hop_check is not None and redirects:
                veto = await hop_check(current)
                if veto:
                    return RawResponse(url, current, None, {}, b"", redirects, veto, f"redirect target refused: {current}")
            raw = await self._send_with_retries(current, accept, ips[0].split("%", 1)[0] if ips else None)
            raw.url, raw.final_url, raw.redirects = url, current, redirects
            if raw.status_code in REDIRECT_STATUSES and not raw.error_type:
                location = raw.headers.get("location")
                if not location:
                    raw.error_type, raw.error = FetchError.BAD_REDIRECT, "redirect without Location"
                    return raw
                redirects.append(current)
                current = urljoin(current, location.strip())
                continue
            return raw
        return RawResponse(url, current, None, {}, b"", redirects, FetchError.TOO_MANY_REDIRECTS,
                           f"more than {self.max_redirects} redirects")

    async def _robots_veto(self, url: str, robots: RobotsCache | None) -> str | None:
        if robots is None:
            return None
        rules = await robots.get(url)
        if rules.error_type in (FetchError.DNS_ERROR, FetchError.UNSAFE_URL, FetchError.SSL_ERROR):
            return rules.error_type  # the site itself is unreachable/unsafe, not merely disallowed
        if not await robots.can_fetch(url):
            return FetchError.ROBOTS_DISALLOWED
        self.set_host_delay(_host(url), await robots.crawl_delay(url))
        return None

    async def fetch(self, url: str, *, robots: RobotsCache | None = None) -> FetchResult:
        """Fetch one HTML page: robots → SSRF → throttle → GET → parse."""
        robots = robots or self.robots
        now = lambda: datetime.now(timezone.utc)  # noqa: E731

        def failed(final: str, etype: str, err: str | None, status: int | None = None,
                   ctype: str | None = None, redirects: list[str] | None = None) -> FetchResult:
            return FetchResult(url, final, status, ctype, None, None, None, None, None, now(), etype, err,
                               redirects or [])

        try:
            validate_url(url)
        except UnsafeURL as e:
            return failed(url, FetchError.UNSAFE_URL, e.reason)
        veto = await self._robots_veto(url, robots)
        if veto:
            msg = "disallowed by robots.txt" if veto == FetchError.ROBOTS_DISALLOWED else "site unreachable"
            return failed(url, veto, msg)

        raw = await self.fetch_raw(url, accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
                                   hop_check=lambda u: self._robots_veto(u, robots))
        ctype = raw.headers.get("content-type")
        if raw.error_type:
            return failed(raw.final_url, raw.error_type, raw.error, raw.status_code, ctype, raw.redirects)
        status = raw.status_code or 0
        if status >= 400:
            return failed(raw.final_url, _status_error(status), f"HTTP {status}", status, ctype, raw.redirects)
        if not _looks_like_html(ctype, raw.body):
            return failed(raw.final_url, FetchError.NOT_HTML, f"content-type {ctype!r}", status, ctype, raw.redirects)
        try:
            html = raw.body.decode(_charset(ctype, raw.body), errors="replace")
        except LookupError:
            html = raw.body.decode("utf-8", errors="replace")
        try:
            parsed = parse_html(html, raw.final_url)
        except Exception as e:  # malformed markup must not kill a crawl
            return failed(raw.final_url, FetchError.INVALID_HTML, f"{type(e).__name__}: {e}", status, ctype,
                          raw.redirects)
        return FetchResult(url, raw.final_url, status, ctype, html, parsed.text, parsed.title, parsed.canonical_url,
                           content_hash(parsed.text), now(), None, None, raw.redirects, parsed.links, parsed.meta)


def build_crawler(*, user_agent: str, **fetcher_kwargs) -> tuple[SafeFetcher, RobotsCache]:
    """Fetcher + robots cache wired together (robots.txt itself is fetched
    through the same SSRF-safe, throttled path)."""
    from app.crawler.robots import RobotsCache

    fetcher = SafeFetcher(user_agent=user_agent, **fetcher_kwargs)
    robots = RobotsCache(lambda u: fetcher.fetch_raw(u, accept="text/plain,*/*;q=0.5"), user_agent)
    fetcher.robots = robots
    return fetcher, robots
