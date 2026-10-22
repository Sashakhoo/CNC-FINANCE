from app.providers.search.base import SearchResult
from app.services.discovery import (DomainEvidence, build_queries, candidates_from_results, is_blocked_domain,
                                    match_profile_results, profile_queries, resolve, score_domain)
from app.services.discovery.candidates import _domain_label, guess_name


def res(url, title="", snippet="", rank=1, query="q"):
    return SearchResult(title=title, url=url, snippet=snippet, rank=rank, provider="brave", query=query)


# --- queries -----------------------------------------------------------

def test_queries_for_johor_engineering():
    qs = build_queries({"country": "Malaysia", "state": "Johor", "industries": ["Manufacturing", "Automation"]})
    texts = [q.query for q in qs]
    assert 'manufacturing company Johor Bahru Malaysia "Sdn Bhd"' in texts
    assert 'industrial automation company Johor Malaysia "Sdn Bhd"' in texts
    assert any(q.industry == "Automation" and q.location == "Johor Bahru" for q in qs)
    assert len(texts) == len(set(t.lower() for t in texts))


def test_queries_singapore_use_pte_ltd_and_city_wins():
    qs = build_queries({"country": "Singapore", "industries": ["Electronics"]})
    assert qs[0].query == 'electronics manufacturer Singapore "Pte Ltd"'
    qs = build_queries({"country": "Malaysia", "state": "Johor", "city": "Pasir Gudang", "industries": ["Engineering"]})
    assert qs[0].location == "Pasir Gudang"


def test_queries_capped():
    qs = build_queries({"state": "Johor", "industries": ["Manufacturing", "Engineering", "Electrical", "Electronics"]},
                       max_queries=3)
    assert len(qs) == 3


# --- candidates -----------------------------------------------------------

def test_blocklist_and_suffixes():
    for d in ("linkedin.com", "my.linkedin.com", "jobstreet.com.my", "mida.gov.my", "utm.edu.my", "thestar.com.my"):
        assert is_blocked_domain(d), d
    assert not is_blocked_domain("fictionalprecision.com.my")


def test_candidates_filter_dedupe_and_keep_provenance():
    results = [
        res("https://www.fictionalprecision.com.my/", "Fictional Precision Sdn Bhd | Home", "CNC machining in Johor", 1),
        res("https://www.linkedin.com/company/fictional", "Fictional Precision | LinkedIn", rank=2),
        res("https://bestlists.example/top-10-manufacturers", "Top 10 Manufacturers in Johor", rank=3),
        res("https://www.fictionalprecision.com.my/about", "About - Fictional Precision Sdn Bhd", rank=4),
        res("https://mirror.example/fictional", "Fictional Precision Sdn. Bhd.", rank=5),
        res("https://acme-auto.example/", "Welcome to Acme Automation", rank=6),
        res("https://jobs.example/careers/123", "Engineer jobs in Johor", rank=7),
        res("https://dir.example/directory/abc", "ABC Engineering", rank=8),
    ]
    out = candidates_from_results(results)
    assert [c.domain for c in out] == ["fictionalprecision.com.my", "acme-auto.example"]
    first = out[0]
    assert first.name_guess == "Fictional Precision Sdn Bhd"
    assert first.website == "https://www.fictionalprecision.com.my"
    assert first.source_url == "https://www.fictionalprecision.com.my/" and first.provider == "brave"


def test_guess_name_falls_back_to_domain():
    assert guess_name("Welcome to Acme Automation", "acme-auto.example") == "Acme Automation"
    assert guess_name("Industrial solutions", "acme-auto.example") == "Acme Auto"
    assert guess_name("Home | Southern Precision", "southernprecision.com") == "Southern Precision"


def test_domain_label():
    assert _domain_label("web.southernprecision.com.my") == "southernprecision"
    assert _domain_label("acme.com") == "acme"
    assert _domain_label("shop.acme.io") == "acme"


# --- domain resolution ------------------------------------------------------

NAME = "Southern Precision Automation Sdn. Bhd."


def test_domain_name_alone_never_resolves():
    s = score_domain(NAME, "southernprecisionautomation.com.my")
    assert s.confidence < 0.75
    r = resolve(NAME, [DomainEvidence("southernprecisionautomation.com.my")])
    assert r.status == "UNCERTAIN" and r.domain is None


def test_page_evidence_resolves():
    r = resolve(NAME, [
        DomainEvidence("southernprecision.com.my", homepage_title="Southern Precision Automation Sdn Bhd",
                       about_text="Southern Precision Automation was founded in Johor Bahru", address_text="Johor Bahru, Johor"),
        DomainEvidence("southernautomation.com", homepage_title="Southern Automation Trading"),
    ], location_hint="Johor")
    assert r.status == "RESOLVED" and r.domain == "southernprecision.com.my" and r.confidence >= 0.75
    assert any("Johor" in reason for reason in r.scores[0].reasons)


def test_close_runner_up_is_uncertain():
    ev = dict(homepage_title="Southern Precision Automation Sdn Bhd",
              about_text="Southern Precision Automation in Johor")
    r = resolve(NAME, [DomainEvidence("southernprecision.com.my", **ev), DomainEvidence("southernprecision.com", **ev)])
    assert r.status == "UNCERTAIN" and len(r.scores) == 2


def test_no_candidates():
    assert resolve(NAME, []).status == "NONE"


def test_initials_domain_recognised():
    s = score_domain("Southern Precision Automation Sdn Bhd", "spa.com.my")
    assert "domain is the company's initials" in s.reasons


# --- professional profiles --------------------------------------------------

def test_profile_queries():
    assert profile_queries("Jane Tan", "Fictional Precision Sdn Bhd")[0] == \
        'site:linkedin.com/in "Jane Tan" "Fictional Precision"'


def test_profile_matching_accepts_only_name_matched_profiles_from_results():
    results = [
        res("https://my.linkedin.com/in/jane-tan-123?trk=x", "Jane Tan - HR Manager - Fictional Precision Sdn Bhd | LinkedIn",
            "Johor Bahru · HR Manager at Fictional Precision"),
        res("https://www.linkedin.com/in/john-lim", "John Lim - HR Manager - Fictional Precision | LinkedIn"),
        res("https://www.linkedin.com/company/fictional-precision", "Jane Tan | Fictional Precision"),
        res("https://www.linkedin.com/in/jane-tan-999", "Jane Tan - Teacher - Some School | LinkedIn", "Kuala Lumpur"),
        res("https://example.com/in/jane-tan", "Jane Tan - Fictional Precision"),
    ]
    out = match_profile_results("Ms. Jane Tan", "Fictional Precision Sdn Bhd", results)
    assert [m.url for m in out] == ["https://www.linkedin.com/in/jane-tan-123", "https://www.linkedin.com/in/jane-tan-999"]
    assert out[0].company_confirmed and out[0].confidence == 0.85
    assert not out[1].company_confirmed and out[1].confidence < 0.5
    assert out[0].evidence_title.startswith("Jane Tan")


def test_profile_matching_rejects_different_person():
    out = match_profile_results("Jane Tan", "Fictional Precision",
                                [res("https://www.linkedin.com/in/janet-tang", "Janet Tang - Fictional Precision | LinkedIn")])
    assert out == []


def test_profile_matching_allows_initials_and_order():
    results = [res("https://www.linkedin.com/in/tan-jane-s", "Tan Jane S. - Fictional Precision | LinkedIn")]
    assert len(match_profile_results("Jane Tan", "Fictional Precision", results)) == 1
