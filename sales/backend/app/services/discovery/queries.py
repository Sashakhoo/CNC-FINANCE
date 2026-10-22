"""Turns prospect-search criteria (spec §6) into search-engine queries."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

INDUSTRY_PHRASES: dict[str, list[str]] = {
    "Manufacturing": ["manufacturing company", "manufacturer"],
    "Engineering": ["engineering company", "engineering services"],
    "Electrical": ["electrical engineering company", "electrical contractor"],
    "Electronics": ["electronics manufacturer", "electronics manufacturing services"],
    "Automation": ["industrial automation company", "automation solutions"],
    "Semiconductor": ["semiconductor company", "semiconductor manufacturing"],
    "Technology": ["technology company", "IT solutions company"],
    "Logistics": ["logistics company", "warehousing and logistics"],
    "Construction": ["construction company", "building contractor"],
    "Schools": ["international school", "private school"],
}
# Schools rarely carry a legal suffix in their name, so don't add "Sdn Bhd" to their queries.
NO_SUFFIX = {"Schools", "Education"}

MAIN_CITY = {
    "Johor": "Johor Bahru", "Selangor": "Shah Alam", "Kuala Lumpur": "Kuala Lumpur", "Penang": "Penang",
    "Pulau Pinang": "Penang", "Singapore": "Singapore", "Melaka": "Melaka", "Perak": "Ipoh",
}


@dataclass(frozen=True)
class DiscoveryQuery:
    query: str
    industry: str
    location: str


def _get(criteria: Mapping[str, Any] | Any, *names: str, default=None):
    for n in names:
        v = criteria.get(n) if isinstance(criteria, Mapping) else getattr(criteria, n, None)
        if v not in (None, "", []):
            return v
    return default


def build_queries(criteria: Mapping[str, Any] | Any, max_queries: int = 40) -> list[DiscoveryQuery]:
    """Industries × locations, phrased the way Malaysian/Singaporean company
    sites describe themselves (legal suffix + city), most specific first."""
    country = str(_get(criteria, "country", default="Malaysia"))
    state = _get(criteria, "state")
    city = _get(criteria, "city")
    industries = list(_get(criteria, "industries", default=[]) or ["Manufacturing"])
    singapore = country.strip().lower() == "singapore" or (state or "").lower() == "singapore"
    suffix = "Pte Ltd" if singapore else "Sdn Bhd"

    locations: list[str] = []
    if city:
        locations.append(str(city))
    if state and str(state) not in locations:
        if not city and MAIN_CITY.get(str(state)) and MAIN_CITY[str(state)] != str(state):
            locations.append(MAIN_CITY[str(state)])
        locations.append(str(state))
    if not locations:
        locations.append("Singapore" if singapore else country)

    out: list[DiscoveryQuery] = []
    seen: set[str] = set()

    def add(q: str, industry: str, loc: str) -> None:
        key = q.lower()
        if key not in seen:
            seen.add(key)
            out.append(DiscoveryQuery(q, industry, loc))

    for phrase_idx in range(2):
        for loc in locations:
            for industry in industries:
                phrases = INDUSTRY_PHRASES.get(industry, [f"{industry.lower()} company"])
                if phrase_idx >= len(phrases):
                    continue
                phrase = phrases[phrase_idx]
                where = loc if singapore or loc == country else f"{loc} {country}"
                if phrase_idx == 0 and industry not in NO_SUFFIX:
                    add(f'{phrase} {where} "{suffix}"', industry, loc)
                else:
                    add(f"{phrase} {where}", industry, loc)
    return out[:max_queries]
