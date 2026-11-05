"""
Quotation document (both types) as HTML, rendered to an A4 PDF with
WeasyPrint. The same HTML drives the builder's live preview, so what you see
while editing is what the customer gets.

Page 1  quotation + totals (+ HRDC training-provider, employer, programme blocks)
Page 2  course content, session by session (plain or detailed), optional Claude block
Page 3+ HRDC only: trainer profile, TP registration reference, participant list
"""
import html as _html
import pathlib
from datetime import datetime

import pdf_generator as _pg
import quote_store

FONT_DIR = pathlib.Path(__file__).resolve().parent / "fonts"
MINT = "#00dcb4"
MINT_INK = "#003d33"
INK = "#15141a"

FONT_FACES = "".join(
    f"@font-face {{ font-family: '{fam}'; font-weight: {w}; src: url('{(FONT_DIR / f).as_uri()}'); }}\n"
    for fam, w, f in (
        ("Space Grotesk", 500, "SpaceGrotesk-Medium.ttf"), ("Space Grotesk", 700, "SpaceGrotesk-Bold.ttf"),
        ("Inter", 400, "Inter-Regular.ttf"), ("Inter", 600, "Inter-SemiBold.ttf"), ("Inter", 700, "Inter-Bold.ttf"),
        ("JetBrains Mono", 400, "JetBrainsMono-Regular.ttf"), ("JetBrains Mono", 700, "JetBrainsMono-Bold.ttf"),
    ))
WEB_FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700'
             '&family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@400;700&display=swap">')

CSS = f"""
@page {{ size: A4; margin: 16mm 15mm 18mm 15mm;
  @bottom-left {{ content: "Code N Code Solution · codencode.my"; font: 7pt 'Inter'; color: #8b8894; }}
  @bottom-right {{ content: "Page " counter(page) " of " counter(pages); font: 7pt 'JetBrains Mono'; color: #8b8894; }} }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: 'Inter', Arial, sans-serif; font-size: 8.6pt; line-height: 1.5; color: {INK}; }}
.sheet {{ page-break-after: always; position: relative; }}
.sheet:last-child {{ page-break-after: auto; }}
h1, h2, h3, .num, .doc-type {{ font-family: 'Space Grotesk', 'Inter', sans-serif; }}
.mono, td.n, .doc-no {{ font-family: 'JetBrains Mono', monospace; }}
.head {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; }}
.logo {{ height: 20px; display: block; margin-bottom: 8px; }}
.biz {{ font-family: 'Space Grotesk'; font-weight: 700; font-size: 10.5pt; }}
.biz-line {{ font-size: 7.5pt; color: #5d5a66; }}
.doc-side {{ text-align: right; }}
.doc-type {{ font-weight: 700; font-size: 19pt; letter-spacing: 1px; line-height: 1.1; }}
.doc-type .tag {{ display: inline-block; background: {MINT}; color: {MINT_INK}; font-size: 7.5pt; letter-spacing: .5px;
  padding: 2px 8px; border-radius: 100px; vertical-align: middle; margin-left: 6px; }}
.doc-no {{ font-weight: 700; font-size: 10pt; margin-top: 4px; }}
.meta {{ font-size: 7.8pt; color: #5d5a66; margin-top: 3px; }}
.meta b {{ color: {INK}; font-weight: 600; }}
.rule {{ height: 4px; background: {MINT}; margin: 12px 0 14px; border-radius: 2px; }}
.grid {{ display: flex; gap: 12px; }}
.grid > div {{ flex: 1; }}
.box {{ border: 1px solid #e3e0d7; border-radius: 8px; padding: 9px 11px; }}
.box.mint {{ background: #e6fbf6; border-color: #b4efe2; }}
.lbl {{ font-size: 6.8pt; font-weight: 700; letter-spacing: .8px; text-transform: uppercase; color: #8b8894; margin-bottom: 3px; }}
.party {{ font-weight: 700; font-size: 10pt; font-family: 'Space Grotesk'; }}
.kv {{ display: flex; gap: 6px; font-size: 7.8pt; }}
.kv span:first-child {{ color: #8b8894; min-width: 84px; }}
h2 {{ font-size: 9pt; font-weight: 700; letter-spacing: .6px; text-transform: uppercase; margin: 14px 0 6px;
     padding-bottom: 4px; border-bottom: 2px solid {MINT}; }}
table.items {{ width: 100%; border-collapse: collapse; }}
table.items th {{ text-align: left; font-size: 7pt; letter-spacing: .5px; text-transform: uppercase; color: #5d5a66;
  padding: 5px 6px; border-bottom: 1.5px solid {INK}; }}
table.items td {{ padding: 6px; border-bottom: 1px solid #ece9e1; vertical-align: top; }}
table.items .r {{ text-align: right; }}
table.items td.n {{ white-space: nowrap; }}
.item-title {{ font-weight: 600; }}
.item-desc {{ color: #5d5a66; font-size: 7.6pt; margin-top: 1px; white-space: pre-line; }}
.claim {{ font-size: 6.8pt; font-weight: 700; padding: 1px 6px; border-radius: 100px; }}
.claim.y {{ background: #d9f7ee; color: #0a6b55; }} .claim.n {{ background: #f1efe9; color: #6b6878; }}
.totals {{ margin-left: auto; width: 62%; margin-top: 8px; }}
.trow {{ display: flex; justify-content: space-between; padding: 4px 8px; font-size: 8.4pt; }}
.trow span:last-child {{ font-family: 'JetBrains Mono'; }}
.trow.hl {{ background: #e6fbf6; border-radius: 4px; }}
.grand {{ display: flex; justify-content: space-between; background: {INK}; color: #fff; padding: 9px 10px; margin-top: 5px;
  border-radius: 6px; font-family: 'Space Grotesk'; font-weight: 700; font-size: 11pt; }}
.grand span:last-child {{ font-family: 'JetBrains Mono'; color: {MINT}; }}
.note {{ font-size: 7.6pt; color: #5d5a66; margin-top: 6px; }}
ul.terms {{ padding-left: 14px; font-size: 7.8pt; color: #3a3846; }}
ul.terms li {{ margin: 2px 0; }}
.session {{ display: flex; gap: 10px; padding: 7px 0; border-bottom: 1px solid #ece9e1; page-break-inside: avoid; }}
.session .no {{ font-family: 'JetBrains Mono'; font-weight: 700; color: {MINT_INK}; background: #e6fbf6; border-radius: 6px;
  min-width: 26px; height: 22px; text-align: center; line-height: 22px; font-size: 8pt; }}
.session .t {{ font-weight: 600; }}
.session .d {{ color: #5d5a66; font-size: 8pt; white-space: pre-line; }}
.course-h {{ font-family: 'Space Grotesk'; font-size: 11pt; font-weight: 700; margin: 12px 0 2px; }}
.course-meta {{ font-size: 7.8pt; color: #5d5a66; margin-bottom: 4px; }}
.claude {{ margin-top: 14px; background: #f6f4ef; border-radius: 8px; padding: 10px 12px; white-space: pre-line; font-size: 8pt; }}
.watermark {{ position: fixed; top: 40%; left: 0; right: 0; text-align: center; transform: rotate(-24deg);
  font-family: 'Space Grotesk'; font-weight: 700; font-size: 34pt; color: rgba(220, 70, 40, .13); letter-spacing: 2px; }}
table.people {{ width: 100%; border-collapse: collapse; font-size: 8pt; }}
table.people th, table.people td {{ border-bottom: 1px solid #ece9e1; padding: 5px 6px; text-align: left; }}
table.people th {{ font-size: 7pt; text-transform: uppercase; color: #5d5a66; border-bottom: 1.5px solid {INK}; }}
@media screen {{
  body {{ background: #e4e0d5; padding: 14px 0; }}
  .sheet {{ background: #fff; width: 210mm; min-height: 297mm; margin: 0 auto 14px; padding: 16mm 15mm 18mm;
           box-shadow: 0 6px 24px rgba(20,18,25,.15); overflow: hidden; }}
  .watermark {{ position: absolute; }}
}}
"""


def esc(v) -> str:
    return _html.escape(str(v if v is not None else ""))


def rm(v) -> str:
    return f"RM {float(v or 0):,.2f}"


def fdate(v) -> str:
    try:
        return datetime.strptime(str(v), "%Y-%m-%d").strftime("%d %b %Y")
    except (ValueError, TypeError):
        return esc(v)


def _kv(label, value) -> str:
    return f'<div class="kv"><span>{esc(label)}</span><span>{esc(value)}</span></div>' if value not in (None, "") else ""


def build_html(q: dict, *, for_pdf: bool = True) -> str:
    s = quote_store.get_settings()
    hrdc = q.get("qtype") == "hrdc"
    h = q.get("hrdc") or {}
    prog = quote_store.get_programme(h.get("programme_id")) if hrdc and h.get("programme_id") else None
    t = quote_store.totals(q, s)
    courses = {c["id"]: c for c in quote_store.list_courses(include_inactive=True)}
    watermark = ('<div class="watermark">SUBJECT TO HRD CORP APPROVAL</div>'
                 if hrdc and prog and prog["status"] != "Approved" else "")

    # header
    logo = f'<img class="logo" src="{_pg.LOGO_URI}" alt="codencode.my">' if _pg.LOGO_URI else ""
    addr = ("".join(f'<div class="biz-line">{esc(l)}</div>' for l in _pg.BUSINESS_ADDRESS)
            if q.get("show_address") else "")
    meta = [("Issue date", fdate(q.get("date"))), ("Valid until", fdate(q.get("valid_until")))]
    if q.get("reference_no"):
        meta.append(("Reference", q["reference_no"]))
    head = f"""
    <div class="head">
      <div>{logo}<div class="biz">Code N Code Solution</div>
        <div class="biz-line">{esc(_pg.BUSINESS_SSM)}</div>{addr}
        <div class="biz-line">{esc(_pg.BUSINESS_CONTACT)} · {esc(_pg.BUSINESS_SITE)}</div></div>
      <div class="doc-side"><div class="doc-type">QUOTATION{'<span class="tag">HRDC CLAIMABLE</span>' if hrdc else ''}</div>
        <div class="doc-no">{esc(q.get('number'))}</div>
        <div class="meta">{''.join(f'<div>{esc(k)}: <b>{esc(v)}</b></div>' for k, v in meta if v)}</div></div>
    </div><div class="rule"></div>"""

    # parties
    company = q.get("company") or q.get("contact") or ""
    if hrdc:
        client = f"""<div class="box"><div class="lbl">Employer</div><div class="party">{esc(company)}</div>
          {_kv('SSM no.', h.get('ssm'))}{_kv('HRD Corp MyCoID', h.get('mycoid'))}
          {_kv('HR contact', h.get('hr_contact') or q.get('attention'))}{_kv('Email', h.get('hr_email') or q.get('email'))}
          {_kv('Phone', h.get('hr_phone') or q.get('phone'))}{_kv('Address', q.get('address'))}</div>"""
        tp = f"""<div class="box mint"><div class="lbl">Training provider</div><div class="party">{esc(s.get('tp_name'))}</div>
          <div class="kv"><span>Status</span><span>HRD Corp certified Training Provider</span></div>
          {_kv('MyCoID / TP no.', s.get('tp_number'))}
          {_kv('Registration', f"{fdate(s.get('tp_valid_from'))} – {fdate(s.get('tp_valid_to'))}")}</div>"""
        parties = f'<div class="grid">{client}{tp}</div>'
        dates = ", ".join(fdate(d) for d in (h.get("dates") or []) if d)
        when = " – ".join(x for x in (h.get("start_time"), h.get("end_time")) if x)
        place = h.get("venue") or (prog or {}).get("venue") if (h.get("mode") or (prog or {}).get("mode")) != "online" \
            else (h.get("platform") or "Zoom")
        programme = f"""<h2>Programme</h2><div class="box">
          <div class="party">{esc((prog or {}).get('title') or '—')}</div>
          {_kv('Programme ID', (prog or {}).get('programme_code'))}
          {_kv('Grant scheme', h.get('grant_scheme'))}{_kv('Training type', (h.get('training_type') or '').title())}
          {_kv('Duration', _duration((prog or {}).get('days'), h.get('hours') or (prog or {}).get('hours')))}
          {_kv('Delivery', ((h.get('mode') or (prog or {}).get('mode') or '')).title())}
          {_kv('Venue / platform', place)}{_kv('Date(s)', dates)}{_kv('Time', when)}
          {_kv('Participants', f"{h.get('pax')} pax" if h.get('pax') else '')}
          {_kv('Trainer(s)', (prog or {}).get('trainers'))}</div>"""
    else:
        parties = f"""<div class="box"><div class="lbl">Prepared for</div><div class="party">{esc(company)}</div>
          {_kv('Attention', q.get('attention'))}{_kv('Address', q.get('address'))}
          {_kv('Phone', q.get('phone'))}{_kv('Email', q.get('email'))}</div>"""
        programme = ""

    # items
    rows = ""
    for n, (it, amt) in enumerate(zip(q.get("items") or [], t["lines"]), 1):
        claim = (f'<td><span class="claim {"y" if it.get("claimable") else "n"}">'
                 f'{"Claimable" if it.get("claimable") else "Not claimable"}</span></td>') if hrdc else ""
        rows += (f'<tr><td class="n">{n:02d}</td><td><div class="item-title">{esc(it.get("title"))}</div>'
                 + (f'<div class="item-desc">{esc(it.get("description"))}</div>' if it.get("description") else "")
                 + f'</td>{claim}<td class="r n">{esc(_qty(it.get("qty")))}</td><td class="r n">{rm(it.get("unit_price"))}</td>'
                 f'<td class="r n">{rm(amt)}</td></tr>')
    table = f"""<h2>{'Cost breakdown' if hrdc else 'Course / service'}</h2><table class="items">
      <tr><th>#</th><th>Item</th>{'<th>HRDC</th>' if hrdc else ''}<th class="r">Qty (pax)</th><th class="r">Unit price</th><th class="r">Amount</th></tr>
      {rows}</table>"""

    trows = f'<div class="trow"><span>Subtotal</span><span>{rm(t["subtotal"])}</span></div>'
    if t["discount"]:
        trows += f'<div class="trow"><span>Discount</span><span>- {rm(t["discount"])}</span></div>'
    if t["sst"]:
        trows += f'<div class="trow"><span>SST {t["sst_rate"]:g}%</span><span>{rm(t["sst"])}</span></div>'
    if t["legacy_tax"]:
        trows += f'<div class="trow"><span>Tax {q.get("tax_pct"):g}%</span><span>{rm(t["legacy_tax"])}</span></div>'
    if hrdc:
        trows += (f'<div class="trow hl"><span>HRD Corp claimable</span><span>{rm(t["claimable"])}</span></div>'
                  f'<div class="trow"><span>Not claimable (paid by employer)</span><span>{rm(t["non_claimable"])}</span></div>')
    totals_html = f'<div class="totals">{trows}<div class="grand"><span>Total</span><span>{rm(t["grand"])}</span></div></div>'

    notes = []
    if q.get("tier_note") and not hrdc:
        notes.append(s.get("tier_note"))
    terms = [f"This quotation is valid until {fdate(q.get('valid_until'))}."]
    if q.get("payment_terms"):
        terms.append(q["payment_terms"])
    if hrdc:
        scheme = h.get("grant_scheme") or "the applicable HRD Corp scheme"
        terms += [
            f"This programme is HRD Corp claimable under {scheme}. Programme ID: {(prog or {}).get('programme_code') or 'to be confirmed'}.",
            "Employer to submit the grant application via the HRD Corp portal before the training start date.",
            "Training proceeds only after grant approval, or with the employer's written confirmation to self-pay if the grant is not approved.",
            f"Fees are not claimable if attendance falls below {s.get('attendance_threshold')}%.",
        ]
        if not q.get("sst"):
            terms.append(s.get("hrdc_sst_note"))
    if q.get("notes"):
        terms.append(q["notes"])
    terms_html = ('<h2>Terms</h2><ul class="terms">' + "".join(f"<li>{esc(x)}</li>" for x in terms if x) + "</ul>"
                  + "".join(f'<div class="note">{esc(n)}</div>' for n in notes if n))
    page1 = f'<section class="sheet">{watermark}{head}{parties}{programme}{table}{totals_html}{terms_html}</section>'

    # page 2: course content
    blocks = ""
    plain = q.get("plain_language", True)
    if hrdc and prog:
        blocks += _outline(prog["title"], _duration(prog.get("days"), prog.get("hours")) + " · "
                           + (prog.get("mode") or "").title(), prog.get("sessions") or [], plain)
    else:
        seen = set()
        for it in q.get("items") or []:
            c = courses.get(it.get("course_id"))
            if c and c["id"] not in seen and c.get("sessions"):
                seen.add(c["id"])
                blocks += _outline(c["name"], "", c["sessions"], plain)
    if q.get("claude_block") and not hrdc:
        blocks += f'<div class="claude"><div class="lbl">Getting the most from Claude</div>{esc(s.get("claude_block"))}</div>'
    page2 = (f'<section class="sheet">{watermark}<h1 class="course-h" style="font-size:15pt;">Course content</h1>'
             f'<div class="course-meta">{esc(q.get("number"))} · {"simple overview" if plain else "detailed outline"}</div>'
             f'{blocks}</section>') if blocks else ""

    # HRDC attachments
    extra = ""
    if hrdc:
        names = [n.strip().lower() for n in ((prog or {}).get("trainers") or "").split(",") if n.strip()]
        profiles = ""
        for tr in s.get("trainers") or []:
            if tr.get("name", "").lower() in names or not names:
                profiles += (f'<div class="box" style="margin-bottom:10px;"><div class="party">{esc(tr.get("name"))}</div>'
                             f'{_kv("HRD Corp Trainer ID", tr.get("trainer_id") or "to be confirmed")}'
                             + (f'<div class="note">{esc(tr.get("summary"))}</div>' if tr.get("summary") else "")
                             + ("<ul class='terms' style='margin-top:4px;'>" + "".join(
                                 f"<li>{esc(x)}</li>" for x in tr.get("specialisations") or []) + "</ul>"
                                if tr.get("specialisations") else "") + "</div>")
        tp_ref = (f'<h2>Training provider registration</h2><div class="box mint">'
                  f'<div class="party">{esc(s.get("tp_name"))}</div>'
                  f'<div class="kv"><span>Status</span><span>HRD Corp certified Training Provider</span></div>'
                  f'{_kv("MyCoID / TP no.", s.get("tp_number"))}'
                  f'{_kv("Registration valid", f"{fdate(s.get("tp_valid_from"))} – {fdate(s.get("tp_valid_to"))}")}'
                  f'{_kv("Certificate ref.", s.get("tp_certificate_ref"))}</div>')
        people = h.get("participants") or []
        ppl = ""
        if people:
            ppl = ('<h2>Participants</h2><table class="people"><tr><th>#</th><th>Name</th><th>IC no.</th><th>Designation</th></tr>'
                   + "".join(f'<tr><td>{i}</td><td>{esc(p.get("name"))}</td><td class="mono">{esc(quote_store.mask_ic(p.get("ic")))}</td>'
                             f'<td>{esc(p.get("designation"))}</td></tr>' for i, p in enumerate(people, 1)) + "</table>")
        extra = (f'<section class="sheet">{watermark}<h1 class="course-h" style="font-size:15pt;">Trainer profile</h1>'
                 f'{profiles}{tp_ref}{ppl}</section>')

    fonts = f"<style>{FONT_FACES}</style>" if for_pdf else WEB_FONTS
    return (f'<!DOCTYPE html><html><head><meta charset="utf-8">{fonts}<style>{CSS}</style></head>'
            f'<body>{page1}{page2}{extra}</body></html>')


def _duration(days, hours) -> str:
    d, h = _qty(days), _qty(hours)
    parts = []
    if d:
        parts.append(f"{d} day" + ("" if d == "1" else "s"))
    if h:
        parts.append(f"{h} hours")
    return " · ".join(parts)


def _qty(v) -> str:
    try:
        f = float(v)
        return f"{f:g}"
    except (TypeError, ValueError):
        return str(v or "")


def _outline(title, meta, sessions, plain) -> str:
    rows = "".join(
        f'<div class="session"><div class="no">{i:02d}</div><div><div class="t">{esc(ss.get("title"))}</div>'
        f'<div class="d">{esc(ss.get("simple") if plain else (ss.get("detailed") or ss.get("simple")))}</div></div></div>'
        for i, ss in enumerate(sessions, 1))
    return f'<div class="course-h">{esc(title)}</div>' + (f'<div class="course-meta">{esc(meta)}</div>' if meta else "") + rows


def render_pdf(q: dict) -> bytes:
    from weasyprint import HTML
    return HTML(string=build_html(q, for_pdf=True), base_url=str(FONT_DIR)).write_pdf()
