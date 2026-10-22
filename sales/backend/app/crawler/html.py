"""HTML → (title, visible text lines, canonical URL, links) and the CrawledPage
model shared by the crawler and the extractors."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Comment

_DROP = ("script", "style", "noscript", "template", "svg", "iframe", "head", "object", "canvas")
_BLOCK = ("address", "article", "aside", "blockquote", "dd", "div", "dl", "dt", "fieldset", "figcaption",
          "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main",
          "nav", "ol", "p", "pre", "section", "table", "tr", "td", "th", "ul", "caption", "summary", "details",
          "label", "option", "button")


@dataclass
class Link:
    url: str
    text: str


@dataclass
class ParsedHTML:
    title: str | None
    text: str
    canonical_url: str | None
    links: list[Link]
    meta: dict[str, str] = field(default_factory=dict)


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "html.parser")


def visible_text(soup: BeautifulSoup) -> str:
    """Text a visitor would read, one block element per line. Works on a copy."""
    s = BeautifulSoup(str(soup), "html.parser")
    for t in s.find_all(_DROP):
        t.decompose()
    for c in s.find_all(string=lambda x: isinstance(x, Comment)):
        c.extract()
    for br in s.find_all("br"):
        br.replace_with("\n")
    for t in s.find_all(_BLOCK):
        t.insert_before("\n")
        t.insert_after("\n")
    raw = s.get_text()
    lines = (re.sub(r"[ \t\r\f\v ]+", " ", ln).strip() for ln in raw.split("\n"))
    return "\n".join(ln for ln in lines if ln)


def content_hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


def parse_html(html: str, base_url: str) -> ParsedHTML:
    soup = soup_of(html)
    title_tag = soup.find("title")
    title = re.sub(r"\s+", " ", title_tag.get_text()).strip() if title_tag else None
    canonical = None
    for link in soup.find_all("link", href=True):
        rel = link.get("rel") or []
        rel = rel if isinstance(rel, list) else [rel]
        if any(r.lower() == "canonical" for r in rel):
            canonical = urljoin(base_url, link["href"].strip())
            break
    meta: dict[str, str] = {}
    for m in soup.find_all("meta"):
        key = (m.get("property") or m.get("name") or "").strip().lower()
        if key and m.get("content") and key not in meta:
            meta[key] = m["content"].strip()
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "data:")):
            continue
        links.append(Link(urljoin(base_url, href), re.sub(r"\s+", " ", a.get_text(" ")).strip()))
    return ParsedHTML(title=title or None, text=visible_text(soup), canonical_url=canonical, links=links, meta=meta)


@dataclass
class CrawledPage:
    url: str
    final_url: str
    html: str
    text: str
    title: str | None = None
    canonical_url: str | None = None
    page_type: str = "other"
    depth: int = 0
    status_code: int | None = 200
    content_type: str | None = "text/html"
    content_hash: str | None = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    links: list[Link] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)

    @property
    def source_url(self) -> str:
        return self.final_url or self.url


def make_page(url: str, html: str, page_type: str | None = None, **kw) -> CrawledPage:
    """Build a CrawledPage from raw HTML (tests, imports, re-analysis of stored pages)."""
    from app.crawler.site import classify_page  # local import: site imports this module

    parsed = parse_html(html, url)
    return CrawledPage(url=url, final_url=kw.pop("final_url", url), html=html, text=parsed.text, title=parsed.title,
                       canonical_url=parsed.canonical_url,
                       page_type=page_type or classify_page(url, parsed.title),
                       content_hash=content_hash(parsed.text), links=parsed.links, meta=parsed.meta, **kw)
