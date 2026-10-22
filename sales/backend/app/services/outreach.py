"""Outreach drafts (email, LinkedIn-style message, follow-up). Drafts are
never sent automatically. Templates use only the facts passed in; the LLM
variant is post-checked and falls back to the template if it introduces any
number, URL, email or name that isn't in the inputs."""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from app.providers.base import ProviderError
from app.services.training import SignalFact, unsupported_tokens

log = logging.getLogger("app.outreach")

Channel = Literal["EMAIL", "LINKEDIN", "FOLLOWUP"]
Tone = Literal["Professional", "Friendly", "Concise", "Consultative"]
LINKEDIN_MAX = 300
QUOTE_MAX = 160


@dataclass
class OutreachContact:
    name: str
    original_title: str | None
    company_name: str
    industry: str | None = None


@dataclass
class OutreachOpportunity:
    program_name: str
    reason: str = ""
    evidence: list[dict] = field(default_factory=list)  # [{source_url, quote}]


@dataclass
class Sender:
    name: str
    title: str
    company: str


@dataclass
class Draft:
    channel: str
    tone: str
    subject: str
    body: str
    evidence_used: list[dict]
    generated_by: str = "TEMPLATE"
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _first_name(name: str) -> str:
    parts = [p for p in name.split() if p.rstrip(".").lower() not in {"mr", "mrs", "ms", "dr", "ir", "ts", "dato", "datuk"}]
    return parts[0] if parts else name


def _short(quote: str, limit: int = QUOTE_MAX) -> str:
    q = re.sub(r"\s+", " ", quote).strip()
    if len(q) <= limit:
        return q
    cut = q[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


def _pick_evidence(opp: OutreachOpportunity | None, signals: list[SignalFact]) -> dict | None:
    for s in signals:
        if s.quote and s.quote.strip():
            return {"source_url": s.source_url, "quote": s.quote.strip()}
    if opp:
        for e in opp.evidence:
            if e.get("quote"):
                return {"source_url": e.get("source_url"), "quote": e["quote"]}
    return None


def _role_phrase(c: OutreachContact) -> str:
    return f"as {c.original_title} at {c.company_name}" if c.original_title else f"at {c.company_name}"


def _tidy(text: str) -> str:
    # Names like "Sdn. Bhd." end in a full stop; don't add a second one.
    return re.sub(r"(?<!\.)\.\.(?!\.)", ".", text)


def generate_draft(contact: OutreachContact, opportunity: OutreachOpportunity | None, signals: list[SignalFact],
                   sender: Sender, channel: Channel = "EMAIL", tone: Tone = "Professional") -> Draft:
    d = _generate(contact, opportunity, signals, sender, channel, tone)
    d.body = _tidy(d.body)
    d.subject = _tidy(d.subject)
    if d.subject:
        d.subject = d.subject[0].upper() + d.subject[1:]
    return d


def _generate(contact: OutreachContact, opportunity: OutreachOpportunity | None, signals: list[SignalFact],
              sender: Sender, channel: Channel = "EMAIL", tone: Tone = "Professional") -> Draft:
    program = opportunity.program_name if opportunity else "corporate technology"
    teams = f"{contact.industry.lower()} teams" if contact.industry else "teams like yours"
    ev = _pick_evidence(opportunity, signals)
    evidence_used = [ev] if ev else []
    first = _first_name(contact.name)
    greeting = {"Professional": f"Dear {contact.name},", "Consultative": f"Dear {contact.name},"}.get(tone, f"Hi {first},")
    sign = f"{sender.name}\n{sender.title}, {sender.company}" if sender.title else f"{sender.name}\n{sender.company}"

    if channel == "LINKEDIN":
        parts = [f"Hi {first},"]
        if ev:
            parts.append(f"I read on {contact.company_name}'s site: \"{_short(ev['quote'], 110)}\"")
        parts.append(f"{sender.company} runs practical {program} training for {teams}.")
        parts.append("Open to a short chat?" if tone != "Consultative" else "Would a short call to compare notes help?")
        parts.append(f"– {sender.name}")
        body = " ".join(parts)
        while len(body) > LINKEDIN_MAX and len(parts) > 3:
            if ev and len(parts) == 5:
                parts.pop(1)
                evidence_used = []
            else:
                parts.pop(-2)
            body = " ".join(parts)
        if len(body) > LINKEDIN_MAX:
            body = body[: LINKEDIN_MAX - 1].rsplit(" ", 1)[0] + "…"
        return Draft("LINKEDIN", tone, "", body, evidence_used)

    if channel == "FOLLOWUP":
        subject = f"Re: {program} training for {contact.company_name}"
        body_lines = [greeting, "",
                      f"Following up on my earlier note about {program} training for {teams} at {contact.company_name}.",
                      "If it's useful, I can share a short course outline tailored to your team's current tools and workflows.",
                      "", "Would a 20-minute call in the next week or two work?" if tone != "Concise" else "Worth a quick call?",
                      "", "Best regards,", sign]
        return Draft("FOLLOWUP", tone, subject, "\n".join(body_lines), evidence_used)

    subject = {"Professional": f"{program} training for {contact.company_name}",
               "Friendly": f"Idea for {contact.company_name}'s team",
               "Concise": f"{program} training — {contact.company_name}",
               "Consultative": f"Upskilling {contact.company_name}'s teams in {program}"}[tone]
    lines = [greeting, ""]
    lines.append(f"I'm reaching out to you {_role_phrase(contact)}.")
    if ev:
        lines.append(f"On {contact.company_name}'s website I read: \"{_short(ev['quote'])}\"")
    if tone == "Concise":
        lines.append(f"{sender.company} runs hands-on {program} training for {teams}. Worth a short call?")
    else:
        lines.append(f"{sender.company} runs hands-on {program} training designed for {teams}, built around the "
                     "tools and workflows your staff already use.")
        if tone == "Consultative":
            lines.append("I'd value 20 minutes to understand your team's priorities and whether a programme like this "
                         "would genuinely help.")
        elif tone == "Friendly":
            lines.append("Happy to share a short outline if that would be useful — no obligation.")
        else:
            lines.append("Would you be open to a 20-minute call to see whether it fits your training plans?")
    lines += ["", "Best regards," if tone != "Friendly" else "Cheers,", sign]
    return Draft("EMAIL", tone, subject, "\n".join(lines), evidence_used)


# --- LLM ------------------------------------------------------------------

class _LLMDraft(BaseModel):
    subject: str = Field(default="", max_length=200)
    body: str = Field(min_length=1, max_length=3000)
    evidence_indexes: list[int] = Field(default_factory=list)


def _facts(contact: OutreachContact, opp: OutreachOpportunity | None, signals: list[SignalFact],
           sender: Sender) -> tuple[list[dict], list[str]]:
    evidence = list(opp.evidence if opp else []) + [{"source_url": s.source_url, "quote": s.quote} for s in signals if s.quote]
    texts = [contact.name, contact.original_title or "", contact.company_name, contact.industry or "",
             sender.name, sender.title, sender.company, opp.program_name if opp else "", opp.reason if opp else ""]
    texts += [e["quote"] for e in evidence] + [s.title for s in signals]
    return evidence, texts


async def generate_draft_llm(ai, contact: OutreachContact, opportunity: OutreachOpportunity | None,
                             signals: list[SignalFact], sender: Sender, channel: Channel = "EMAIL",
                             tone: Tone = "Professional") -> Draft:
    template = generate_draft(contact, opportunity, signals, sender, channel, tone)
    evidence, texts = _facts(contact, opportunity, signals, sender)
    numbered = "\n".join(f"[{i}] {e['quote']}" for i, e in enumerate(evidence))
    system = ("You write short, respectful B2B outreach about corporate training. Use ONLY the facts provided. "
              "Never invent personal details, numbers, clients, results, dates, URLs or names. Do not claim to "
              "know anything about the recipient beyond their name, title and company. "
              f"Channel: {channel}. Tone: {tone}." + (f" Keep the message under {LINKEDIN_MAX} characters and leave "
                                                       "subject empty." if channel == "LINKEDIN" else ""))
    prompt = (f"Recipient: {contact.name}, {contact.original_title or 'title unknown'}, {contact.company_name}"
              f"{', ' + contact.industry if contact.industry else ''}\n"
              f"Sender: {sender.name}, {sender.title}, {sender.company}\n"
              f"Programme: {opportunity.program_name if opportunity else 'corporate technology training'}\n"
              f"Why it fits (from evidence): {opportunity.reason if opportunity else ''}\n"
              f"Evidence (cite by index in evidence_indexes):\n{numbered or '(none)'}")
    try:
        out = await ai.generate_structured(system, prompt, _LLMDraft, max_tokens=900)
    except ProviderError as e:
        log.warning("LLM draft failed; using template", extra={"error_type": e.error_type})
        template.note = f"AI drafting unavailable ({e.error_type}); template used."
        return template
    body = out.body.strip()
    bad = unsupported_tokens(body, texts) + unsupported_tokens(out.subject, texts)
    if bad or (channel == "LINKEDIN" and len(body) > LINKEDIN_MAX):
        template.note = ("AI draft rejected: it mentioned facts not in the evidence"
                         + (f" ({', '.join(bad[:5])})" if bad else " (too long)") + "; template used.")
        return template
    used = [evidence[i] for i in dict.fromkeys(out.evidence_indexes) if 0 <= i < len(evidence)]
    return Draft(channel, tone, "" if channel == "LINKEDIN" else out.subject.strip(), body, used, generated_by="LLM")
