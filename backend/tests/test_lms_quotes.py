"""Corporate training enquiries from learn.codencode.my become Draft
quotations: catalogue courses priced per pax, unknown topics at RM0."""
import pytest

import lms_quotes
import lms_sync
import quote_store as qs
from test_stamp import app_client  # noqa: F401

SECRET = "test-lms-secret"
H = {"x-lms-secret": SECRET}


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(lms_sync, "LMS_SYNC_SECRET", SECRET)


def enquiry(c, ref, **kw):
    body = {"external_ref": ref, "company": "Ocean Test Sdn Bhd", "contact_name": "Jess Wong",
            "email": "jess@example.com", "phone": "012-345 6789", "pax": 6, "hrd_claim": "Yes",
            "topics": ["AI for Automation", "AI Agents & Vibe Coding", "Cybersecurity"],
            "location": "Johor Bahru", "requirements": "Admin team, mostly Excel and email.", **kw}
    return c.post("/api/integrations/lms/corporate", json=body, headers=H)


def test_wrong_secret_is_refused(app_client):
    r = app_client.post("/api/integrations/lms/corporate", json={"external_ref": "x", "company": "X"},
                        headers={"x-lms-secret": "nope"})
    assert r.status_code == 401


def test_enquiry_becomes_a_draft_quotation(app_client):
    r = enquiry(app_client, "lms-corp-1")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["created"] and out["quote_number"].startswith("QUO") and out["status"] == "Draft"
    q = qs.get_quotation(out["quote_id"])
    assert q["qtype"] == "standard" and q["company"] == "Ocean Test Sdn Bhd" and q["attention"] == "Jess Wong"
    assert q["reference_no"] == "lms-corp-1" and q["validity_days"] == 14
    by_title = {i["title"]: i for i in q["items"]}
    auto = by_title["AI for Automation"]                     # catalogue course, priced per pax
    assert auto["course_id"] and auto["qty"] == 6 and auto["unit_price"] == 288
    vibe = by_title["Vibe Coding from Scratch"]               # matched on "vibe coding"
    assert vibe["course_id"] and vibe["unit_price"] == 800
    cyber = by_title["Cybersecurity"]                         # not in the catalogue -> RM0 to price
    assert cyber["course_id"] is None and cyber["unit_price"] == 0
    assert out["unpriced"] == ["Cybersecurity"]
    assert "HRD Corp claim requested" in q["notes"] and "Admin team" in q["notes"]
    # a retry returns the same quotation
    again = enquiry(app_client, "lms-corp-1").json()
    assert not again["created"] and again["quote_id"] == out["quote_id"]


def test_ai_alone_does_not_match_another_ai_course():
    courses = [{"id": 1, "name": "AI for Automation"}, {"id": 2, "name": "AI for Marketing (2-day, 4.5h/day)"}]
    assert lms_quotes.match_course("AI for Marketing", courses)["id"] == 2
    assert lms_quotes.match_course("AI for Video Creation", courses) is None


def test_no_topics_still_gives_one_line(app_client):
    q = qs.get_quotation(enquiry(app_client, "lms-corp-2", topics=[], pax=None).json()["quote_id"])
    assert [i["title"] for i in q["items"]] == ["Corporate training"]
