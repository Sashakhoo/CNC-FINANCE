import httpx
from httpx import Response
from sqlalchemy import select, update

from app.models import AuditLog, CompanySource, ContactSource, DuplicateCandidate, Suppression, User
from app.models.base import Role
from tests.conftest import finance_session


async def _admin(client, finance):
    client.cookies.update(finance_session(finance, username="owner", role="director"))
    assert (await client.get("/api/auth/me")).status_code == 200


async def _company(client, **kw):
    body = {"legal_name": "Southern Precision Automation Sdn Bhd", "website": "southernprecision.example",
            "industry": "Automation", "city": "Johor Bahru", "state": "Johor", "employee_estimate": 240,
            "source_url": "https://southernprecision.example/about", **kw}
    r = await client.post("/api/companies", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def _contact(client, company_id, **kw):
    body = {"company_id": company_id, "full_name": "Jane Tan", "original_title": "Manager, Human Resources",
            "email": "jane.tan@southernprecision.example", **kw}
    r = await client.post("/api/contacts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_create_company_records_user_sources_and_location(client, finance, db):
    await _admin(client, finance)
    co = await _company(client)
    assert co["domain"] == "southernprecision.example" and co["domain_status"] == "USER_PROVIDED"
    assert co["location"]["state"] == "Johor"
    fields = {s["field"]: s for s in co["sources"]}
    assert fields["legal_name"]["provenance"] == "USER_PROVIDED"
    assert fields["industry"]["source_url"] == "https://southernprecision.example/about"
    assert (await db.execute(select(AuditLog.action))).scalars().all() == ["company_created"]


async def test_same_domain_is_rejected(client, finance):
    await _admin(client, finance)
    co = await _company(client)
    r = await client.post("/api/companies", json={"legal_name": "Other Name Sdn Bhd", "website": "https://www.southernprecision.example"})
    assert r.status_code == 409 and r.json()["detail"]["existing_id"] == co["id"]


async def test_similar_name_is_flagged_not_merged(client, finance, db):
    await _admin(client, finance)
    await _company(client)
    r = await client.post("/api/companies", json={"legal_name": "Southern Precision Automation Sdn. Bhd."})
    assert r.status_code == 201
    assert r.json()["possible_duplicates"][0]["legal_name"] == "Southern Precision Automation Sdn Bhd"
    assert len((await db.execute(select(DuplicateCandidate))).scalars().all()) == 1


async def test_company_list_filters_and_patch(client, finance, db):
    await _admin(client, finance)
    co = await _company(client)
    await _company(client, legal_name="Penang Circuits Sdn Bhd", website="penangcircuits.example", state="Penang",
                   city="George Town", industry="Electronics")
    r = (await client.get("/api/companies", params={"state": "Johor"})).json()
    assert r["total"] == 1 and r["items"][0]["id"] == co["id"]
    r = (await client.get("/api/companies", params={"q": "circuits"})).json()
    assert r["total"] == 1

    r = await client.patch(f"/api/companies/{co['id']}", json={"deal_value": 18000, "phone": "+60 7-123 4567"})
    assert r.status_code == 200 and r.json()["deal_value"] == 18000
    assert any(s.field_name == "phone" for s in (await db.execute(select(CompanySource))).scalars())
    log = (await db.execute(select(AuditLog).where(AuditLog.action == "company_updated"))).scalar_one()
    assert set(log.meta["changes"]) == {"deal_value", "phone"}


async def test_viewer_cannot_edit(client, finance, db):
    client.cookies.update(finance_session(finance, username="viewer", role="admin"))
    await client.get("/api/auth/me")
    await db.execute(update(User).where(User.finance_username == "viewer").values(role=Role.VIEWER))
    await db.commit()
    assert (await client.get("/api/companies")).status_code == 200
    assert (await client.post("/api/companies", json={"legal_name": "Nope Sdn Bhd"})).status_code == 403


async def test_contact_title_normalized_with_sources(client, finance, db):
    await _admin(client, finance)
    co = await _company(client)
    ct = await _contact(client, co["id"])
    assert (ct["normalized_title"], ct["department"], ct["seniority"], ct["status"]) == ("HR Manager", "HR", "Manager", "REVIEW")
    email = ct["emails"][0]
    assert (email["provenance"], email["verification_status"], email["discovery_method"], email["is_primary"]) == \
        ("USER_PROVIDED", "UNVERIFIED", "USER_ENTRY", True)
    assert {s.field_name for s in (await db.execute(select(ContactSource))).scalars()} == {"full_name", "title"}
    r = await client.post(f"/api/contacts/{ct['id']}/emails", json={"email": "Jane.Tan@southernprecision.example"})
    assert r.status_code == 409


async def test_prospect_filters(client, finance):
    await _admin(client, finance)
    co = await _company(client)
    a = await _contact(client, co["id"])
    await _contact(client, co["id"], full_name="Lim Wei", original_title="IT Manager", email=None)
    r = (await client.get("/api/prospects", params={"department": "HR"})).json()
    assert [p["id"] for p in r["items"]] == [a["id"]]
    assert r["items"][0]["email_status"] == "UNVERIFIED" and r["items"][0]["lead_score"] is not None
    assert (await client.get("/api/prospects", params={"has_email": "false"})).json()["total"] == 1
    assert (await client.get("/api/prospects", params={"q": "southern", "state": "Johor"})).json()["total"] == 2
    assert (await client.get("/api/prospects", params={"sort": "nope"})).status_code == 422


async def test_status_changes_log_activity_and_dnc_suppresses(client, finance, db):
    await _admin(client, finance)
    co = await _company(client)
    ct = await _contact(client, co["id"])
    r = await client.post(f"/api/contacts/{ct['id']}/status", json={"status": "APPROVED"})
    assert r.json()["status"] == "APPROVED"
    r = await client.post(f"/api/contacts/{ct['id']}/status", json={"status": "DO_NOT_CONTACT", "note": "Asked not to be contacted"})
    body = r.json()
    assert "CONTACT:%d" % ct["id"] in body["suppressed"]
    kinds = {(s.kind, s.value) for s in (await db.execute(select(Suppression))).scalars()}
    assert ("EMAIL", "jane.tan@southernprecision.example") in kinds
    assert [a["meta"].get("to") for a in body["activities"] if a["type"] == "status"][:2] == ["DO_NOT_CONTACT", "APPROVED"]
    assert (await client.get("/api/prospects", params={"hide_suppressed": "true"})).json()["total"] == 0


async def test_only_admin_can_lift_dnc(client, finance, db):
    await _admin(client, finance)
    co = await _company(client)
    ct = await _contact(client, co["id"])
    await client.post(f"/api/contacts/{ct['id']}/status", json={"status": "DO_NOT_CONTACT"})
    client.cookies.clear()
    client.cookies.update(finance_session(finance, username="sam", role="admin", token="tok-sam"))
    r = await client.post(f"/api/contacts/{ct['id']}/status", json={"status": "APPROVED"})
    assert r.status_code == 403


async def test_won_requires_deal_value(client, finance):
    await _admin(client, finance)
    co = await _company(client)
    ct = await _contact(client, co["id"])
    r = await client.post(f"/api/contacts/{ct['id']}/status", json={"status": "WON"})
    assert r.status_code == 422 and "deal value" in r.json()["detail"]


async def test_won_raises_invoice_once(client, finance, db):
    await _admin(client, finance)
    co = await _company(client, deal_value=12000)
    ct = await _contact(client, co["id"])
    route = finance.post("/api/integrations/crm/won").mock(return_value=Response(
        200, json={"created": True, "invoice_id": 41, "invoice_number": "INV-0170", "amount": 12000.0}))
    r = (await client.post(f"/api/contacts/{ct['id']}/status", json={"status": "WON"})).json()
    assert r["invoice"]["invoice_number"] == "INV-0170" and r["invoice_error"] is None
    sent = route.calls.last.request
    assert sent.headers["x-crm-secret"] == "test-integration-secret"
    assert b'"external_ref":"crm-company-%d"' % co["id"] in sent.content.replace(b" ", b"")
    assert (await client.post(f"/api/contacts/{ct['id']}/raise-invoice")).json()["invoice"]["invoice_number"] == "INV-0170"
    assert route.call_count == 1
    company = (await client.get(f"/api/companies/{co['id']}")).json()
    assert company["invoices"][0]["invoice_number"] == "INV-0170"
    summary = (await client.get("/api/analytics/summary")).json()
    assert summary["won"] == 1 and summary["won_value"] == 12000


async def test_won_keeps_status_when_finance_fails_and_retry_works(client, finance):
    await _admin(client, finance)
    co = await _company(client, deal_value=9000)
    ct = await _contact(client, co["id"])
    route = finance.post("/api/integrations/crm/won").mock(side_effect=httpx.ConnectError("down"))
    r = (await client.post(f"/api/contacts/{ct['id']}/status", json={"status": "WON"})).json()
    assert r["status"] == "WON" and r["invoice"] is None and "unreachable" in r["invoice_error"]
    route.mock(return_value=Response(200, json={"created": True, "invoice_id": 7, "invoice_number": "INV-0171", "amount": 9000}))
    r = (await client.post(f"/api/contacts/{ct['id']}/raise-invoice")).json()
    assert r["invoice"]["invoice_number"] == "INV-0171"


async def test_bulk_status_rejects_won(client, finance):
    await _admin(client, finance)
    co = await _company(client)
    ct = await _contact(client, co["id"])
    assert (await client.post("/api/contacts/bulk-status", json={"ids": [ct["id"]], "status": "WON"})).status_code == 422
    r = (await client.post("/api/contacts/bulk-status", json={"ids": [ct["id"], 999], "status": "APPROVED"})).json()
    assert r == {"changed": 1, "skipped": [], "not_found": [999]}


async def test_notes_activities_and_ownership(client, finance):
    await _admin(client, finance)
    co = await _company(client)
    ct = await _contact(client, co["id"])
    n = (await client.post("/api/notes", json={"contact_id": ct["id"], "body": "Prefers WhatsApp"})).json()
    assert (await client.post("/api/notes", json={"body": "orphan"})).status_code == 422
    a = await client.post("/api/activities", json={"contact_id": ct["id"], "activity_type": "call", "text": "Intro call"})
    assert a.status_code == 201
    detail = (await client.get(f"/api/contacts/{ct['id']}")).json()
    assert detail["notes"][0]["body"] == "Prefers WhatsApp" and detail["last_contacted_at"]

    client.cookies.clear()
    client.cookies.update(finance_session(finance, username="sam", role="admin", token="tok-sam"))
    assert (await client.patch(f"/api/notes/{n['id']}", json={"body": "edited"})).status_code == 403


async def test_settings_validation_and_audit_admin_only(client, finance):
    await _admin(client, finance)
    assert (await client.put("/api/settings/general", json={"company_name": ""})).status_code == 422
    r = await client.put("/api/settings/general", json={"company_name": "Codencode Academy", "sender_name": "Sasha"})
    assert r.status_code == 200 and r.json()["version"] == 2
    assert (await client.put("/api/settings/nope", json={})).status_code == 404
    audit_log = (await client.get("/api/audit")).json()
    assert "settings_changed" in audit_log["actions"]
    meta = (await client.get("/api/meta")).json()
    assert "DO_NOT_CONTACT" in meta["statuses"] and len(meta["programs"]) == 12

    client.cookies.clear()
    client.cookies.update(finance_session(finance, username="sam", role="admin", token="tok-sam"))
    assert (await client.get("/api/audit")).status_code == 403
    assert (await client.put("/api/settings/general", json={"company_name": "X"})).status_code == 403


async def test_suppression_list(client, finance):
    await _admin(client, finance)
    assert (await client.post("/api/suppression", json={"kind": "DOMAIN", "value": "https://x.example/path"})).status_code == 422
    assert (await client.post("/api/suppression", json={"kind": "EMAIL", "value": "Boss@Example.com"})).status_code == 201
    items = (await client.get("/api/suppression")).json()["items"]
    assert items[0]["value"] == "boss@example.com"
    assert (await client.delete(f"/api/suppression/{items[0]['id']}")).status_code == 200


async def test_soft_delete_company_hides_contacts(client, finance):
    await _admin(client, finance)
    co = await _company(client)
    ct = await _contact(client, co["id"])
    assert (await client.delete(f"/api/companies/{co['id']}")).status_code == 200
    assert (await client.get(f"/api/companies/{co['id']}")).status_code == 404
    assert (await client.get(f"/api/contacts/{ct['id']}")).status_code == 404
    assert (await client.get("/api/prospects")).json()["total"] == 0
