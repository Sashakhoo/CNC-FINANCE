"""Invoices raised from learn.codencode.my registrations: RM0 on sign-up,
amount + LMS course title on approval, removed on cancel while unpaid."""
import pytest

import lms_sync
import storage
from test_stamp import ORIGIN, app_client, boss  # noqa: F401

SECRET = "test-lms-secret"
H = {"x-lms-secret": SECRET}


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(lms_sync, "LMS_SYNC_SECRET", SECRET)


def register(c, ref, **kw):
    body = {"external_ref": ref, "name": "Reg Tester " + ref, "email": f"{ref}@example.com",
            "phone": "012-345 6789", "course": "AI for Marketing", "location": "Ipoh", **kw}
    return c.post("/api/integrations/lms/registration", json=body, headers=H)


def test_wrong_or_missing_secret_is_refused(app_client):
    assert register(app_client, "lms-reg-x").status_code == 200   # sanity: right secret works
    r = app_client.post("/api/integrations/lms/registration",
                        json={"external_ref": "lms-reg-y", "name": "N", "course": "C"},
                        headers={"x-lms-secret": "nope"})
    assert r.status_code == 401
    assert app_client.post("/api/integrations/lms/registration/lms-reg-x/cancel").status_code == 401


def test_registration_raises_one_rm0_pending_invoice(app_client):
    r = register(app_client, "lms-reg-1")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["created"] and out["invoice_number"].startswith("INV") and out["amount"] == 0
    assert out["status"] == "Pending"
    inv = storage.get_invoice(out["invoice_id"])
    assert inv["reference_no"] == "lms-reg-1"
    assert "AI for Marketing" in inv["items"][0]["description"]
    assert storage.get_contact_by_name("Reg Tester lms-reg-1", "debtor")["email"] == "lms-reg-1@example.com"
    # a retry returns the same invoice instead of a second one
    again = register(app_client, "lms-reg-1").json()
    assert not again["created"] and again["invoice_id"] == out["invoice_id"]


def test_registration_with_standard_price(app_client):
    out = register(app_client, "lms-reg-7", course="AI Agents & Vibe Coding", amount=1128).json()
    assert out["created"] and out["amount"] == 1128 and out["status"] == "Pending"
    assert storage.get_invoice(out["invoice_id"])["items"][0]["unit_price"] == 1128
    bad = register(app_client, "lms-reg-8", amount=-5)
    assert bad.status_code == 422


def test_approve_sets_amount_and_lms_course_title(app_client):
    iid = register(app_client, "lms-reg-2").json()["invoice_id"]
    r = app_client.post("/api/integrations/lms/registration/lms-reg-2/amount",
                        json={"amount": 1350, "course_title": "Python Fundamentals"}, headers=H)
    assert r.status_code == 200, r.text
    inv = storage.get_invoice(iid)
    assert inv["amount"] == 1350
    assert inv["items"][0]["description"].startswith("Python Fundamentals")   # what lms_sync matches on
    assert inv["status"] == "Pending"
    missing = app_client.post("/api/integrations/lms/registration/nope/amount",
                              json={"amount": 1, "course_title": "X"}, headers=H)
    assert missing.status_code == 404


def test_amount_refused_once_money_is_recorded(app_client, boss):
    iid = register(app_client, "lms-reg-3").json()["invoice_id"]
    app_client.post("/api/integrations/lms/registration/lms-reg-3/amount",
                    json={"amount": 800, "course_title": "Vibe Coding"}, headers=H)
    assert boss.post(f"/api/invoices/{iid}/deposit", json={"amount": 100, "post_to_ledger": False},
                     headers=ORIGIN).status_code == 200
    r = app_client.post("/api/integrations/lms/registration/lms-reg-3/amount",
                        json={"amount": 999, "course_title": "Vibe Coding"}, headers=H)
    assert r.status_code == 409
    assert storage.get_invoice(iid)["amount"] == 800


def test_cancel_deletes_only_untouched_invoices(app_client, boss):
    iid = register(app_client, "lms-reg-4").json()["invoice_id"]
    out = app_client.post("/api/integrations/lms/registration/lms-reg-4/cancel", headers=H).json()
    assert out["deleted"] and storage.get_invoice(iid) is None
    # cancelling again (or a registration that never had one) is harmless
    assert app_client.post("/api/integrations/lms/registration/lms-reg-4/cancel", headers=H).json()["deleted"] is False

    paid_iid = register(app_client, "lms-reg-5").json()["invoice_id"]
    app_client.post("/api/integrations/lms/registration/lms-reg-5/amount",
                    json={"amount": 500, "course_title": "Python Fundamentals"}, headers=H)
    boss.post(f"/api/invoices/{paid_iid}/deposit", json={"amount": 100, "post_to_ledger": False}, headers=ORIGIN)
    kept = app_client.post("/api/integrations/lms/registration/lms-reg-5/cancel", headers=H).json()
    assert kept["deleted"] is False and storage.get_invoice(paid_iid) is not None


def test_invoice_deleted_in_finance_is_raised_again(app_client):
    iid = register(app_client, "lms-reg-6").json()["invoice_id"]
    storage.delete_row("invoices", iid)
    again = register(app_client, "lms-reg-6").json()
    assert again["created"] and again["invoice_id"] != iid
