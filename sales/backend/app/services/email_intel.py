"""Email intelligence that needs no provider: syntax checks, role/generic
classification, and company email-pattern detection + inference.

Inference rules (spec §19): a pattern is only ever derived from real example
addresses on the company's own domain (or reported by a provider). With no
evidence, nothing is inferred. Every inferred address is labelled INFERRED /
EMAIL_PATTERN / UNVERIFIED and its confidence is capped."""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

from email_validator import EmailNotValidError, validate_email

from app.models.base import EmailDiscoveryMethod, EmailType, Provenance, VerificationStatus

# Inbox-style addresses that reach "the company", not a person.
GENERIC_LOCALS = {
    "info", "enquiry", "enquiries", "inquiry", "inquiries", "contact", "contactus", "hello", "hi", "admin", "office",
    "mail", "general", "reception", "webmaster", "postmaster", "noreply", "no-reply", "donotreply", "team", "main",
}
# Department/function addresses.
ROLE_LOCALS = {
    "hr", "humanresource", "humanresources", "careers", "career", "jobs", "job", "recruit", "recruitment",
    "recruiting", "hiring", "talent", "sales", "marketing", "support", "help", "helpdesk", "service",
    "customerservice", "cs", "finance", "accounts", "account", "accounting", "billing", "purchasing",
    "procurement", "purchase", "it", "training", "learning", "legal", "media", "press", "pr", "ops",
    "operations", "engineering", "admission", "admissions", "payroll", "compliance", "security", "privacy", "qa",
    "quality", "export", "import", "logistics", "shipping", "store", "orders", "order", "partners", "partnership",
}

PATTERNS = [
    "{first}.{last}", "{first}{last}", "{f}{last}", "{f}.{last}", "{first}", "{first}_{last}",
    "{last}.{first}", "{last}{f}", "{first}{l}", "{first}-{last}", "{last}",
]

_PATRONYMIC = re.compile(r"\b(bin|binti|bte|bt|a/l|a/p|s/o|d/o)\b", re.I)
SINGLE_EXAMPLE_CAP = 0.5
MULTI_EXAMPLE_CAP = 0.7
PROVIDER_PATTERN_CONFIDENCE = 0.5


def validate_syntax(email: str) -> str | None:
    """Normalized (lower-cased) address if syntactically valid, else None. No DNS/SMTP."""
    try:
        return validate_email(email.strip(), check_deliverability=False).normalized.lower()
    except (EmailNotValidError, AttributeError):
        return None


def _local_tokens(email: str) -> list[str]:
    local = email.split("@", 1)[0].lower().split("+", 1)[0]
    return [t for t in re.split(r"[._\-]", local) if t]


def classify_email(email: str) -> EmailType:
    local = email.split("@", 1)[0].lower().split("+", 1)[0]
    compact = re.sub(r"[._\-]", "", local)
    tokens = _local_tokens(email)
    if compact in GENERIC_LOCALS or (tokens and tokens[0] in GENERIC_LOCALS):
        return EmailType.GENERIC
    if compact in ROLE_LOCALS or (tokens and tokens[0] in ROLE_LOCALS):
        return EmailType.ROLE
    return EmailType.PERSONAL_BUSINESS


def _clean(s: str | None) -> list[str]:
    """Name -> lowercase ASCII tokens, patronymic markers removed."""
    if not s:
        return []
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = _PATRONYMIC.sub(" ", s)
    return [t for t in re.split(r"[^a-z]+", s) if t]


def _variants(tokens: list[str]) -> dict[str, str]:
    """Ways a multi-word name part can appear: 'Wei Ming' -> weiming / wei."""
    if not tokens:
        return {}
    out = {"joined": "".join(tokens), "first_token": tokens[0], "last_token": tokens[-1]}
    return out


def _render(pattern: str, first: str, last: str) -> str:
    return (pattern.replace("{first}", first).replace("{last}", last)
            .replace("{f}", first[:1]).replace("{l}", last[:1]))


@dataclass
class PatternGuess:
    pattern: str
    support_count: int
    considered: int
    confidence: float
    first_style: str = "joined"
    last_style: str = "joined"
    examples: list[str] = field(default_factory=list)
    source: str = "company_emails"     # or "provider:<name>"


def detect_pattern(examples: list[tuple[str | None, str | None, str]], domain: str) -> PatternGuess | None:
    """Best-supported pattern from (first, last, email) examples on `domain`.
    Returns None when there is no supporting example or the top patterns tie."""
    domain = domain.lower().strip().lstrip("@")
    support: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    considered = 0
    for first, last, email in examples:
        norm = validate_syntax(email or "")
        if not norm or norm.rsplit("@", 1)[1] != domain or classify_email(norm) != EmailType.PERSONAL_BUSINESS:
            continue
        fv, lv = _variants(_clean(first)), _variants(_clean(last))
        if not fv or not lv:
            continue
        considered += 1
        local = norm.split("@", 1)[0]
        matched: set[tuple[str, str, str]] = set()
        for pattern in PATTERNS:
            for fs, fval in fv.items():
                for ls, lval in lv.items():
                    if _render(pattern, fval, lval) == local:
                        # Keep the simplest style that explains this example.
                        key = (pattern, fs, ls)
                        if not any(m[0] == pattern for m in matched):
                            matched.add(key)
                            support[key].append(norm)
    if not support:
        return None
    ranked = sorted(support.items(), key=lambda kv: len(kv[1]), reverse=True)
    (pattern, fs, ls), used = ranked[0]
    if len(ranked) > 1 and len(ranked[1][1]) == len(used) and ranked[1][0][0] != pattern:
        return None  # two different patterns explain the evidence equally well
    n = len(used)
    cap = SINGLE_EXAMPLE_CAP if n == 1 else MULTI_EXAMPLE_CAP
    return PatternGuess(pattern=pattern, support_count=n, considered=considered,
                        confidence=round(min(cap, cap * n / max(considered, 1)), 3),
                        first_style=fs, last_style=ls, examples=used)


def pattern_from_provider(pattern: str | None, provider: str) -> PatternGuess | None:
    """Wrap a provider-reported pattern (e.g. Hunter's data.pattern) as evidence."""
    if not pattern or pattern not in PATTERNS:
        return None
    return PatternGuess(pattern=pattern, support_count=0, considered=0, confidence=PROVIDER_PATTERN_CONFIDENCE,
                        source=f"provider:{provider}")


@dataclass
class InferredEmail:
    email: str
    pattern: str
    confidence: float
    evidence: list[str]
    email_type: EmailType = EmailType.PERSONAL_BUSINESS
    provenance: Provenance = Provenance.INFERRED
    discovery_method: EmailDiscoveryMethod = EmailDiscoveryMethod.EMAIL_PATTERN
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED


def infer_email(first_name: str | None, last_name: str | None, domain: str,
                pattern: PatternGuess | None) -> InferredEmail | None:
    """Apply an evidenced pattern to a person. Refuses (None) when there is no
    pattern, or when the name can't be split into first/last unambiguously —
    e.g. single-token names, or patronymic names (bin/binti/a/l) where the
    pattern relies on the surname."""
    if pattern is None:
        return None
    if _PATRONYMIC.search(f"{first_name or ''} {last_name or ''}") and ("{last}" in pattern.pattern or "{l}" in pattern.pattern):
        return None
    fv, lv = _variants(_clean(first_name)), _variants(_clean(last_name))
    if not fv or not lv:
        return None  # a single-token name: can't tell given name from family name
    local = _render(pattern.pattern, fv[pattern.first_style], lv[pattern.last_style])
    email = validate_syntax(f"{local}@{domain.lower().strip().lstrip('@')}")
    if not email:
        return None
    evidence = pattern.examples or [pattern.source]
    return InferredEmail(email=email, pattern=pattern.pattern, confidence=min(pattern.confidence, MULTI_EXAMPLE_CAP),
                         evidence=evidence)
