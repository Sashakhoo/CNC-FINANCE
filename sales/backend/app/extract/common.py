"""Shared extraction helpers. Evidence snippets are always exact substrings of
the page (visible text or raw source), so they can be shown as proof."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterator

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class Evidence:
    source_url: str
    snippet: str


def window(text: str, start: int, end: int, size: int = 80) -> str:
    """Exact substring around [start, end), widened to word boundaries."""
    a, b = max(0, start - size), min(len(text), end + size)
    while a > 0 and not text[a - 1].isspace() and start - a < size + 20:
        a -= 1
    while b < len(text) and not text[b].isspace() and b - end < size + 20:
        b += 1
    return text[a:b].strip()


def line_at(text: str, pos: int) -> str:
    a = text.rfind("\n", 0, pos) + 1
    b = text.find("\n", pos)
    return text[a: b if b != -1 else len(text)].strip()


def sentences(text: str) -> Iterator[tuple[str, int]]:
    """(sentence, line_index) — exact substrings of `text`."""
    for i, line in enumerate(text.split("\n")):
        start = 0
        for m in re.finditer(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", line):
            seg = line[start:m.start()].strip()
            if seg:
                yield seg, i
            start = m.end()
        seg = line[start:].strip()
        if seg:
            yield seg, i


def json_ld_objects(soup: BeautifulSoup) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for n in node:
                walk(n)
        elif isinstance(node, dict):
            out.append(node)
            for k, v in node.items():
                if k in ("@graph", "employee", "employees", "founder", "founders", "member", "members",
                         "author", "contactPoint", "address", "subOrganization", "mainEntity", "itemListElement", "item"):
                    walk(v)

    for tag in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = tag.string or tag.get_text() or ""
        try:
            walk(json.loads(raw))
        except (ValueError, TypeError):
            continue
    return out


def ld_types(obj: dict[str, Any]) -> set[str]:
    t = obj.get("@type")
    if isinstance(t, list):
        return {str(x) for x in t}
    return {str(t)} if t else set()


def ld_str(v: Any) -> str | None:
    if isinstance(v, str):
        return v.strip() or None
    if isinstance(v, dict):
        return ld_str(v.get("name") or v.get("@value"))
    if isinstance(v, list) and v:
        return ld_str(v[0])
    return None
