"""Search results → candidate companies. Only results that look like a
company's own website survive; directories, marketplaces, social networks,
news, job boards and government portals are dropped (they're not the
company), and every candidate keeps the result it came from."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.providers.search.base import SearchResult
from app.services.normalize import domain_from_url, normalize_company_name

BLOCKED_DOMAINS = {
    # social / professional networks
    "facebook.com", "linkedin.com", "instagram.com", "twitter.com", "x.com", "youtube.com", "tiktok.com",
    "pinterest.com", "reddit.com", "medium.com", "wikipedia.org", "quora.com",
    # job boards
    "jobstreet.com", "jobstreet.com.my", "jobstreet.com.sg", "indeed.com", "glassdoor.com", "hiredly.com",
    "maukerja.my", "ricebowl.my", "jobsdb.com", "monster.com", "mycareersfuture.gov.sg", "jora.com",
    # directories / business data
    "yellowpages.my", "yellowpages.com.sg", "businesslist.my", "cybo.com", "kompass.com", "ctos.com.my",
    "dnb.com", "zoominfo.com", "crunchbase.com", "opencorporates.com", "infobel.com", "yelp.com",
    "malaysia-business.com", "cylex.com.my", "bizdirectory.my", "rocketreach.co", "apollo.io",
    "signalhire.com", "lusha.com", "contactout.com", "theorg.com",
    # marketplaces
    "shopee.com.my", "lazada.com.my", "alibaba.com", "made-in-china.com", "indiamart.com", "amazon.com",
    "globalsources.com", "tradeindia.com", "ecvv.com",
    # news / media
    "thestar.com.my", "nst.com.my", "theedgemalaysia.com", "malaymail.com", "freemalaysiatoday.com",
    "bernama.com", "thesun.my", "straitstimes.com", "businesstimes.com.sg", "reuters.com", "bloomberg.com",
    "theedgesingapore.com", "malaysiakini.com", "says.com",
    # search / maps / misc
    "google.com", "maps.google.com", "bing.com", "duckduckgo.com", "waze.com", "foursquare.com",
}
BLOCKED_SUFFIXES = (".gov.my", ".gov.sg", ".gov", ".edu.my", ".edu.sg", ".edu", ".ac.uk", ".mil")

_LISTICLE = re.compile(
    r"\b(top \d+|\d+ (best|top|leading|largest)|best \d+|list of|directory|companies in|"
    r"jobs? (in|at|vacanc)|vacanc(y|ies)|hiring|careers? at|salary|reviews?)\b", re.I)
_LISTING_PATH = re.compile(r"/(directory|listing|listings|companies|company-list|search|tag|category)/", re.I)
_TITLE_SPLIT = re.compile(r"\s+[-|–—:·•]\s+|\s*\|\s*")
_NOISE = re.compile(r"^(home|homepage|welcome( to)?|official (web)?site|about us|contact us)\b[\s:,-]*", re.I)
_LEGAL = re.compile(r"\b(sdn\.? ?bhd\.?|berhad|bhd|pte\.? ?ltd\.?|limited|ltd)\b", re.I)


@dataclass(frozen=True)
class CompanyCandidate:
    name_guess: str
    website: str
    domain: str
    snippet: str
    source_url: str
    provider: str
    query: str
    rank: int
    title: str = ""


def is_blocked_domain(domain: str) -> bool:
    d = domain.lower()
    if d.endswith(BLOCKED_SUFFIXES):
        return True
    return any(d == b or d.endswith("." + b) for b in BLOCKED_DOMAINS)


def looks_like_listing(result: SearchResult) -> bool:
    if _LISTICLE.search(result.title or ""):
        return True
    path = urlsplit(result.url).path or "/"
    return bool(_LISTING_PATH.search(path + "/"))


_PUBLIC_SUFFIXES = sorted([
    "com.my", "net.my", "org.my", "edu.my", "gov.my", "biz.my", "name.my", "com.sg", "net.sg", "org.sg", "edu.sg",
    "gov.sg", "co.uk", "org.uk", "com.au", "net.au", "co.id", "co.th", "com.cn", "com.hk", "co.jp", "co.in",
    "com.ph", "com.vn", "my", "sg", "com", "net", "org", "io", "co", "biz", "asia", "info", "tech", "ai", "app",
], key=lambda s: s.count("."), reverse=True)


def _domain_label(domain: str) -> str:
    """Registrable label: 'web.southernprecision.com.my' -> 'southernprecision'."""
    d = domain.lower().strip(".")
    for suf in _PUBLIC_SUFFIXES:
        if d.endswith("." + suf):
            rest = d[: -len(suf) - 1]
            return rest.split(".")[-1]
    parts = d.split(".")
    return parts[-2] if len(parts) >= 2 else parts[0]


def guess_name(title: str, domain: str) -> str:
    """Pick the title segment that names the company (legal suffix wins);
    fall back to the domain label. A guess only — confirmed later from the site."""
    segments = [_NOISE.sub("", s).strip() for s in _TITLE_SPLIT.split(title or "") if s.strip()]
    segments = [s for s in segments if s]
    for s in segments:
        if _LEGAL.search(s):
            return s
    label = _domain_label(domain).replace("-", "")
    best, best_len = None, 0
    for s in segments:
        compact = normalize_company_name(s).replace(" ", "")
        if compact and (compact in label or label in compact) and len(s) > best_len:
            best, best_len = s, len(s)
    if best:
        return best
    return _domain_label(domain).replace("-", " ").title()


def candidates_from_results(results: list[SearchResult]) -> list[CompanyCandidate]:
    out: list[CompanyCandidate] = []
    seen_domains: set[str] = set()
    seen_names: set[str] = set()
    for r in sorted(results, key=lambda x: x.rank):
        domain = domain_from_url(r.url)
        if not domain or is_blocked_domain(domain) or looks_like_listing(r):
            continue
        if domain in seen_domains:
            continue
        name = guess_name(r.title, domain)
        norm = normalize_company_name(name)
        if norm and norm in seen_names:
            continue
        seen_domains.add(domain)
        if norm:
            seen_names.add(norm)
        scheme = urlsplit(r.url).scheme or "https"
        out.append(CompanyCandidate(
            name_guess=name, website=f"{scheme}://{urlsplit(r.url).hostname}", domain=domain, snippet=r.snippet,
            source_url=r.url, provider=r.provider, query=r.query, rank=r.rank, title=r.title))
    return out
