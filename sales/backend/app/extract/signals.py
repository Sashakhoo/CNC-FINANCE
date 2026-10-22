"""Sales signals from crawled pages (spec §22) using keyword/regex rules only.
Each signal quotes the exact sentence it was found in."""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from app.crawler.html import CrawledPage
from app.extract.common import sentences


@dataclass
class DetectedSignal:
    signal_type: str
    title: str
    description: str
    evidence: str
    source_url: str
    confidence: float
    source_date: date | None = None
    matches: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Rule:
    signal_type: str
    title: str
    pattern: re.Pattern
    confidence: float
    requires: re.Pattern | None = None       # extra context needed in the same sentence
    boost_if: re.Pattern | None = None


def _r(p: str, flags=re.I) -> re.Pattern:
    return re.compile(p, flags)


_HIRING_CONTEXT = _r(r"\b(hiring|we are hiring|we're hiring|vacanc(y|ies)|we are looking for|looking for an?|join our|"
                     r"career opportunit|open positions?|job openings?|now recruiting|recruiting|apply now|position)\b")
_ENG_JOB = _r(r"\b(engineers?|engineering|technicians?|automation|mechanical|electrical|electronics?|process engineer|"
              r"production engineer|quality engineer|r&d|maintenance|plc|mechatronic)\b")
_IT_JOB = _r(r"\b(it executive|it officer|it manager|it support|it specialist|software|developers?|programmers?|"
             r"system administrator|sysadmin|network (engineer|administrator)|data (analyst|engineer|scientist)|"
             r"devops|full[- ]stack|front[- ]end|back[- ]end|erp (analyst|consultant|executive))\b")
_SEC_JOB = _r(r"\b(cyber ?security|information security|infosec|security analyst|soc analyst|penetration tester|"
              r"security engineer)\b")

RULES: list[_Rule] = [
    _Rule("NEW_FACILITY", "New facility",
          _r(r"\b(new|second|third|additional)\s+(manufacturing\s+|production\s+|regional\s+)?(plant|facility|factory|"
             r"warehouse|headquarters|hq|office|production line|site|campus|distribution cent(re|er))\b|"
             r"\b(open(ed|s|ing)|launch(ed|es|ing)|complet(ed|es|ion of)|groundbreaking|broke ground|"
             r"official opening)\b.{0,60}\b(plant|facility|factory|warehouse|headquarters|production line)\b"), 0.75),
    _Rule("EXPANSION", "Company expansion",
          _r(r"\b(expan(d|ds|ded|ding|sion)|increas(e|ed|ing) (our )?(production )?capacity|new branch|"
             r"entered the [\w\s]{2,30} market|growing our (team|operations|presence))\b"), 0.6),
    _Rule("DIGITAL_TRANSFORMATION", "Digital transformation",
          _r(r"\b(digital transformation|digitali[sz](ation|e|ing|ed)|going digital|paperless|e-?invoicing system)\b"), 0.7),
    _Rule("INDUSTRY_4_0", "Industry 4.0 initiative",
          _r(r"\b(industry\s*4\.0|industry4wrd|ir\s*4\.0|4ir|fourth industrial revolution|smart (factory|manufacturing)|"
             r"iiot|industrial internet of things|digital twin)\b"), 0.75),
    _Rule("AI_INITIATIVE", "AI initiative",
          re.compile(r"(\b[Aa]rtificial [Ii]ntelligence\b|\bmachine learning\b|\b(?<![A-Za-z])AI(?![A-Za-z])|"
                     r"\bgenerative AI\b|\bcomputer vision\b|\bchatbots?\b|\bpredictive analytics\b)"), 0.65),
    _Rule("AUTOMATION", "Automation initiative",
          _r(r"\b(automat(ion|ed|ing|e)|robotic(s)?|robots?|rpa|cobots?|plc|scada)\b"), 0.5,
          boost_if=_r(r"\b(implement|invest|introduc|deploy|upgrad|new|launch|adopt)\w*\b")),
    _Rule("CLOUD_MIGRATION", "Cloud migration",
          _r(r"\b(cloud migration|migrat\w+ (to|into) the cloud|move(d)? to the cloud|cloud[- ]based|aws|"
             r"amazon web services|microsoft azure|azure|google cloud|gcp|microsoft 365|office 365)\b"), 0.55,
          boost_if=_r(r"\b(migrat|move|moved|implement|adopt|transition)\w*\b")),
    _Rule("ERP_IMPLEMENTATION", "ERP implementation",
          _r(r"\b(erp|sap( s/4hana| business one)?|s/4hana|oracle netsuite|netsuite|microsoft dynamics|"
             r"dynamics 365|odoo|autocount|sql account)\b"), 0.5,
          boost_if=_r(r"\b(implement|go[- ]live|went live|roll(ed)?[- ]?out|deploy|adopt|upgrad|migrat)\w*\b")),
    _Rule("CYBERSECURITY_CERTIFICATION", "Cybersecurity certification",
          _r(r"\b((ms\s+)?iso(/iec)?\s*27001|soc\s*2|pci[- ]?dss|cyber essentials|crest|iso(/iec)?\s*27701)\b"), 0.8),
    _Rule("NEW_TECH_DEPARTMENT", "New technology department",
          _r(r"\b(new|newly|established|set up|setting up|formed|launch(ed)?|created)\b.{0,40}\b(it|digital|data|"
             r"innovation|technology|r&d|engineering|automation|ai)\s+(department|division|team|cent(re|er)|unit|hub|lab)\b"),
          0.75),
    _Rule("EMPLOYEE_DEVELOPMENT", "Employee development initiative",
          _r(r"\b(training (programme|program|programs|programmes|initiative)s?|upskill\w*|reskill\w*|"
             r"employee development|staff development|learning (and|&) development|talent development|"
             r"hrdf|hrd corp|hrdcorp|competency development|continuous learning|training academy)\b"), 0.65),
]

_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
_MONTH_NUM = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DATE_PATTERNS = [
    (_r(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "ymd"),
    (_r(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTHS})[a-z]*\.?,?\s+(\d{{4}})\b"), "dmy_name"),
    (_r(rf"\b({_MONTHS})[a-z]*\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b"), "mdy_name"),
    (_r(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "dmy"),
    (_r(rf"\b({_MONTHS})[a-z]*\.?\s+(\d{{4}})\b"), "my_name"),
]


def find_date(text: str) -> date | None:
    for pattern, kind in _DATE_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        try:
            if kind == "ymd":
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if kind == "dmy_name":
                return date(int(m.group(3)), _MONTH_NUM[m.group(2).lower()[:3]], int(m.group(1)))
            if kind == "mdy_name":
                return date(int(m.group(3)), _MONTH_NUM[m.group(1).lower()[:3]], int(m.group(2)))
            if kind == "dmy":  # Malaysian/Singapore convention: day first
                return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            return date(int(m.group(2)), _MONTH_NUM[m.group(1).lower()[:3]], 1)
        except ValueError:
            continue
    return None


def _hiring_signals(page: CrawledPage) -> list[DetectedSignal]:
    lines = (page.text or "").split("\n")
    is_careers = page.page_type == "careers"
    out = []
    for signal_type, title, pattern in (("HIRING_ENGINEERS", "Hiring engineers", _ENG_JOB),
                                        ("HIRING_IT", "Hiring IT staff", _IT_JOB),
                                        ("HIRING_CYBERSECURITY", "Hiring cybersecurity professionals", _SEC_JOB)):
        roles: list[str] = []
        evidence = None
        for line in lines:
            if not pattern.search(line):
                continue
            short_job_line = is_careers and len(line) <= 80 and len(line.split()) <= 10
            if short_job_line or _HIRING_CONTEXT.search(line):
                evidence = evidence or line
                if short_job_line and line not in roles:
                    roles.append(line)
        if evidence:
            desc = f"{title} — found on the {page.page_type} page"
            if roles:
                desc += ": " + "; ".join(roles[:5])
            out.append(DetectedSignal(signal_type, title, desc, evidence, page.source_url,
                                      0.8 if is_careers else 0.6, None, roles[:10]))
    return out


def detect_signals_on_page(page: CrawledPage) -> list[DetectedSignal]:
    if not page.text:
        return []
    lines = page.text.split("\n")
    found: dict[str, DetectedSignal] = {}
    for sentence, line_idx in sentences(page.text):
        if len(sentence) < 12:
            continue
        for rule in RULES:
            m = rule.pattern.search(sentence)
            if not m or (rule.requires and not rule.requires.search(sentence)):
                continue
            conf = rule.confidence + (0.15 if rule.boost_if and rule.boost_if.search(sentence) else 0.0)
            if page.page_type == "news":
                conf += 0.05
            nearby = "\n".join(lines[max(0, line_idx - 2): line_idx + 1])
            when = find_date(nearby)
            existing = found.get(rule.signal_type)
            if existing and existing.confidence >= conf:
                continue
            found[rule.signal_type] = DetectedSignal(
                rule.signal_type, rule.title, f"{rule.title} mentioned on the {page.page_type} page",
                sentence[:500], page.source_url, round(min(conf, 0.95), 2), when, [m.group(0)])
    signals = list(found.values()) + _hiring_signals(page)
    return signals


def detect_signals(pages: Iterable[CrawledPage]) -> list[DetectedSignal]:
    out: list[DetectedSignal] = []
    seen: set[tuple[str, str]] = set()
    for page in pages:
        for s in detect_signals_on_page(page):
            key = (s.signal_type, s.evidence)
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
    out.sort(key=lambda s: -s.confidence)
    return out
