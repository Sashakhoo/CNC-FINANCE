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


@pytest.mark.parametrize("title,norm,dept,sen", [
    ("Principal", "Principal", Department.MANAGEMENT, Seniority.HEAD),
    ("Head of School", "Principal", Department.MANAGEMENT, Seniority.HEAD),
    ("Headmistress", "Principal", Department.MANAGEMENT, Seniority.HEAD),
    ("Vice Principal (Secondary)", "Vice Principal", Department.MANAGEMENT, Seniority.DIRECTOR),
    ("Director of Studies", "Director of Studies", Department.LD, Seniority.DIRECTOR),
    ("ICT Coordinator", "Head of ICT/Computing", Department.IT, Seniority.HEAD),
    ("Head of Computing", "Head of ICT/Computing", Department.IT, Seniority.HEAD),
    ("STEM Coordinator", "Head of STEM", Department.LD, Seniority.HEAD),
    ("Bursar", "Bursar", Department.OPERATIONS, Seniority.MANAGER),
])
def test_school_titles(title, norm, dept, sen):
    t = normalize_title(title)
    assert (t.normalized_title, t.department, t.seniority) == (norm, dept, sen)


@pytest.mark.parametrize("title", ["Principal Engineer", "Principal Consultant", "Principal Software Engineer"])
def test_industrial_principal_titles_are_not_school_heads(title):
    assert normalize_title(title).normalized_title != "Principal"


def test_teacher_is_not_a_decision_maker_title():
    t = normalize_title("Year 5 Teacher")
    assert t.normalized_title is None and t.seniority == Seniority.INDIVIDUAL


@pytest.mark.parametrize("title,norm,sen", [
    ("Executive Chairman", "Chairman", Seniority.C_LEVEL),
    ("Executive Director", "Executive Director", Seniority.DIRECTOR),
    ("Independent Non-Executive Director", None, Seniority.INDIVIDUAL),
    ("Alternate Director to Beh Chern Wei", None, Seniority.INDIVIDUAL),
    ("Senior Independent Non-Executive Chairman", None, Seniority.INDIVIDUAL),
])
def test_board_titles(title, norm, sen):
    t = normalize_title(title)
    assert (t.normalized_title, t.seniority) == (norm, sen)


def test_choose_company_name():
    from types import SimpleNamespace as NS

    from app.services.pipeline import _choose_name
    ev = NS(source_url="u", snippet="s")
    cand = lambda v, c=0.5: NS(value=v, confidence=c, evidence=ev)  # noqa: E731
    co = NS(legal_name="skpres.com", domain="skpres.com", website="https://skpres.com")
    assert _choose_name(co, [cand("Investor Relations Bursa Malaysia Overview"), cand("SKP Resources Bhd (524297-T)")]) == ("SKP Resources Bhd", "site")
    co = NS(legal_name="robomatics.com", domain="robomatics.com", website="https://robomatics.com")
    assert _choose_name(co, [cand("About Us/ Overview"), cand("Enquiry")]) == ("Robomatics", "domain")
    co = NS(legal_name="Acme Holdings", domain="acme.my", website="https://acme.my")
    assert _choose_name(co, [cand("Acme Precision Sdn Bhd", 0.9)]) == (None, "")


def test_principals_message_is_not_a_title():
    assert normalize_title("Principal’s Message").normalized_title is None
    assert normalize_title("Principal's Welcome").normalized_title is None


@pytest.mark.parametrize("text,crit,out", [
    ("Campus Principal, REAL Schools, Shah Alam Campus https://x/shah-alam-campus/", {"state": "Johor"}, "shah alam"),
    ("Campus Principal, Johor Bahru Campus https://x/johor-bahru-campus/", {"state": "Johor"}, None),
    ("Chief Executive Officer https://x/about-us/", {"state": "Johor"}, None),
    ("Head of School https://x/cheras-campus/", {}, None),
])
def test_outside_target_area(text, crit, out):
    from app.services.pipeline import outside_target_area
    assert outside_target_area(text, crit) == out
