from app.providers.base import TransientError
from app.services.training import (CompanyFacts, PageText, SignalFact, analyze_training, analyze_training_llm,
                                   programs_from_defaults, unsupported_tokens, verbatim_in)

PAGES = [
    PageText("https://acme.example/about", "Acme Precision Sdn Bhd is a contract manufacturer in Johor. "
             "Our engineering team designs special purpose machines and industrial automation cells. "
             "We are investing in Industry 4.0 and smart manufacturing across our two plants.", "about"),
    PageText("https://acme.example/careers", "We are hiring a Process Engineer. "
             "Experience with Python scripting and Excel reporting is an advantage.", "careers"),
]
COMPANY = CompanyFacts("Acme Precision Sdn Bhd", industry="Automation")
PROGRAMS = programs_from_defaults()


class FakeAI:
    def __init__(self, payload=None, error=None):
        self.payload, self.error, self.calls = payload, error, 0

    async def generate_structured(self, system, prompt, schema, max_tokens=1500):
        self.calls += 1
        if self.error:
            raise self.error
        return schema.model_validate(self.payload)


def test_rules_evidence_is_verbatim_from_pages():
    opps = analyze_training(COMPANY, PAGES, [], PROGRAMS)
    assert opps, "expected at least one opportunity"
    corpus = " ".join(p.text for p in PAGES)
    for o in opps:
        assert o.evidence and o.method == "RULES"
        for e in o.evidence:
            assert verbatim_in(e["quote"], corpus)
            assert e["source_url"] in {p.url for p in PAGES}
        assert 0 <= o.match_score <= 95
    assert opps == sorted(opps, key=lambda o: -o.match_score)
    by = {o.program_code: o for o in opps}
    assert {o.program_code for o in opps[:2]} == {"AI_FOR_ENGINEERS", "PYTHON_AUTOMATION"}
    afe = by["AI_FOR_ENGINEERS"]
    assert afe.target_department == "Engineering" and afe.recommended_decision_maker == "Engineering Manager"
    assert "Industry-based" in afe.reason and "'industry 4.0'" in afe.reason
    assert afe.alternative_program_codes and afe.program_code not in afe.alternative_program_codes


def test_programmes_without_evidence_are_omitted_even_with_industry_prior():
    opps = analyze_training(CompanyFacts("Blank Co", industry="Technology"), [PageText("u", "Welcome to our homepage today.")],
                            [], PROGRAMS)
    assert opps == []


def test_signal_creates_evidenced_opportunity():
    sig = SignalFact("CYBERSECURITY_CERTIFICATION", "Achieved ISO 27001 certification",
                     "Acme achieved ISO 27001 certification in 2026.", "https://acme.example/news")
    opps = {o.program_code: o for o in analyze_training(CompanyFacts("Acme"), [], [sig], PROGRAMS)}
    assert "TECHNICAL_CYBERSECURITY" in opps
    assert {"source_url": "https://acme.example/news", "quote": sig.quote} in opps["TECHNICAL_CYBERSECURITY"].evidence
    assert "Signal: Achieved ISO 27001 certification" in opps["TECHNICAL_CYBERSECURITY"].reason


def test_ai_signal_does_not_match_maintenance():
    sig = SignalFact("PREDICTIVE_MAINTENANCE", "New maintenance programme", "They run a maintenance programme for plants.", "u")
    opps = {o.program_code for o in analyze_training(CompanyFacts("X"), [], [sig], PROGRAMS)}
    assert "GENERATIVE_AI" not in opps and "ARTIFICIAL_INTELLIGENCE" not in opps


async def test_llm_drops_fabricated_quotes_and_keeps_valid():
    ai = FakeAI({"recommendations": [
        {"program_code": "PYTHON_AUTOMATION", "match_score": 88, "reason": "Careers page asks for Python scripting.",
         "quotes": [{"source_id": "S2", "quote": "Experience with Python scripting and Excel reporting is an advantage."},
                    {"source_id": "S1", "quote": "Acme trains 500 staff in Python every year."}]},
        {"program_code": "GENERATIVE_AI", "match_score": 90, "reason": "They love ChatGPT.",
         "quotes": [{"source_id": "S1", "quote": "Acme is rolling out ChatGPT to every employee."}]},
        {"program_code": "NOT_A_PROGRAM", "match_score": 99, "reason": "x",
         "quotes": [{"source_id": "S1", "quote": "Our engineering team designs special purpose machines"}]},
    ]})
    opps = await analyze_training_llm(ai, COMPANY, PAGES, [], PROGRAMS)
    by = {o.program_code: o for o in opps}
    assert by["PYTHON_AUTOMATION"].method == "LLM"
    assert by["PYTHON_AUTOMATION"].evidence == [{"source_url": "https://acme.example/careers",
                                                 "quote": "Experience with Python scripting and Excel reporting is an advantage."}]
    assert "GENERATIVE_AI" not in by and "NOT_A_PROGRAM" not in by
    assert by["AI_FOR_ENGINEERS"].method == "RULES"  # rules coverage is kept


async def test_llm_reason_with_unsupported_facts_is_replaced():
    ai = FakeAI({"recommendations": [{"program_code": "PYTHON_AUTOMATION", "match_score": 80,
                                      "reason": "Siemens says they have 3000 engineers.",
                                      "quotes": [{"source_id": "S2", "quote": "We are hiring a Process Engineer."}]}]})
    by = {o.program_code: o for o in await analyze_training_llm(ai, COMPANY, PAGES, [], PROGRAMS)}
    assert "Siemens" not in by["PYTHON_AUTOMATION"].reason and "3000" not in by["PYTHON_AUTOMATION"].reason


async def test_llm_with_no_valid_evidence_falls_back_to_rules():
    ai = FakeAI({"recommendations": [{"program_code": "GENERATIVE_AI", "match_score": 95, "reason": "x",
                                      "quotes": [{"source_id": "S1", "quote": "Totally made up sentence here."}]}]})
    llm = await analyze_training_llm(ai, COMPANY, PAGES, [], PROGRAMS)
    rules = analyze_training(COMPANY, PAGES, [], PROGRAMS)
    assert [o.to_dict() for o in llm] == [o.to_dict() for o in rules]


async def test_llm_provider_error_falls_back_to_rules():
    llm = await analyze_training_llm(FakeAI(error=TransientError("down")), COMPANY, PAGES, [], PROGRAMS)
    assert llm and all(o.method == "RULES" for o in llm)


def test_verbatim_and_unsupported_helpers():
    assert verbatim_in("our  ENGINEERING team designs", "Our engineering team designs machines.")
    assert not verbatim_in("short", "short")
    assert unsupported_tokens("Hello. We met Siemens in 2024 at https://x.io", ["We met"]) == ["2024", "https://x.io", "Siemens"] \
        or set(unsupported_tokens("Hello. We met Siemens in 2024 at https://x.io", ["We met"])) == {"2024", "https://x.io", "Siemens"}
