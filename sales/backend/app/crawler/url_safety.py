"""SSRF guard for the crawler (spec §10).

Every URL — the first one and every redirect hop — goes through
validate_url() (syntax/host rules) and resolve_and_check() (DNS answers must
all be public). Anything internal raises UnsafeURL."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit, urlunsplit

Resolver = Callable[[str, int], Awaitable[list[str]]]


class UnsafeURL(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class DNSResolutionError(Exception):
    pass


_BLOCKED_HOSTS = {
    "localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback",
    "metadata", "metadata.google.internal", "instance-data", "instance-data.ec2.internal",
}
_BLOCKED_SUFFIXES = (".local", ".internal", ".localhost", ".localdomain", ".home.arpa", ".lan",
                     ".intranet", ".corp", ".railway.internal")
_EXTRA_BLOCKED_NETS = [ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "100.64.0.0/10", "192.0.0.0/24", "192.0.2.0/24", "198.18.0.0/15", "198.51.100.0/24",
    "203.0.113.0/24", "240.0.0.0/4", "255.255.255.255/32",
    "fc00::/7", "fe80::/10", "fec0::/10", "::/128", "::1/128", "64:ff9b::/96", "100::/64", "2001:db8::/32",
)]
_METADATA_IPS = {ipaddress.ip_address("169.254.169.254"), ipaddress.ip_address("fd00:ec2::254"),
                 ipaddress.ip_address("169.254.170.2")}
ALLOWED_PORTS = {None, 80, 443}


def check_ip(ip: str | ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    addr = ipaddress.ip_address(ip) if isinstance(ip, str) else ip
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            check_ip(addr.ipv4_mapped)
        if addr.sixtofour is not None:
            check_ip(addr.sixtofour)
        if addr.teredo is not None:
            check_ip(addr.teredo[1])
    if addr in _METADATA_IPS:
        raise UnsafeURL(f"cloud metadata address {addr}")
    if (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_reserved
            or addr.is_unspecified or not addr.is_global):
        raise UnsafeURL(f"non-public address {addr}")
    if any(addr in net for net in _EXTRA_BLOCKED_NETS if net.version == addr.version):
        raise UnsafeURL(f"non-public address {addr}")


def _ip_literal(host: str):
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    # Integer / octal / hex forms like 2130706433 or 0x7f.1 — never legitimate here.
    if host.replace(".", "").isdigit() or host.lower().startswith("0x"):
        raise UnsafeURL(f"numeric host {host!r}")
    return None


def validate_url(url: str) -> str:
    """Syntax-level checks. Returns the URL with a normalized (lowercase) host."""
    if not isinstance(url, str) or not url.strip():
        raise UnsafeURL("empty URL")
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError as e:
        raise UnsafeURL(f"malformed URL: {e}") from e
    if parts.scheme.lower() not in ("http", "https"):
        raise UnsafeURL(f"scheme {parts.scheme!r} not allowed")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise UnsafeURL("credentials in URL not allowed")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeURL("missing host")
    if port not in ALLOWED_PORTS:
        raise UnsafeURL(f"port {port} not allowed")
    ip = _ip_literal(host)
    if ip is not None:
        check_ip(ip)
    else:
        if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_SUFFIXES):
            raise UnsafeURL(f"internal hostname {host!r}")
        if "." not in host:
            raise UnsafeURL(f"single-label hostname {host!r}")
        try:
            host.encode("idna")
        except UnicodeError as e:
            raise UnsafeURL(f"invalid hostname {host!r}") from e
    netloc = f"[{host}]" if ip is not None and ip.version == 6 else host
    if port is not None:
        netloc += f":{port}"
    return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", parts.query, parts.fragment))


async def system_resolve(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as e:
        raise DNSResolutionError(f"could not resolve {host}: {e}") from e
    return sorted({info[4][0] for info in infos})


async def resolve_and_check(host: str, port: int = 443, resolver: Resolver | None = None) -> list[str]:
    """Resolves `host` and raises UnsafeURL if ANY answer is non-public
    (so a mixed public/private answer can't be used for DNS-rebinding)."""
    host = host.strip("[]").rstrip(".").lower()
    ip = _ip_literal(host)
    if ip is not None:
        check_ip(ip)
        return [str(ip)]
    addrs = await (resolver or system_resolve)(host, port)
    if not addrs:
        raise DNSResolutionError(f"no addresses for {host}")
    for a in addrs:
        check_ip(a.split("%", 1)[0])
    return addrs


async def check_url(url: str, resolver: Resolver | None = None) -> str:
    """validate_url + DNS check. Returns the normalized URL."""
    safe = validate_url(url)
    parts = urlsplit(safe)
    await resolve_and_check(parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80), resolver)
    return safe
