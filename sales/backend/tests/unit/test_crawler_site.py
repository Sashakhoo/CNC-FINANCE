import pathlib

import httpx
import respx

from app.crawler.fetcher import SafeFetcher
from app.crawler.robots import RobotsCache
from app.crawler.site import classify_page, crawl_company_site, normalize_url
from app.crawler.url_safety import DNSResolutionError

FIX = pathlib.Path(__file__).parent / "fixtures" / "crawler"
HOST = "www.precision-example.com.my"
BASE = f"https://{HOST}"
UA = "CodencodeLeadIntelligence/1.0"


async def resolver(host, port):
    if "precision-example" not in host:
        raise DNSResolutionError(host)
    return ["203.106.1.1"]


async def nosleep(_):
    return None


def html(name: str) -> httpx.Response:
    return httpx.Response(200, text=(FIX / name).read_text(), headers={"content-type": "text/html; charset=utf-8"})


def setup_site(mock: respx.MockRouter, robots_txt: str = "User-agent: *\nDisallow: /admin\n") -> dict:
    routes = {
        "robots": mock.get(f"{BASE}/robots.txt").respond(200, text=robots_txt),
        "home": mock.get(f"{BASE}/").mock(return_value=html("home.html")),
        "about": mock.get(f"{BASE}/about-us").mock(return_value=html("about.html")),
        "team": mock.get(f"{BASE}/our-team").mock(return_value=html("team.html")),
        "careers": mock.get(f"{BASE}/careers").mock(return_value=html("careers.html")),
        "news": mock.get(f"{BASE}/news").mock(return_value=html("news.html")),
        "contact": mock.get(f"{BASE}/contact").mock(return_value=html("about.html")),  # duplicate content
        "pdf": mock.get(f"{BASE}/brochure.pdf").respond(200, content=b"%PDF"),
        "partner": mock.get("https://other-example.com/partner").respond(200, text="x"),
    }
    routes["rest"] = mock.route(host=HOST).respond(404)
    return routes


def crawler():
    f = SafeFetcher(user_agent=UA, min_delay=0, resolver=resolver, sleep=nosleep)
    return f, RobotsCache(lambda u: f.fetch_raw(u), UA)


async def test_crawl_collects_priority_pages_and_dedupes():
    with respx.mock(assert_all_called=False) as mock:
        routes = setup_site(mock)
        f, robots = crawler()
        res = await crawl_company_site(BASE + "/", f, robots, max_pages=25, max_depth=2)

    types = {p.page_type for p in res.pages}
    assert {"home", "about", "team", "careers", "news"} <= types
    urls = [p.final_url for p in res.pages]
    assert len(urls) == len(set(urls))
    assert routes["team"].call_count == 1                   # ?utm_source variant deduped
    assert routes["about"].call_count == 1                  # #history fragment deduped
    assert routes["pdf"].call_count == 0                    # non-page link not followed
    assert routes["partner"].call_count == 0                # off-site link not followed
    assert any(s.reason == "duplicate_content" for s in res.skipped)   # /contact == /about-us content
    assert res.robots_allowed is True and res.base_url == BASE
    assert not res.cancelled


async def test_page_limit_respected():
    with respx.mock(assert_all_called=False) as mock:
        setup_site(mock)
        f, robots = crawler()
        res = await crawl_company_site(BASE, f, robots, max_pages=2)
    assert len(res.pages) == 2


async def test_depth_zero_only_home():
    with respx.mock(assert_all_called=False) as mock:
        routes = setup_site(mock)
        f, robots = crawler()
        res = await crawl_company_site(BASE, f, robots, max_depth=0)
    assert [p.page_type for p in res.pages] == ["home"] and routes["about"].call_count == 0


async def test_cancel_stops_crawl():
    calls = {"n": 0}

    def should_cancel():
        calls["n"] += 1
        return calls["n"] > 2

    with respx.mock(assert_all_called=False) as mock:
        setup_site(mock)
        f, robots = crawler()
        res = await crawl_company_site(BASE, f, robots, should_cancel=should_cancel)
    assert res.cancelled and len(res.pages) <= 2


async def test_robots_disallowed_pages_skipped():
    with respx.mock(assert_all_called=False) as mock:
        routes = setup_site(mock, robots_txt="User-agent: *\nDisallow: /our-team\n")
        f, robots = crawler()
        res = await crawl_company_site(BASE, f, robots)
    assert routes["team"].call_count == 0
    assert any(s.reason == "robots_disallowed" for s in res.skipped)


async def test_robots_disallow_all_stops_at_home():
    with respx.mock(assert_all_called=False) as mock:
        routes = setup_site(mock, robots_txt="User-agent: *\nDisallow: /\n")
        f, robots = crawler()
        res = await crawl_company_site(BASE, f, robots)
    assert res.pages == [] and res.robots_allowed is False and routes["home"].call_count == 0


async def test_unresolvable_domain_fails_fast():
    f = SafeFetcher(user_agent=UA, min_delay=0, resolver=resolver, sleep=nosleep)
    res = await crawl_company_site("https://no-such-example.com", f, RobotsCache(lambda u: f.fetch_raw(u), UA))
    assert res.pages == [] and res.errors and res.attempts == 1


async def test_unsafe_start_url():
    f = SafeFetcher(user_agent=UA, min_delay=0, resolver=resolver, sleep=nosleep)
    res = await crawl_company_site("http://192.168.0.1/", f, None)
    assert res.errors[0].error_type == "UNSAFE_URL" and res.attempts == 0


def test_normalize_and_classify():
    assert normalize_url("HTTPS://WWW.Example.com/About/?utm_source=x&b=2#top") == "https://www.example.com/About?b=2"
    assert classify_page("https://x.com/") == "home"
    assert classify_page("https://x.com/our-team") == "team"
    assert classify_page("https://x.com/en/contact-us") == "contact"
    assert classify_page("https://x.com/p?id=3", anchor="Careers") == "careers"
