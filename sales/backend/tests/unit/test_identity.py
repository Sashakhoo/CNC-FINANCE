import pytest

from app.services.identity import (CompanyRecord, PersonRecord, company_duplicate_reasons, contact_duplicate_reasons,
                                   find_duplicates, person_name_similarity)


@pytest.mark.parametrize("other", ["Jane S. Tan", "Tan Jane", "Ms. Jane Tan"])
def test_name_variants_are_flagged_for_review_not_certain(other):
    m = contact_duplicate_reasons(PersonRecord("Jane Tan", company_id=1), PersonRecord(other, company_id=1))
    assert m.needs_review and not m.is_certain
    assert m.score >= 0.85


def test_bin_binti_ignored():
    assert person_name_similarity("Ahmad bin Ali", "Ahmad Ali").score == 1.0


def test_different_people_not_flagged():
    m = contact_duplicate_reasons(PersonRecord("Jane Tan", company_id=1), PersonRecord("Kumar Raj", company_id=1))
    assert not m.needs_review and not m.is_certain


def test_initials_consistent():
    assert person_name_similarity("J. Tan", "Jane Tan").score >= 0.85


def test_same_verified_email_same_company_is_certain():
    a = PersonRecord("Jane Tan", 1, verified_emails=["Jane.Tan@acme.com"])
    b = PersonRecord("J Tan", 1, verified_emails=["jane.tan@acme.com"])
    assert contact_duplicate_reasons(a, b).is_certain


def test_same_unverified_email_is_only_review():
    a = PersonRecord("Jane Tan", 1, emails=["jane@acme.com"])
    b = PersonRecord("Someone Else", 1, emails=["jane@acme.com"])
    m = contact_duplicate_reasons(a, b)
    assert not m.is_certain and m.needs_review
    assert any("not verified" in r for r in m.reasons)


def test_same_profile_url_same_company_is_certain():
    a = PersonRecord("Jane Tan", 1, profile_urls=["https://www.linkedin.com/in/janetan/"])
    b = PersonRecord("Jane Tan", 1, profile_urls=["linkedin.com/in/JaneTan"])
    assert contact_duplicate_reasons(a, b).is_certain


def test_same_verified_email_different_company_not_certain():
    a = PersonRecord("Jane Tan", 1, verified_emails=["jane@acme.com"])
    b = PersonRecord("Jane Tan", 2, verified_emails=["jane@acme.com"])
    m = contact_duplicate_reasons(a, b)
    assert not m.is_certain and m.needs_review


def test_identical_domain_is_certain_company_match():
    m = company_duplicate_reasons(CompanyRecord("Acme Automation Sdn Bhd", "https://www.acme.com.my"),
                                  CompanyRecord("ACME Group", "acme.com.my"))
    assert m.is_certain and m.score == 1.0


def test_sdn_bhd_variants_equivalent_but_review():
    m = company_duplicate_reasons(CompanyRecord("Southern Precision Automation Sdn Bhd"),
                                  CompanyRecord("Southern Precision Automation Sdn. Bhd."))
    assert not m.is_certain and m.needs_review and m.score >= 0.95
    assert any("legal suffix" in r for r in m.reasons)


def test_same_name_different_domains_still_reviewed_but_lower():
    m = company_duplicate_reasons(CompanyRecord("Acme Sdn Bhd", "acme.com"), CompanyRecord("Acme Pte Ltd", "acme.sg"))
    assert not m.is_certain and m.score == 0.85 and m.needs_review


def test_phone_match_raises_score():
    m = company_duplicate_reasons(CompanyRecord("Acme Tech", phone="+60 7-123 4567"),
                                  CompanyRecord("Acme Technologies Solutions", phone="07 1234567"))
    assert "same phone number" in m.reasons and m.needs_review


def test_unrelated_companies_not_flagged():
    m = company_duplicate_reasons(CompanyRecord("Southern Precision"), CompanyRecord("Northern Logistics"))
    assert not m.needs_review and not m.is_certain


def test_find_duplicates_sorted_certain_first():
    recs = [CompanyRecord("Acme Sdn Bhd", id=1), CompanyRecord("Acme Sdn. Bhd.", id=2),
            CompanyRecord("Zeta", "zeta.com", id=3), CompanyRecord("Zeta Holdings", "www.zeta.com", id=4),
            CompanyRecord("Unrelated Co", id=5)]
    pairs = find_duplicates(recs, "company")
    assert [(a.id, b.id) for a, b, _ in pairs] == [(3, 4), (1, 2)]
    with pytest.raises(ValueError):
        find_duplicates(recs, "widget")
