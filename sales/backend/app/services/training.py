"""TRAINING MATCH — which Codencode programme fits a company, and why.

Rules mode: a programme is recommended only when collected text actually
mentions one of its keywords (or a signal points to it). Every evidence quote
is an exact sentence from a supplied page or signal. An industry prior can
raise the score but never creates an opportunity on its own, and is labelled
"industry-based" in the reason. Programmes with no evidence are omitted.

LLM mode: the model proposes programmes and quotes; each quote must be a
verbatim (whitespace/case-insensitive) substring of the supplied text or it is
dropped, a recommendation with no surviving quote is rejected, and anything
the LLM can't support falls back to the rules result."""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field

from pydantic import BaseModel, Field

from app.providers.base import ProviderError

log = logging.getLogger("app.training")

MAX_RULES_SCORE = 95
MAX_EVIDENCE = 3


@dataclass
class CompanyFacts:
    name: str
    industry: str | None = None
    description: str | None = None
    employee_estimate: int | None = None


@dataclass
class PageText:
    url: str
    text: str
    page_type: str | None = None


@dataclass
class SignalFact:
    signal_type: str
    title: str
    quote: str
    source_url: str | None


@dataclass
class ProgramDef:
    code: str
    name: str
    keywords: list[str]
    target_departments: list[str] = field(default_factory=list)


@dataclass
class Opportunity:
    program_code: str
    program_name: str
    match_score: int
    reason: str
    target_department: str | None
    recommended_decision_maker: str | None
    evidence: list[dict]
    alternative_program_codes: list[str] = field(default_factory=list)
    method: str = "RULES"

    def to_dict(self) -> dict:
        return asdict(self)


def programs_from_defaults() -> list[ProgramDef]:
    from app.services.defaults import TRAINING_PROGRAMS
    return [ProgramDef(code=c, name=n, keywords=k, target_departments=d) for c, n, _desc, d, k in TRAINING_PROGRAMS]


# --- text helpers (shared with classify / outreach) -------------------------

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', " ": " ", "–": "-",
                         "—": "-"})


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_QUOTES)).strip().lower()


def verbatim_in(quote: str, text: str) -> bool:
    q = norm(quote).strip(" .\"'")
    return len(q) >= 12 and q in norm(text)


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+|\s*[•·|]\s*", text)
    return [re.sub(r"\s+", " ", p).strip() for p in parts if 20 <= len(p.strip()) <= 400]


def keyword_pattern(kw: str) -> re.Pattern:
    return re.compile(r"(?<![a-z0-9])" + re.escape(kw.lower()).replace(r"\ ", r"\s+") + r"(?![a-z0-9])", re.I)


# --- rules ----------------------------------------------------------------

# Industry priors: labelled as industry-based in the reason, never sufficient alone.
INDUSTRY_PRIORS: dict[str, list[str]] = {
    "Manufacturing": ["AI_PRODUCTIVITY", "PYTHON_AUTOMATION", "DATA_ANALYTICS"],
    "Engineering": ["AI_FOR_ENGINEERS", "PYTHON_PROGRAMMING", "DATA_ANALYTICS"],
    "Automation": ["AI_FOR_ENGINEERS", "PYTHON_AUTOMATION"],
    "Electrical": ["AI_FOR_ENGINEERS", "CYBERSECURITY_AWARENESS"],
    "Electronics": ["DATA_ANALYTICS", "AI_FOR_ENGINEERS"],
    "Semiconductor": ["DATA_ANALYTICS", "TECHNICAL_CYBERSECURITY"],
    "Technology": ["GENERATIVE_AI", "SOFTWARE_DEVELOPMENT", "TECHNICAL_CYBERSECURITY"],
    "Logistics": ["DIGITAL_TRANSFORMATION", "AI_PRODUCTIVITY"],
    "Construction": ["DIGITAL_TRANSFORMATION", "CYBERSECURITY_AWARENESS"],
}
INDUSTRY_PRIOR_POINTS = 8

# signal_type substrings → programmes they support.
SIGNAL_PROGRAMS: list[tuple[str, list[str]]] = [
    ("cyber", ["CYBERSECURITY_AWARENESS", "TECHNICAL_CYBERSECURITY"]),
    ("security", ["CYBERSECURITY_AWARENESS", "TECHNICAL_CYBERSECURITY"]),
    ("ai", ["GENERATIVE_AI", "ARTIFICIAL_INTELLIGENCE", "AI_PRODUCTIVITY"]),
    ("automation", ["PYTHON_AUTOMATION", "AI_FOR_ENGINEERS"]),
    ("industry_4", ["AI_FOR_ENGINEERS", "DATA_ANALYTICS"]),
    ("industry 4", ["AI_FOR_ENGINEERS", "DATA_ANALYTICS"]),
    ("digital", ["DIGITAL_TRANSFORMATION"]),
    ("erp", ["DIGITAL_TRANSFORMATION", "DATA_ANALYTICS"]),
    ("cloud", ["SOFTWARE_DEVELOPMENT", "TECHNICAL_CYBERSECURITY"]),
    ("hiring_it", ["SOFTWARE_DEVELOPMENT", "TECHNICAL_CYBERSECURITY"]),
    ("hiring_engineer", ["AI_FOR_ENGINEERS", "PYTHON_PROGRAMMING"]),
    ("data", ["DATA_ANALYTICS"]),
    ("training", ["AI_PRODUCTIVITY"]),
    ("employee_development", ["AI_PRODUCTIVITY"]),
]

DEPARTMENT_DECISION_MAKER = {
    "HR": "HR Manager", "L&D": "L&D Manager", "IT": "IT Manager", "Engineering": "Engineering Manager",
    "Operations": "Operations Manager", "Management": "Managing Director",
}


def _signal_matches(signal: SignalFact, program_code: str) -> bool:
    st = re.sub(r"[\s-]+", "_", signal.signal_type.lower())
    tokens = st.split("_")
    for needle, codes in SIGNAL_PROGRAMS:
        if program_code not in codes:
            continue
        n = needle.replace(" ", "_")
        if "_" in n:
            hit = re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z])", st)
        else:  # short needles ("ai") must be a whole token; longer ones may prefix ("cyber" → "cybersecurity")
            hit = any(t == n or (len(n) >= 4 and t.startswith(n)) for t in tokens)
        if hit:
            return True
    return False


def _evidence_for(program: ProgramDef, pages: list[PageText]) -> tuple[list[dict], list[str], int]:
    """Returns (evidence, matched keywords, number of distinct pages)."""
    patterns = [(kw, keyword_pattern(kw)) for kw in program.keywords if kw.strip()]
    hits: list[tuple[int, str, str, set[str]]] = []  # (keyword count, url, sentence, keywords)
    for page in pages:
        for s in sentences(page.text):
            found = {kw for kw, p in patterns if p.search(s)}
            if found:
                hits.append((len(found), page.url, s, found))
    hits.sort(key=lambda h: -h[0])
    evidence, used_kw, pages_seen, seen_sent = [], set(), set(), set()
    for _, url, s, found in hits:
        key = norm(s)
        if key in seen_sent:
            continue
        # Prefer sentences that add a new keyword or a new page.
        if len(evidence) < MAX_EVIDENCE and (found - used_kw or url not in pages_seen or not evidence):
            evidence.append({"source_url": url or None, "quote": s})
            seen_sent.add(key)
        used_kw |= found
        pages_seen.add(url)
    all_kw = sorted(used_kw, key=lambda k: program.keywords.index(k) if k in program.keywords else 99)
    return evidence, all_kw, len(pages_seen)


def _decision_maker(program: ProgramDef) -> tuple[str | None, str | None]:
    dept = program.target_departments[0] if program.target_departments else None
    return dept, DEPARTMENT_DECISION_MAKER.get(dept or "", None)


def analyze_training(company: CompanyFacts, pages: list[PageText], signals: list[SignalFact],
                     programs: list[ProgramDef]) -> list[Opportunity]:
    all_pages = list(pages)
    if company.description:
        all_pages.append(PageText(url="", text=company.description, page_type="description"))
    results: list[Opportunity] = []
    for program in programs:
        evidence, keywords, n_pages = _evidence_for(program, all_pages)
        sig = [s for s in signals if _signal_matches(s, program.code) and s.quote.strip()]
        if not evidence and not sig:
            continue
        score = 40 + 12 * min(len(keywords), 3) + 4 * min(n_pages, 3)
        reasons = []
        if keywords:
            where = f"{n_pages} page{'s' if n_pages != 1 else ''}" if n_pages else "the company description"
            reasons.append(f"Company content mentions {', '.join(repr(k) for k in keywords[:4])} ({where}).")
        for s in sig[:2]:
            score += 10
            evidence.append({"source_url": s.source_url, "quote": s.quote.strip()})
            reasons.append(f"Signal: {s.title}.")
        if company.industry and program.code in INDUSTRY_PRIORS.get(company.industry, []):
            score += INDUSTRY_PRIOR_POINTS
            reasons.append(f"Industry-based: {company.industry} companies commonly need {program.name}.")
        dept, dm = _decision_maker(program)
        results.append(Opportunity(
            program_code=program.code, program_name=program.name, match_score=min(MAX_RULES_SCORE, score),
            reason=" ".join(reasons), target_department=dept, recommended_decision_maker=dm,
            evidence=evidence[:MAX_EVIDENCE + 2]))
    results.sort(key=lambda o: -o.match_score)
    for o in results:
        o.alternative_program_codes = [x.program_code for x in results if x is not o][:2]
    return results


# --- LLM mode -----------------------------------------------------------

class _LLMQuote(BaseModel):
    source_id: str = Field(description="The [S#] id of the source the quote comes from")
    quote: str = Field(description="An exact sentence copied from that source")


class _LLMRecommendation(BaseModel):
    program_code: str
    match_score: int = Field(ge=0, le=100)
    reason: str = Field(max_length=600)
    quotes: list[_LLMQuote]


class _LLMTraining(BaseModel):
    recommendations: list[_LLMRecommendation]


_SYSTEM = (
    "You assess which corporate technology training programmes fit a company. Use ONLY the numbered sources "
    "provided. Every recommendation must cite exact sentences copied verbatim from the sources. Do not use "
    "outside knowledge, do not guess facts, and omit programmes the sources don't support."
)


def unsupported_tokens(text: str, sources: list[str]) -> list[str]:
    """Numbers, URLs, emails and capitalised words in `text` that never appear in `sources`."""
    corpus = norm(" ".join(sources))
    words = set(re.findall(r"[a-z0-9][a-z0-9&'.-]*", corpus))
    bad = []
    for tok in re.findall(r"https?://\S+|\S+@\S+\.\S+|\b\d[\d,.%]*\b", text):
        if norm(tok).rstrip(".,") not in corpus:
            bad.append(tok)
    for m in re.finditer(r"\b([A-Z][a-zA-Z&'-]{2,})\b", text):
        before = text[: m.start()].rstrip(" \t\"'(")
        if not before or before[-1] in ".!?:\n,":
            continue  # sentence start / greeting — capitalised for grammar, not a name
        w = re.sub(r"'s$", "", m.group(1).lower())
        if w not in words and w not in _COMMON_CAPS:
            bad.append(m.group(1))
    return bad


_COMMON_CAPS = {
    "the", "this", "that", "they", "their", "these", "our", "your", "you", "we", "hi", "hello", "dear", "best",
    "regards", "thanks", "thank", "kind", "warm", "cheers", "sincerely", "looking", "would", "could", "are", "is",
    "it", "its", "and", "with", "for", "from", "programme", "program", "training", "team", "teams", "company",
    "corporate", "academy", "monday", "tuesday", "wednesday", "thursday", "friday", "linkedin", "email", "ai",
    "it's", "i'm", "i'd", "i've", "let", "happy", "glad", "quick", "following", "follow", "just", "hope", "re",
}


async def analyze_training_llm(ai, company: CompanyFacts, pages: list[PageText], signals: list[SignalFact],
                               programs: list[ProgramDef], max_chars: int = 12000) -> list[Opportunity]:
    rules = analyze_training(company, pages, signals, programs)
    sources: dict[str, tuple[str | None, str]] = {}
    for i, p in enumerate(pages, 1):
        sources[f"S{i}"] = (p.url, p.text)
    for j, s in enumerate(signals, len(pages) + 1):
        sources[f"S{j}"] = (s.source_url, s.quote)
    if company.description:
        sources[f"S{len(sources) + 1}"] = (None, company.description)
    if not sources:
        return rules

    budget, chunks = max_chars, []
    for sid, (url, text) in sources.items():
        piece = f"[{sid}] {url or 'company description'}\n{text[: max(0, budget)]}"
        budget -= len(piece)
        chunks.append(piece)
        if budget <= 0:
            break
    allowed = {p.code: p for p in programs}
    prompt = (f"Company: {company.name}\nIndustry: {company.industry or 'unknown'}\n\n"
              f"Programmes (code: name): " + "; ".join(f"{p.code}: {p.name}" for p in programs) +
              "\n\nSources:\n" + "\n\n".join(chunks))
    try:
        out = await ai.generate_structured(_SYSTEM, prompt, _LLMTraining, max_tokens=1500)
    except ProviderError as e:
        log.warning("LLM training analysis failed; using rules", extra={"error_type": e.error_type})
        return rules

    validated: dict[str, Opportunity] = {}
    texts = [t for _, t in sources.values()]
    for rec in out.recommendations:
        program = allowed.get(rec.program_code)
        if not program or rec.program_code in validated:
            continue
        evidence = []
        for q in rec.quotes:
            src = sources.get(q.source_id.strip("[] "))
            if src and verbatim_in(q.quote, src[1]):
                evidence.append({"source_url": src[0], "quote": q.quote.strip()})
                continue
            match = next(((u, t) for u, t in sources.values() if verbatim_in(q.quote, t)), None)
            if match:
                evidence.append({"source_url": match[0], "quote": q.quote.strip()})
        if not evidence:
            continue
        reason = rec.reason.strip()
        if not reason or unsupported_tokens(reason, texts + [company.name, company.industry or "", program.name]):
            reason = f"Sources reference {program.name}-related activity (see evidence)."
        dept, dm = _decision_maker(program)
        validated[program.code] = Opportunity(
            program_code=program.code, program_name=program.name, match_score=min(MAX_RULES_SCORE, rec.match_score),
            reason=reason, target_department=dept, recommended_decision_maker=dm, evidence=evidence[:MAX_EVIDENCE],
            method="LLM")
    if not validated:
        return rules
    merged = list(validated.values()) + [o for o in rules if o.program_code not in validated]
    merged.sort(key=lambda o: -o.match_score)
    for o in merged:
        o.alternative_program_codes = [x.program_code for x in merged if x is not o][:2]
    return merged
