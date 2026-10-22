"""Company facts from crawled pages (spec §11). Every value carries the
page URL and the exact text it came from; nothing is inferred."""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

from app.crawler.html import CrawledPage, soup_of
from app.extract.common import Evidence, json_ld_objects, ld_str, ld_types, line_at, window

ORG_TYPES = {"Organization", "Corporation", "LocalBusiness", "Company", "ProfessionalService",
             "EducationalOrganization", "NGO", "GovernmentOrganization", "Store", "Manufacturer"}

ROLE_LOCALS = {"info", "sales", "enquiry", "enquiries", "inquiry", "inquiries", "contact", "contactus", "admin",
               "hr", "careers", "career", "jobs", "job", "recruitment", "recruit", "support", "help", "hello",
               "marketing", "finance", "accounts", "account", "office", "general", "service", "services",
               "customerservice", "cs", "billing", "purchasing", "procurement", "media", "press", "pr", "webmaster",
               "noreply", "no-reply", "mail", "team", "operations", "ops", "export", "legal", "privacy", "it"}
_JUNK_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "domain.com", "email.com", "yourdomain.com",
                       "yourcompany.com", "company.com", "sentry.io", "wixpress.com", "sentry-next.wixpress.com",
                       "test.com", "mysite.com"}
_FILE_TLDS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "css", "js", "pdf", "ico", "bmp", "tif", "tiff", "mp4"}
_EMAIL_RE = re.compile(r"(?<![\w.+-])([A-Za-z0-9][A-Za-z0-9._%+-]{0,63})@([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.[A-Za-z]{2,24})(?![\w-])")
_AT = re.compile(r"\s*[\[\(\{]\s*at\s*[\]\)\}]\s*", re.I)
_DOT = re.compile(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*", re.I)

MY_STATES = ["Johor", "Kedah", "Kelantan", "Melaka", "Malacca", "Negeri Sembilan", "Pahang", "Perak", "Perlis",
             "Pulau Pinang", "Penang", "Sabah", "Sarawak", "Selangor", "Terengganu", "Kuala Lumpur",
             "Wilayah Persekutuan", "Putrajaya", "Labuan"]
_STATE_CANON = {"Malacca": "Melaka", "Pulau Pinang": "Penang", "Wilayah Persekutuan": "Kuala Lumpur"}
_STATE_RE = "|".join(sorted((re.escape(s) for s in MY_STATES), key=len, reverse=True))
_MY_ADDR = re.compile(rf"\b(\d{{5}})\s*,?\s*([A-Z][A-Za-z.' ]{{1,40}}?)?\s*,?\s*\b({_STATE_RE})\b")
_JB = re.compile(r"\b(\d{5})\s*,?\s*(Johor Bahru|Johor Bharu|JB)\b")
_SG_ADDR = re.compile(r"\bSingapore\s*,?\s*(\d{6})\b|\bS\s*\(?(\d{6})\)?\b")
_ADDR_HINT = re.compile(r"\b(jalan|jln|lot|no\.?\s*\d|taman|tmn|lorong|persiaran|kawasan|perindustrian|industrial|"
                        r"park|plot|block|blk|level|floor|unit|road|street|avenue|lebuh|bandar|wisma|menara|tower)\b", re.I)

_PHONE_MY = re.compile(r"(?<![\d+])(\+?\s?6?0)[\s.-]?\(?(\d{1,2})\)?[\s.-]?(\d{3,4})[\s.-]?(\d{4})(?!\d)")
_PHONE_SG = re.compile(r"(?<![\d+])(\+?\s?65)[\s.-]?([3689]\d{3})[\s.-]?(\d{4})(?!\d)")
_EMPLOYEES = re.compile(
    r"\b(?:(over|more than|about|approximately|around|nearly|close to|some|almost|exceeding)\s+)?"
    r"(\d{1,3}(?:,\d{3})+|\d{1,6})\s*(\+)?\s*(?:dedicated\s+|skilled\s+|full[- ]time\s+)?"
    r"(employees|staff|workforce|personnel|workers|team members|people)\b", re.I)
_WORKFORCE_OF = re.compile(r"\bworkforce of\s+(?:(over|more than|about|approximately|around|nearly)\s+)?(\d{1,3}(?:,\d{3})+|\d{1,6})\b", re.I)

_SOCIAL = [
    ("LINKEDIN", re.compile(r"^https?://([a-z]{2,3}\.)?(www\.)?linkedin\.com/(company|school|showcase)/[^/?#]+", re.I)),
    ("FACEBOOK", re.compile(r"^https?://(www\.|m\.|web\.)?facebook\.com/(?!sharer|share|dialog|plugins|tr\b)[^?#]+", re.I)),
    ("INSTAGRAM", re.compile(r"^https?://(www\.)?instagram\.com/(?!p/|share)[^/?#]+", re.I)),
    ("YOUTUBE", re.compile(r"^https?://(www\.)?youtube\.com/(channel/|c/|user/|@)[^/?#]+", re.I)),
    ("X", re.compile(r"^https?://(www\.)?(twitter|x)\.com/(?!intent|share|home)[^/?#]+", re.I)),
]
_GENERIC_TITLE_PARTS = {"home", "homepage", "welcome", "about", "about us", "contact", "contact us", "official website",
                        "official site", "index", "main"}


@dataclass
class ExtractedValue:
    value: str
    evidence: Evidence
    confidence: float
    kind: str | None = None
    data: dict = field(default_factory=dict)


@dataclass
class CompanyInfo:
    name_candidates: list[ExtractedValue] = field(default_factory=list)
    descriptions: list[ExtractedValue] = field(default_factory=list)
    emails: list[ExtractedValue] = field(default_factory=list)
    phones: list[ExtractedValue] = field(default_factory=list)
    addresses: list[ExtractedValue] = field(default_factory=list)
    social_links: list[ExtractedValue] = field(default_factory=list)
    employee_counts: list[ExtractedValue] = field(default_factory=list)


def _add(bucket: list[ExtractedValue], item: ExtractedValue, key: str | None = None) -> None:
    k = (key or item.value).lower()
    for existing in bucket:
        if (existing.data.get("_key") or existing.value).lower() == k:
            if item.confidence > existing.confidence:
                existing.confidence = item.confidence
            return
    if key:
        item.data["_key"] = key
    bucket.append(item)


def is_role_email(email: str) -> bool:
    local = email.split("@", 1)[0].lower()
    return local in ROLE_LOCALS or re.sub(r"[\d._-]+$", "", local) in ROLE_LOCALS


def _valid_email(local: str, domain: str) -> bool:
    d = domain.lower()
    tld = d.rsplit(".", 1)[-1]
    if tld in _FILE_TLDS or d in _JUNK_EMAIL_DOMAINS or ".." in local or local.startswith("."):
        return False
    return not re.fullmatch(r"[0-9a-f]{16,}", local.lower())


def find_emails(text: str) -> list[tuple[str, int, int]]:
    """(email, start, end) in `text`, handling '[at]'/'(dot)' obfuscation.
    Positions refer to `text`."""
    found: list[tuple[str, int, int]] = []
    for m in _EMAIL_RE.finditer(text):
        if _valid_email(m.group(1), m.group(2)):
            found.append((f"{m.group(1)}@{m.group(2)}".lower(), m.start(), m.end()))
    for m in re.finditer(r"[A-Za-z0-9._%+-]+" + _AT.pattern + r"[A-Za-z0-9-]+(?:(?:" + _DOT.pattern + r"|\.)[A-Za-z0-9-]+)+",
                         text, re.I):
        clean = _DOT.sub(".", _AT.sub("@", m.group(0)))
        em = _EMAIL_RE.fullmatch(clean)
        if em and _valid_email(em.group(1), em.group(2)):
            found.append((clean.lower(), m.start(), m.end()))
    return found


def normalize_phone(raw: str) -> tuple[str, str] | None:
    """('+6071234567', 'MY') — or None if it isn't a plausible MY/SG number."""
    digits = re.sub(r"\D", "", raw)
    if raw.strip().startswith("+65") or (digits.startswith("65") and len(digits) == 10):
        return ("+" + digits, "SG") if len(digits) == 10 and digits[2] in "3689" else None
    if digits.startswith("60"):
        national = digits[2:]
    elif digits.startswith("0"):
        national = digits[1:]
    else:
        return None
    if not 8 <= len(national) <= 10 or national[0] not in "13456789":
        return None
    if national[0] == "1" and not 9 <= len(national) <= 10:
        return None
    return "+60" + national, "MY"


def _company_from_title(title: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"\s+[|\-–—:»·]\s+", title) if p.strip()]
    return [p for p in parts if p.lower() not in _GENERIC_TITLE_PARTS and len(p) >= 3]


def _extract_page(page: CrawledPage, info: CompanyInfo) -> None:
    url = page.source_url
    soup = soup_of(page.html)
    text = page.text or ""
    weight = 1.0 if page.page_type in ("home", "about", "contact") else 0.85

    # Names
    site_name = page.meta.get("og:site_name")
    if site_name:
        _add(info.name_candidates, ExtractedValue(site_name, Evidence(url, site_name), 0.8 * weight, "og:site_name"))
    if page.title and page.page_type in ("home", "about", "contact"):
        for part in _company_from_title(page.title):
            _add(info.name_candidates, ExtractedValue(part, Evidence(url, page.title), 0.5 * weight, "title"))

    # Structured data
    for obj in json_ld_objects(soup):
        if not ld_types(obj) & ORG_TYPES:
            continue
        for key, conf in (("legalName", 0.95), ("name", 0.9)):
            v = ld_str(obj.get(key))
            if v:
                _add(info.name_candidates, ExtractedValue(v, Evidence(url, v), conf, f"schema.org {key}"))
        desc = ld_str(obj.get("description"))
        if desc:
            _add(info.descriptions, ExtractedValue(desc, Evidence(url, desc), 0.85, "schema.org"))
        tel = ld_str(obj.get("telephone"))
        if tel and (norm := normalize_phone(tel)):
            _add(info.phones, ExtractedValue(norm[0], Evidence(url, tel), 0.9, "phone", {"country": norm[1]}))
        mail = ld_str(obj.get("email"))
        if mail:
            mail = mail.removeprefix("mailto:").strip().lower()
            if _EMAIL_RE.fullmatch(mail):
                _add(info.emails, ExtractedValue(mail, Evidence(url, mail), 0.9, "role" if is_role_email(mail) else "unknown"))
        addr = obj.get("address")
        if isinstance(addr, dict):
            parts = [ld_str(addr.get(k)) for k in ("streetAddress", "postalCode", "addressLocality", "addressRegion", "addressCountry")]
            full = ", ".join(p for p in parts if p)
            if full:
                _add(info.addresses, ExtractedValue(full, Evidence(url, full), 0.9, "schema.org", {
                    "postcode": ld_str(addr.get("postalCode")), "city": ld_str(addr.get("addressLocality")),
                    "state": ld_str(addr.get("addressRegion")), "country": ld_str(addr.get("addressCountry"))}))
        same_as = obj.get("sameAs") or []
        for link in same_as if isinstance(same_as, list) else [same_as]:
            if isinstance(link, str):
                _social(info, link, url, link, 0.9)
        emp = obj.get("numberOfEmployees")
        n = ld_str(emp.get("value") if isinstance(emp, dict) else emp) if emp is not None else None
        if n is None and isinstance(emp, (int, float)):
            n = str(int(emp))
        if n and str(n).replace(",", "").isdigit():
            _add(info.employee_counts, ExtractedValue(str(n).replace(",", ""), Evidence(url, str(n)), 0.85, "schema.org"))

    # Descriptions
    for key, conf in (("description", 0.7), ("og:description", 0.7)):
        v = page.meta.get(key)
        if v and len(v) >= 30:
            _add(info.descriptions, ExtractedValue(v, Evidence(url, v), conf * weight, key))
    if page.page_type == "about":
        for p in soup.find_all("p"):
            t = re.sub(r"\s+", " ", p.get_text(" ")).strip()
            if len(t) >= 80 and t in text:
                _add(info.descriptions, ExtractedValue(t, Evidence(url, t), 0.6, "about paragraph"))
                break

    # Emails: mailto links, then visible text
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("mailto:"):
            addr = unquote(href[7:].split("?", 1)[0]).strip().lower()
            m = _EMAIL_RE.fullmatch(addr)
            if m and _valid_email(m.group(1), m.group(2)):
                label = re.sub(r"\s+", " ", a.get_text(" ")).strip() or href
                _add(info.emails, ExtractedValue(addr, Evidence(url, label), 0.85 * weight,
                                                 "role" if is_role_email(addr) else "unknown"))
        elif href.lower().startswith("tel:"):
            norm = normalize_phone(unquote(href[4:]))
            if norm:
                label = re.sub(r"\s+", " ", a.get_text(" ")).strip() or href
                _add(info.phones, ExtractedValue(norm[0], Evidence(url, label), 0.85 * weight, "phone", {"country": norm[1]}))
        else:
            _social(info, urlsplit(href).geturl() if href.startswith("http") else "", url,
                    re.sub(r"\s+", " ", a.get_text(" ")).strip() or href, 0.8)
    for email, s, e in find_emails(text):
        _add(info.emails, ExtractedValue(email, Evidence(url, window(text, s, e)), 0.8 * weight,
                                         "role" if is_role_email(email) else "unknown"))

    # Phones
    for pattern in (_PHONE_SG, _PHONE_MY):
        for m in pattern.finditer(text):
            norm = normalize_phone(m.group(0))
            if not norm:
                continue
            before = text[max(0, m.start() - 20):m.start()].lower()
            if re.search(r"\b(reg(istration)?|co\.?\s*no|company no|ssm|postcode)\b", before):
                continue
            kind = "fax" if re.search(r"\bfax\b|\bf\s*[:.]", before) else "phone"
            _add(info.phones, ExtractedValue(norm[0], Evidence(url, window(text, m.start(), m.end(), 40)),
                                             0.7 * weight, kind, {"country": norm[1]}))

    # Addresses
    # Johor Bahru first: "81100 Johor Bahru, Johor" must not read as city=None, state=Johor.
    for m in list(_JB.finditer(text)) + list(_MY_ADDR.finditer(text)):
        line = line_at(text, m.start())
        lines = text.split("\n")
        idx = next((i for i, ln in enumerate(lines) if ln.strip() == line), None)
        block = line
        if idx is not None:
            prev = [lines[j] for j in range(max(0, idx - 2), idx) if _ADDR_HINT.search(lines[j]) and len(lines[j]) < 120]
            if prev:
                block = "\n".join(prev + [line])
        postcode = m.group(1)
        if m.re is _JB:
            city, state = "Johor Bahru", "Johor"
        else:
            state = _STATE_CANON.get(m.group(3), m.group(3))
            city = (m.group(2) or "").strip(" ,") or None
            if city and city.lower() in (state.lower(), "malaysia"):
                city = None
        if not (_ADDR_HINT.search(block) or len(block) > len(m.group(0)) + 5):
            continue
        _add(info.addresses, ExtractedValue(block, Evidence(url, block), 0.75 * weight, "MY",
                                            {"postcode": postcode, "city": city, "state": state, "country": "Malaysia"}),
             key=f"{postcode}|{block[:40]}")
    for m in _SG_ADDR.finditer(text):
        postcode = m.group(1) or m.group(2)
        line = line_at(text, m.start())
        if not _ADDR_HINT.search(line) and m.group(2):
            continue
        _add(info.addresses, ExtractedValue(line, Evidence(url, line), 0.7 * weight, "SG",
                                            {"postcode": postcode, "city": "Singapore", "state": None, "country": "Singapore"}),
             key=f"{postcode}|{line[:40]}")

    # Employee counts
    for pattern in (_EMPLOYEES, _WORKFORCE_OF):
        for m in pattern.finditer(text):
            num = (m.group(2) if pattern is _EMPLOYEES else m.group(2)).replace(",", "")
            n = int(num)
            if pattern is _EMPLOYEES and m.group(4).lower() == "people" and not re.search(
                    r"\b(employ|staff|workforce|team of|strong)\b", text[max(0, m.start() - 40):m.end() + 20], re.I):
                continue
            if not 2 <= n <= 500_000:
                continue
            qualifier = (m.group(1) or "").lower() or ("+" if pattern is _EMPLOYEES and m.group(3) else "")
            _add(info.employee_counts, ExtractedValue(str(n), Evidence(url, window(text, m.start(), m.end(), 60)),
                                                      0.7 * weight, "text", {"qualifier": qualifier or None}))


def _social(info: CompanyInfo, href: str, page_url: str, label: str, conf: float) -> None:
    if not href:
        return
    for platform, pattern in _SOCIAL:
        m = pattern.match(href)
        if m:
            link = m.group(0).rstrip("/")
            _add(info.social_links, ExtractedValue(link, Evidence(page_url, label), conf, platform))
            return


def extract_company_info(pages: Iterable[CrawledPage]) -> CompanyInfo:
    info = CompanyInfo()
    for page in pages:
        if page.html:
            _extract_page(page, info)
    for bucket in (info.name_candidates, info.descriptions, info.emails, info.phones, info.addresses,
                   info.social_links, info.employee_counts):
        bucket.sort(key=lambda v: -v.confidence)
        for v in bucket:
            v.data.pop("_key", None)
    return info
