"""Domain resolution (spec §8): which website belongs to this company?

A domain-name similarity alone can never resolve a company — page evidence
(homepage title, About text) is required to clear the threshold. Uncertain
cases are returned as UNCERTAIN with every candidate's score, for review."""
from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz import fuzz

from app.services.discovery.candidates import _domain_label
from app.services.normalize import normalize_company_name

RESOLVE_THRESHOLD = 0.75
MIN_LEAD = 0.10

W_NAME, W_TITLE, W_ABOUT, W_LOCATION = 0.45, 0.35, 0.12, 0.08


@dataclass(frozen=True)
class DomainScore:
    domain: str
    confidence: float
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DomainEvidence:
    domain: str
    homepage_title: str | None = None
    about_text: str | None = None
    address_text: str | None = None


@dataclass(frozen=True)
class DomainResolution:
    status: str                    # RESOLVED | UNCERTAIN | NONE
    domain: str | None
    confidence: float
    scores: list[DomainScore]


def _initials(norm: str) -> str:
    return "".join(w[0] for w in norm.split() if w)


def score_domain(company_name: str, domain: str, homepage_title: str | None = None, about_text: str | None = None,
                 location_hint: str | None = None, address_text: str | None = None) -> DomainScore:
    norm = normalize_company_name(company_name)
    compact = norm.replace(" ", "")
    label = _domain_label(domain.lower()).replace("-", "")
    reasons: list[str] = []

    name_sim = fuzz.ratio(compact, label) / 100 if compact and label else 0.0
    if len(label) >= 4 and compact:
        name_sim = max(name_sim, fuzz.partial_ratio(label, compact) / 100 * (0.95 if label in compact else 0.85))
    if len(norm.split()) >= 2 and label == _initials(norm):
        name_sim = max(name_sim, 0.85)
        reasons.append("domain is the company's initials")
    reasons.append(f"domain name similarity {name_sim:.0%}")

    title_sim = 0.0
    if homepage_title:
        title_sim = fuzz.token_set_ratio(norm, normalize_company_name(homepage_title)) / 100
        reasons.append(f"homepage title similarity {title_sim:.0%}")
    else:
        reasons.append("no homepage title checked")

    about_hit = 0.0
    if about_text and norm and norm in normalize_company_name(about_text):
        about_hit = 1.0
        reasons.append("company name appears on the site's About text")

    loc_hit = 0.0
    if location_hint:
        hay = " ".join(x for x in (address_text, about_text, homepage_title) if x).lower()
        if location_hint.lower() in hay:
            loc_hit = 1.0
            reasons.append(f"site mentions {location_hint}")

    conf = W_NAME * name_sim + W_TITLE * title_sim + W_ABOUT * about_hit + W_LOCATION * loc_hit
    return DomainScore(domain=domain.lower(), confidence=round(min(conf, 1.0), 3), reasons=reasons)


def resolve(company_name: str, candidates: list[DomainEvidence], location_hint: str | None = None) -> DomainResolution:
    if not candidates:
        return DomainResolution("NONE", None, 0.0, [])
    scores = sorted(
        (score_domain(company_name, c.domain, c.homepage_title, c.about_text, location_hint, c.address_text)
         for c in candidates),
        key=lambda s: s.confidence, reverse=True)
    best = scores[0]
    runner = scores[1].confidence if len(scores) > 1 else 0.0
    if best.confidence >= RESOLVE_THRESHOLD and best.confidence - runner >= MIN_LEAD:
        return DomainResolution("RESOLVED", best.domain, best.confidence, scores)
    return DomainResolution("UNCERTAIN", None, best.confidence, scores)
