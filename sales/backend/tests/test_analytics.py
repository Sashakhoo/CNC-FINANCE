from app.models import Company, CompanyLocation, Contact, ContactConfidenceScore, ContactSource, LeadScore, ProviderUsage
from app.models.base import Department, PipelineStatus, Priority, Provenance, SourceType
from tests.conftest import finance_session


async def _seed(db):
    a = Company(legal_name="Alpha Automation Sdn Bhd", display_name="Alpha", normalized_name="alpha automation",
                industry="Automation", deal_value=10000)
    b = Company(legal_name="Beta Electronics Sdn Bhd", display_name="Beta", normalized_name="beta electronics",
                industry="Electronics", deal_value=20000)
    db.add_all([a, b])
    await db.flush()
    db.add_all([CompanyLocation(company_id=a.id, state="Johor", is_primary=True),
                CompanyLocation(company_id=b.id, state="Penang", is_primary=True)])
    people = [(a, "HR Manager", PipelineStatus.MEETING, 85, Priority.HIGH, 92, SourceType.COMPANY_WEBSITE),
              (a, "IT Manager", PipelineStatus.CONTACTED, 70, Priority.MEDIUM, 55, SourceType.COMPANY_WEBSITE),
              (b, "HR Manager", PipelineStatus.WON, 90, Priority.HIGH, 98, SourceType.USER_ENTRY),
              (b, "Engineering Manager", PipelineStatus.LOST, 40, Priority.LOW, 30, SourceType.USER_ENTRY),
              (b, "Engineering Manager", PipelineStatus.REVIEW, 50, Priority.LOW, 10, SourceType.USER_ENTRY)]
    for i, (co, title, status, score, prio, conf, src) in enumerate(people):
        c = Contact(company_id=co.id, full_name=f"Person {i}", normalized_name=f"person {i}", normalized_title=title,
                    department=Department.HR, status=status)
        db.add(c)
        await db.flush()
        db.add_all([LeadScore(contact_id=c.id, score=score, priority=prio, breakdown=[]),
                    ContactConfidenceScore(contact_id=c.id, score=conf, breakdown=[]),
                    ContactSource(contact_id=c.id, field_name="full_name", value=c.full_name, provenance=Provenance.DISCOVERED,
                                  source_type=src)])
    db.add_all([ProviderUsage(provider="brave", kind="SEARCH", operation="web_search", success=True, duration_ms=200),
                ProviderUsage(provider="brave", kind="SEARCH", operation="web_search", success=False, duration_ms=100, error_type="RATE_LIMITED")])
    await db.commit()


async def test_report_counts_from_database(client, finance, db):
    client.cookies.update(finance_session(finance))
    await _seed(db)
    r = (await client.get("/api/analytics/report")).json()
    assert r["funnel"] == {"prospects": 5, "reached": 4, "responded": 2, "meetings": 2, "proposals": 1, "won": 1, "lost": 1}
    assert r["rates"] == {"response": 50.0, "meeting": 50.0, "proposal": 25.0, "win": 50.0}
    assert r["qualified"] == {"HIGH": 2, "MEDIUM": 1, "LOW": 2}
    assert [d["contacts"] for d in r["confidence_distribution"]] == [1, 1, 1, 0, 2]
    assert r["pipeline_value"] == 10000.0          # Alpha has contacts in active stages; Beta only WON/LOST/REVIEW
    ind = {x["name"]: x for x in r["industry"]}
    assert ind["Electronics"]["won"] == 1 and ind["Automation"]["meetings"] == 1
    assert {x["name"] for x in r["location"]} == {"Johor", "Penang"}
    roles = {x["name"]: x["prospects"] for x in r["role"]}
    assert roles["Engineering Manager"] == 2
    src = {x["name"]: x["prospects"] for x in r["lead_source"]}
    assert src == {"Company Website": 2, "User Entry": 3}
    brave = next(p for p in r["providers"] if p["provider"] == "brave")
    assert brave["calls"] == 2 and brave["success_rate"] == 50.0
    assert sum(w["leads"] for w in r["lead_growth"]) == 5


async def test_report_empty_database(client, finance):
    client.cookies.update(finance_session(finance))
    r = (await client.get("/api/analytics/report", params={"days": 30})).json()
    assert r["funnel"]["prospects"] == 0 and r["rates"]["response"] is None and r["providers"] == []
