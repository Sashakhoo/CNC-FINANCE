import pytest

from app.models.base import Department, Seniority
from app.services.normalize import (domain_from_url, normalize_company_name, normalize_person_name, normalize_website,
                                    profile_platform)
from app.services.titles import normalize_title


@pytest.mark.parametrize("name", ["Southern Precision Automation Sdn Bhd", "Southern Precision Automation Sdn. Bhd.",
                                  "SOUTHERN PRECISION AUTOMATION SDN. BHD", "Southern Precision Automation (M) Sdn Bhd"])
def test_company_suffixes_removed(name):
    assert normalize_company_name(name) == "southern precision automation"


def test_company_pte_ltd_and_ampersand():
    assert normalize_company_name("Tan & Lim Engineering Pte. Ltd.") == "tan and lim engineering"


def test_person_name_drops_honorifics():
    assert normalize_person_name("Dr. Jane Tan") == "jane tan"
    assert normalize_person_name("Ahmad bin Ismail") == "ahmad ismail"


def test_domains_and_websites():
    assert domain_from_url("https://www.Example.com.my/about") == "example.com.my"
    assert normalize_website("example.com/") == "https://example.com"
    with pytest.raises(ValueError):
        normalize_website("javascript:alert(1)")
    assert profile_platform("https://my.linkedin.com/in/jane") == "LINKEDIN"


@pytest.mark.parametrize("title,norm,dept,sen", [
    ("Manager, Human Resources", "HR Manager", Department.HR, Seniority.MANAGER),
    ("Human Resources Manager", "HR Manager", Department.HR, Seniority.MANAGER),
    ("HR & Admin Manager", "HR Manager", Department.HR, Seniority.MANAGER),
    ("Learning & Development Manager", "L&D Manager", Department.LD, Seniority.MANAGER),
    ("Head of IT", "Head of IT", Department.IT, Seniority.HEAD),
    ("Senior Engineering Manager", "Engineering Manager", Department.ENGINEERING, Seniority.MANAGER),
    ("Chief Technology Officer", "CTO", Department.IT, Seniority.C_LEVEL),
    ("Managing Director", "Managing Director", Department.MANAGEMENT, Seniority.C_LEVEL),
])
def test_title_rules(title, norm, dept, sen):
    t = normalize_title(title)
    assert (t.normalized_title, t.department, t.seniority, t.matched) == (norm, dept, sen, True)


def test_unknown_title_is_not_guessed():
    t = normalize_title("Quality Assurance Executive")
    assert t.normalized_title is None and t.matched is False
