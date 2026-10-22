"""Bounded, polite crawl of ONE company website (spec §9): the home page plus
the pages that matter for prospecting (about, team, contact, careers, news,
services). Never the whole site."""
from __future__ import annotations

import inspect
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.crawler.fetcher import FetchError, FetchResult, SafeFetcher
from app.crawler.html import CrawledPage
from app.crawler.robots import RobotsCache
from app.crawler.url_safety import UnsafeURL, validate_url

PRIORITY_PATHS = ["/", "/about", "/about-us", "/company", "/our-company", "/team", "/management", "/leadership",
                  "/people", "/contact", "/contact-us", "/careers", "/jobs", "/news", "/blog", "/services",
                  "/solutions"]

# (page_type, regex on path or anchor text, priority rank — lower first)
_TYPES: list[tuple[str, str, int]] = [
    ("team", r"\b(team|management|leadership|people|board|directors?|our[-_ ]people|who[-_ ]we[-_ ]are|key[-_ ]personnel|organi[sz]ation[-_ ]chart)\b", 0),
    ("about", r"\b(about|about[-_ ]us|company|our[-_ ]company|profile|our[-_ ]story|corporate[-_ ]info(rmation)?|overview|history)\b", 1),
    ("contact", r"\b(contact|contact[-_ ]us|enquir(y|ies)|get[-_ ]in[-_ ]touch|location|reach[-_ ]us)\b", 2),
    ("careers", r"\b(careers?|jobs?|vacanc(y|ies)|join[-_ ]us|recruitment|hiring|work[-_ ]with[-_ ]us)\b", 3),
    ("news", r"\b(news|press|media|blog|announcements?|events?|newsroom|insights?|articles?)\b", 4),
    ("services", r"\b(services?|solutions?|products?|capabilit(y|ies)|what[-_ ]we[-_ ]do|industries)\b", 5),
]
_TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|mc_|_ga$|ref$|source$)", re.I)
_SKIP_EXT = re.compile(r"\.(pdf|jpe?g|png|gif|svg|webp|ico|zip|rar|7z|docx?|xlsx?|pptx?|mp4|mp3|avi|mov|css|js|xml|json|txt)$", re.I)
_FATAL = {FetchError.DNS_ERROR, FetchError.UNSAFE_URL, FetchError.SSL_ERROR}


@dataclass
class SkippedURL:
    url: str
    reason: str
    status_code: int | None = None


@dataclass
class CrawlError:
    url: str
    error_type: str
    error: str | None


@dataclass
class CrawlResult:
    start_url: str
    base_url: str | None = None
    pages: list[CrawledPage] = field(default_factory=list)
    skipped: list[SkippedURL] = field(default_factory=list)
    errors: list[CrawlError] = field(default_factory=list)
    cancelled: bool = False
    robots_allowed: bool | None = None
    attempts: int = 0


def site_host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def normalize_url(url: str) -> str:
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    netloc = host + (f":{p.port}" if p.port and p.port not in (80, 443) else "")
    path = re.sub(r"/{2,}", "/", p.path or "/")
    if len(path) > 1:
        path = path.rstrip("/")
    query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not _TRACKING.match(k)))
    return urlunsplit((p.scheme.lower(), netloc, path, query, ""))


def classify_page(url: str, title: str | None = None, anchor: str | None = None) -> str:
    path = urlsplit(url).path.lower().strip("/")
    if not path or path in ("index.html", "index.php", "home", "en", "ms"):
        return "home"
    for kind, pattern, _ in _TYPES:
        if re.search(pattern, path.replace("/", " ")):
            return kind
    for text in (anchor or "", title or ""):
        for kind, pattern, _ in _TYPES:
            if re.search(pattern, text.lower()):
                return kind
    return "other"


def _rank(page_type: str) -> int:
    return next((r for k, _, r in _TYPES if k == page_type), 9)


def _is_interesting(url: str, anchor: str) -> str | None:
    """page_type if the link is worth following, else None."""
    if _SKIP_EXT.search(urlsplit(url).path):
        return None
    kind = classify_page(url, None, anchor)
    return kind if kind not in ("home", "other") else None


async def _cancelled(should_cancel) -> bool:
    if should_cancel is None:
        return False
    res = should_cancel()
    if inspect.isawaitable(res):
        res = await res
    return bool(res)


async def crawl_company_site(start_url: str, fetcher: SafeFetcher, robots: RobotsCache | None,
                             max_pages: int = 25, max_depth: int = 2,
                             should_cancel: Callable[[], bool | Awaitable[bool]] | None = None,
                             max_attempts: int | None = None) -> CrawlResult:
    result = CrawlResult(start_url=start_url)
    try:
        start = validate_url(start_url if "://" in start_url else "https://" + start_url)
    except UnsafeURL as e:
        result.errors.append(CrawlError(start_url, FetchError.UNSAFE_URL, e.reason))
        return result
    p = urlsplit(start)
    base = f"{p.scheme}://{p.netloc}"
    base_site = site_host(start)
    attempts_cap = max_attempts or max_pages + 12

    seen: set[str] = set()
    hashes: set[str] = set()
    # (depth, rank, order, url, anchor, guessed)
    queue: list[tuple[int, int, int, str, str, bool]] = []
    order = 0

    def enqueue(url: str, depth: int, anchor: str = "", guessed: bool = False, kind: str | None = None) -> None:
        nonlocal order
        key = normalize_url(url)
        if key in seen or depth > max_depth or site_host(url) != base_site:
            return
        seen.add(key)
        order += 1
        queue.append((depth, _rank(kind or classify_page(url, None, anchor)), order, url, anchor, guessed))

    enqueue(start, 0)
    guesses_added = False

    while queue and len(result.pages) < max_pages and result.attempts < attempts_cap:
        if await _cancelled(should_cancel):
            result.cancelled = True
            break
        queue.sort(key=lambda q: (q[0], q[1], q[2]))
        depth, _, _, url, anchor, guessed = queue.pop(0)
        result.attempts += 1
        fr: FetchResult = await fetcher.fetch(url, robots=robots)
        if depth == 0 and fr.error_type not in _FATAL:
            result.robots_allowed = fr.error_type != FetchError.ROBOTS_DISALLOWED

        if not fr.ok:
            if fr.error_type in (FetchError.HTTP_404, FetchError.ROBOTS_DISALLOWED, FetchError.NOT_HTML):
                result.skipped.append(SkippedURL(url, fr.error_type.lower(), fr.status_code))
            else:
                result.errors.append(CrawlError(url, fr.error_type or "UNKNOWN", fr.error))
            if depth == 0 and fr.error_type in _FATAL | {FetchError.ROBOTS_DISALLOWED}:
                break
        else:
            final_site = site_host(fr.final_url)
            if final_site != base_site:
                if depth == 0:
                    # The company's site moved (e.g. .com → .com.my): follow it, record the new base.
                    base_site = final_site
                    fp = urlsplit(fr.final_url)
                    base = f"{fp.scheme}://{fp.netloc}"
                else:
                    result.skipped.append(SkippedURL(url, "offsite_redirect", fr.status_code))
                    continue
            for alias in (fr.final_url, fr.canonical_url):
                if alias and site_host(alias) == base_site:
                    seen.add(normalize_url(alias))
            if fr.content_hash in hashes:
                result.skipped.append(SkippedURL(url, "duplicate_content", fr.status_code))
            else:
                hashes.add(fr.content_hash or "")
                canonical = fr.canonical_url if fr.canonical_url and site_host(fr.canonical_url) == base_site else None
                page_url = canonical or fr.final_url
                result.pages.append(CrawledPage(
                    url=url, final_url=fr.final_url, html=fr.html or "", text=fr.text or "", title=fr.title,
                    canonical_url=canonical, page_type=classify_page(page_url, fr.title, anchor), depth=depth,
                    status_code=fr.status_code, content_type=fr.content_type, content_hash=fr.content_hash,
                    fetched_at=fr.fetched_at, links=fr.links, meta=fr.meta))
                if depth < max_depth:
                    for link in fr.links:
                        kind = _is_interesting(link.url, link.text)
                        if kind and urlsplit(link.url).scheme in ("http", "https"):
                            enqueue(link.url, depth + 1, link.text, kind=kind)

        if depth == 0 and not guesses_added:
            if result.errors and result.errors[-1].error_type in _FATAL:
                break
            guesses_added = True
            for path in PRIORITY_PATHS[1:]:
                enqueue(base + path, 1, guessed=True)

    if result.pages and result.base_url is None:
        result.base_url = base
    return result
