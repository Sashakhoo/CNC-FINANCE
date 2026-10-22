"""Public professional-profile references from search results.

Profile URLs are only ever taken from results returned by a permitted search
provider — never constructed, never fetched, never logged into."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from rapidfuzz import fuzz

from app.providers.search.base import SearchResult
from app.services.normalize import normalize_company_name, normalize_person_name

_LEGAL = re.compile(r"\s*,?\s*\b(sdn\.? ?bhd\.?|berhad|bhd|pte\.? ?ltd\.?|private limited|limited|ltd)\.?$", re.I)
_PROFILE_PATH = re.compile(r"^/in/[A-Za-z0-9\-_%]+/?$")
NAME_MATCH_MIN = 85
COMPANY_MATCH_MIN = 80


@dataclass(frozen=True)
class ProfileMatch:
    url: str
    platform: str
    confidence: float
    company_confirmed: bool
    evidence_title: str
    evidence_snippet: str
    provider: str
    query: str


def _short_company(company: str) -> str:
    return _LEGAL.sub("", company.strip()).strip()


def profile_queries(name: str, company: str) -> list[str]:
    short = _short_company(company)
    return [f'site:linkedin.com/in "{name}" "{short}"', f'"{name}" "{short}" linkedin']


def _canonical_profile_url(url: str) -> str | None:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https"):
        return None
    if not (host == "linkedin.com" or host.endswith(".linkedin.com")):
        return None
    if not _PROFILE_PATH.match(parts.path or ""):
        return None
    return f"https://www.linkedin.com{parts.path.rstrip('/')}"


def _title_head(title: str) -> str:
    return re.split(r"\s+[-|–—]\s+|\s*\|\s*", title or "", maxsplit=1)[0]


def _same_name(target: str, head: str) -> bool:
    """Every name token must appear in the result title (order-free; middle
    initials ignored). Fuzzy similarity is too loose for identity: it would
    accept 'Janet Tang' for 'Jane Tan'."""
    want = {t for t in target.split() if len(t) > 1}
    have = set(head.split())
    return bool(want) and want <= have and fuzz.token_set_ratio(target, head) >= NAME_MATCH_MIN


def match_profile_results(name: str, company: str, results: list[SearchResult]) -> list[ProfileMatch]:
    target = normalize_person_name(name)
    company_norm = normalize_company_name(company)
    if not target:
        return []
    found: dict[str, ProfileMatch] = {}
    for r in results:
        url = _canonical_profile_url(r.url)
        if not url:
            continue
        head = normalize_person_name(_title_head(r.title))
        if not _same_name(target, head):
            continue
        company_ok = bool(company_norm) and fuzz.partial_token_set_ratio(
            company_norm, normalize_company_name(f"{r.title} {r.snippet}")) >= COMPANY_MATCH_MIN
        match = ProfileMatch(url=url, platform="LINKEDIN", confidence=0.85 if company_ok else 0.45,
                             company_confirmed=company_ok, evidence_title=r.title, evidence_snippet=r.snippet,
                             provider=r.provider, query=r.query)
        if url not in found or found[url].confidence < match.confidence:
            found[url] = match
    return sorted(found.values(), key=lambda m: m.confidence, reverse=True)
