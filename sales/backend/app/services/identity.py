"""Duplicate detection for companies and contacts (spec §16, §28).

Only identical strong identifiers (same domain; same verified email or same
professional profile URL within one company) are treated as certain. Every
other match is a candidate for human review — never merged automatically.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from rapidfuzz import fuzz

from app.services.normalize import domain_from_url, normalize_company_name, normalize_person_name

REVIEW_THRESHOLD = 0.85


@dataclass
class NameSimilarity:
    score: float
    reasons: list[str]


@dataclass
class DuplicateMatch:
    score: float
    reasons: list[str] = field(default_factory=list)
    is_certain: bool = False

    @property
    def needs_review(self) -> bool:
        return not self.is_certain and self.score >= REVIEW_THRESHOLD


@dataclass
class PersonRecord:
    full_name: str
    company_id: int | None = None
    emails: list[str] = field(default_factory=list)
    profile_urls: list[str] = field(default_factory=list)
    verified_emails: list[str] = field(default_factory=list)
    id: int | None = None


@dataclass
class CompanyRecord:
    legal_name: str
    domain: str | None = None
    phone: str | None = None
    address: str | None = None
    id: int | None = None


# --- names ----------------------------------------------------------------------

def _tokens(name: str) -> list[str]:
    return [t for t in normalize_person_name(name).replace("-", " ").split() if t]


def person_name_similarity(a: str, b: str) -> NameSimilarity:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return NameSimilarity(0.0, ["a name is empty"])
    if ta == tb:
        return NameSimilarity(1.0, ["identical name"])
    if sorted(ta) == sorted(tb):
        return NameSimilarity(0.95, ["same name parts in a different order"])

    full_a = [t for t in ta if len(t) > 1]
    full_b = [t for t in tb if len(t) > 1]
    if full_a and full_b and sorted(full_a) == sorted(full_b):
        return NameSimilarity(0.92, ["same name ignoring a middle initial"])

    sa, sb = set(full_a), set(full_b)
    if len(sa) >= 2 and len(sb) >= 2 and (sa <= sb or sb <= sa):
        return NameSimilarity(0.88, ["one name contains all parts of the other"])

    # "J. Tan" vs "Jane Tan": initials compatible with full names
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    initials_ok = len(short) >= 2 and all(
        any(s == l or (len(s) == 1 and l.startswith(s)) for l in long_) for s in short)
    if initials_ok and any(len(s) == 1 for s in short):
        return NameSimilarity(0.85, ["initials consistent with the full name"])

    ratio = fuzz.token_sort_ratio(" ".join(ta), " ".join(tb)) / 100
    return NameSimilarity(round(ratio * 0.9, 3), [f"name spelling {ratio:.0%} similar"])


# --- contacts -------------------------------------------------------------------

def _norm_email(e: str) -> str:
    return e.strip().lower()


def _norm_profile(url: str) -> str:
    u = url.strip()
    if "://" not in u:
        u = "https://" + u
    p = urlsplit(u)
    host = (p.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    return f"{host}{p.path.rstrip('/').lower()}"


def contact_duplicate_reasons(a: PersonRecord, b: PersonRecord) -> DuplicateMatch:
    same_company = a.company_id is not None and a.company_id == b.company_id
    verified_a = {_norm_email(e) for e in a.verified_emails}
    verified_b = {_norm_email(e) for e in b.verified_emails}
    emails_a = {_norm_email(e) for e in a.emails} | verified_a
    emails_b = {_norm_email(e) for e in b.emails} | verified_b
    profiles_shared = {_norm_profile(u) for u in a.profile_urls} & {_norm_profile(u) for u in b.profile_urls}
    shared_verified = verified_a & verified_b
    shared_email = emails_a & emails_b
    name = person_name_similarity(a.full_name, b.full_name)

    if same_company and shared_verified:
        return DuplicateMatch(1.0, [f"same verified email ({sorted(shared_verified)[0]})", *name.reasons], True)
    if same_company and profiles_shared:
        return DuplicateMatch(1.0, ["same professional profile URL", *name.reasons], True)

    reasons = list(name.reasons)
    score = name.score
    if shared_email:
        score = max(score, 0.95 if same_company else 0.9)
        reasons.append(f"same email ({sorted(shared_email)[0]}), not verified" if same_company
                       else f"same email ({sorted(shared_email)[0]}) at a different company")
    if profiles_shared and not same_company:
        score = max(score, 0.9)
        reasons.append("same professional profile URL at a different company")
    if not same_company and not shared_email and not profiles_shared:
        score = round(score * 0.5, 3)
        reasons.append("different companies")
    return DuplicateMatch(min(score, 0.99), reasons, False)


# --- companies --------------------------------------------------------------------

def _digits(phone: str | None) -> str:
    d = re.sub(r"\D", "", phone or "")
    return d[-9:] if len(d) >= 7 else ""


def _norm_domain(domain: str | None) -> str | None:
    return domain_from_url(domain) if domain else None


def _company_key(name: str) -> str:
    # Dots as spaces first: normalize_company_name alone leaves "sdn" from "Sdn. Bhd.".
    return normalize_company_name(re.sub(r"\.", " ", name))


def company_duplicate_reasons(a: CompanyRecord, b: CompanyRecord) -> DuplicateMatch:
    da, db = _norm_domain(a.domain), _norm_domain(b.domain)
    na, nb = _company_key(a.legal_name), _company_key(b.legal_name)

    if da and da == db:
        return DuplicateMatch(1.0, [f"same website domain ({da})"], True)

    reasons: list[str] = []
    if na and na == nb:
        score = 0.95
        reasons.append("same name ignoring legal suffix (Sdn Bhd, Pte Ltd…)")
    else:
        ratio = fuzz.token_set_ratio(na, nb) / 100 if na and nb else 0.0
        score = round(ratio * 0.9, 3)
        reasons.append(f"names {ratio:.0%} similar")

    if da and db and da != db:
        score = min(score, REVIEW_THRESHOLD)
        reasons.append(f"different domains ({da} vs {db})")

    pa, pb = _digits(a.phone), _digits(b.phone)
    if pa and pa == pb:
        score = min(0.99, max(score + 0.1, REVIEW_THRESHOLD))
        reasons.append("same phone number")

    if a.address and b.address:
        addr = fuzz.token_set_ratio(a.address.lower(), b.address.lower()) / 100
        if addr >= 0.9:
            score = min(0.99, score + 0.05)
            reasons.append(f"addresses {addr:.0%} similar")

    return DuplicateMatch(round(min(score, 0.99), 3), reasons, False)


def find_duplicates(records: list, kind: str, threshold: float = REVIEW_THRESHOLD) -> list[tuple]:
    """All pairs at or above `threshold`, highest score first.
    kind: "contact" (PersonRecord) or "company" (CompanyRecord)."""
    if kind == "contact":
        compare = contact_duplicate_reasons
    elif kind == "company":
        compare = company_duplicate_reasons
    else:
        raise ValueError("kind must be 'contact' or 'company'")
    out = []
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            m = compare(records[i], records[j])
            if m.is_certain or m.score >= threshold:
                out.append((records[i], records[j], m))
    out.sort(key=lambda t: (t[2].is_certain, t[2].score), reverse=True)
    return out
