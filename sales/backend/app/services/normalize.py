"""Deterministic normalization used for duplicate detection and display."""
import re
import unicodedata
from urllib.parse import urlsplit

# Longest first so "Sdn. Bhd." wins over "Bhd".
_LEGAL_SUFFIXES = sorted([
    "sdn bhd", "sdn. bhd.", "sendirian berhad", "berhad", "bhd", "pte ltd", "pte. ltd.", "private limited",
    "pte limited", "limited", "ltd", "llp", "plc", "inc", "incorporated", "corp", "corporation", "co ltd",
    "company limited", "(m)", "(malaysia)", "(s)", "(singapore)",
], key=len, reverse=True)

_HONORIFICS = {"mr", "mrs", "ms", "miss", "dr", "ir", "ts", "prof", "dato", "datuk", "datin", "tan sri", "puan",
               "encik", "en", "cik", "sir", "madam"}


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def normalize_company_name(name: str) -> str:
    """'Southern Precision Automation Sdn. Bhd.' -> 'southern precision automation'.
    Only for comparison — the legal name is stored and displayed unchanged."""
    s = _ascii(name).lower().replace("&", " and ")
    s = re.sub(r"[.,]", " ", s)  # "Sdn. Bhd." → "sdn bhd" before suffix matching
    s = re.sub(r"\s+", " ", s).strip(" -")
    changed = True
    while changed:
        changed = False
        for suf in _LEGAL_SUFFIXES:
            if s.endswith(" " + suf) or s == suf:
                s = s[: -len(suf)].strip(" ,.-")
                changed = True
                break
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_person_name(name: str) -> str:
    s = _ascii(name).lower()
    s = re.sub(r"[^a-z\s'-]", " ", s)
    parts = [p for p in s.split() if p.strip(".") not in _HONORIFICS and p not in ("bin", "binti", "a/l", "a/p")]
    return " ".join(parts).strip()


def split_name(full_name: str) -> tuple[str | None, str | None]:
    parts = full_name.strip().split()
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def domain_from_url(url: str | None) -> str | None:
    if not url:
        return None
    u = url.strip()
    if "://" not in u:
        u = "http://" + u
    host = (urlsplit(u).hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host or None


def normalize_website(url: str | None) -> str | None:
    if not url or not url.strip():
        return None
    u = url.strip()
    if re.match(r"^(javascript|data|vbscript|file|mailto|ftp|tel):", u, re.I) or re.match(r"^[a-z][a-z0-9+.-]*://", u, re.I) and not re.match(r"^https?://", u, re.I):
        raise ValueError("Website must be an http(s) URL")
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    parts = urlsplit(u)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname or "." not in parts.hostname:
        raise ValueError("Website must be an http(s) URL")
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path or ''}".rstrip("/")


def email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower()


def profile_platform(url: str) -> str:
    host = domain_from_url(url) or ""
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        return "LINKEDIN"
    return "OTHER"
