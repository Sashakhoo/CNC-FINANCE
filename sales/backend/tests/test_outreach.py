from sqlalchemy import select

from app.models import CompanySignal, TrainingOpportunity, TrainingProgram
from app.models.base import Provenance
from tests.conftest import finance_session


async def _setup(client, finance, db, with_evidence=True):
    client.cookies.update(finance_session(finance))
    await client.get("/api/auth/me")
    co = (await client.post("/api/companies", json={"legal_name": "Southern Precision Automation Sdn Bhd",
                                                    "website": "southern-precision.example.my", "industry": "Automation",
                                                    "deal_value": 15000})).json()
    ct = (await client.post("/api/contacts", json={"company_id": co["id"], "full_name": "Jane Tan",
                                                   "original_title": "HR Manager", "email": "jane.tan@southern-precision.example.my"})).json()
    if with_evidence:
        prog = (await db.execute(select(TrainingProgram).where(TrainingProgram.code == "AI_FOR_ENGINEERS"))).scalar_one()
        quote = "Our engineering team is rolling out Industry 4.0 dashboards across customer factories."
        db.add(TrainingOpportunity(company_id=co["id"], program_id=prog.id, match_score=88, reason="Engineering teams and Industry 4.0",
                                   evidence=[{"source_url": "https://southern-precision.example.my/", "quote": quote}], is_current=True))
        db.add(CompanySignal(company_id=co["id"], signal_type="INDUSTRY_4_0", title="Industry 4.0 initiative", evidence_text=quote,
                             source_url="https://southern-precision.example.my/", provenance=Provenance.DISCOVERED, confidence=0.8))
        await db.commit()
    return co, ct


async def test_draft_uses_only_supplied_evidence(client, finance, db):
    co, ct = await _setup(client, finance, db)
    r = await client.post(f"/api/contacts/{ct['id']}/drafts", json={"channel": "EMAIL", "tone": "Consultative"})
    assert r.status_code == 201
    d = r.json()
    assert d["generated_by"] == "TEMPLATE" and d["status"] == "DRAFT"
    assert "Jane" in d["body"] and d["evidence"] and d["evidence"][0]["source_url"].startswith("https://southern-precision")
    li = (await client.post(f"/api/contacts/{ct['id']}/drafts", json={"channel": "LINKEDIN"})).json()
    assert len(li["body"]) <= 300
    assert (await client.post(f"/api/contacts/{ct['id']}/drafts", json={"use_ai": True})).status_code == 422


async def test_approve_then_mark_sent_moves_pipeline(client, finance, db):
    co, ct = await _setup(client, finance, db)
    d = (await client.post(f"/api/contacts/{ct['id']}/drafts", json={})).json()
    assert (await client.post(f"/api/drafts/{d['id']}/mark-sent")).status_code == 409
    edited = (await client.patch(f"/api/drafts/{d['id']}", json={"body": "Hi Jane, edited."})).json()
    assert edited["body"] == "Hi Jane, edited."
    assert (await client.post(f"/api/drafts/{d['id']}/approve")).json()["status"] == "APPROVED"
    assert (await client.post(f"/api/drafts/{d['id']}/mark-sent")).json()["status"] == "SENT"
    contact = (await client.get(f"/api/contacts/{ct['id']}")).json()
    assert contact["status"] == "CONTACTED" and contact["last_contacted_at"]
    assert any(a["type"] == "email" for a in contact["activities"])
    assert (await client.patch(f"/api/drafts/{d['id']}", json={"body": "x"})).status_code == 409


async def test_do_not_contact_blocks_drafts_and_campaigns(client, finance, db):
    co, ct = await _setup(client, finance, db, with_evidence=False)
    await client.post(f"/api/contacts/{ct['id']}/status", json={"status": "DO_NOT_CONTACT"})
    assert (await client.post(f"/api/contacts/{ct['id']}/drafts", json={})).status_code == 409
    camp = (await client.post("/api/campaigns", json={"name": "Johor Manufacturing — AI Productivity"})).json()
    r = (await client.post(f"/api/campaigns/{camp['id']}/contacts", json={"contact_ids": [ct["id"], 9999]})).json()
    assert r["added"] == 0 and {s["reason"] for s in r["skipped"]} == {"Do Not Contact", "Not found"}


async def test_campaign_metrics_and_members(client, finance, db):
    co, ct = await _setup(client, finance, db)
    prog = (await db.execute(select(TrainingProgram).where(TrainingProgram.code == "AI_FOR_ENGINEERS"))).scalar_one()
    camp = (await client.post("/api/campaigns", json={"name": "Johor Engineering — AI for Engineers", "program_id": prog.id,
                                                      "status": "ACTIVE", "start_date": "2026-11-01"})).json()
    assert camp["program"] == "AI for Engineers" and camp["owner"] == "owner"
    r = (await client.post(f"/api/campaigns/{camp['id']}/contacts", json={"contact_ids": [ct["id"]]})).json()
    assert r == {"added": 1, "skipped": []}
    again = (await client.post(f"/api/campaigns/{camp['id']}/contacts", json={"contact_ids": [ct["id"]]})).json()
    assert again["skipped"][0]["reason"] == "Already in campaign"
    await client.post(f"/api/contacts/{ct['id']}/status", json={"status": "MEETING"})
    m = (await client.get(f"/api/campaigns/{camp['id']}")).json()["metrics"]
    assert m["prospects"] == 1 and m["meeting"] == 1 and m["pipeline_value"] == 15000 and m["response_rate"] == 100.0
    members = (await client.get("/api/prospects", params={"campaign_id": camp["id"]})).json()
    assert [p["id"] for p in members["items"]] == [ct["id"]]
    d = (await client.post(f"/api/contacts/{ct['id']}/drafts", json={"campaign_id": camp["id"]})).json()
    assert d["campaign_id"] == camp["id"] and "AI for Engineers" in d["body"] + d["subject"]
    await client.post(f"/api/campaigns/{camp['id']}/contacts/remove", json={"contact_ids": [ct["id"]]})
    assert (await client.get(f"/api/campaigns/{camp['id']}")).json()["metrics"]["prospects"] == 0


async def test_viewer_cannot_create_campaign(client, finance, db):
    from sqlalchemy import update

    from app.models import User
    from app.models.base import Role
    client.cookies.update(finance_session(finance, username="viewer", role="admin"))
    await client.get("/api/auth/me")
    await db.execute(update(User).where(User.finance_username == "viewer").values(role=Role.VIEWER))
    await db.commit()
    assert (await client.post("/api/campaigns", json={"name": "Nope"})).status_code == 403
    assert (await client.get("/api/campaigns")).status_code == 200
