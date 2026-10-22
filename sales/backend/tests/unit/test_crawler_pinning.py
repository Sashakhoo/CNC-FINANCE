import httpx
import respx

from app.crawler.fetcher import SafeFetcher


async def _resolver(host, port):
    return ["93.184.216.34"]


async def _nosleep(_):
    return None


async def test_request_goes_to_checked_ip_with_original_host():
    f = SafeFetcher(user_agent="t", min_delay=0, resolver=_resolver, sleep=_nosleep, pin_dns=True)
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get("http://93.184.216.34/about").mock(
            return_value=httpx.Response(200, html="<html><title>About</title><body>Hi</body></html>",
                                        headers={"content-type": "text/html"}))
        res = await f.fetch("http://example.my/about")
    await f.aclose()
    assert res.ok and res.final_url == "http://example.my/about"
    assert route.calls.last.request.headers["host"] == "example.my"


async def test_https_pins_ip_and_keeps_sni_hostname():
    f = SafeFetcher(user_agent="t", min_delay=0, resolver=_resolver, sleep=_nosleep, pin_dns=True)
    target, headers, ext = f._pinned("https://www.example.my/team", "93.184.216.34")
    assert target == "https://93.184.216.34/team"
    assert headers == {"Host": "www.example.my"} and ext == {"sni_hostname": "www.example.my"}
    assert f._pinned("https://example.my:8443/x", "2001:db8::1")[0] == "https://[2001:db8::1]:8443/x"
    await f.aclose()


async def test_pinning_off_leaves_url_alone():
    f = SafeFetcher(user_agent="t", min_delay=0, resolver=_resolver, sleep=_nosleep)
    assert f._pinned("https://example.my/", "93.184.216.34") == ("https://example.my/", {}, {})
    await f.aclose()
