"""Discovery pipeline: search → domain → crawl → company intel → people →
profiles → emails → verification → training match → scores.

Every value written here carries provenance (source type, URL, evidence,
confidence, time). Nothing is invented: when a step has no evidence or its
provider isn't configured, the value stays unknown and the job records a
warning. One company failing never stops the run."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlsplit

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.crawler.fetcher import SafeFetcher, build_crawler
from app.crawler.html import CrawledPage
from app.crawler.robots import RobotsCache
from app.crawler.site import crawl_company_site
from app.extract.company import extract_company_info
from app.extract.people import ExtractedPerson, extract_people_from_pages
from app.extract.signals import detect_signals
from app.models import (Company, CompanyLocation, CompanySignal, CompanySource, Contact, ContactEmail, ContactProfile,
                        ContactSource, CrawlJob, CrawlPage, DuplicateCandidate, EnrichmentJob, Job, ProspectSearch,
                        Suppression, TrainingOpportunity, TrainingProgram)
from app.models.base import (EmailDiscoveryMethod, EmailType, JobStatus, PipelineStatus, Provenance, Seniority,
                             SourceType, VerificationStatus)
from app.providers.base import NotConfigured, ProviderError, QuotaExceeded
from app.services.classify import classify_industry
from app.services.crm import log_activity
from app.services.discovery.candidates import CompanyCandidate, candidates_from_results
from app.services.discovery.domains import DomainEvidence, resolve
from app.services.discovery.profiles import match_profile_results, profile_queries
from app.services.discovery.queries import build_queries
from app.services.email_intel import classify_email, detect_pattern, infer_email, pattern_from_provider, validate_syntax
from app.services.identity import PersonRecord, contact_duplicate_reasons
from app.services.jobs import JobRun
from app.services.normalize import (domain_from_url, normalize_company_name, normalize_person_name, normalize_website,
                                    profile_platform, split_name)
from app.services.runtime import Providers
from app.services.scores import load_weights, rescore_contact
from app.services.titles import normalize_title
from app.services.training import CompanyFacts, PageText, ProgramDef, SignalFact, analyze_training, analyze_training_llm

log = logging.getLogger("app.pipeline")

MAX_PAGE_TEXT = 100_000
DECISION_SENIORITY = {Seniority.MANAGER, Seniority.HEAD, Seniority.DIRECTOR, Seniority.VP, Seniority.C_LEVEL, Seniority.OWNER}
MAX_PROFILE_SEARCHES_PER_COMPANY = 5
MAX_EMAIL_LOOKUPS_PER_COMPANY = 8

COUNTERS = ("companies_discovered", "domains_resolved", "websites_crawled", "contacts_discovered", "profiles_found",
            "emails_discovered", "emails_verified", "training_opportunities", "high_priority")


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Steps:
    crawl: bool = True
    people: bool = True
    profiles: bool = True
    emails: bool = True
    verify: bool = True
    training: bool = True
    scores: bool = True


@dataclass
class Ctx:
    db: AsyncSession
    run: JobRun
    providers: Providers
    fetcher: SafeFetcher
    robots: RobotsCache
    criteria: dict
    steps: Steps = field(default_factory=Steps)
    user_id: int | None = None
    programs: list[ProgramDef] = field(default_factory=list)
    weights: tuple[dict, dict] | None = None


# --- helpers ---------------------------------------------------------------------

def _home(url: str) -> str:
    p = urlsplit(url if "://" in url else "https://" + url)
    return f"{p.scheme or 'https'}://{(p.hostname or '').lower()}"


def _csrc(company_id: int, field_name: str, value, *, prov: Provenance, stype: SourceType, url: str | None,
          evidence: str | None = None, confidence: float | None = None, provider: str | None = None) -> CompanySource:
    return CompanySource(company_id=company_id, field_name=field_name, value=None if value is None else str(value)[:5000],
                         provenance=prov, source_type=stype, provider=provider, source_url=(url or None) and url[:1000],
                         evidence_text=(evidence or None) and evidence[:2000], confidence=confidence)


def _ksrc(contact_id: int, field_name: str, value, *, prov: Provenance, stype: SourceType, url: str | None,
          evidence: str | None = None, confidence: float | None = None, provider: str | None = None) -> ContactSource:
    return ContactSource(contact_id=contact_id, field_name=field_name, value=None if value is None else str(value)[:2000],
                         provenance=prov, source_type=stype, provider=provider, source_url=(url or None) and url[:1000],
                         evidence_text=(evidence or None) and evidence[:2000], confidence=confidence)


async def _suppressed(db: AsyncSession, kind: str, value: str) -> bool:
    return bool(await db.scalar(select(Suppression.id).where(Suppression.kind == kind, Suppression.value == value.lower())))


async def _programs(db: AsyncSession) -> list[ProgramDef]:
    rows = (await db.execute(select(TrainingProgram).where(TrainingProgram.enabled.is_(True)))).scalars().all()
    return [ProgramDef(code=p.code, name=p.name, keywords=list(p.keywords or []), target_departments=list(p.target_departments or []))
            for p in rows]


_PROVIDER_TERMS = re.compile(r"\b(courses?|enrol(?:l|ment)?s?|bootcamps?|syllabus|curriculum|our students|learners|"
                             r"training provider|academy|class schedule|intake|tuition|certification courses?|hrd ?corp claimable|"
                             r"lesson|instructor[s-]?led)\b", re.I)


_SCHOOL_TERMS = re.compile(r"\b(international school|primary school|secondary school|private school|kindergarten|preschool|"
                           r"pupils|principal'?s? (message|welcome)|headmaster|headmistress|head of school|admissions|"
                           r"igcse|a[- ]levels?|cambridge (primary|lower secondary|curriculum)|year [1-9]|form [1-6]|"
                           r"school fees|parents|pta|boarding)\b", re.I)


def school_evidence(pages: list[CrawledPage]) -> list[str]:
    """Distinct school terms. A school is a training *buyer* (staff and students), not a competitor."""
    text = " ".join(p.text[:8000] for p in pages if p.page_type in ("home", "about", "other", "contact"))
    return sorted({m.group(0).lower() for m in _SCHOOL_TERMS.finditer(text)})


def training_provider_evidence(pages: list[CrawledPage]) -> list[str]:
    """Distinct course-selling terms on the home/about pages. A company that
    sells training is a competitor, not a training prospect."""
    text = " ".join(p.text[:8000] for p in pages if p.page_type in ("home", "about", "services", "other"))
    return sorted({m.group(0).lower() for m in _PROVIDER_TERMS.finditer(text)})


_LEGAL_RE = re.compile(r"\b(sdn\.? ?bhd\.?|berhad|bhd\.?|pte\.? ?ltd\.?|limited|ltd\.?|plc|inc\.?)\b|\bschool\b|\bcollege\b", re.I)
_REG_NO = re.compile(r"\s*\((?=[^)]*\d{5,})[^)]*\)")
_GENERIC_NAME = re.compile(r"^(home|about|contact|enquir|overview|welcome|investor|our |corporate|news|products?|services?)", re.I)


def _choose_name(company: Company, candidates, from_search_title: bool = False) -> tuple[str | None, str]:
    """Picks the organisation's own name from the site. Returns (name, how): how is "site" or "domain".
    Only replaces a placeholder (the domain) or a name taken from a search-result title — never a typed name."""
    domain = company.domain or domain_from_url(company.website) or ""
    label = domain.split(".")[0]
    placeholder = company.legal_name.lower() in (domain, label, f"www.{domain}")
    from rapidfuzz import fuzz
    scored = []
    for v in candidates:
        name = _REG_NO.sub("", v.value).strip(" -|,")
        if not name or len(name) > 120 or _GENERIC_NAME.match(name):
            continue
        legal = bool(_LEGAL_RE.search(name))
        sim = fuzz.partial_ratio(re.sub(r"[^a-z0-9]", "", name.lower()), re.sub(r"[^a-z0-9]", "", label.lower())) / 100
        if legal or sim >= 0.8:
            scored.append((v.confidence + (0.3 if legal else 0) + 0.3 * sim, name))
    if scored:
        score, name = max(scored)
        if placeholder or (from_search_title and score >= 0.9):
            return name, "site"
    if placeholder:
        return label.replace("-", " ").title(), "domain"
    return None, ""


_PLACES = ["johor bahru", "johor", "iskandar puteri", "senai", "kulai", "pasir gudang", "batu pahat", "muar", "kluang",
           "kuala lumpur", "cheras", "shah alam", "selangor", "petaling jaya", "subang", "puchong", "klang", "cyberjaya",
           "putrajaya", "penang", "bayan lepas", "george town", "ipoh", "perak", "melaka", "malacca", "seremban",
           "negeri sembilan", "kota kinabalu", "sabah", "kuching", "sarawak", "kedah", "kelantan", "terengganu",
           "pahang", "kuantan", "singapore"]
_JOHOR = {"johor", "johor bahru", "iskandar puteri", "senai", "kulai", "pasir gudang", "batu pahat", "muar", "kluang"}


def outside_target_area(text: str, criteria: dict) -> str | None:
    """A place named in a person's title/page that is clearly not the target area (multi-campus/branch sites)."""
    state = (criteria.get("state") or "").lower()
    city = (criteria.get("city") or "").lower()
    if not state and not city:
        return None
    target = {state, city} - {""}
    if state == "johor":
        target |= _JOHOR
    t = text.lower().replace("-", " ")
    named = [p for p in _PLACES if re.search(rf"\b{re.escape(p)}\b", t)]
    if not named or any(p in target for p in named):
        return None
    return named[0]


def _is_decision_maker(title: str | None, criteria: dict) -> tuple[bool, object]:
    nt = normalize_title(title)
    wanted_titles = {t.lower() for t in criteria.get("titles") or []}
    wanted_depts = {d.lower() for d in criteria.get("departments") or []}
    if nt.normalized_title and (not wanted_titles or nt.normalized_title.lower() in wanted_titles):
        return True, nt
    if nt.seniority in DECISION_SENIORITY and (not wanted_depts or nt.department.value.lower() in wanted_depts
                                               or nt.department.value == "Management"):
        return True, nt
    return False, nt


# --- company resolution --------------------------------------------------------------

async def _find_or_create_company(ctx: Ctx, cand: CompanyCandidate, seeded: bool) -> tuple[Company | None, bool]:
    db, s = ctx.db, get_settings()
    domain = cand.domain
    existing = await db.scalar(select(Company).where(Company.deleted_at.is_(None), Company.is_demo == s.demo_mode,
                                                     Company.domain == domain))
    if existing:
        return existing, False
    normalized = normalize_company_name(cand.name_guess) or domain.split(".")[0]
    same = await db.scalar(select(Company).where(Company.deleted_at.is_(None), Company.is_demo == s.demo_mode,
                                                 Company.normalized_name == normalized, Company.domain.is_(None)))
    if same:
        same.website = same.website or cand.website
        return same, False
    c = Company(legal_name=cand.name_guess[:300], display_name=cand.name_guess[:300], normalized_name=normalized,
                website=cand.website, domain=None, domain_status="UNRESOLVED", is_demo=s.demo_mode,
                created_by_id=ctx.user_id)
    db.add(c)
    await db.flush()
    stype = SourceType.USER_ENTRY if seeded else SourceType.SEARCH_PROVIDER
    prov = Provenance.USER_PROVIDED if seeded else Provenance.DISCOVERED
    db.add(_csrc(c.id, "legal_name", c.legal_name, prov=prov, stype=stype, url=cand.source_url,
                 evidence=cand.title or cand.snippet, provider=None if seeded else cand.provider))
    db.add(_csrc(c.id, "website", cand.website, prov=prov, stype=stype, url=cand.source_url, evidence=cand.snippet,
                 provider=None if seeded else cand.provider))
    similar = (await db.execute(select(Company.id, func.similarity(Company.normalized_name, normalized)).where(
        Company.deleted_at.is_(None), Company.id != c.id, func.similarity(Company.normalized_name, normalized) >= 0.55)
        .limit(5))).all()
    for oid, sim in similar:
        lo, hi = sorted((c.id, oid))
        db.add(DuplicateCandidate(entity_type="company", left_id=lo, right_id=hi, similarity=float(sim),
                                  reasons=["Similar company name found during discovery"]))
    log_activity(db, "discovered", "Found by discovery" + (f" (query: {cand.query})" if cand.query else ""),
                 company_id=c.id, user_id=ctx.user_id)
    return c, True


# --- crawl ---------------------------------------------------------------------------

async def _crawl(ctx: Ctx, company: Company) -> list[CrawledPage]:
    s = get_settings()
    cj = CrawlJob(job_id=ctx.run.job_id, company_id=company.id, domain=domain_from_url(company.website) or "",
                  status=JobStatus.RUNNING, started_at=_now())
    ctx.db.add(cj)
    await ctx.db.flush()

    async def cancelled() -> bool:
        return bool(await ctx.db.scalar(select(Job.cancel_requested).where(Job.id == ctx.run.job_id)))

    result = await crawl_company_site(company.website, ctx.fetcher, ctx.robots, max_pages=s.crawler_max_pages_per_domain,
                                      max_depth=s.crawler_max_depth, should_cancel=cancelled)
    for p in result.pages:
        ctx.db.add(CrawlPage(crawl_job_id=cj.id, company_id=company.id, url=p.url[:1000],
                             canonical_url=(p.canonical_url or p.final_url or "")[:1000] or None, page_type=p.page_type,
                             status_code=p.status_code, content_type=(p.content_type or "")[:120] or None,
                             content_hash=p.content_hash, title=(p.title or "")[:500] or None,
                             text=(p.text or "")[:MAX_PAGE_TEXT], fetched_at=p.fetched_at))
    cj.pages_fetched = len(result.pages)
    cj.pages_skipped = len(result.skipped)
    cj.robots_allowed = result.robots_allowed
    cj.finished_at = _now()
    cj.status = JobStatus.CANCELLED if result.cancelled else (JobStatus.COMPLETED if result.pages else JobStatus.FAILED)
    if result.errors and not result.pages:
        cj.error = "; ".join(f"{e.error_type}: {e.error or e.url}" for e in result.errors[:3])[:2000]
    company.last_crawled_at = _now()
    await ctx.db.flush()
    if result.cancelled:
        await ctx.run.check_cancel()
    if result.pages and len(result.pages) == 1 and (result.pages[0].status_code == 202 or len(result.pages[0].text or "") < 300):
        await ctx.run.note("warning", f"{company.display_name}: the website appears to block automated access (bot protection) "
                                      "or needs JavaScript — only an empty page came back. It is not bypassed; add details manually.",
                           company_id=company.id)
    if not result.pages:
        await ctx.run.note("warning", f"{company.display_name}: website could not be crawled",
                           company_id=company.id, reason=cj.error or ("robots.txt disallows crawling" if result.robots_allowed is False else "no pages"))
    return result.pages


# --- company intelligence --------------------------------------------------------------

async def _company_intel(ctx: Ctx, company: Company, pages: list[CrawledPage]) -> list[SignalFact]:
    db = ctx.db
    info = extract_company_info(pages)
    web = SourceType.COMPANY_WEBSITE

    search_named = bool(await db.scalar(select(CompanySource.id).where(
        CompanySource.company_id == company.id, CompanySource.field_name == "legal_name",
        CompanySource.source_type == SourceType.SEARCH_PROVIDER, CompanySource.value == company.legal_name)))
    user_named = bool(await db.scalar(select(CompanySource.id).where(
        CompanySource.company_id == company.id, CompanySource.field_name == "legal_name",
        CompanySource.source_type.in_([SourceType.USER_ENTRY, SourceType.USER_IMPORT]), CompanySource.value == company.legal_name,
        CompanySource.value != (company.domain or domain_from_url(company.website) or ""))))
    chosen, how = (None, "") if user_named else _choose_name(company, info.name_candidates, search_named)
    if chosen and chosen != company.legal_name:
        company.legal_name = company.display_name = chosen[:300]
        company.normalized_name = normalize_company_name(chosen) or chosen.lower()
        if how == "domain":
            db.add(_csrc(company.id, "legal_name", chosen, prov=Provenance.INFERRED, stype=web, url=company.website,
                         evidence="No organisation name on the site; derived from the domain", confidence=0.3))
    for v in info.name_candidates[:3]:
        db.add(_csrc(company.id, "legal_name", v.value, prov=Provenance.DISCOVERED, stype=web, url=v.evidence.source_url,
                     evidence=v.evidence.snippet, confidence=v.confidence))

    def fill(attr: str, values, field_name: str, transform=lambda x: x, prefer=lambda v: 0.0):
        best = max(values, key=lambda v: v.confidence + prefer(v), default=None)
        if not best:
            return
        db.add(_csrc(company.id, field_name, best.value, prov=Provenance.DISCOVERED, stype=web,
                     url=best.evidence.source_url, evidence=best.evidence.snippet, confidence=best.confidence))
        if getattr(company, attr) in (None, ""):
            setattr(company, attr, transform(best.value))

    fill("description", info.descriptions, "description", lambda v: v[:5000])
    # Multi-branch companies list several offices: prefer the one in the target area / on the company's own domain.
    area = [x.lower() for x in (ctx.criteria.get("city"), ctx.criteria.get("state")) if x]
    own = company.domain or domain_from_url(company.website) or ""
    fill("phone", [p for p in info.phones if p.kind != "fax"], "phone", lambda v: v[:60],
         prefer=lambda v: 0.5 if any(a in (v.evidence.snippet or "").lower() for a in area) else 0.0)
    fill("general_email", [e for e in info.emails if e.kind == "role"], "general_email", lambda v: v.lower()[:320],
         prefer=lambda v: 0.5 if own and v.value.lower().endswith("@" + own) else 0.0)
    best_emp = max(info.employee_counts, key=lambda v: v.confidence, default=None)
    if best_emp:
        try:
            n = int(str(best_emp.value).replace(",", "").split()[0])
        except (ValueError, IndexError):
            n = None
        db.add(_csrc(company.id, "employee_estimate", best_emp.value, prov=Provenance.DISCOVERED, stype=web,
                     url=best_emp.evidence.source_url, evidence=best_emp.evidence.snippet, confidence=best_emp.confidence))
        if n and not company.employee_estimate:
            company.employee_estimate = n
            company.employee_estimate_source = f"Company website: {best_emp.evidence.source_url}"
    for link in info.social_links[:8]:
        db.add(_csrc(company.id, f"profile:{link.kind or 'link'}", link.value, prov=Provenance.DISCOVERED, stype=web,
                     url=link.evidence.source_url, evidence=link.evidence.snippet, confidence=link.confidence))

    target_state = (ctx.criteria.get("state") or "").lower()
    existing_locs = (await db.execute(select(CompanyLocation).where(CompanyLocation.company_id == company.id))).scalars().all()
    known = {(loc.address or "").strip().lower() for loc in existing_locs}
    # Multi-site companies list several addresses: keep the ones in the target state first.
    ranked = sorted(info.addresses, key=lambda v: ((v.data.get("state") or "").lower() == target_state, v.confidence), reverse=True)
    for addr in ranked[:5]:
        if addr.value.strip().lower() in known:
            continue
        src = _csrc(company.id, "address", addr.value, prov=Provenance.DISCOVERED, stype=web,
                    url=addr.evidence.source_url, evidence=addr.evidence.snippet, confidence=addr.confidence)
        db.add(src)
        await db.flush()
        d = addr.data
        loc = CompanyLocation(company_id=company.id, address=addr.value[:1000], city=d.get("city"), state=d.get("state"),
                              postcode=d.get("postcode"), country=d.get("country") or "Malaysia",
                              is_primary=not existing_locs, source_id=src.id)
        db.add(loc)
        existing_locs.append(loc)
        known.add(addr.value.strip().lower())
    await db.flush()
    if target_state and existing_locs:
        primary = next((loc for loc in existing_locs if loc.is_primary), None)
        in_area = next((loc for loc in existing_locs if (loc.state or "").lower() == target_state), None)
        # Only re-point a discovered primary address; one a person entered (no source_id) is left alone.
        if in_area and (primary is None or (primary.source_id and (primary.state or "").lower() != target_state)):
            for loc in existing_locs:
                loc.is_primary = loc is in_area

    if not company.industry:
        text = " ".join([company.description or ""] + [p.text[:4000] for p in pages if p.page_type in ("home", "about", "services")])
        cls = classify_industry(text)
        if cls.industry and cls.industry != "Other":
            company.industry = cls.industry
            db.add(_csrc(company.id, "industry", cls.industry, prov=Provenance.INFERRED, stype=web, url=pages[0].source_url,
                         evidence="Matched terms: " + ", ".join(cls.evidence_terms[:8]), confidence=cls.confidence))

    signals = detect_signals(pages)
    seen = {(s.signal_type, s.evidence_text) for s in (await db.execute(
        select(CompanySignal).where(CompanySignal.company_id == company.id))).scalars()}
    facts = []
    for s in signals:
        facts.append(SignalFact(signal_type=s.signal_type, title=s.title, quote=s.evidence, source_url=s.source_url))
        if (s.signal_type, s.evidence) in seen:
            continue
        db.add(CompanySignal(company_id=company.id, signal_type=s.signal_type, title=s.title[:300], description=s.description,
                             evidence_text=s.evidence[:2000], source_url=s.source_url[:1000],
                             source_date=datetime(s.source_date.year, s.source_date.month, s.source_date.day, tzinfo=timezone.utc) if s.source_date else None,
                             provenance=Provenance.DISCOVERED, confidence=s.confidence))
    company.last_enriched_at = _now()
    await db.flush()
    return facts


async def _resolve_domain(ctx: Ctx, company: Company, pages: list[CrawledPage], location_hint: str | None) -> bool:
    """Confirms the crawled site belongs to the company. Uncertain → never assigned."""
    domain = domain_from_url(pages[0].final_url if pages else company.website)
    if company.domain_status == "USER_PROVIDED":
        company.domain = company.domain or domain
        return True
    home = next((p for p in pages if p.page_type == "home"), pages[0] if pages else None)
    about = " ".join(p.text[:3000] for p in pages if p.page_type in ("about", "home"))[:6000]
    contact = " ".join(p.text[:3000] for p in pages if p.page_type == "contact")[:4000]
    res = resolve(company.legal_name, [DomainEvidence(domain=domain or "", homepage_title=home.title if home else None,
                                                      about_text=about, address_text=contact)], location_hint)
    reasons = "; ".join(r for sc in res.scores for r in sc.reasons)[:2000]
    ctx.db.add(_csrc(company.id, "domain", domain, prov=Provenance.INFERRED, stype=SourceType.COMPANY_WEBSITE,
                     url=home.source_url if home else company.website, evidence=reasons, confidence=res.confidence))
    company.domain_confidence = round(res.confidence, 3)
    if res.status == "RESOLVED" and res.domain:
        clash = await ctx.db.scalar(select(Company.id).where(Company.deleted_at.is_(None), Company.domain == res.domain,
                                                             Company.id != company.id))
        if clash:
            lo, hi = sorted((company.id, clash))
            ctx.db.add(DuplicateCandidate(entity_type="company", left_id=lo, right_id=hi, similarity=1.0,
                                          reasons=[f"Same domain {res.domain}"]))
            company.domain_status = "UNCERTAIN"
            await ctx.run.note("warning", f"{company.display_name}: domain {res.domain} already belongs to company #{clash}",
                               company_id=company.id)
            return False
        company.domain, company.domain_status = res.domain, "RESOLVED"
        return True
    company.domain_status = "UNCERTAIN"
    await ctx.run.note("warning", f"{company.display_name}: website not confidently matched to the company "
                                  f"({round(res.confidence * 100)}%) — people extraction skipped, review manually",
                       company_id=company.id)
    return False


# --- people ------------------------------------------------------------------------------

async def _people(ctx: Ctx, company: Company, pages: list[CrawledPage]) -> list[Contact]:
    db, s = ctx.db, get_settings()
    found = extract_people_from_pages(pages, [company.legal_name, company.display_name])
    existing = (await db.execute(select(Contact).where(Contact.company_id == company.id, Contact.deleted_at.is_(None)))).scalars().all()
    created: list[Contact] = []
    kept = skipped = elsewhere = 0
    for person in found:
        ok, nt = _is_decision_maker(person.original_title, ctx.criteria)
        if not ok:
            skipped += 1
            continue
        if outside_target_area(f"{person.original_title or ''} {person.source_url}", ctx.criteria):
            elsewhere += 1
            continue
        kept += 1
        rec = PersonRecord(full_name=person.full_name, company_id=company.id, emails=[person.email] if person.email else [],
                           profile_urls=[person.profile_url] if person.profile_url else [])
        match = None
        for c in existing + created:
            m = contact_duplicate_reasons(rec, PersonRecord(full_name=c.full_name, company_id=c.company_id, id=c.id))
            if m.is_certain or m.score >= 0.97:
                match = c
                break
        target = match
        if target is None:
            first, last = split_name(person.full_name)
            target = Contact(company_id=company.id, full_name=person.full_name[:200],
                             normalized_name=normalize_person_name(person.full_name), first_name=first, last_name=last,
                             status=PipelineStatus.REVIEW, is_demo=s.demo_mode, owner_id=ctx.user_id)
            target.original_title = (person.original_title or None) and person.original_title[:200]
            target.normalized_title, target.department, target.seniority = nt.normalized_title, nt.department, nt.seniority
            db.add(target)
            await db.flush()
            created.append(target)
            for c in existing:
                m = contact_duplicate_reasons(rec, PersonRecord(full_name=c.full_name, company_id=c.company_id, id=c.id))
                if m.needs_review and not m.is_certain:
                    lo, hi = sorted((c.id, target.id))
                    db.add(DuplicateCandidate(entity_type="contact", left_id=lo, right_id=hi, similarity=m.score, reasons=m.reasons))
            log_activity(db, "discovered", f"Found on {person.source_url}", contact_id=target.id, company_id=company.id,
                         user_id=ctx.user_id)
            await ctx.run.bump(contacts_discovered=1, created=1)
        db.add(_ksrc(target.id, "full_name", person.full_name, prov=Provenance.DISCOVERED, stype=SourceType.COMPANY_WEBSITE,
                     url=person.source_url, evidence=person.evidence, confidence=person.confidence))
        if person.original_title:
            db.add(_ksrc(target.id, "title", person.original_title, prov=Provenance.DISCOVERED,
                         stype=SourceType.COMPANY_WEBSITE, url=person.source_url, evidence=person.evidence,
                         confidence=person.confidence))
        db.add(_ksrc(target.id, "company", company.legal_name, prov=Provenance.DISCOVERED, stype=SourceType.COMPANY_WEBSITE,
                     url=person.source_url, evidence=person.evidence, confidence=person.confidence))
        if person.profile_url:
            await _add_profile(ctx, target, person.profile_url, SourceType.COMPANY_WEBSITE, person.source_url, 0.9, None)
        if person.email:
            await _add_email(ctx, target, company, person.email, method=EmailDiscoveryMethod.PUBLIC_WEBSITE,
                             prov=Provenance.DISCOVERED, source="Company website", url=person.source_url,
                             confidence=0.8, evidence=person.email_evidence)
    if skipped:
        await ctx.run.note("warning", f"{company.display_name}: {skipped} people found but not decision makers for this search",
                           company_id=company.id)
    if elsewhere:
        await ctx.run.note("warning", f"{company.display_name}: {elsewhere} decision makers skipped — they work at a branch/campus "
                                      "outside the target area", company_id=company.id)
    await db.flush()
    return created


async def _add_profile(ctx: Ctx, contact: Contact, url: str, stype: SourceType, source_url: str | None,
                       confidence: float | None, provider: str | None) -> None:
    try:
        url = normalize_website(url) or url
    except ValueError:
        return
    if await ctx.db.scalar(select(ContactProfile.id).where(ContactProfile.contact_id == contact.id, ContactProfile.url == url)):
        return
    ctx.db.add(ContactProfile(contact_id=contact.id, platform=profile_platform(url), url=url[:1000], source_type=stype,
                              provider=provider, source_url=(source_url or None) and source_url[:1000], confidence=confidence))
    await ctx.run.bump(profiles_found=1)


async def _add_email(ctx: Ctx, contact: Contact, company: Company, email: str, *, method: EmailDiscoveryMethod,
                     prov: Provenance, source: str, url: str | None, confidence: float | None,
                     evidence: str | None = None, provider: str | None = None) -> ContactEmail | None:
    norm = validate_syntax(email)
    if not norm:
        return None
    existing = await ctx.db.scalar(select(ContactEmail).where(ContactEmail.contact_id == contact.id, ContactEmail.email == norm))
    if existing:
        if prov != Provenance.INFERRED and existing.provenance == Provenance.INFERRED:
            # independent evidence upgrades an inferred address; its verification status stays as-is
            existing.provenance, existing.discovery_method, existing.source, existing.source_url = prov, method, source, url
        return existing
    has_primary = await ctx.db.scalar(select(ContactEmail.id).where(ContactEmail.contact_id == contact.id,
                                                                    ContactEmail.is_primary.is_(True)))
    e = ContactEmail(contact_id=contact.id, email=norm, email_type=classify_email(norm), discovery_method=method,
                     provenance=prov, source=(provider or source)[:120], source_url=(url or None) and url[:1000],
                     confidence=confidence, verification_status=VerificationStatus.UNVERIFIED,
                     is_primary=not has_primary and prov != Provenance.INFERRED)
    ctx.db.add(e)
    if evidence:
        await ctx.db.flush()
        ctx.db.add(_ksrc(contact.id, "email", norm, prov=prov, stype=SourceType.COMPANY_WEBSITE if method == EmailDiscoveryMethod.PUBLIC_WEBSITE
                         else SourceType.EMAIL_PROVIDER, url=url, evidence=evidence, confidence=confidence, provider=provider))
    await ctx.run.bump(emails_discovered=1)
    return e


async def _profiles_via_search(ctx: Ctx, company: Company, contacts: list[Contact]) -> None:
    search = ctx.providers.search
    if not search:
        return
    for c in contacts[:MAX_PROFILE_SEARCHES_PER_COMPANY]:
        if await ctx.db.scalar(select(ContactProfile.id).where(ContactProfile.contact_id == c.id)):
            continue
        q = profile_queries(c.full_name, company.legal_name)[0]
        try:
            results = await ctx.providers.call(search, lambda q=q: search.search(q, count=5))
        except QuotaExceeded as e:
            await ctx.run.note("warning", f"Search quota reached — profile lookup stopped: {e}", provider=search.info.name)
            return
        except ProviderError as e:
            await ctx.run.note("warning", f"Profile search failed for {c.full_name}: {e.error_type}", provider=search.info.name)
            continue
        matches = match_profile_results(c.full_name, company.legal_name, results)
        if matches:
            m = matches[0]
            await _add_profile(ctx, c, m.url, SourceType.SEARCH_PROVIDER, m.url, m.confidence, m.provider)
            ctx.db.add(_ksrc(c.id, "profile", m.url, prov=Provenance.DISCOVERED, stype=SourceType.SEARCH_PROVIDER,
                             url=m.url, evidence=f"{m.evidence_title} — {m.evidence_snippet}"[:2000],
                             confidence=m.confidence, provider=m.provider))
            if m.company_confirmed:
                ctx.db.add(_ksrc(c.id, "company", company.legal_name, prov=Provenance.DISCOVERED,
                                 stype=SourceType.SEARCH_PROVIDER, url=m.url, evidence=m.evidence_title,
                                 confidence=m.confidence, provider=m.provider))


async def _emails(ctx: Ctx, company: Company) -> None:
    db = ctx.db
    if not company.domain:
        return
    contacts = (await db.execute(select(Contact).where(Contact.company_id == company.id, Contact.deleted_at.is_(None),
                                                       Contact.status != PipelineStatus.DO_NOT_CONTACT))).scalars().all()
    if not contacts:
        return
    by_id = {c.id: c for c in contacts}
    known = (await db.execute(select(ContactEmail).where(ContactEmail.contact_id.in_(by_id),
                                                         ContactEmail.provenance != Provenance.INFERRED))).scalars().all()
    examples = [(by_id[e.contact_id].first_name, by_id[e.contact_id].last_name, e.email) for e in known]
    pattern = detect_pattern(examples, company.domain)

    provider = ctx.providers.email
    if provider:
        try:
            ds = await ctx.providers.call(provider, lambda: provider.domain_search(company.domain, limit=10))
            pattern = pattern or pattern_from_provider(ds.pattern, provider.info.name)
            for de in ds.emails:
                for c in contacts:
                    if de.first_name and de.last_name and normalize_person_name(f"{de.first_name} {de.last_name}") == c.normalized_name:
                        await _add_email(ctx, c, company, de.email, method=EmailDiscoveryMethod.PROVIDER, prov=de.provenance,
                                         source=provider.info.display_name, url=de.sources[0] if de.sources else None,
                                         confidence=de.confidence, provider=provider.info.name,
                                         evidence=f"{provider.info.display_name} domain search")
        except QuotaExceeded as e:
            await ctx.run.note("warning", f"Email discovery quota reached: {e}", provider=provider.info.name)
            provider = None
        except ProviderError as e:
            await ctx.run.note("warning", f"Email discovery failed for {company.domain}: {e.error_type}", provider=provider.info.name)
            if getattr(e, "error_type", "") == "OPTED_OUT":
                db.add(Suppression(kind="DOMAIN", value=company.domain, reason="Opted out at email provider"))
            provider = None

    lookups = 0
    for c in contacts:
        if await db.scalar(select(ContactEmail.id).where(ContactEmail.contact_id == c.id)):
            continue
        if provider and lookups < MAX_EMAIL_LOOKUPS_PER_COMPANY and c.first_name and c.last_name:
            lookups += 1
            try:
                found = await ctx.providers.call(provider, lambda c=c: provider.find_email(c.first_name, c.last_name, company.domain))
                if found:
                    await _add_email(ctx, c, company, found.email, method=EmailDiscoveryMethod.PROVIDER, prov=found.provenance,
                                     source=provider.info.display_name, url=found.sources[0] if found.sources else None,
                                     confidence=found.confidence, provider=provider.info.name,
                                     evidence=f"{provider.info.display_name} email finder")
                    continue
            except QuotaExceeded as e:
                await ctx.run.note("warning", f"Email discovery quota reached: {e}", provider=provider.info.name)
                provider = None
            except ProviderError as e:
                if getattr(e, "error_type", "") == "OPTED_OUT":
                    db.add(Suppression(kind="CONTACT", value=str(c.id), reason="Opted out at email provider"))
                    continue
        guess = infer_email(c.first_name, c.last_name, company.domain, pattern)
        if guess:
            await _add_email(ctx, c, company, guess.email, method=EmailDiscoveryMethod.EMAIL_PATTERN, prov=Provenance.INFERRED,
                             source="Pattern inference", url=None, confidence=guess.confidence,
                             evidence=f"Pattern {guess.pattern} from: {', '.join(guess.evidence[:3])}")
    await db.flush()


async def _verify(ctx: Ctx, company: Company) -> None:
    verifier = ctx.providers.verifier
    if not verifier:
        return
    emails = (await ctx.db.execute(select(ContactEmail).join(Contact, Contact.id == ContactEmail.contact_id).where(
        Contact.company_id == company.id, ContactEmail.verification_status == VerificationStatus.UNVERIFIED,
        ContactEmail.email_type != EmailType.GENERIC))).scalars().all()
    for e in emails:
        try:
            r = await ctx.providers.call(verifier, lambda e=e: verifier.verify(e.email))
        except QuotaExceeded as ex:
            await ctx.run.note("warning", f"Verification quota reached: {ex}", provider=verifier.info.name)
            return
        except ProviderError as ex:
            await ctx.run.note("warning", f"Verification failed for {e.email}: {ex.error_type}", provider=verifier.info.name)
            continue
        e.verification_status, e.verification_provider = r.status, r.provider
        e.verification_confidence, e.verification_meta, e.verified_at = r.confidence, r.meta, r.checked_at
        if r.status == VerificationStatus.VERIFIED:
            await ctx.run.bump(emails_verified=1)
    await ctx.db.flush()


async def _training(ctx: Ctx, company: Company, signals: list[SignalFact]) -> int:
    db = ctx.db
    pages = (await db.execute(select(CrawlPage).where(CrawlPage.company_id == company.id)
                              .order_by(CrawlPage.fetched_at.desc()).limit(40))).scalars().all()
    texts = [PageText(url=p.canonical_url or p.url, text=p.text or "", page_type=p.page_type) for p in pages if p.text]
    if not texts and not company.description:
        return 0
    if not signals:
        signals = [SignalFact(signal_type=s.signal_type, title=s.title, quote=s.evidence_text or "", source_url=s.source_url)
                   for s in (await db.execute(select(CompanySignal).where(CompanySignal.company_id == company.id))).scalars()]
    facts = CompanyFacts(name=company.legal_name, industry=company.industry, description=company.description,
                         employee_estimate=company.employee_estimate)
    opps = None
    if ctx.providers.ai:
        try:
            opps = await analyze_training_llm(ctx.providers.ai, facts, texts, signals, ctx.programs)
        except ProviderError as e:
            await ctx.run.note("warning", f"AI training analysis unavailable ({e.error_type}); used rules", provider=ctx.providers.ai.info.name)
    if opps is None:
        opps = analyze_training(facts, texts, signals, ctx.programs)
    ids = {p.code: p.id for p in (await db.execute(select(TrainingProgram))).scalars()}
    await db.execute(update(TrainingOpportunity).where(TrainingOpportunity.company_id == company.id).values(is_current=False))
    n = 0
    for o in opps:
        if o.program_code not in ids:
            continue
        db.add(TrainingOpportunity(company_id=company.id, program_id=ids[o.program_code], match_score=o.match_score,
                                   reason=o.reason, target_department=o.target_department,
                                   recommended_decision_maker=o.recommended_decision_maker, evidence=o.evidence,
                                   alternative_program_ids=[ids[c] for c in o.alternative_program_codes if c in ids],
                                   method=o.method, is_current=True))
        n += 1
    await db.flush()
    return n


async def _scores(ctx: Ctx, company: Company) -> int:
    ctx.weights = ctx.weights or await load_weights(ctx.db)
    ids = (await ctx.db.execute(select(Contact.id).where(Contact.company_id == company.id, Contact.deleted_at.is_(None)))).scalars().all()
    high = 0
    for cid in ids:
        r = await rescore_contact(ctx.db, cid, ctx.weights)
        high += bool(r and r[1].value == "HIGH")
    return high


# --- one company ---------------------------------------------------------------------

async def enrich_company(ctx: Ctx, company: Company, location_hint: str | None = None) -> None:
    """Crawl → intel → domain → people → profiles → emails → verify → training → scores."""
    db = ctx.db
    if company.domain and await _suppressed(db, "DOMAIN", company.domain):
        await ctx.run.note("warning", f"{company.display_name}: domain is on the Do Not Contact list — skipped", company_id=company.id)
        return
    if not company.website:
        await ctx.run.note("warning", f"{company.display_name}: no website to crawl", company_id=company.id)
        return
    signals: list[SignalFact] = []
    pages: list[CrawledPage] = []
    provider_terms: list[str] = []
    if ctx.steps.crawl:
        pages = await _crawl(ctx, company)
        if pages:
            await ctx.run.bump(websites_crawled=1)
    else:
        from app.crawler.html import make_page
        stored = (await db.execute(select(CrawlPage).where(CrawlPage.company_id == company.id))).scalars().all()
        pages = [make_page(p.url, f"<html><title>{p.title or ''}</title><body><p>{(p.text or '').replace('<', '&lt;')}</p></body></html>",
                           page_type=p.page_type or "other") for p in stored]
    if pages:
        trusted = await _resolve_domain(ctx, company, pages, location_hint)
        if trusted:
            await ctx.run.bump(domains_resolved=1)
            signals = await _company_intel(ctx, company, pages)
            school_terms = school_evidence(pages)
            provider_terms = [] if len(school_terms) >= 3 else training_provider_evidence(pages)
            if len(school_terms) >= 3 and company.industry in (None, "", "Other", "Education"):
                company.industry = "Schools"
                db.add(_csrc(company.id, "industry", "Schools", prov=Provenance.INFERRED, stype=SourceType.COMPANY_WEBSITE,
                             url=pages[0].source_url, evidence="School terms: " + ", ".join(school_terms[:10]), confidence=0.75))
            if len(provider_terms) >= 3:
                if company.industry in (None, "", "Other"):
                    company.industry = "Education"
                    db.add(_csrc(company.id, "industry", "Education", prov=Provenance.INFERRED,
                                 stype=SourceType.COMPANY_WEBSITE, url=pages[0].source_url,
                                 evidence="Training-provider terms: " + ", ".join(provider_terms[:10]), confidence=0.7))
            if ctx.steps.people:
                contacts = await _people(ctx, company, pages)
                if ctx.steps.profiles and ctx.criteria.get("find_profiles", True):
                    all_contacts = (await db.execute(select(Contact).where(Contact.company_id == company.id,
                                                                           Contact.deleted_at.is_(None)))).scalars().all()
                    await _profiles_via_search(ctx, company, list(contacts) or list(all_contacts))
            if ctx.steps.emails:
                await _emails(ctx, company)
            if ctx.steps.verify:
                await _verify(ctx, company)
    await db.commit()
    if len(provider_terms) >= 3:
        await db.execute(update(TrainingOpportunity).where(TrainingOpportunity.company_id == company.id).values(is_current=False))
        await ctx.run.note("warning", f"{company.display_name}: looks like a training provider (possible competitor: "
                                      f"{', '.join(provider_terms[:5])}) — training match not calculated", company_id=company.id)
    elif ctx.steps.training:
        n = await _training(ctx, company, signals)
        if n:
            await ctx.run.bump(training_opportunities=n)
    if ctx.steps.scores:
        high = await _scores(ctx, company)
        if high:
            await ctx.run.bump(high_priority=high)
    await db.commit()


# --- discovery job ---------------------------------------------------------------------

async def _candidates(ctx: Ctx, limit: int) -> list[tuple[CompanyCandidate, bool]]:
    out: list[tuple[CompanyCandidate, bool]] = []
    seen: set[str] = set()
    for raw in ctx.criteria.get("seed_websites") or []:
        try:
            site = normalize_website(raw)
        except ValueError:
            await ctx.run.note("warning", f"Ignored invalid website: {raw[:100]}")
            continue
        dom = domain_from_url(site)
        if not dom or dom in seen:
            continue
        seen.add(dom)
        out.append((CompanyCandidate(name_guess=dom, website=_home(site), domain=dom, snippet="", source_url=site,
                                     provider="user", query="", rank=0, title=""), True))
    search = ctx.providers.search
    if not search:
        if not out:
            raise NotConfigured("No search provider is configured and no websites were given. Add SEARCH_PROVIDER and "
                                "SEARCH_API_KEY, or list company websites in the search.")
        await ctx.run.note("warning", "Search provider not configured — only the listed websites were processed")
        return out[:limit]
    queries = build_queries(ctx.criteria, max_queries=40)
    await ctx.run.bump(stage="Searching for companies")
    for q in queries:
        if len(out) >= limit:
            break
        await ctx.run.check_cancel()
        try:
            results = await ctx.providers.call(search, lambda q=q: search.search(q.query, count=20,
                                                                                country="SG" if (ctx.criteria.get("country") or "").lower() == "singapore" else "MY"))
        except QuotaExceeded as e:
            await ctx.run.note("warning", f"Search quota reached after {len(out)} candidates: {e}", provider=search.info.name)
            break
        except ProviderError as e:
            await ctx.run.note("error", f"Search failed for '{q.query}': {e.error_type}", provider=search.info.name)
            if e.error_type in ("INVALID_CREDENTIALS", "NOT_CONFIGURED"):
                raise
            continue
        for cand in candidates_from_results(results):
            if cand.domain in seen:
                continue
            if await _suppressed(ctx.db, "DOMAIN", cand.domain):
                continue
            seen.add(cand.domain)
            out.append((cand, False))
    return out[:limit]


async def run_discovery(db: AsyncSession, run: JobRun, providers: Providers, user_id: int | None) -> None:
    job = await db.get(Job, run.job_id)
    search = await db.get(ProspectSearch, job.search_id) if job.search_id else None
    criteria = dict(search.criteria if search else job.params.get("criteria", {}))
    s = get_settings()
    fetcher, robots = build_crawler(user_agent=s.crawler_user_agent, timeout=s.crawler_timeout_seconds,
                                    min_delay=s.crawler_min_delay_seconds, pin_dns=True)
    ctx = Ctx(db=db, run=run, providers=providers, fetcher=fetcher, robots=robots, criteria=criteria, user_id=user_id,
              programs=await _programs(db))
    try:
        await run.bump(stage="Preparing", **{k: 0 for k in COUNTERS})
        limit = max(1, min(int(criteria.get("max_companies") or 20), 500))
        candidates = await _candidates(ctx, limit)
        if not candidates:
            await run.note("warning", "No candidate companies found for these criteria")
            return
        for i, (cand, seeded) in enumerate(candidates):
            await run.check_cancel()
            await run.bump(stage=f"Processing {cand.domain} ({i + 1}/{len(candidates)})",
                           progress=100 * i / len(candidates), processed=1)
            try:
                company, new = await _find_or_create_company(ctx, cand, seeded)
                if company is None:
                    continue
                if seeded and not company.domain:
                    company.domain_status = "USER_PROVIDED"
                await db.commit()
                if new:
                    await run.bump(companies_discovered=1, created=1)
                db.add(EnrichmentJob(job_id=run.job_id, company_id=company.id, step="enrich_company", status=JobStatus.RUNNING))
                await enrich_company(ctx, company, criteria.get("state"))
            except Exception as e:  # isolate per-company failures
                if type(e).__name__ == "JobCancelled":
                    raise
                await db.rollback()
                log.exception("company failed", extra={"job_id": run.job_id, "error_type": type(e).__name__})
                await run.note("error", f"{cand.domain}: {type(e).__name__}: {str(e)[:200]}", company=cand.domain)
        await run.bump(stage="Done", progress=100)
    finally:
        await fetcher.aclose()


async def run_enrich(db: AsyncSession, run: JobRun, providers: Providers, user_id: int | None) -> None:
    job = await db.get(Job, run.job_id)
    company = await db.get(Company, job.params["company_id"])
    steps = Steps(**{k: v for k, v in (job.params.get("steps") or {}).items() if k in Steps.__dataclass_fields__})
    s = get_settings()
    fetcher, robots = build_crawler(user_agent=s.crawler_user_agent, timeout=s.crawler_timeout_seconds,
                                    min_delay=s.crawler_min_delay_seconds, pin_dns=True)
    loc = await db.scalar(select(CompanyLocation.state).where(CompanyLocation.company_id == company.id).limit(1))
    criteria = dict(job.params.get("criteria") or {})
    if not criteria.get("state"):
        # A re-enrich has no search criteria: target the best-scoring location from the lead-score settings.
        from app.services.scores import load_weights
        locations = (await load_weights(db))[0].get("locations") or {}
        if locations:
            criteria["state"] = max(locations, key=locations.get)
    ctx = Ctx(db=db, run=run, providers=providers, fetcher=fetcher, robots=robots,
              criteria=criteria, steps=steps, user_id=user_id, programs=await _programs(db))
    try:
        await run.bump(stage=f"Enriching {company.display_name}", **{k: 0 for k in COUNTERS})
        await enrich_company(ctx, company, loc)
    finally:
        await fetcher.aclose()
