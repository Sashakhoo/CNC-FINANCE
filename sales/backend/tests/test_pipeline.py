"""End-to-end discovery pipeline against a fake web (respx) and real Postgres.
DNS is faked per hostname; the fetcher pins requests to those IPs, so routes
match the IP with the original Host header."""
import os

import httpx
import pytest
import respx
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import sessionmaker
from app.crawler import url_safety
from app.models import (Company, CompanySignal, CompanySource, Contact, ContactEmail, ContactSource, Job, LeadScore,
                        ProspectSearch, ProviderUsage, TrainingOpportunity)
from app.models.base import JobStatus, Provenance, SourceType, VerificationStatus
from app.providers.ratelimit import MemoryQuotaStore, ProviderGuard
from app.services.jobs import create_job, run_job
from app.services.pipeline import run_discovery
from app.services.runtime import build_providers

SITES = {"southern-precision.com.my": "93.184.216.10", "www.southern-precision.com.my": "93.184.216.10",
         "rotiroti-bakes.com.my": "93.184.216.11", "www.rotiroti-bakes.com.my": "93.184.216.11"}

HOME = """<!doctype html><html><head><title>Southern Precision Automation Sdn Bhd | Industrial Automation, Johor Bahru</title>
<meta property="og:site_name" content="Southern Precision Automation Sdn Bhd">
<meta name="description" content="Southern Precision Automation designs automation and robotics cells for electronics manufacturers in Johor."></head>
<body><h1>Southern Precision Automation</h1>
<p>We build industrial automation systems and robotic assembly lines for semiconductor and electronics plants.</p>
<p>Our engineering team is rolling out Industry 4.0 dashboards and predictive maintenance across customer factories.</p>
<a href="/about">About</a> <a href="/team">Our Team</a> <a href="/careers">Careers</a> <a href="/contact">Contact</a></body></html>"""
ABOUT = """<html><head><title>About Us | Southern Precision Automation</title></head><body><h1>About Us</h1>
<p>Founded in 2009, Southern Precision Automation Sdn Bhd employs over 240 employees in Johor Bahru.</p>
<p>We are investing in digital transformation of our own operations, including a new ERP implementation this year.</p></body></html>"""
TEAM = """<html><head><title>Management Team | Southern Precision Automation</title></head><body><h1>Management Team</h1>
<div class="card"><h3>Jane Tan</h3><p>HR Manager</p><p>jane.tan@southern-precision.com.my</p></div>
<div class="card"><h3>Daniel Lee</h3><p>Engineering Manager</p></div>
<div class="card"><h3>Aishah Rahman</h3><p>Receptionist</p></div>
</body></html>"""
CAREERS = """<html><head><title>Careers | Southern Precision Automation</title></head><body><h1>Careers</h1>
<p>We are hiring! Join our growing team.</p><ul><li>Automation Engineer</li><li>Electrical Engineer</li></ul></body></html>"""
CONTACT = """<html><head><title>Contact | Southern Precision Automation</title></head><body><h1>Contact Us</h1>
<p>Lot 12, Jalan Perindustrian 3, Taman Perindustrian Maju</p><p>81100 Johor Bahru, Johor</p>
<p>Tel: +60 7-355 1234</p><p>Email: info@southern-precision.com.my</p></body></html>"""
BAKERY = """<html><head><title>RotiRoti Bakes - Fresh Bread Daily</title></head><body><h1>Fresh bread daily</h1>
<p>Our bakery serves croissants and kaya buns in Melaka.</p><div class="card"><h3>Mei Ling Ong</h3><p>Operations Manager</p></div></body></html>"""


@pytest.fixture
def env(monkeypatch):
    for k, v in {"SEARCH_PROVIDER": "brave", "SEARCH_API_KEY": "test-brave-key", "CRAWLER_MIN_DELAY_SECONDS": "0",
                 "EMAIL_DISCOVERY_PROVIDER": "", "EMAIL_VERIFICATION_PROVIDER": "", "LLM_PROVIDER": ""}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()

    async def fake_resolve(host, port):
        if host not in SITES:
            raise url_safety.DNSResolutionError(f"no addresses for {host}")
        return [SITES[host]]
    monkeypatch.setattr(url_safety, "system_resolve", fake_resolve)
    yield
    get_settings.cache_clear()


def _site(mock, ip: str, host: str, pages: dict[str, str]):
    def handler(request: httpx.Request):
        if request.headers.get("host") not in (host, f"www.{host}"):
            return httpx.Response(421)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        html = pages.get(request.url.path.rstrip("/") or "/")
        return httpx.Response(200, html=html, headers={"content-type": "text/html; charset=utf-8"}) if html else httpx.Response(404)
    mock.route(host=ip).mock(side_effect=handler)


def _brave(mock):
    mock.get("https://api.search.brave.com/res/v1/web/search").mock(return_value=httpx.Response(200, json={"web": {"results": [
        {"title": "Southern Precision Automation Sdn Bhd - Industrial Automation Johor", "url": "https://www.southern-precision.com.my/",
         "description": "Automation and robotics for electronics manufacturers in Johor Bahru."},
        {"title": "Automation Engineer jobs in Johor", "url": "https://www.jobstreet.com.my/automation-jobs", "description": "Jobs"},
        {"title": "Johor Precision Tools Sdn Bhd - CNC Machining", "url": "https://rotiroti-bakes.com.my/", "description": "Precision machining in Johor"},
    ]}}))


async def _run(db, criteria) -> int:
    s = ProspectSearch(name="Johor Engineering Prospects", criteria=criteria)
    db.add(s)
    await db.flush()
    job = await create_job(db, "discovery", s.name, search_id=s.id)
    await db.commit()
    providers = build_providers(sessionmaker(), job.id, guard=ProviderGuard(MemoryQuotaStore()))
    try:
        await run_job(db, job.id, lambda run: run_discovery(db, run, providers, None))
    finally:
        await providers.aclose()
    return job.id


CRITERIA = {"country": "Malaysia", "state": "Johor", "industries": ["Automation"], "max_companies": 5,
            "departments": ["HR", "L&D", "IT", "Engineering", "Operations", "Management"], "titles": [], "find_profiles": False}


async def test_discovery_end_to_end(db, env):
    with respx.mock(assert_all_called=False) as mock:
        _brave(mock)
        _site(mock, "93.184.216.10", "southern-precision.com.my",
              {"/": HOME, "/about": ABOUT, "/team": TEAM, "/careers": CAREERS, "/contact": CONTACT})
        _site(mock, "93.184.216.11", "rotiroti-bakes.com.my", {"/": BAKERY})
        job_id = await _run(db, CRITERIA)

    job = await db.get(Job, job_id)
    await db.refresh(job)
    assert job.status == JobStatus.COMPLETED, job.errors
    assert job.counters["companies_discovered"] == 2          # job board filtered out
    assert job.counters["domains_resolved"] == 1               # bakery not confidently matched
    assert job.counters["websites_crawled"] == 2
    assert any("not confidently matched" in w["message"] for w in job.warnings)

    co = (await db.execute(select(Company).where(Company.domain == "southern-precision.com.my"))).scalar_one()
    assert co.domain_status == "RESOLVED" and co.domain_confidence >= 0.75
    assert co.legal_name == "Southern Precision Automation Sdn Bhd"
    assert co.phone and co.phone.startswith("+60") and co.general_email == "info@southern-precision.com.my"
    assert co.employee_estimate == 240 and co.industry
    srcs = (await db.execute(select(CompanySource).where(CompanySource.company_id == co.id))).scalars().all()
    phone_src = next(s for s in srcs if s.field_name == "phone")
    assert phone_src.provenance == Provenance.DISCOVERED and phone_src.source_url.endswith("/contact")
    assert "355 1234" in phone_src.evidence_text

    bakery = (await db.execute(select(Company).where(Company.website.like("%rotiroti%")))).scalar_one()
    assert bakery.domain is None and bakery.domain_status == "UNCERTAIN"
    assert not (await db.execute(select(Contact).where(Contact.company_id == bakery.id))).scalars().all()

    people = {c.full_name: c for c in (await db.execute(select(Contact).where(Contact.company_id == co.id))).scalars()}
    assert set(people) == {"Jane Tan", "Daniel Lee"}           # receptionist isn't a decision maker
    jane, daniel = people["Jane Tan"], people["Daniel Lee"]
    assert jane.status.value == "REVIEW" and jane.department.value == "HR"
    name_src = (await db.execute(select(ContactSource).where(ContactSource.contact_id == jane.id,
                                                              ContactSource.field_name == "full_name"))).scalars().first()
    assert name_src.source_type == SourceType.COMPANY_WEBSITE and name_src.source_url.endswith("/team")

    je = (await db.execute(select(ContactEmail).where(ContactEmail.contact_id == jane.id))).scalar_one()
    assert (je.email, je.provenance, je.verification_status) == ("jane.tan@southern-precision.com.my", Provenance.DISCOVERED,
                                                                 VerificationStatus.UNVERIFIED)
    de = (await db.execute(select(ContactEmail).where(ContactEmail.contact_id == daniel.id))).scalar_one()
    assert de.email == "daniel.lee@southern-precision.com.my"
    assert (de.provenance, de.verification_status, de.discovery_method.value) == (Provenance.INFERRED, VerificationStatus.UNVERIFIED, "EMAIL_PATTERN")
    assert de.is_primary is False

    sig_types = {s.signal_type for s in (await db.execute(select(CompanySignal).where(CompanySignal.company_id == co.id))).scalars()}
    assert {"HIRING_ENGINEERS", "INDUSTRY_4_0"} <= sig_types

    opps = (await db.execute(select(TrainingOpportunity).where(TrainingOpportunity.company_id == co.id))).scalars().all()
    assert opps, "expected training opportunities"
    page_text = (HOME + ABOUT + CAREERS).replace("&amp;", "&")
    for o in opps:
        for ev in o.evidence:
            assert ev["quote"][:40] in page_text or ev["quote"][:40].replace("  ", " ") in " ".join(page_text.split())

    scores = {s.contact_id: s for s in (await db.execute(select(LeadScore).where(LeadScore.is_current.is_(True)))).scalars()}
    assert jane.id in scores and daniel.id in scores
    usage = (await db.execute(select(ProviderUsage))).scalars().all()
    assert usage and all(u.provider == "brave" for u in usage)


async def test_no_search_provider_and_no_websites_fails_clearly(db, env, monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER", "")
    get_settings.cache_clear()
    job_id = await _run(db, CRITERIA)
    job = await db.get(Job, job_id)
    await db.refresh(job)
    assert job.status == JobStatus.FAILED
    assert "No search provider is configured" in job.errors[0]["message"]


async def test_seed_websites_work_without_search_provider(db, env, monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER", "")
    get_settings.cache_clear()
    with respx.mock(assert_all_called=False) as mock:
        _site(mock, "93.184.216.10", "southern-precision.com.my", {"/": HOME, "/team": TEAM, "/contact": CONTACT})
        job_id = await _run(db, {**CRITERIA, "seed_websites": ["southern-precision.com.my"]})
    job = await db.get(Job, job_id)
    await db.refresh(job)
    assert job.status == JobStatus.COMPLETED, job.errors
    co = (await db.execute(select(Company))).scalar_one()
    assert co.domain == "southern-precision.com.my" and co.domain_status == "USER_PROVIDED"
    assert co.legal_name == "Southern Precision Automation Sdn Bhd"   # site's own name replaces the domain placeholder
    assert job.counters["contacts_discovered"] == 2


async def test_cancel_before_start(db, env):
    s = ProspectSearch(name="x", criteria=CRITERIA)
    db.add(s)
    await db.flush()
    job = await create_job(db, "discovery", "x", search_id=s.id)
    job.cancel_requested = True
    await db.commit()
    providers = build_providers(sessionmaker(), job.id, guard=ProviderGuard(MemoryQuotaStore()))
    try:
        await run_job(db, job.id, lambda run: run_discovery(db, run, providers, None))
    finally:
        await providers.aclose()
    await db.refresh(job)
    assert job.status in (JobStatus.CANCELLED, JobStatus.FAILED)
    assert os.environ.get("APP_ENV") == "test"


ACADEMY = """<html><head><title>Example Code Academy</title></head><body><h1>Example Code Academy</h1>
<p>Our Python courses and AI bootcamps help learners upskill. Enrol now for the next intake.</p>
<p>Each course follows a hands-on curriculum with instructor-led lessons and certification courses.</p></body></html>"""


async def test_training_provider_is_not_scored_as_a_prospect(db, env, monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER", "")
    get_settings.cache_clear()
    SITES["example-academy.com.my"] = "93.184.216.12"
    try:
        with respx.mock(assert_all_called=False) as mock:
            _site(mock, "93.184.216.12", "example-academy.com.my", {"/": ACADEMY})
            job_id = await _run(db, {**CRITERIA, "seed_websites": ["example-academy.com.my"]})
    finally:
        SITES.pop("example-academy.com.my")
    job = await db.get(Job, job_id)
    await db.refresh(job)
    co = (await db.execute(select(Company))).scalar_one()
    assert co.industry == "Education"
    assert not (await db.execute(select(TrainingOpportunity).where(TrainingOpportunity.is_current.is_(True)))).scalars().all()
    assert any("training provider" in w["message"] for w in job.warnings)
