"""Fictional demo dataset (spec §57). Runs only when DEMO_MODE=true; every record
is flagged is_demo and uses reserved *.example domains, so it can never be mistaken
for — or mixed with — real prospects (production views filter is_demo=false).

    docker compose run --rm -e DEMO_MODE=true backend python -m app.scripts.seed_demo
"""
import asyncio
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import task_session
from app.models import Company, CompanyLocation, CompanySignal, CompanySource, Contact, ContactEmail, ContactSource
from app.models.base import (EmailDiscoveryMethod, EmailType, PipelineStatus, Provenance, SourceType, VerificationStatus)
from app.services.normalize import normalize_company_name, normalize_person_name, split_name
from app.services.scores import rescore_company
from app.services.titles import normalize_title

DEMO = [
    ("Demo Precision Automation Sdn Bhd", "demo-precision.example", "Automation", "Johor Bahru", "Johor", 240, 18000,
     [("Aina Demo", "HR Manager", "aina.demo", PipelineStatus.REVIEW), ("Ben Example", "Engineering Manager", None, PipelineStatus.APPROVED)],
     ("INDUSTRY_4_0", "Industry 4.0 initiative", "Demo text: we are rolling out Industry 4.0 dashboards.")),
    ("Example Electronics Sdn Bhd", "example-electronics.example", "Electronics", "Senai", "Johor", 520, 24000,
     [("Chen Sample", "L&D Manager", "chen.sample", PipelineStatus.CONTACTED)],
     ("HIRING_ENGINEERS", "Hiring engineers", "Demo text: we are hiring process engineers.")),
    ("Sample Semiconductor Sdn Bhd", "sample-semi.example", "Semiconductor", "Bayan Lepas", "Penang", 900, 32000,
     [("Dee Placeholder", "Head of IT", "dee.placeholder", PipelineStatus.MEETING)],
     ("CYBERSECURITY_CERTIFICATION", "Cybersecurity certification", "Demo text: ISO 27001 certification achieved.")),
]


async def seed() -> int:
    if not get_settings().demo_mode:
        print("Refusing to seed: DEMO_MODE is not true.", file=sys.stderr)
        return 1
    async with task_session() as db:
        if await db.scalar(select(Company.id).where(Company.is_demo.is_(True)).limit(1)):
            print("Demo data already present.")
            return 0
        for name, domain, industry, city, state, size, deal, people, signal in DEMO:
            co = Company(legal_name=name, display_name=name, normalized_name=normalize_company_name(name), website=f"https://{domain}",
                         domain=domain, domain_status="USER_PROVIDED", industry=industry, employee_estimate=size,
                         employee_estimate_source="Demo data", deal_value=deal, is_demo=True,
                         description="Fictional company for demonstrations — not a real business.")
            db.add(co)
            await db.flush()
            db.add(CompanyLocation(company_id=co.id, city=city, state=state, is_primary=True))
            db.add(CompanySource(company_id=co.id, field_name="legal_name", value=name, provenance=Provenance.USER_PROVIDED,
                                 source_type=SourceType.DEMO, evidence_text="Fictional demo record"))
            db.add(CompanySignal(company_id=co.id, signal_type=signal[0], title=signal[1], evidence_text=signal[2],
                                 provenance=Provenance.USER_PROVIDED, confidence=0.8))
            for full, title, local, status in people:
                nt = normalize_title(title)
                first, last = split_name(full)
                c = Contact(company_id=co.id, full_name=full, normalized_name=normalize_person_name(full), first_name=first,
                            last_name=last, original_title=title, normalized_title=nt.normalized_title, department=nt.department,
                            seniority=nt.seniority, status=status, is_demo=True)
                db.add(c)
                await db.flush()
                db.add(ContactSource(contact_id=c.id, field_name="full_name", value=full, provenance=Provenance.USER_PROVIDED,
                                     source_type=SourceType.DEMO, evidence_text="Fictional demo record"))
                if local:
                    db.add(ContactEmail(contact_id=c.id, email=f"{local}@{domain}", email_type=EmailType.PERSONAL_BUSINESS,
                                        discovery_method=EmailDiscoveryMethod.USER_ENTRY, provenance=Provenance.USER_PROVIDED,
                                        source="Demo data", verification_status=VerificationStatus.UNVERIFIED, is_primary=True))
            await db.flush()
            await rescore_company(db, co.id)
        await db.commit()
    print(f"Seeded {len(DEMO)} fictional demo companies.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(seed()))
