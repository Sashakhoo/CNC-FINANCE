import httpx
import pytest
import respx

from app.crawler.fetcher import FetchError, SafeFetcher, build_crawler, parse_retry_after
from app.crawler.robots import RobotsCache
from app.crawler.url_safety import DNSResolutionError

HOST = "precision-example.com.my"
BASE = f"https://{HOST}"
UA = "CodencodeLeadIntelligence/1.0 (+https://crm.codencode.my/bot)"
PUBLIC = {HOST: ["203.106.1.1"], "www." + HOST: ["203.106.1.1"], "cdn-example.com": ["203.106.9.9"],
          "evil-example.com": ["10.9.9.9"]}
HTML = "<html><head><title>Hi</title><link rel='canonical' href='/canon'></head><body><p>Hello there</p></body></html>"


async def resolver(host, port):
    if host not in PUBLIC:
        raise DNSResolutionError(host)
    return PUBLIC[host]


class Sleeper:
    def __init__(self):
        self.calls = []

    async def __call__(self, s):
        self.calls.append(s)


def fetcher(**kw):
    sleeper = Sleeper()
    f = SafeFetcher(user_agent=UA, min_delay=0, resolver=resolver, sleep=sleeper, backoff_base=0.01, **kw)
    return f, sleeper


@respx.mock
async def test_fetch_html_page():
    respx.get(f"{BASE}/about").respond(200, text=HTML, headers={"content-type": "text/html; charset=utf-8"})
    f, _ = fetcher()
    r = await f.fetch(f"{BASE}/about")
    assert r.ok and r.title == "Hi" and r.text == "Hello there"
    assert r.canonical_url == f"{BASE}/canon"
    assert len(r.content_hash) == 64
    assert respx.calls.last.request.headers["user-agent"] == UA


@respx.mock
async def test_retry_on_429_honours_retry_after():
    route = respx.get(f"{BASE}/team")
    route.side_effect = [httpx.Response(429, headers={"Retry-After": "3"}),
                         httpx.Response(200, text=HTML, headers={"content-type": "text/html"})]
    f, sleeper = fetcher()
    r = await f.fetch(f"{BASE}/team")
    assert r.ok and route.call_count == 2
    assert 3.0 in sleeper.calls


@respx.mock
async def test_gives_up_when_retry_after_too_long():
    respx.get(f"{BASE}/team").respond(429, headers={"Retry-After": "3600"})
    f, _ = fetcher()
    r = await f.fetch(f"{BASE}/team")
    assert r.error_type == FetchError.HTTP_429


@respx.mock
async def test_retries_5xx_then_reports():
    route = respx.get(f"{BASE}/x").respond(503)
    f, _ = fetcher(max_retries=2)
    r = await f.fetch(f"{BASE}/x")
    assert r.error_type == FetchError.HTTP_5XX and route.call_count == 3


@respx.mock
async def test_timeout_is_error_value():
    respx.get(f"{BASE}/slow").mock(side_effect=httpx.ReadTimeout("slow"))
    f, _ = fetcher(max_retries=1)
    r = await f.fetch(f"{BASE}/slow")
    assert r.error_type == FetchError.TIMEOUT


@respx.mock
async def test_404_and_403_classified():
    respx.get(f"{BASE}/gone").respond(404)
    respx.get(f"{BASE}/private").respond(403)
    f, _ = fetcher()
    assert (await f.fetch(f"{BASE}/gone")).error_type == FetchError.HTTP_404
    assert (await f.fetch(f"{BASE}/private")).error_type == FetchError.HTTP_403


@respx.mock
async def test_size_limit_streamed_body():
    respx.get(f"{BASE}/big").respond(200, content=b"<html>" + b"a" * 5000, headers={"content-type": "text/html"})
    f, _ = fetcher(max_bytes=1000)
    r = await f.fetch(f"{BASE}/big")
    assert r.error_type == FetchError.TOO_LARGE


@respx.mock
async def test_size_limit_declared_length():
    respx.get(f"{BASE}/big").respond(200, content=b"x", headers={"content-type": "text/html", "content-length": "99999999"})
    f, _ = fetcher()
    assert (await f.fetch(f"{BASE}/big")).error_type == FetchError.TOO_LARGE


@respx.mock
async def test_non_html_skipped():
    respx.get(f"{BASE}/file").respond(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"})
    f, _ = fetcher()
    assert (await f.fetch(f"{BASE}/file")).error_type == FetchError.NOT_HTML


@respx.mock
async def test_redirect_to_private_ip_blocked():
    respx.get(f"{BASE}/go").respond(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
    f, _ = fetcher()
    r = await f.fetch(f"{BASE}/go")
    assert r.error_type == FetchError.UNSAFE_URL


@respx.mock
async def test_redirect_to_host_resolving_privately_blocked():
    respx.get(f"{BASE}/go").respond(301, headers={"location": "https://evil-example.com/"})
    evil = respx.get("https://evil-example.com/").respond(200, text=HTML)
    f, _ = fetcher()
    r = await f.fetch(f"{BASE}/go")
    assert r.error_type == FetchError.UNSAFE_URL and evil.call_count == 0


@respx.mock
async def test_redirect_followed_and_recorded():
    respx.get(f"{BASE}/old").respond(301, headers={"location": "/new"})
    respx.get(f"{BASE}/new").respond(200, text=HTML, headers={"content-type": "text/html"})
    f, _ = fetcher()
    r = await f.fetch(f"{BASE}/old")
    assert r.ok and r.final_url == f"{BASE}/new" and r.redirects == [f"{BASE}/old"]


@respx.mock
async def test_too_many_redirects():
    for i in range(10):
        respx.get(f"{BASE}/r{i}").respond(302, headers={"location": f"/r{i + 1}"})
    f, _ = fetcher(max_redirects=3)
    assert (await f.fetch(f"{BASE}/r0")).error_type == FetchError.TOO_MANY_REDIRECTS


async def test_unsafe_start_url_never_requested():
    f, _ = fetcher()
    with respx.mock(assert_all_called=False) as m:
        route = m.get("http://127.0.0.1/").respond(200)
        r = await f.fetch("http://127.0.0.1/")
    assert r.error_type == FetchError.UNSAFE_URL and route.call_count == 0


async def test_dns_failure_reported():
    f, _ = fetcher()
    r = await f.fetch("https://no-such-example.com/")
    assert r.error_type == FetchError.DNS_ERROR


@respx.mock
async def test_per_host_delay_enforced():
    respx.get(url__regex=rf"{BASE}/p\d").respond(200, text=HTML, headers={"content-type": "text/html"})
    sleeper = Sleeper()
    f = SafeFetcher(user_agent=UA, min_delay=5, resolver=resolver, sleep=sleeper, clock=lambda: 0.0)
    await f.fetch(f"{BASE}/p1")
    await f.fetch(f"{BASE}/p2")
    assert sleeper.calls == [5.0]


# --- robots.txt ---------------------------------------------------------

def robots_for(f: SafeFetcher) -> RobotsCache:
    return RobotsCache(lambda u: f.fetch_raw(u), UA)


@respx.mock
async def test_robots_disallow_and_crawl_delay():
    respx.get(f"{BASE}/robots.txt").respond(
        200, text="User-agent: *\nDisallow: /private\nCrawl-delay: 7\n", headers={"content-type": "text/plain"})
    page = respx.get(f"{BASE}/private/x").respond(200, text=HTML, headers={"content-type": "text/html"})
    f, _ = fetcher()
    robots = robots_for(f)
    assert await robots.can_fetch(f"{BASE}/about") is True
    assert await robots.can_fetch(f"{BASE}/private/x") is False
    assert await robots.crawl_delay(f"{BASE}/about") == 7
    r = await f.fetch(f"{BASE}/private/x", robots=robots)
    assert r.error_type == FetchError.ROBOTS_DISALLOWED and page.call_count == 0


@respx.mock
async def test_robots_specific_agent_block():
    respx.get(f"{BASE}/robots.txt").respond(200, text="User-agent: CodencodeLeadIntelligence\nDisallow: /\n\n"
                                                      "User-agent: *\nAllow: /\n")
    f, _ = fetcher()
    assert await robots_for(f).can_fetch(f"{BASE}/about") is False


@respx.mock
async def test_robots_404_allows_all():
    respx.get(f"{BASE}/robots.txt").respond(404)
    f, _ = fetcher()
    assert await robots_for(f).can_fetch(f"{BASE}/anything") is True


@respx.mock
async def test_robots_5xx_disallows_all():
    respx.get(f"{BASE}/robots.txt").respond(503)
    f, _ = fetcher(max_retries=0)
    robots = robots_for(f)
    assert await robots.can_fetch(f"{BASE}/about") is False
    assert (await robots.get(f"{BASE}/")).mode == "disallow_all"


@respx.mock
async def test_robots_network_error_disallows_all():
    respx.get(f"{BASE}/robots.txt").mock(side_effect=httpx.ConnectError("refused"))
    f, _ = fetcher(max_retries=0)
    assert await robots_for(f).can_fetch(f"{BASE}/about") is False


@respx.mock
async def test_robots_cached():
    route = respx.get(f"{BASE}/robots.txt").respond(200, text="User-agent: *\nDisallow:\n")
    f, _ = fetcher()
    robots = robots_for(f)
    for _ in range(3):
        await robots.can_fetch(f"{BASE}/a")
    assert route.call_count == 1


@respx.mock
async def test_build_crawler_wires_robots():
    respx.get(f"{BASE}/robots.txt").respond(200, text="User-agent: *\nDisallow: /secret\n")
    f, robots = build_crawler(user_agent=UA, min_delay=0, resolver=resolver)
    r = await f.fetch(f"{BASE}/secret")
    assert r.error_type == FetchError.ROBOTS_DISALLOWED
    await f.aclose()


def test_parse_retry_after_forms():
    assert parse_retry_after("120") == 120.0
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT", now=1445412480 - 60) == pytest.approx(60, abs=1)
    assert parse_retry_after("soon") is None
