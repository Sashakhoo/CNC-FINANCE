from pydantic import ValidationError

from app.models.base import Department, Seniority
from app.providers.base import BadResponse
from app.services.classify import classify_industry, classify_industry_llm, llm_normalize_title


class FakeAI:
    """Behaves like a real provider: schema violations surface as BadResponse."""

    def __init__(self, payload=None, error=None):
        self.payload, self.error, self.calls = payload, error, 0

    async def generate_structured(self, system, prompt, schema, max_tokens=1500):
        self.calls += 1
        if self.error:
            raise self.error
        try:
            return schema.model_validate(self.payload)
        except ValidationError as e:
            raise BadResponse(str(e)) from e


def test_rules_pick_specific_industry_with_evidence():
    c = classify_industry("We are an OSAT provider offering IC packaging and wafer test for semiconductor customers. "
                          "Our manufacturing plant is in Penang.")
    assert c.industry == "Semiconductor" and c.method == "RULES"
    assert "wafer" in c.evidence_terms and 0 < c.confidence <= 0.95


def test_rules_other_when_no_terms():
    assert classify_industry("Welcome to our homepage.").industry == "Other"
    assert classify_industry("").confidence == 0.0


def test_rules_automation():
    assert classify_industry("Industrial automation, robotics and PLC/SCADA integration for factories.").industry == "Automation"


async def test_llm_industry_must_be_allowed_and_quoted():
    text = "We provide freight forwarding and warehousing across Johor."
    ok = await classify_industry_llm(FakeAI({"industry": "Logistics", "evidence_quote": "freight forwarding and warehousing"}), text)
    assert ok.industry == "Logistics" and ok.method == "LLM"
    invented = await classify_industry_llm(FakeAI({"industry": "Logistics", "evidence_quote": "global shipping leader"}), text)
    assert invented.method == "RULES"
    not_allowed = await classify_industry_llm(FakeAI({"industry": "Aerospace", "evidence_quote": "freight forwarding"}), text)
    assert not_allowed.method == "RULES"
    failed = await classify_industry_llm(FakeAI(error=BadResponse("x")), text)
    assert failed.method == "RULES" and failed.industry == "Logistics"


async def test_title_rules_first_llm_not_called():
    ai = FakeAI({"normalized_title": "X", "department": "IT", "seniority": "Manager"})
    r = await llm_normalize_title(ai, "Manager, Human Resources")
    assert r.method == "RULES" and r.normalized_title == "HR Manager" and ai.calls == 0


async def test_title_llm_fallback_constrained_to_enums():
    ai = FakeAI({"normalized_title": "Quality Assurance Lead", "department": "Engineering", "seniority": "Manager"})
    r = await llm_normalize_title(ai, "QA Lead (Plant 2)")
    assert r.method == "LLM" and r.department == Department.ENGINEERING and r.seniority == Seniority.MANAGER
    bad = FakeAI({"normalized_title": "QA", "department": "Quality", "seniority": "Boss"})
    r2 = await llm_normalize_title(bad, "QA Lead (Plant 2)")
    assert r2.method == "NONE"


async def test_title_without_ai_or_text():
    assert (await llm_normalize_title(None, "Kepala Bahagian Q")).method == "NONE"
    assert (await llm_normalize_title(FakeAI({}), "")).normalized_title is None
