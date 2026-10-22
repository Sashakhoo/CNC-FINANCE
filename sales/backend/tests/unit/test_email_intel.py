from app.models.base import EmailDiscoveryMethod, EmailType, Provenance, VerificationStatus
from app.services.email_intel import (classify_email, detect_pattern, infer_email, pattern_from_provider,
                                      validate_syntax)

D = "southern-precision.example"


def test_validate_syntax():
    assert validate_syntax("  John.Lim@Southern-Precision.Example ") == "john.lim@southern-precision.example"
    assert validate_syntax("not-an-email") is None
    assert validate_syntax("a@b") is None


def test_classify_role_generic_personal():
    assert classify_email(f"info@{D}") == EmailType.GENERIC
    assert classify_email(f"enquiry@{D}") == EmailType.GENERIC
    assert classify_email(f"hr@{D}") == EmailType.ROLE
    assert classify_email(f"careers.jb@{D}") == EmailType.ROLE
    assert classify_email(f"sales@{D}") == EmailType.ROLE
    assert classify_email(f"mary.tan@{D}") == EmailType.PERSONAL_BUSINESS


def test_detects_first_dot_last_from_two_examples():
    guess = detect_pattern([("John", "Lim", f"john.lim@{D}"), ("Mary", "Tan", f"Mary.Tan@{D}")], D)
    assert guess and guess.pattern == "{first}.{last}"
    assert guess.support_count == 2 and guess.confidence == 0.7


def test_single_example_confidence_capped():
    guess = detect_pattern([("John", "Lim", f"jlim@{D}")], D)
    assert guess.pattern == "{f}{last}" and guess.confidence == 0.5


def test_ignores_other_domains_and_role_addresses():
    assert detect_pattern([("John", "Lim", "john.lim@gmail.com"), ("HR", "Team", f"hr@{D}")], D) is None


def test_no_examples_means_no_pattern_and_no_inference():
    assert detect_pattern([], D) is None
    assert infer_email("Jane", "Tan", D, None) is None


def test_conflicting_patterns_tie_returns_none():
    examples = [("John", "Lim", f"john.lim@{D}"), ("Mary", "Tan", f"mtan@{D}")]
    assert detect_pattern(examples, D) is None


def test_diacritics_and_multi_word_given_names():
    guess = detect_pattern([("José", "Ramírez", f"jose.ramirez@{D}"), ("Wei Ming", "Tan", f"weiming.tan@{D}")], D)
    assert guess.pattern == "{first}.{last}"


def test_inferred_email_is_labelled_and_unverified():
    guess = detect_pattern([("John", "Lim", f"john.lim@{D}"), ("Mary", "Tan", f"mary.tan@{D}")], D)
    inferred = infer_email("Jane", "Tan", D, guess)
    assert inferred.email == f"jane.tan@{D}"
    assert inferred.provenance == Provenance.INFERRED
    assert inferred.discovery_method == EmailDiscoveryMethod.EMAIL_PATTERN
    assert inferred.verification_status == VerificationStatus.UNVERIFIED
    assert inferred.confidence <= 0.7
    assert inferred.evidence == [f"john.lim@{D}", f"mary.tan@{D}"]


def test_refuses_single_token_names():
    guess = detect_pattern([("John", "Lim", f"john.lim@{D}"), ("Mary", "Tan", f"mary.tan@{D}")], D)
    assert infer_email("Suresh", None, D, guess) is None
    assert infer_email("", "Tan", D, guess) is None


def test_refuses_patronymic_names_when_pattern_uses_surname():
    guess = detect_pattern([("John", "Lim", f"john.lim@{D}"), ("Mary", "Tan", f"mary.tan@{D}")], D)
    assert infer_email("Ahmad", "bin Ismail", D, guess) is None


def test_provider_pattern_is_evidence_but_low_confidence():
    guess = pattern_from_provider("{first}.{last}", "hunter")
    inferred = infer_email("Jane", "Tan", D, guess)
    assert inferred.email == f"jane.tan@{D}" and inferred.confidence == 0.5
    assert inferred.evidence == ["provider:hunter"]
    assert pattern_from_provider("{weird}", "hunter") is None
