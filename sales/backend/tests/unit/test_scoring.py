import pytest

from app.models.base import PipelineStatus, Priority, Provenance, VerificationStatus
from app.services.defaults import CONTACT_CONFIDENCE, LEAD_SCORING
from app.services.scoring import (ConfidenceWeights, ContactEvidence, LeadInputs, LeadWeights, WeightsError,
                                  contact_confidence, lead_score, validate_lead_weights)


# --- contact confidence --------------------------------------------------------

def test_full_evidence_is_100_with_explanations():
    r = contact_confidence(ContactEvidence(True, True, True, True, VerificationStatus.VERIFIED, Provenance.VERIFIED))
    assert r.score == 100 and r.max_points == 100
    assert all(f.met and f.explanation for f in r.breakdown)
    assert r.breakdown[0].explanation == "Name found on the company's own website"


def test_no_evidence_is_zero():
    r = contact_confidence(ContactEvidence())
    assert r.score == 0
    assert next(f for f in r.breakdown if f.factor == "business_email").explanation == "No business email on file"


def test_inferred_email_gets_only_small_credit():
    inferred = contact_confidence(ContactEvidence(best_email_status=VerificationStatus.UNVERIFIED,
                                                  best_email_provenance=Provenance.INFERRED))
    verified = contact_confidence(ContactEvidence(best_email_status=VerificationStatus.VERIFIED))
    assert inferred.score == CONTACT_CONFIDENCE["inferred_email"]
    assert verified.score == CONTACT_CONFIDENCE["verified_business_email"]
    assert "inferred" in inferred.breakdown[-1].explanation.lower()


def test_inferred_but_later_verified_counts_as_verified():
    r = contact_confidence(ContactEvidence(best_email_status=VerificationStatus.VERIFIED,
                                           best_email_provenance=Provenance.INFERRED))
    assert r.breakdown[-1].met


def test_invalid_email_earns_nothing():
    r = contact_confidence(ContactEvidence(best_email_status=VerificationStatus.INVALID))
    assert r.score == 0


def test_confidence_normalizes_against_custom_max():
    w = dict(CONTACT_CONFIDENCE, name_confirmed_on_company_site=50)  # max becomes 125
    r = contact_confidence(ContactEvidence(name_on_company_site=True), w)
    assert r.max_points == 125 and r.score == 40


def test_confidence_weights_reject_negative_and_missing():
    with pytest.raises(WeightsError, match="title_confirmed"):
        contact_confidence(ContactEvidence(), dict(CONTACT_CONFIDENCE, title_confirmed=-1))
    bad = dict(CONTACT_CONFIDENCE)
    del bad["company_confirmed"]
    with pytest.raises(WeightsError, match="company_confirmed"):
        contact_confidence(ContactEvidence(), bad)
    with pytest.raises(WeightsError, match="verified_business_email"):
        ConfidenceWeights  # noqa: B018 — model exported for the Settings API
        contact_confidence(ContactEvidence(), dict(CONTACT_CONFIDENCE, inferred_email=40))


# --- lead score ------------------------------------------------------------------

def _ideal(**over) -> LeadInputs:
    base = dict(normalized_title="L&D Manager", state="Johor", industry="Manufacturing", employee_estimate=200,
                best_email_status=VerificationStatus.VERIFIED, contact_confidence=100, best_training_match=90,
                strongest_signal_confidence=0.9)
    base.update(over)
    return LeadInputs(**base)


def test_ideal_prospect_scores_100_high():
    r = lead_score(_ideal())
    assert r.score == 100 and r.priority == Priority.HIGH
    assert r.max_points == LeadWeights.model_validate(LEAD_SCORING).max_points()


def test_unknown_inputs_score_zero_and_say_unknown():
    r = lead_score(LeadInputs())
    assert r.score == 0 and r.priority == Priority.LOW
    texts = {f.factor: f.explanation for f in r.breakdown}
    assert texts["role"] == "Job title unknown"
    assert texts["location"] == "Location unknown"
    assert texts["industry"] == "Industry unknown"
    assert texts["company_size"] == "Company size unknown"
    assert texts["training_match"] == "Training match not calculated yet"
    assert all(f.points == 0 for f in r.breakdown)


def test_unmapped_title_gets_default_points():
    r = lead_score(LeadInputs(normalized_title="Receptionist"))
    role = r.breakdown[0]
    assert role.points == LEAD_SCORING["default_title"] and not role.met


def test_location_matches_city_or_state_case_insensitive():
    r = lead_score(LeadInputs(state="selangor"))
    assert r.breakdown[1].points == LEAD_SCORING["locations"]["Selangor"]
    r2 = lead_score(LeadInputs(state="Melaka"))
    assert r2.breakdown[1].points == LEAD_SCORING["default_location"]


def test_size_outside_range_scores_zero():
    r = lead_score(LeadInputs(employee_estimate=5000))
    f = next(x for x in r.breakdown if x.factor == "company_size")
    assert f.points == 0 and "outside" in f.explanation


def test_training_match_threshold():
    t = LEAD_SCORING["strong_training_match_threshold"]
    hit = next(x for x in lead_score(LeadInputs(best_training_match=t)).breakdown if x.factor == "training_match")
    miss = next(x for x in lead_score(LeadInputs(best_training_match=t - 1)).breakdown if x.factor == "training_match")
    assert hit.met and not miss.met


@pytest.mark.parametrize("high,medium,score,expected", [
    (80, 60, 80, Priority.HIGH), (80, 60, 79, Priority.MEDIUM), (80, 60, 60, Priority.MEDIUM), (80, 60, 59, Priority.LOW),
])
def test_priority_boundaries(high, medium, score, expected):
    from app.services.scoring import _priority
    w = validate_lead_weights(dict(LEAD_SCORING, priority_high=high, priority_medium=medium))
    assert _priority(score, w) == expected


def test_do_not_contact_holds_priority_low():
    r = lead_score(_ideal(engagement=PipelineStatus.DO_NOT_CONTACT))
    assert r.score == 100 and r.priority == Priority.LOW
    assert "LOW" in r.breakdown[-1].explanation


def test_lead_weights_validation_errors_are_clear():
    with pytest.raises(WeightsError, match="priority_medium must be lower"):
        validate_lead_weights(dict(LEAD_SCORING, priority_medium=90))
    with pytest.raises(WeightsError, match="company_size_min"):
        validate_lead_weights(dict(LEAD_SCORING, company_size_min=2000))
    with pytest.raises(WeightsError, match="verified_email"):
        validate_lead_weights({k: v for k, v in LEAD_SCORING.items() if k != "verified_email"})
    with pytest.raises(WeightsError, match="unexpected_key"):
        validate_lead_weights(dict(LEAD_SCORING, unexpected_key=1))
    with pytest.raises(WeightsError, match="titles"):
        validate_lead_weights(dict(LEAD_SCORING, titles={"CEO": -5}))


def test_breakdown_dicts_serializable():
    import json
    assert json.dumps(lead_score(_ideal()).breakdown_dicts())
