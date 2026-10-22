"""Decision-maker candidates from company pages (spec §12–13).

A person is returned only when their name literally appears on the page next
to a job title. No guessing, no enrichment — that is a later, separate step."""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from app.crawler.html import CrawledPage, soup_of
from app.extract.common import json_ld_objects, ld_str, ld_types
from app.extract.company import _EMAIL_RE, find_emails, is_role_email

PEOPLE_PAGE_TYPES = {"team", "about", "news", "home", "contact"}

_HONORIFIC = r"(?:(?:Mr|Mrs|Ms|Mdm|Madam|Miss|Dr|Ir|Ts|Prof|Assoc\.? Prof|Sr|Ar|Hj|Haji|Hajah|Puan|Encik|Cik|" \
             r"Dato'?\s*Sri|Datuk\s*Seri|Dato'?|Datuk|Datin|Tan Sri|Toh Puan|Tun|Yb|YBhg|Sir)\.?\s+)"
_PARTICLES = {"bin", "binti", "bt", "bte", "b.", "a/l", "a/p", "al", "ap", "de", "van", "von", "der", "da", "dos",
              "@", "s/o", "d/o", "anak", "ak", "binte"}
_TITLE_WORDS = re.compile(
    r"\b(manager|director|head|chief|officer|ceo|cto|cio|coo|cfo|cmo|chro|founder|co-founder|president|vp|"
    r"vice president|engineer|lead|executive|chairman|chairperson|chairwoman|partner|owner|general manager|gm|"
    r"supervisor|specialist|consultant|coordinator|superintendent|principal|secretary|treasurer|controller|"
    r"accountant|administrator|analyst|managing|deputy|assistant|associate|senior|hr|human resources?|"
    r"l&d|learning|training|talent|people|operations|technical|technology|it|board|trustee|advisor|adviser|"
    r"proprietor|architect|scientist|developer|programmer|planner|buyer|purchaser|sales|marketing)\b", re.I)
_NOT_NAME_WORDS = {
    "team", "our", "the", "management", "leadership", "about", "us", "contact", "services", "service", "company",
    "solutions", "board", "directors", "meet", "read", "more", "view", "profile", "home", "news", "careers", "career",
    "engineering", "products", "product", "group", "sdn", "bhd", "berhad", "ltd", "limited", "pte", "inc", "corp",
    "corporation", "industries", "industry", "technology", "technologies", "systems", "automation", "precision",
    "manufacturing", "malaysia", "singapore", "johor", "bahru", "kuala", "lumpur", "penang", "selangor", "office",
    "headquarters", "department", "division", "welcome", "message", "vision", "mission", "values", "history",
    "copyright", "rights", "reserved", "privacy", "policy", "terms", "email", "phone", "tel", "fax", "address",
    "click", "here", "learn", "join", "apply", "now", "submit", "send", "follow", "subscribe", "and", "of", "for",
    "with", "in", "on", "at", "to", "by", "is", "are", "we", "you", "your", "its", "new", "all", "staff", "people",
    "key", "personnel", "executive", "committee", "profile", "linkedin", "facebook", "jan", "feb", "mar", "apr",
    "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec", "monday", "friday", "quality", "safety", "customer",
    "customers", "partners", "award", "awards", "certified", "iso", "chairman", "founder", "ceo",
}
_SEPARATORS = re.compile(r"\s+[–—-]\s+|\s*\|\s*|,\s+(?=[A-Za-z])")


@dataclass
class ExtractedPerson:
    full_name: str
    original_title: str | None
    source_url: str
    evidence: str
    confidence: float
    method: str                  # schema_org | microdata | team_card | text_line | caption
    email: str | None = None
    email_evidence: str | None = None
    profile_url: str | None = None


def _strip_honorific(name: str) -> str:
    return re.sub(rf"^{_HONORIFIC}+", "", name.strip(), flags=re.I).strip()


def looks_like_person_name(s: str, company_names: Iterable[str] = ()) -> bool:
    s = re.sub(r"\s+", " ", (s or "")).strip().strip(",:;")
    if not 4 <= len(s) <= 60 or re.search(r"[\d@#&/\\|()\[\]{}<>=+*!?:;\"]", s.replace("a/l", "").replace("a/p", "")
                                                                               .replace("s/o", "").replace("d/o", "")):
        return False
    core = _strip_honorific(s)
    tokens = core.split()
    if not 2 <= len(tokens) <= 6:
        return False
    if _TITLE_WORDS.search(core):
        return False
    low = core.lower()
    for cn in company_names:
        if cn and (low == cn.lower() or low in cn.lower()):
            return False
    name_tokens = 0
    for t in tokens:
        tl = t.lower().strip(".,'")
        if tl in _PARTICLES:
            continue
        if tl in _NOT_NAME_WORDS:
            return False
        if not re.fullmatch(r"[A-Z][A-Za-z'’.-]*|[A-Z]{2,}", t.strip(",")):
            return False
        name_tokens += 1
    return name_tokens >= 2 or (name_tokens == 1 and any(t.lower() in _PARTICLES for t in tokens))


def looks_like_title(s: str) -> bool:
    s = (s or "").strip()
    if not 2 <= len(s) <= 100 or s.count(".") > 2 or len(s.split()) > 12:
        return False
    return bool(_TITLE_WORDS.search(s)) and not re.search(r"\b(we|our|you|your|is|are|was|will)\b", s, re.I)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _name_tokens(name: str) -> list[str]:
    return [t.lower().strip(".,'’") for t in _strip_honorific(name).split() if t.lower() not in _PARTICLES]


def _email_matches(email: str, name: str) -> bool:
    if is_role_email(email):
        return False
    local = re.sub(r"[^a-z]", "", email.split("@", 1)[0].lower())
    toks = [t for t in (re.sub(r"[^a-z]", "", x) for x in _name_tokens(name)) if len(t) >= 2]
    if not toks or not local:
        return False
    if any(len(t) >= 3 and t in local for t in toks):
        return True
    initials = "".join(t[0] for t in toks)
    return local in (initials, toks[0][0] + toks[-1], toks[-1] + toks[0][0])


def _linkedin_near(soup: BeautifulSoup, name: str) -> str | None:
    node = soup.find(string=lambda t: t and name in t)
    container = node.parent if node else None
    for _ in range(3):
        if not isinstance(container, Tag):
            return None
        links = {a["href"].split("?", 1)[0].rstrip("/") for a in container.find_all("a", href=True)
                 if re.match(r"^https?://([a-z]{2,3}\.)?(www\.)?linkedin\.com/in/[^/?#]+", a["href"], re.I)}
        if len(links) == 1:
            return links.pop()
        if len(links) > 1:
            return None
        container = container.parent
    return None


def _from_structured(page: CrawledPage, soup: BeautifulSoup, company_names: list[str]) -> list[ExtractedPerson]:
    out = []
    url = page.source_url
    for obj in json_ld_objects(soup):
        if "Person" not in ld_types(obj):
            continue
        name = ld_str(obj.get("name"))
        if not name or name not in page.html or not looks_like_person_name(name, company_names):
            continue
        title = ld_str(obj.get("jobTitle"))
        email = ld_str(obj.get("email"))
        email = email.removeprefix("mailto:").lower() if email else None
        if email and not _EMAIL_RE.fullmatch(email):
            email = None
        same_as = obj.get("sameAs") or []
        same_as = same_as if isinstance(same_as, list) else [same_as]
        profile = next((s for s in same_as if isinstance(s, str) and "linkedin.com/in/" in s.lower()), None)
        out.append(ExtractedPerson(name, title, url, f"{name}" + (f" — {title}" if title else ""), 0.9,
                                   "schema_org", email, email, profile))
    for scope in soup.find_all(attrs={"itemtype": re.compile(r"schema\.org/Person", re.I)}):
        n = scope.find(attrs={"itemprop": "name"})
        t = scope.find(attrs={"itemprop": "jobTitle"})
        name = _clean(n.get_text(" ")) if n else ""
        if name and looks_like_person_name(name, company_names):
            title = _clean(t.get_text(" ")) if t else None
            out.append(ExtractedPerson(name, title, url, _clean(scope.get_text(" "))[:300], 0.85, "microdata"))
    return out


def _from_text(page: CrawledPage, company_names: list[str]) -> list[ExtractedPerson]:
    out: list[ExtractedPerson] = []
    lines = (page.text or "").split("\n")
    used: set[int] = set()
    url = page.source_url
    boost = 0.1 if page.page_type == "team" else 0.0
    for i, line in enumerate(lines):
        if i in used:
            continue
        # "Name – Title" / "Name, Title" / "Name | Title" on one line
        parts = _SEPARATORS.split(line, maxsplit=1)
        if len(parts) == 2 and looks_like_person_name(parts[0], company_names) and looks_like_title(parts[1]):
            out.append(ExtractedPerson(_clean(parts[0]), _clean(parts[1]), url, line, 0.6 + boost, "text_line"))
            used.add(i)
            continue
        if looks_like_person_name(line, company_names):
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if looks_like_title(nxt):
                out.append(ExtractedPerson(_clean(line), _clean(nxt), url, f"{line}\n{nxt}", 0.7 + boost, "team_card"))
                used.update({i, i + 1})
                continue
            prev = lines[i - 1] if i > 0 else ""
            if i - 1 not in used and looks_like_title(prev) and not looks_like_person_name(prev, company_names):
                out.append(ExtractedPerson(_clean(line), _clean(prev), url, f"{prev}\n{line}", 0.55 + boost, "team_card"))
                used.update({i - 1, i})
    return out


def _attach_emails(people: list[ExtractedPerson], page: CrawledPage) -> None:
    text = page.text or ""
    emails = [(e, s, end) for e, s, end in find_emails(text)]
    mailtos = {m.group(0).lower() for m in _EMAIL_RE.finditer(" ".join(
        a.get("href", "")[7:] for a in soup_of(page.html).find_all("a", href=True) if a["href"].lower().startswith("mailto:")))}
    for p in people:
        if p.email:
            continue
        candidates = [e for e, _, _ in emails if _email_matches(e, p.full_name)] + \
                     [e for e in mailtos if _email_matches(e, p.full_name)]
        unique = sorted(set(candidates))
        if len(unique) == 1:
            p.email = unique[0]
            p.email_evidence = unique[0]


def extract_people(page: CrawledPage, company_names: Iterable[str] = ()) -> list[ExtractedPerson]:
    if not page.html:
        return []
    names = [c for c in company_names if c]
    soup = soup_of(page.html)
    found = _from_structured(page, soup, names)
    if page.page_type in PEOPLE_PAGE_TYPES or page.page_type == "other":
        found += _from_text(page, names)
    by_name: dict[str, ExtractedPerson] = {}
    for p in found:
        if p.full_name not in page.html and p.full_name not in (page.text or ""):
            continue  # never return a name that isn't literally on the page
        key = " ".join(_name_tokens(p.full_name))
        cur = by_name.get(key)
        if cur is None or p.confidence > cur.confidence:
            if cur is not None:
                p.original_title = p.original_title or cur.original_title
                p.email = p.email or cur.email
                p.profile_url = p.profile_url or cur.profile_url
            by_name[key] = p
        else:
            cur.original_title = cur.original_title or p.original_title
    people = list(by_name.values())
    _attach_emails(people, page)
    for p in people:
        if not p.profile_url:
            p.profile_url = _linkedin_near(soup, p.full_name)
    return people


def extract_people_from_pages(pages: Iterable[CrawledPage], company_names: Iterable[str] = ()) -> list[ExtractedPerson]:
    names = list(company_names)
    out: list[ExtractedPerson] = []
    for page in pages:
        out.extend(extract_people(page, names))
    return out
