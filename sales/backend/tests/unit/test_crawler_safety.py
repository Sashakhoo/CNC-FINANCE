import pytest

from app.crawler.url_safety import DNSResolutionError, UnsafeURL, check_ip, check_url, resolve_and_check, validate_url


def fake_resolver(mapping):
    async def resolve(host, port):
        if host not in mapping:
            raise DNSResolutionError(f"NXDOMAIN {host}")
        return mapping[host]
    return resolve


@pytest.mark.parametrize("url", [
    "ftp://precision-example.com.my/",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "http://user:pw@precision-example.com.my/",
    "http://precision-example.com.my@10.0.0.1/",
    "http://precision-example.com.my:8080/",
    "http://localhost/",
    "http://LOCALHOST./admin",
    "http://intranet/",
    "http://printer.local/",
    "http://db.internal/",
    "http://backend.railway.internal:8000/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://127.0.0.1/",
    "http://127.1/",
    "http://2130706433/",
    "http://0x7f000001/",
    "http://10.1.2.3/",
    "http://172.16.0.1/",
    "http://172.31.255.255/",
    "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/",
    "http://100.64.0.1/",
    "http://0.0.0.0/",
    "http://[::1]/",
    "http://[fe80::1]/",
    "http://[fc00::1]/",
    "http://[fd00:ec2::254]/",
    "http://[::ffff:10.0.0.1]/",
    "http://[::ffff:127.0.0.1]/",
    "",
])
def test_validate_url_rejects(url):
    with pytest.raises(UnsafeURL):
        validate_url(url)


@pytest.mark.parametrize("url", ["https://precision-example.com.my/about", "http://www.precision-example.com.my",
                                 "https://8.8.8.8/", "https://precision-example.com.my:443/x?q=1"])
def test_validate_url_accepts_public(url):
    assert validate_url(url).startswith(("http://", "https://"))


@pytest.mark.parametrize("ip", ["10.0.0.5", "172.20.1.1", "192.168.0.10", "127.0.0.53", "169.254.1.1",
                                "100.100.100.100", "224.0.0.1", "::1", "fd12:3456::1", "fe80::abcd",
                                "::ffff:192.168.0.1", "2002:c0a8:0101::1"])
def test_private_ips_rejected(ip):
    with pytest.raises(UnsafeURL):
        check_ip(ip)


async def test_dns_answer_pointing_inside_is_rejected():
    resolver = fake_resolver({"evil-example.com": ["93.184.216.34", "10.0.0.7"]})
    with pytest.raises(UnsafeURL):
        await resolve_and_check("evil-example.com", 443, resolver)


async def test_dns_ipv6_link_local_rejected():
    resolver = fake_resolver({"v6-example.com": ["fe80::1"]})
    with pytest.raises(UnsafeURL):
        await check_url("https://v6-example.com/", resolver)


async def test_dns_failure_is_dns_error():
    with pytest.raises(DNSResolutionError):
        await resolve_and_check("missing-example.com", 443, fake_resolver({}))


async def test_public_dns_answer_ok():
    resolver = fake_resolver({"precision-example.com.my": ["203.106.1.1"]})
    assert await check_url("https://precision-example.com.my/team", resolver) == "https://precision-example.com.my/team"
