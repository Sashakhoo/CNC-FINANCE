import re

import pytest

from app.providers.base import RateLimited
from app.services.outreach import (LINKEDIN_MAX, OutreachContact, OutreachOpportunity, Sender, generate_draft,
                                   generate_draft_llm)
from app.services.training import SignalFact, unsupported_tokens

CONTACT = OutreachContact("Jane Tan", "HR Manager", "Acme Precision Sdn Bhd", "Automation")
OPP = OutreachOpportunity("AI for Engineers", "Company content mentions 'industry 4.0'.",
                          [{"source_url": "https://acme.example/about",
                            "quote": "We are investing in Industry 4.0 and smart manufacturing across our two plants."}])
SENDER = Sender("Sasha", "Corporate Training Lead", "Codencode Academy")


def _inputs_text():
    return [CONTACT.name, CONTACT.original_title, CONTACT.company_name, CONTACT.industry, SENDER.name, SENDER.title,
            SENDER.company, OPP.program_name, OPP.reason] + [e["quote"] for e in OPP.evidence]


class FakeAI:
    def __init__(self, payload=None, error=None):
        self.payload, self.error = payload, error

    async def generate_structured(self, system, prompt, schema, max_tokens=1500):
        if self.error:
            raise self.error
        return schema.model_validate(self.payload)


@pytest.mark.parametrize("tone", ["Professional", "Friendly", "Concise", "Consultative"])
@pytest.mark.parametrize("channel", ["EMAIL", "FOLLOWUP", "LINKEDIN"])
def test_templates_use_only_supplied_facts(channel, tone):
    d = generate_draft(CONTACT, OPP, [], SENDER, channel, tone)
    assert d.generated_by == "TEMPLATE" and d.body
    # Only numbers allowed in templates: the "20-minute" call ask and numbers in the quoted evidence.
    nums = set(re.findall(r"\b\d+\b", d.body)) - {"20"}
    assert not nums - set(re.findall(r"\b\d+\b", " ".join(_inputs_text())))
    assert "http" not in d.body
    found = unsupported_tokens(d.body, _inputs_text()) + unsupported_tokens(d.subject, _inputs_text())
    caps = [w for w in found if not w.isdigit() and w != "20"]
    assert caps == [], caps
    for e in d.evidence_used:
        assert e in OPP.evidence


@pytest.mark.parametrize("tone", ["Professional", "Friendly", "Concise", "Consultative"])
def test_linkedin_respects_length(tone):
    long = OutreachContact("Jane Tan", "Senior Regional Learning and Development Manager, Asia Pacific",
                           "Southern Precision Automation and Engineering Sdn Bhd", "Industrial Automation")
    d = generate_draft(long, OPP, [], SENDER, "LINKEDIN", tone)
    assert len(d.body) <= LINKEDIN_MAX and d.subject == ""


def test_signal_evidence_preferred_and_quoted_verbatim():
    sig = SignalFact("AI_INITIATIVE", "AI pilot", "Acme launched an AI pilot for quality inspection.", "https://acme.example/news")
    d = generate_draft(CONTACT, OPP, [sig], SENDER)
    assert d.evidence_used == [{"source_url": sig.source_url, "quote": sig.quote}]
    assert sig.quote in d.body


def test_no_opportunity_no_evidence_still_safe():
    d = generate_draft(CONTACT, None, [], SENDER)
    assert d.evidence_used == [] and "website" not in d.body


async def test_llm_draft_accepted_when_grounded():
    ai = FakeAI({"subject": "AI for Engineers training for Acme Precision Sdn Bhd",
                 "body": "Dear Jane Tan,\n\nI saw that Acme Precision Sdn Bhd is investing in Industry 4.0 and smart "
                         "manufacturing. Codencode Academy runs AI for Engineers training. Open to a chat?\n\nSasha",
                 "evidence_indexes": [0, 5]})
    d = await generate_draft_llm(ai, CONTACT, OPP, [], SENDER)
    assert d.generated_by == "LLM" and d.evidence_used == OPP.evidence


async def test_llm_draft_with_invented_facts_falls_back():
    ai = FakeAI({"subject": "Hi", "body": "Dear Jane, congrats on Acme's 25 years and your work with Petronas! "
                                          "See https://codencode.example/brochure", "evidence_indexes": []})
    d = await generate_draft_llm(ai, CONTACT, OPP, [], SENDER)
    assert d.generated_by == "TEMPLATE" and "rejected" in d.note and "Petronas" in d.note


async def test_llm_linkedin_too_long_falls_back():
    ai = FakeAI({"subject": "", "body": "Hi Jane, " + "Codencode Academy runs AI for Engineers training. " * 10,
                 "evidence_indexes": []})
    d = await generate_draft_llm(ai, CONTACT, OPP, [], SENDER, "LINKEDIN")
    assert d.generated_by == "TEMPLATE" and len(d.body) <= LINKEDIN_MAX


async def test_llm_error_falls_back_with_note():
    d = await generate_draft_llm(FakeAI(error=RateLimited("slow")), CONTACT, OPP, [], SENDER)
    assert d.generated_by == "TEMPLATE" and "RATE_LIMITED" in d.note
