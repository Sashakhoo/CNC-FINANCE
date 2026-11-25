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
    r = enquiry(app_client, "lms-corp-1", hrd_claim="No")
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
    assert "Admin team" in q["notes"]
    # a retry returns the same quotation
    again = enquiry(app_client, "lms-corp-1", hrd_claim="No").json()
    assert not again["created"] and again["quote_id"] == out["quote_id"]


def test_ai_alone_does_not_match_another_ai_course():
    courses = [{"id": 1, "name": "AI for Automation"}, {"id": 2, "name": "AI for Marketing (2-day, 4.5h/day)"}]
    assert lms_quotes.match_course("AI for Marketing", courses)["id"] == 2
    assert lms_quotes.match_course("AI for Video Creation", courses) is None


def test_no_topics_still_gives_one_line(app_client):
    q = qs.get_quotation(enquiry(app_client, "lms-corp-2", topics=[], pax=None).json()["quote_id"])
    assert [i["title"] for i in q["items"]] == ["Corporate training"]


GUAN_CHONG = dict(company="GUAN CHONG COCOA TEST SDN BHD", contact_name="Sarah Binti Md Nor", contact_role="HR",
                  email="sarah@example.com", phone="016-778 5043", ssm="133057U", mycoid="133057U",
                  hrd_claim="Yes", topics=["Python Fundamentals"], mode="Online (Zoom, live)", location="",
                  dates=["2026-12-07", "2026-12-05", "2026-12-06"], start_time="09:00", end_time="17:00",
                  pax=None, participants=[{"name": "Lim Yu Cheng", "department": "Finance", "level": "Beginner"}],
                  requirements="")


def test_claimable_python_enquiry_becomes_an_hrdc_quotation(app_client):
    out = enquiry(app_client, "lms-corp-3", **GUAN_CHONG).json()
    assert out["created"] and out["quote_number"].startswith("QHR")
    q = qs.get_quotation(out["quote_id"])
    h = q["hrdc"]
    prog = qs.get_programme(h["programme_id"])
    assert q["qtype"] == "hrdc" and "Python" in prog["title"] and q["status"] == "Draft"
    assert q["attention"] == "Sarah Binti Md Nor (HR)"
    assert (h["ssm"], h["mycoid"], h["hr_email"]) == ("133057U", "133057U", "sarah@example.com")
    assert h["mode"] == "online" and "Zoom" in h["platform"] and h["venue"] == ""
    assert h["dates"] == ["2026-12-05", "2026-12-06", "2026-12-07"]                  # sorted
    assert (h["start_time"], h["end_time"], h["pax"]) == ("09:00", "17:00", 1)        # pax from participants
    assert h["participants"] == [{"name": "Lim Yu Cheng", "ic": "", "designation": "Finance, Beginner"}]
    item = q["items"][0]
    assert item["title"] == prog["title"] and item["claimable"] and item["qty"] == 1
    assert item["unit_price"] == 0 and "Set the fee" in q["notes"]     # the owner sets the fee
    assert "IC numbers" in q["notes"]


def test_claimable_but_no_programme_stays_standard_with_details_in_notes(app_client):
    out = enquiry(app_client, "lms-corp-4", **{**GUAN_CHONG, "topics": ["Cybersecurity"],
                                                "mode": "At our office", "location": "Penang"}).json()
    q = qs.get_quotation(out["quote_id"])
    assert q["qtype"] == "standard" and q["number"].startswith("QUO")
    for bit in ("SSM: 133057U", "At our office", "2026-12-05", "Lim Yu Cheng (Finance, Beginner)",
                "no approved HRD Corp programme"):
        assert bit in q["notes"], bit


def test_workplace_ai_maps_to_the_workflow_programme_at_the_client_office(app_client):
    out = enquiry(app_client, "lms-corp-5", **{**GUAN_CHONG, "topics": ["AI for Workplace Productivity"],
                                                "mode": "At our office", "location": "Johor Bahru", "pax": 8,
                                                "participants": []}).json()
    q = qs.get_quotation(out["quote_id"])
    assert q["qtype"] == "hrdc" and "Workflow" in qs.get_programme(q["hrdc"]["programme_id"])["title"]
    assert q["hrdc"]["venue_type"] == "client" and "Johor Bahru" in q["hrdc"]["venue"]
    assert q["items"][0]["qty"] == 8
