"""CONTACT CONFIDENCE and LEAD SCORE calculators (spec §21, §25, §64).

Pure functions over plain inputs — no database access. Each score returns a
per-factor breakdown with a plain-English explanation. Unknown inputs earn 0
and say so; nothing is assumed. Training Match is computed elsewhere and only
consumed here as an input.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.models.base import PipelineStatus, Priority, Provenance, VerificationStatus
from app.services.defaults import CONTACT_CONFIDENCE, LEAD_SCORING

STRONG_SIGNAL_CONFIDENCE = 0.7
_CAPPED_STATUSES = {PipelineStatus.DO_NOT_CONTACT, PipelineStatus.REJECTED, PipelineStatus.LOST}


class WeightsError(ValueError):
    """Invalid weights; message lists every problem."""


# --- weight models (validated before use; also used by the Settings API) ------

class ConfidenceWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_confirmed_on_company_site: int = Field(ge=0)
    title_confirmed: int = Field(ge=0)
    company_confirmed: int = Field(ge=0)
    professional_profile_matched: int = Field(ge=0)
    verified_business_email: int = Field(ge=0)
    likely_business_email: int = Field(ge=0)
    inferred_email: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordering(self):
        if not (self.verified_business_email >= self.likely_business_email >= self.inferred_email):
            raise ValueError("verified_business_email ≥ likely_business_email ≥ inferred_email is required")
        if self.max_points() == 0:
            raise ValueError("at least one confidence weight must be above 0")
        return self

    def max_points(self) -> int:
        return (self.name_confirmed_on_company_site + self.title_confirmed + self.company_confirmed
                + self.professional_profile_matched + self.verified_business_email)


class LeadWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    titles: dict[str, int]
    default_title: int = Field(ge=0)
    locations: dict[str, int]
    default_location: int = Field(ge=0)
    target_industries: list[str]
    target_industry: int = Field(ge=0)
    company_size_min: int = Field(ge=0)
    company_size_max: int = Field(ge=0)
    ideal_company_size: int = Field(ge=0)
    verified_email: int = Field(ge=0)
    likely_email: int = Field(ge=0)
    strong_training_match: int = Field(ge=0)
    strong_training_match_threshold: int = Field(ge=0, le=100)
    strong_buying_signal: int = Field(ge=0)
    contact_confidence_weight: int = Field(ge=0)
    priority_high: int = Field(ge=0, le=100)
    priority_medium: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _consistency(self):
        problems = []
        for k, v in {**{f"titles[{t}]": p for t, p in self.titles.items()},
                     **{f"locations[{loc}]": p for loc, p in self.locations.items()}}.items():
            if v < 0:
                problems.append(f"{k} must be ≥ 0 (got {v})")
        if self.company_size_min > self.company_size_max:
            problems.append("company_size_min must be ≤ company_size_max")
        if self.priority_medium >= self.priority_high:
            problems.append("priority_medium must be lower than priority_high")
        if self.likely_email > self.verified_email:
            problems.append("likely_email must be ≤ verified_email")
        if problems:
            raise ValueError("; ".join(problems))
        if self.max_points() == 0:
            raise ValueError("at least one lead-score weight must be above 0")
        return self

    def role_max(self) -> int:
        return max([self.default_title, *self.titles.values()])

    def location_max(self) -> int:
        return max([self.default_location, *self.locations.values()])

    def max_points(self) -> int:
        return (self.role_max() + self.location_max() + self.target_industry + self.ideal_company_size
                + self.verified_email + self.strong_training_match + self.strong_buying_signal
                + self.contact_confidence_weight)


def _coerce(model: type[BaseModel], weights):
    if isinstance(weights, model):
        return weights
    try:
        return model.model_validate(dict(weights))
    except ValidationError as e:
        msgs = [f"{'.'.join(str(p) for p in err['loc']) or 'weights'}: {err['msg']}" for err in e.errors()]
        raise WeightsError("; ".join(msgs)) from None


def validate_confidence_weights(weights: Mapping) -> ConfidenceWeights:
    return _coerce(ConfidenceWeights, weights)


def validate_lead_weights(weights: Mapping) -> LeadWeights:
    return _coerce(LeadWeights, weights)


# --- results -----------------------------------------------------------------

@dataclass
class ScoreFactor:
    factor: str
    points: int
    max_points: int
    met: bool
    explanation: str


@dataclass
class ScoreResult:
    score: int
    breakdown: list[ScoreFactor] = field(default_factory=list)
    raw_points: int = 0
    max_points: int = 0
    priority: Priority | None = None

    def breakdown_dicts(self) -> list[dict]:
        return [asdict(f) for f in self.breakdown]


def _normalize(raw: int, maximum: int) -> int:
    if maximum <= 0:
        return 0
    return max(0, min(100, round(100 * raw / maximum)))


# --- CONTACT CONFIDENCE ---------------------------------------------------------

@dataclass
class ContactEvidence:
    name_on_company_site: bool = False
    title_confirmed: bool = False
    company_confirmed: bool = False
    profile_matched: bool = False
    best_email_status: VerificationStatus | None = None
    best_email_provenance: Provenance | None = None


def _email_confidence(ev: ContactEvidence, w: ConfidenceWeights) -> ScoreFactor:
    mx = w.verified_business_email
    st, prov = ev.best_email_status, ev.best_email_provenance
    if st is None:
        return ScoreFactor("business_email", 0, mx, False, "No business email on file")
    if st == VerificationStatus.VERIFIED:
        return ScoreFactor("business_email", mx, mx, True, "Business email verified by a verification provider")
    if st == VerificationStatus.INVALID:
        return ScoreFactor("business_email", 0, mx, False, "Business email failed verification (invalid)")
    if prov == Provenance.INFERRED:
        return ScoreFactor("business_email", w.inferred_email, mx, False,
                           "Email only inferred from the company's address pattern — not verified")
    if st == VerificationStatus.LIKELY:
        return ScoreFactor("business_email", w.likely_business_email, mx, False,
                           "Business email rated likely deliverable, not fully verified")
    if st == VerificationStatus.RISKY:
        return ScoreFactor("business_email", w.inferred_email, mx, False,
                           "Business email rated risky by the verification provider")
    pts = w.likely_business_email // 2
    return ScoreFactor("business_email", pts, mx, False,
                       "Business email found from a source but not yet verified")


def contact_confidence(ev: ContactEvidence, weights: Mapping | ConfidenceWeights = CONTACT_CONFIDENCE) -> ScoreResult:
    """How confident are we that this contact information is correct?"""
    w = _coerce(ConfidenceWeights, weights)

    def flag(name: str, met: bool, pts: int, yes: str, no: str) -> ScoreFactor:
        return ScoreFactor(name, pts if met else 0, pts, met, yes if met else no)

    factors = [
        flag("name_on_company_site", ev.name_on_company_site, w.name_confirmed_on_company_site,
             "Name found on the company's own website", "Name not confirmed on the company's website"),
        flag("title_confirmed", ev.title_confirmed, w.title_confirmed,
             "Job title confirmed by a source", "Job title not confirmed by a source"),
        flag("company_confirmed", ev.company_confirmed, w.company_confirmed,
             "Works at this company according to a source", "Employment at this company not confirmed"),
        flag("profile_matched", ev.profile_matched, w.professional_profile_matched,
             "Professional profile matched to this person", "No professional profile matched"),
        _email_confidence(ev, w),
    ]
    raw = sum(f.points for f in factors)
    mx = w.max_points()
    return ScoreResult(score=_normalize(raw, mx), breakdown=factors, raw_points=raw, max_points=mx)


# --- LEAD SCORE -------------------------------------------------------------------

@dataclass
class LeadInputs:
    normalized_title: str | None = None
    department: str | None = None
    seniority: str | None = None
    state: str | None = None
    city: str | None = None
    industry: str | None = None
    employee_estimate: int | None = None
    best_email_status: VerificationStatus | None = None
    contact_confidence: int | None = None
    best_training_match: int | None = None
    strongest_signal_confidence: float | None = None
    engagement: PipelineStatus | None = None


def _ci_lookup(mapping: Mapping[str, int], key: str | None) -> int | None:
    if not key:
        return None
    k = key.strip().lower()
    for name, pts in mapping.items():
        if name.lower() == k:
            return pts
    return None


def _priority(score: int, w: LeadWeights) -> Priority:
    if score >= w.priority_high:
        return Priority.HIGH
    if score >= w.priority_medium:
        return Priority.MEDIUM
    return Priority.LOW


def lead_score(inp: LeadInputs, weights: Mapping | LeadWeights = LEAD_SCORING) -> ScoreResult:
    """How valuable is this sales prospect? Separate from contact confidence and training match."""
    w = _coerce(LeadWeights, weights)
    f: list[ScoreFactor] = []

    # role
    mx = w.role_max()
    if not inp.normalized_title:
        f.append(ScoreFactor("role", 0, mx, False, "Job title unknown"))
    else:
        pts = _ci_lookup(w.titles, inp.normalized_title)
        if pts is None:
            f.append(ScoreFactor("role", w.default_title, mx, False,
                                 f"{inp.normalized_title} is not a priority training decision-maker title"))
        else:
            f.append(ScoreFactor("role", pts, mx, pts >= mx * 0.7, f"{inp.normalized_title} (+{pts})"))

    # location
    mx = w.location_max()
    if not inp.state and not inp.city:
        f.append(ScoreFactor("location", 0, mx, False, "Location unknown"))
    else:
        pts, where = None, None
        for cand in (inp.state, inp.city):
            p = _ci_lookup(w.locations, cand)
            if p is not None and (pts is None or p > pts):
                pts, where = p, cand
        if pts is None:
            f.append(ScoreFactor("location", w.default_location, mx, False,
                                 f"{inp.state or inp.city} is outside the target locations"))
        else:
            f.append(ScoreFactor("location", pts, mx, True, f"Located in {where} (+{pts})"))

    # industry
    mx = w.target_industry
    if not inp.industry:
        f.append(ScoreFactor("industry", 0, mx, False, "Industry unknown"))
    elif inp.industry.strip().lower() in {t.lower() for t in w.target_industries}:
        f.append(ScoreFactor("industry", mx, mx, True, f"{inp.industry} is a target industry"))
    else:
        f.append(ScoreFactor("industry", 0, mx, False, f"{inp.industry} is not a target industry"))

    # company size
    mx = w.ideal_company_size
    rng = f"{w.company_size_min}–{w.company_size_max} employees"
    if inp.employee_estimate is None:
        f.append(ScoreFactor("company_size", 0, mx, False, "Company size unknown"))
    elif w.company_size_min <= inp.employee_estimate <= w.company_size_max:
        f.append(ScoreFactor("company_size", mx, mx, True, f"About {inp.employee_estimate} employees — within {rng}"))
    else:
        f.append(ScoreFactor("company_size", 0, mx, False, f"About {inp.employee_estimate} employees — outside {rng}"))

    # email
    mx = w.verified_email
    st = inp.best_email_status
    if st is None:
        f.append(ScoreFactor("email", 0, mx, False, "No business email on file"))
    elif st == VerificationStatus.VERIFIED:
        f.append(ScoreFactor("email", mx, mx, True, "Verified business email"))
    elif st == VerificationStatus.LIKELY:
        f.append(ScoreFactor("email", w.likely_email, mx, False, "Business email likely deliverable"))
    else:
        f.append(ScoreFactor("email", 0, mx, False, f"Business email not verified ({st.value})"))

    # training match
    mx = w.strong_training_match
    if inp.best_training_match is None:
        f.append(ScoreFactor("training_match", 0, mx, False, "Training match not calculated yet"))
    elif inp.best_training_match >= w.strong_training_match_threshold:
        f.append(ScoreFactor("training_match", mx, mx, True, f"Strong training match ({inp.best_training_match}%)"))
    else:
        f.append(ScoreFactor("training_match", 0, mx, False,
                             f"Training match {inp.best_training_match}% is below {w.strong_training_match_threshold}%"))

    # buying signal
    mx = w.strong_buying_signal
    sig = inp.strongest_signal_confidence
    if sig is None:
        f.append(ScoreFactor("buying_signal", 0, mx, False, "No buying signals detected"))
    elif sig >= STRONG_SIGNAL_CONFIDENCE:
        f.append(ScoreFactor("buying_signal", mx, mx, True, f"Strong buying signal (confidence {sig:.0%})"))
    else:
        f.append(ScoreFactor("buying_signal", 0, mx, False, f"Only weak buying signals (confidence {sig:.0%})"))

    # contact confidence
    mx = w.contact_confidence_weight
    cc = inp.contact_confidence
    if cc is None:
        f.append(ScoreFactor("contact_confidence", 0, mx, False, "Contact confidence not calculated yet"))
    else:
        cc = max(0, min(100, cc))
        pts = round(mx * cc / 100)
        f.append(ScoreFactor("contact_confidence", pts, mx, cc >= 80, f"Contact confidence {cc}%"))

    raw = sum(x.points for x in f)
    mx_total = w.max_points()
    score = _normalize(raw, mx_total)
    priority = _priority(score, w)

    if inp.engagement in _CAPPED_STATUSES:
        priority = Priority.LOW
        f.append(ScoreFactor("engagement", 0, 0, False,
                             f"Pipeline status {inp.engagement.value} — priority held at LOW"))
    elif inp.engagement is not None:
        f.append(ScoreFactor("engagement", 0, 0, True, f"Pipeline status {inp.engagement.value} (does not change the score)"))

    return ScoreResult(score=score, breakdown=f, raw_points=raw, max_points=mx_total, priority=priority)
