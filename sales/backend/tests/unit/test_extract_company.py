import pathlib

from app.crawler.html import make_page
from app.extract.company import extract_company_info, find_emails, normalize_phone

FIX = pathlib.Path(__file__).parent / "fixtures" / "crawler"
BASE = "https://www.precision-example.com.my"


def pages():
    return [make_page(f"{BASE}/", (FIX / "home.html").read_text()),
            make_page(f"{BASE}/about-us", (FIX / "about.html").read_text())]


def values(bucket):
    return [v.value for v in bucket]


def test_names_and_description_have_evidence():
    info = extract_company_info(pages())
    names = values(info.name_candidates)
    assert names[0] == "Precision Example Automation Sdn Bhd"          # schema.org name ranks first
    assert "Precision Example Automation" in names                      # og:site_name
    assert "Home" not in names
    desc = values(info.descriptions)
    assert any("industrial automation cells" in d for d in desc)
    assert any(d.startswith("Precision Example Automation Sdn Bhd is a Johor-based") for d in desc)
    for v in info.name_candidates + info.descriptions:
        assert v.evidence.source_url.startswith(BASE)


def test_emails_including_obfuscated_and_not_filenames():
    info = extract_company_info(pages())
    emails = values(info.emails)
    assert "info@precision-example.com.my" in emails
    assert "sales@precision-example.com.my" in emails       # "sales [at] ... [dot] com [dot] my"
    assert "hr@precision-example.com.my" in emails          # mailto
    assert not any("png" in e for e in emails)
    assert all(v.kind == "role" for v in info.emails)


def test_phones_normalized_and_fax_flagged():
    info = extract_company_info(pages())
    by_value = {v.value: v for v in info.phones}
    assert "+6075551234" in by_value
    assert by_value["+6075551299"].kind == "fax"
    assert "+60123456789" in by_value
    assert "+6561234567" in by_value and by_value["+6561234567"].data["country"] == "SG"
    assert not any("200401012345" in v.value for v in info.phones)     # company registration number


def test_addresses():
    info = extract_company_info(pages())
    my = [a for a in info.addresses if a.data.get("country") == "Malaysia"]
    assert my and my[0].data["postcode"] == "81400" and my[0].data["state"] == "Johor" and my[0].data["city"] == "Senai"
    assert "Jalan Teknologi 3" in my[0].evidence.snippet
    sg = [a for a in info.addresses if a.data.get("country") == "Singapore"]
    assert sg and sg[0].data["postcode"] == "123456"


def test_johor_bahru_address():
    page = make_page("https://x-example.com/contact", "<p>No. 5, Jalan Example<br>81100 Johor Bahru, Johor</p>")
    a = extract_company_info([page]).addresses[0]
    assert (a.data["city"], a.data["state"]) == ("Johor Bahru", "Johor")


def test_social_links_and_employee_counts():
    info = extract_company_info(pages())
    social = {v.kind: v.value for v in info.social_links}
    assert social["LINKEDIN"] == "https://www.linkedin.com/company/precision-example-automation"
    assert "X" not in social                                     # share-intent link ignored
    counts = {v.value: v for v in info.employee_counts}
    assert "320" in counts                                       # schema.org
    assert counts["300"].data["qualifier"] == "over"
    assert "over 300 employees" in counts["300"].evidence.snippet


def test_find_emails_ignores_junk():
    text = "Write to name@example.com or icon@2x.png or ops@precision-example.com.my"
    assert [e for e, _, _ in find_emails(text)] == ["ops@precision-example.com.my"]


def test_normalize_phone():
    assert normalize_phone("07-555 1234") == ("+6075551234", "MY")
    assert normalize_phone("+60 12-345 6789") == ("+60123456789", "MY")
    assert normalize_phone("+65 6123 4567") == ("+6561234567", "SG")
    assert normalize_phone("12345") is None


def test_empty_page_returns_nothing():
    info = extract_company_info([make_page("https://x-example.com/", "<html><body><p>Hello</p></body></html>")])
    assert not (info.emails or info.phones or info.addresses or info.employee_counts or info.social_links)
