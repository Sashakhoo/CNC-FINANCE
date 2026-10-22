"""Job-title normalization: deterministic rules (an LLM fallback is added in
Phase 7 for titles these rules can't place)."""
import re
from dataclasses import dataclass

from app.models.base import Department, Seniority


@dataclass(frozen=True)
class NormalizedTitle:
    normalized_title: str | None
    department: Department
    seniority: Seniority
    matched: bool


# (pattern, normalized title, department, seniority) — first match wins, so
# more specific titles come first.
_RULES: list[tuple[str, str | None, Department, Seniority]] = [
    (r"\b(chief executive|ceo)\b", "CEO", Department.MANAGEMENT, Seniority.C_LEVEL),
    (r"\b(chief operating|coo)\b", "COO", Department.MANAGEMENT, Seniority.C_LEVEL),
    (r"\b(chief information officer|cio)\b", "CIO", Department.IT, Seniority.C_LEVEL),
    (r"\b(chief technology|cto)\b", "CTO", Department.IT, Seniority.C_LEVEL),
    (r"\b(chief human|chief people|chro|cpo)\b", "Chief People Officer", Department.HR, Seniority.C_LEVEL),
    # Schools — "Principal Engineer/Consultant…" is an industrial title, not a school head.
    (r"\b(vice principal|deputy (head|principal)|assistant principal)\b", "Vice Principal", Department.MANAGEMENT, Seniority.DIRECTOR),
    (r"\b(headmaster|headmistress|head ?teacher|head of school)\b|\bprincipal\b(?!['’]s)(?!\s*(engineer|consultant|scientist|architect|software|designer|analyst|specialist|officer|investigator|partner|product|program|research))",
     "Principal", Department.MANAGEMENT, Seniority.HEAD),
    (r"\b(director of studies|academic director|head of (teaching (and|&) learning|academics?|curriculum)|curriculum (coordinator|director))\b",
     "Director of Studies", Department.LD, Seniority.DIRECTOR),
    (r"\bbursar\b|\bschool business manager\b", "Bursar", Department.OPERATIONS, Seniority.MANAGER),
    # Board roles: independent / non-executive / alternate directors don't run the business — not decision makers.
    (r"\b(independent|non[- ]?executive|alternate)\b.*\b(director|chairman|chairperson)\b", None, Department.MANAGEMENT, Seniority.INDIVIDUAL),
    (r"\b(executive )?(chairman|chairperson)\b", "Chairman", Department.MANAGEMENT, Seniority.C_LEVEL),
    (r"\b(group )?executive director\b", "Executive Director", Department.MANAGEMENT, Seniority.DIRECTOR),
    (r"\bmanaging director\b", "Managing Director", Department.MANAGEMENT, Seniority.C_LEVEL),
    (r"\b(founder|co-founder|owner|proprietor)\b", "Owner", Department.MANAGEMENT, Seniority.OWNER),
    (r"\bgeneral manager\b", "General Manager", Department.MANAGEMENT, Seniority.HEAD),
    (r"\b(learning (and|&) development|l\s*&\s*d|l&d)\b.*\b(head|director)\b|\b(head|director)\b.*\b(learning|l\s*&\s*d)\b",
     "Head of L&D", Department.LD, Seniority.HEAD),
    (r"\b(learning (and|&) development|l\s*&\s*d)\b", "L&D Manager", Department.LD, Seniority.MANAGER),
    (r"\btraining\b.*\bmanager\b|\bmanager\b.*\btraining\b", "Training Manager", Department.LD, Seniority.MANAGER),
    (r"\btalent (development|management)\b", "Talent Development Manager", Department.LD, Seniority.MANAGER),
    (r"\bpeople (and|&) culture\b", "People & Culture Manager", Department.HR, Seniority.MANAGER),
    (r"\b(hr|human resources?|human capital)\b.*\bdirector\b|\bdirector\b.*\b(hr|human resources?)\b",
     "HR Director", Department.HR, Seniority.DIRECTOR),
    (r"\bhead of (hr|human resources?|people)\b", "Head of HR", Department.HR, Seniority.HEAD),
    (r"\b(hr|human resources?|human capital)\b.*\bmanager\b|\bmanager\b.*\b(hr|human resources?)\b",
     "HR Manager", Department.HR, Seniority.MANAGER),
    (r"\bdigital transformation\b", "Digital Transformation Manager", Department.IT, Seniority.MANAGER),
    (r"\b(it|information technology|ict)\b.*\bdirector\b|\bdirector\b.*\b(it|information technology)\b",
     "IT Director", Department.IT, Seniority.DIRECTOR),
    (r"\bhead of (it|information technology|ict|technology)\b", "Head of IT", Department.IT, Seniority.HEAD),
    (r"\b(it|information technology|ict)\b.*\bmanager\b|\bmanager\b.*\b(it|information technology)\b",
     "IT Manager", Department.IT, Seniority.MANAGER),
    (r"\btechnology manager\b", "Technology Manager", Department.IT, Seniority.MANAGER),
    (r"\b(ict|computing|computer science|digital learning|edtech|educational technology)\b.*\b(coordinator|head|lead|director)\b|\bhead of (computing|computer science|digital learning)\b",
     "Head of ICT/Computing", Department.IT, Seniority.HEAD),
    (r"\bstem\b.*\b(coordinator|head|lead|director)\b|\bhead of stem\b", "Head of STEM", Department.LD, Seniority.HEAD),
    (r"\bengineering\b.*\bdirector\b|\bdirector\b.*\bengineering\b", "Engineering Director", Department.ENGINEERING, Seniority.DIRECTOR),
    (r"\bhead of engineering\b", "Head of Engineering", Department.ENGINEERING, Seniority.HEAD),
    (r"\bautomation\b.*\bmanager\b", "Automation Manager", Department.ENGINEERING, Seniority.MANAGER),
    (r"\bengineering\b.*\bmanager\b|\bmanager\b.*\bengineering\b", "Engineering Manager", Department.ENGINEERING, Seniority.MANAGER),
    (r"\btechnical manager\b", "Technical Manager", Department.ENGINEERING, Seniority.MANAGER),
    (r"\boperations?\b.*\bdirector\b", "Operations Director", Department.OPERATIONS, Seniority.DIRECTOR),
    (r"\boperations?\b.*\bmanager\b|\bmanager\b.*\boperations?\b", "Operations Manager", Department.OPERATIONS, Seniority.MANAGER),
    (r"\bplant manager\b|\bfactory manager\b", "Plant Manager", Department.OPERATIONS, Seniority.MANAGER),
]

_SENIORITY_HINTS = [
    (r"\b(chief|c[etio]o)\b", Seniority.C_LEVEL),
    (r"\b(vp|vice president)\b", Seniority.VP),
    (r"\bdirector\b", Seniority.DIRECTOR),
    (r"\bhead\b", Seniority.HEAD),
    (r"\bmanager\b", Seniority.MANAGER),
]
_DEPT_HINTS = [
    (r"\b(hr|human resources?|people|recruit|payroll)\b", Department.HR),
    (r"\b(training|learning|talent)\b", Department.LD),
    (r"\b(it|software|systems?|network|technology|ict|data)\b", Department.IT),
    (r"\b(engineer|engineering|automation|technical|mechanical|electrical|process)\b", Department.ENGINEERING),
    (r"\b(operations?|production|plant|manufacturing|supply chain|logistics)\b", Department.OPERATIONS),
]


def normalize_title(title: str | None) -> NormalizedTitle:
    if not title or not title.strip():
        return NormalizedTitle(None, Department.OTHER, Seniority.INDIVIDUAL, False)
    t = re.sub(r"\s+", " ", title.lower().replace("&amp;", "&")).strip()
    for pattern, norm, dept, sen in _RULES:
        if re.search(pattern, t):
            return NormalizedTitle(norm, dept, sen, True)
    seniority = next((s for p, s in _SENIORITY_HINTS if re.search(p, t)), Seniority.INDIVIDUAL)
    dept = next((d for p, d in _DEPT_HINTS if re.search(p, t)), Department.OTHER)
    return NormalizedTitle(None, dept, seniority, False)
