"""robots.txt handling per RFC 9309: 2xx → parse; 4xx → allow everything;
5xx / timeout / network error → disallow everything for that host (cached
briefly, then retried)."""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

if TYPE_CHECKING:
    from app.crawler.fetcher import RawResponse

FetchRaw = Callable[[str], Awaitable["RawResponse"]]

MAX_ROBOTS_BYTES = 500_000      # RFC 9309 requires parsing at least 500 KiB
MAX_CRAWL_DELAY = 60.0


@dataclass
class RobotsRules:
    origin: str
    mode: str                    # "parsed" | "allow_all" | "disallow_all"
    parser: RobotFileParser | None
    status_code: int | None
    expires_at: float
    note: str = ""
    error_type: str | None = None    # set when robots.txt couldn't be fetched at all (DNS, unsafe, TLS…)


class RobotsCache:
    def __init__(self, fetch_raw: FetchRaw, user_agent: str, *, ttl_seconds: float = 24 * 3600,
                 unavailable_ttl_seconds: float = 600, clock: Callable[[], float] = time.monotonic):
        self._fetch_raw = fetch_raw
        self.user_agent = user_agent
        self.ttl = ttl_seconds
        self.unavailable_ttl = unavailable_ttl_seconds
        self._clock = clock
        self._cache: dict[str, RobotsRules] = {}

    @staticmethod
    def origin_of(url: str) -> str:
        p = urlsplit(url)
        return f"{p.scheme.lower()}://{p.netloc.lower()}"

    async def get(self, url: str) -> RobotsRules:
        origin = self.origin_of(url)
        hit = self._cache.get(origin)
        if hit and hit.expires_at > self._clock():
            return hit
        rules = await self._load(origin)
        self._cache[origin] = rules
        return rules

    async def _load(self, origin: str) -> RobotsRules:
        now = self._clock()
        resp = await self._fetch_raw(origin + "/robots.txt")
        if resp.error_type and resp.status_code is None:
            return RobotsRules(origin, "disallow_all", None, None, now + self.unavailable_ttl,
                               f"robots.txt unreachable ({resp.error_type})", resp.error_type)
        status = resp.status_code or 0
        if 200 <= status < 300:
            body = resp.body[:MAX_ROBOTS_BYTES].decode("utf-8", errors="replace")
            parser = RobotFileParser()
            parser.parse(body.splitlines())
            return RobotsRules(origin, "parsed", parser, status, now + self.ttl)
        if 400 <= status < 500:
            return RobotsRules(origin, "allow_all", None, status, now + self.ttl, f"robots.txt {status}: allow all")
        return RobotsRules(origin, "disallow_all", None, status, now + self.unavailable_ttl,
                           f"robots.txt {status}: temporarily disallow all")

    async def can_fetch(self, url: str) -> bool:
        rules = await self.get(url)
        if rules.mode == "allow_all":
            return True
        if rules.mode == "disallow_all":
            return False
        if urlsplit(url).path == "/robots.txt":
            return True
        assert rules.parser is not None
        return rules.parser.can_fetch(self.user_agent, url)

    async def crawl_delay(self, url: str) -> float | None:
        rules = await self.get(url)
        if rules.mode != "parsed" or rules.parser is None:
            return None
        delay = rules.parser.crawl_delay(self.user_agent)
        if delay is None:
            rate = rules.parser.request_rate(self.user_agent)
            if rate and rate.requests:
                delay = rate.seconds / rate.requests
        return None if delay is None else min(float(delay), MAX_CRAWL_DELAY)
