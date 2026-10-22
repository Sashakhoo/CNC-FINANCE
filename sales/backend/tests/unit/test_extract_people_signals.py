import pathlib
from datetime import date

from app.crawler.html import make_page
from app.extract.people import extract_people, looks_like_person_name, looks_like_title
from app.extract.signals import detect_signals, find_date

FIX = pathlib.Path(__file__).parent / "fixtures" / "crawler"
BASE = "https://www.precision-example.com.my"
COMPANY = ["Precision Example Automation Sdn Bhd", "Precision Example Automation"]


def team_page():
    return make_page(f"{BASE}/our-team", (FIX / "team.html").read_text())


def test_people_from_team_page():
    people = {p.full_name: p for p in extract_people(team_page(), COMPANY)}
    assert set(people) == {"Tan Wei Ming", "Siti Nurhaliza binti Ahmad", "Farah Aziz", "Rajesh Kumar"}
    assert people["Tan Wei Ming"].original_title == "Managing Director"
    assert people["Tan Wei Ming"].profile_url == "https://www.linkedin.com/in/tan-wei-ming-example"
    assert people["Siti Nurhaliza binti Ahmad"].original_title == "L&D Manager"
    assert people["Siti Nurhaliza binti Ahmad"].email == "siti.ahmad@precision-example.com.my"
    assert people["Farah Aziz"].method == "schema_org" and people["Farah Aziz"].confidence >= 0.9
    assert people["Farah Aziz"].profile_url == "https://www.linkedin.com/in/farah-aziz-example"
    assert people["Rajesh Kumar"].original_title == "Engineering Manager"
    assert people["Rajesh Kumar"].email is None                  # info@ is a role inbox, never attributed
    for p in people.values():
        assert p.source_url == f"{BASE}/our-team" and p.evidence


def test_every_returned_name_is_on_the_page():
    page = team_page()
    for p in extract_people(page, COMPANY):
        assert p.full_name in page.html or p.full_name in page.text


def test_no_people_invented_from_non_people_pages():
    page = make_page(f"{BASE}/services", "<h1>Our Services</h1><p>Robotic Assembly</p><p>Machine Vision Systems</p>"
                                         "<h3>Precision Example Automation Sdn Bhd</h3><p>Head Office</p>")
    assert extract_people(page, COMPANY) == []


def test_name_and_title_heuristics():
    assert looks_like_person_name("Dato' Lim Ah Kow")
    assert looks_like_person_name("Muhammad Firdaus bin Abdullah")
    assert not looks_like_person_name("Our Leadership Team")
    assert not looks_like_person_name("Precision Example Automation Sdn Bhd", COMPANY)
    assert not looks_like_person_name("Senior Automation Engineer")
    assert not looks_like_person_name("Read More")
    assert looks_like_title("Head of Human Resources")
    assert not looks_like_title("We are hiring talented people across Johor and beyond, apply today")


def signals_by_type():
    pages = [make_page(f"{BASE}/careers", (FIX / "careers.html").read_text()),
             make_page(f"{BASE}/news", (FIX / "news.html").read_text()),
             make_page(f"{BASE}/", (FIX / "home.html").read_text())]
    best = {}
    for s in detect_signals(pages):          # sorted by confidence: keep the strongest per type
        best.setdefault(s.signal_type, s)
    return pages, best


def test_signals_detected_with_exact_evidence():
    pages, sig = signals_by_type()
    expected = {"HIRING_ENGINEERS", "HIRING_IT", "HIRING_CYBERSECURITY", "NEW_FACILITY", "INDUSTRY_4_0",
                "CYBERSECURITY_CERTIFICATION", "ERP_IMPLEMENTATION", "NEW_TECH_DEPARTMENT", "AI_INITIATIVE",
                "EMPLOYEE_DEVELOPMENT", "EXPANSION"}
    assert expected <= set(sig)
    texts = {p.source_url: p.text for p in pages}
    for s in sig.values():
        assert s.evidence in texts[s.source_url]


def test_signal_details():
    _, sig = signals_by_type()
    assert "Senior Automation Engineer" in sig["HIRING_ENGINEERS"].matches
    assert sig["HIRING_ENGINEERS"].confidence >= 0.8
    assert sig["NEW_FACILITY"].source_date == date(2026, 3, 12)
    assert sig["CYBERSECURITY_CERTIFICATION"].source_date == date(2026, 1, 3)
    assert sig["ERP_IMPLEMENTATION"].confidence > 0.6           # boosted: "go-live"


def test_no_signals_on_plain_page():
    page = make_page("https://x-example.com/", "<p>Welcome to our website. We make quality furniture.</p>")
    assert detect_signals([page]) == []


def test_find_date_formats():
    assert find_date("Posted 2026-02-01") == date(2026, 2, 1)
    assert find_date("March 5, 2026") == date(2026, 3, 5)
    assert find_date("05/04/2026") == date(2026, 4, 5)
    assert find_date("no date here") is None
