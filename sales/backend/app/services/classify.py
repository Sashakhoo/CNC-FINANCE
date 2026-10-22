"""Company industry classification and LLM title normalization fallback.
Rules first; an LLM is only consulted when rules can't decide, and its answer
must stay within the allowed values and cite text it was given."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from app.models.base import Department, Seniority
from app.providers.base import ProviderError
from app.services.titles import NormalizedTitle, normalize_title
from app.services.training import keyword_pattern, verbatim_in

log = logging.getLogger("app.classify")

INDUSTRIES = ["Manufacturing", "Engineering", "Electrical", "Electronics", "Automation", "Semiconductor",
              "Technology", "Logistics", "Construction", "Oil & Gas", "Healthcare", "Education", "Retail",
              "Finance", "Other"]

# (term, weight). Specific industries carry more weight than generic "manufacturing".
_TERMS: dict[str, list[tuple[str, float]]] = {
    "Semiconductor": [("semiconductor", 3), ("wafer", 3), ("fab", 2), ("ic packaging", 3), ("osat", 3),
                      ("integrated circuit", 3), ("die bonding", 3)],
    "Electronics": [("electronics", 2.5), ("pcba", 3), ("pcb assembly", 3), ("printed circuit", 3), ("ems", 1.5),
                    ("electronic manufacturing services", 3), ("smt", 2.5), ("box build", 2.5)],
    "Electrical": [("electrical", 2.5), ("switchgear", 3), ("cable", 1.5), ("transformer", 2), ("power distribution", 2.5),
                   ("electrical installation", 3), ("low voltage", 2)],
    "Automation": [("automation", 2.5), ("robotics", 2.5), ("plc", 2.5), ("scada", 2.5), ("machine vision", 2.5),
                   ("industrial automation", 3), ("special purpose machine", 3)],
    "Engineering": [("engineering", 2), ("fabrication", 2), ("precision machining", 3), ("cnc machining", 3),
                    ("mechanical engineering", 3), ("tooling", 2), ("mould", 2), ("mold", 2), ("stamping", 2)],
    "Manufacturing": [("manufacturing", 1.5), ("manufacturer", 1.5), ("factory", 1.5), ("production line", 2),
                      ("plant", 1), ("oem", 1.5), ("contract manufacturing", 2)],
    "Technology": [("software", 2.5), ("saas", 3), ("it services", 3), ("cloud", 1.5), ("app development", 3),
                   ("system integrator", 2.5), ("digital solutions", 2)],
    "Logistics": [("logistics", 3), ("freight", 3), ("warehousing", 3), ("forwarding", 2.5), ("supply chain", 1.5),
                  ("courier", 2.5), ("transportation", 2)],
    "Construction": [("construction", 3), ("contractor", 2), ("civil works", 3), ("building materials", 2.5),
                     ("property development", 2.5), ("m&e", 2)],
    "Oil & Gas": [("oil and gas", 3), ("oil & gas", 3), ("petroleum", 3), ("offshore", 2), ("refinery", 3),
                  ("petrochemical", 3)],
    "Healthcare": [("hospital", 3), ("clinic", 2.5), ("healthcare", 3), ("medical device", 3), ("pharmaceutical", 3)],
    "Education": [("university", 3), ("college", 2.5), ("school", 2), ("education", 2.5), ("training provider", 2)],
    "Retail": [("retail", 3), ("supermarket", 3), ("e-commerce", 2.5), ("outlets", 1.5), ("store", 1)],
    "Finance": [("bank", 2.5), ("insurance", 3), ("financial services", 3), ("fintech", 3), ("investment", 1.5)],
}


@dataclass
class IndustryClassification:
    industry: str
    confidence: float
    evidence_terms: list[str] = field(default_factory=list)
    method: str = "RULES"


def classify_industry(text: str) -> IndustryClassification:
    if not text or not text.strip():
        return IndustryClassification("Other", 0.0, [])
    scores: dict[str, float] = {}
    terms_hit: dict[str, list[str]] = {}
    for industry, terms in _TERMS.items():
        for term, weight in terms:
            n = len(keyword_pattern(term).findall(text))
            if n:
                scores[industry] = scores.get(industry, 0) + weight * min(n, 3)
                terms_hit.setdefault(industry, []).append(term)
    if not scores:
        return IndustryClassification("Other", 0.0, [])
    order = list(_TERMS)
    best = max(scores, key=lambda k: (scores[k], -order.index(k)))
    total = sum(scores.values())
    confidence = round(min(0.95, 0.35 + 0.08 * scores[best]) * (scores[best] / total) ** 0.5, 2)
    return IndustryClassification(best, confidence, terms_hit[best])


class _LLMIndustry(BaseModel):
    industry: str
    evidence_quote: str = Field(description="An exact phrase copied from the text supporting the industry")


async def classify_industry_llm(ai, text: str, allowed: list[str] = INDUSTRIES) -> IndustryClassification:
    rules = classify_industry(text)
    prompt = f"Allowed industries: {', '.join(allowed)}\n\nCompany text:\n{text[:8000]}"
    system = ("Classify the company's industry using only the text given. Pick exactly one allowed industry. "
              "Quote an exact phrase from the text that supports it. If nothing supports a specific industry, answer Other.")
    try:
        out = await ai.generate_structured(system, prompt, _LLMIndustry, max_tokens=300)
    except ProviderError as e:
        log.warning("LLM industry classification failed; using rules", extra={"error_type": e.error_type})
        return rules
    if out.industry not in allowed or (out.industry != "Other" and not verbatim_in(out.evidence_quote, text)):
        return rules
    return IndustryClassification(out.industry, 0.7 if out.industry != "Other" else 0.0,
                                  [out.evidence_quote.strip()] if out.industry != "Other" else [], method="LLM")


# --- title normalization fallback --------------------------------------------

_DEPARTMENTS = tuple(d.value for d in Department)
_SENIORITIES = tuple(s.value for s in Seniority)


class _LLMTitle(BaseModel):
    normalized_title: str = Field(min_length=1, max_length=120)
    department: Literal[_DEPARTMENTS]  # type: ignore[valid-type]
    seniority: Literal[_SENIORITIES]  # type: ignore[valid-type]


@dataclass
class TitleResult:
    normalized_title: str | None
    department: Department
    seniority: Seniority
    method: str  # RULES | LLM | NONE


def _from_rules(n: NormalizedTitle) -> TitleResult:
    return TitleResult(n.normalized_title, n.department, n.seniority, "RULES" if n.matched else "NONE")


async def llm_normalize_title(ai, title: str | None) -> TitleResult:
    """Deterministic rules first; the LLM is asked only for titles they can't place."""
    rules = normalize_title(title)
    if rules.matched or not title or not title.strip() or ai is None:
        return _from_rules(rules)
    system = ("Normalise a job title to a concise standard English title and classify its department and "
              "seniority. Use only the allowed values. Do not invent a different role.")
    prompt = (f"Title: {title.strip()[:200]}\nAllowed departments: {', '.join(_DEPARTMENTS)}\n"
              f"Allowed seniority: {', '.join(_SENIORITIES)}")
    try:
        out = await ai.generate_structured(system, prompt, _LLMTitle, max_tokens=200)
    except ProviderError as e:
        log.warning("LLM title normalization failed; using rules", extra={"error_type": e.error_type})
        return _from_rules(rules)
    clean = re.sub(r"\s+", " ", out.normalized_title).strip()
    return TitleResult(clean, Department(out.department), Seniority(out.seniority), "LLM")
