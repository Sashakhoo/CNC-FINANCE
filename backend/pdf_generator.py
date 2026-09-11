"""
Renders receipts, payment/cash vouchers, and invoices to PDF bytes with
WeasyPrint, matching the house style already used by learn.codencode.my's
documents: codencode.my wordmark, monospace body, thick mint rule under the
letterhead, mint section underlines, a mint "Balance Due" bar, and the
standard PAYMENT / footer block.

Public API (unchanged — the Telegram bot and the dashboard API both call
these):
    render_receipt_pdf(receipt_no, date, payer, description, amount)
    render_voucher_pdf(voucher_no, voucher_type, date, party, description, category, amount)
    render_invoice_pdf(invoice_no, contact, date, due, amount)
"""
import base64
import html as _html
import pathlib
from datetime import date as _date, datetime


def _render(html: str) -> bytes:
    # Imported lazily so the app can boot (and the dashboard/API run) on a
    # machine without the native Pango/Cairo libs — only PDF calls need them.
    from weasyprint import HTML
    return HTML(string=html).write_pdf()


def _logo_data_uri() -> str:
    p = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "assets" / "logo-wordmark.png"
    try:
        return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode("ascii")
    except OSError:
        return ""


LOGO_URI = _logo_data_uri()

# --- business identity (from the SSM extract) --------------------------------
BUSINESS_NAME = "CODE N CODE SOLUTION"
BUSINESS_SSM = "SSM / Business Registration No.: 202603072017 (AS0511861-M)"
BUSINESS_ADDRESS = [
    "1st Floor - Room 16, 117",
    "Jalan Mutiara Emas 10/19",
    "Taman Mount Austin",
    "81100 Johor Bahru",
    "Johor Darul Ta'zim, Malaysia",
]
BUSINESS_CONTACT = "0196811628 • codencodemy@gmail.com"
BUSINESS_SITE = "codencode.my"
BANK = {
    "Bank": "MAYBANK",
    "Account Name": "CODE N CODE SOLUTION",
    "Account No.": "5512 7610 6077",
}

MINT = "#12d69a"
MINT_DARK = "#0a8f68"
INK = "#15141a"

BASE_CSS = f"""
@page {{ size: A4; margin: 40px 46px 44px 46px; }}
* {{ box-sizing: border-box; }}
body {{ font-family: 'DejaVu Sans Mono', 'Courier New', monospace; color: {INK};
        font-size: 9pt; line-height: 1.5; }}
.head {{ display: flex; justify-content: space-between; align-items: flex-start; }}
.head .logo {{ height: 22px; margin-bottom: 10px; }}
.biz-name {{ font-weight: bold; font-size: 11pt; letter-spacing: 0.5px; }}
.biz-line {{ font-size: 7.5pt; color: #555; }}
.doc-side {{ text-align: right; min-width: 210px; }}
.doc-type {{ font-weight: bold; font-size: 20pt; letter-spacing: 3px; }}
.doc-no {{ font-weight: bold; font-size: 10pt; margin-top: 6px; }}
.doc-meta {{ font-size: 8pt; color: #555; margin-top: 4px; }}
.status {{ display: inline-block; margin-top: 6px; padding: 2px 10px; border-radius: 100px;
          font-size: 7.5pt; font-weight: bold; letter-spacing: 0.5px; }}
.status.paid {{ background: {MINT}; color: #063d2c; }}
.status.pending {{ background: #ffe08a; color: #4a3402; }}
.rule {{ height: 6px; background: {INK}; margin: 14px 0 18px; }}
.rule.mint {{ background: {MINT}; }}
h2.sec {{ font-size: 8pt; font-weight: bold; letter-spacing: 1px; margin: 20px 0 6px;
          padding-bottom: 5px; border-bottom: 2px solid {MINT}; }}
.party-name {{ font-weight: bold; font-size: 10.5pt; margin-bottom: 2px; }}
.muted {{ color: #555; }}
table.items {{ width: 100%; border-collapse: collapse; margin-top: 4px; }}
table.items th {{ background: {MINT}; color: #063d2c; text-align: left; padding: 7px 10px;
                  font-size: 8pt; letter-spacing: 0.5px; }}
table.items th.r, table.items td.r {{ text-align: right; }}
table.items td {{ padding: 9px 10px; border-bottom: 1px solid #e6e2d6; vertical-align: top; }}
.subnote {{ color: #555; font-size: 8pt; margin-top: 6px; }}
.totals {{ margin-top: 10px; }}
.totals .row {{ display: flex; justify-content: space-between; padding: 6px 10px; font-size: 9pt; }}
.totals .row.grand {{ font-weight: bold; border-top: 1px solid #cfcabb; }}
.totals .row.due {{ background: {MINT}; color: #063d2c; font-weight: bold; margin-top: 4px;
                    padding: 9px 10px; }}
.pay-grid {{ display: grid; grid-template-columns: 120px 1fr; row-gap: 3px; font-size: 8.5pt; }}
.pay-grid b {{ font-weight: bold; }}
.terms {{ font-size: 8pt; color: #555; margin-top: 12px; }}
.sig-row {{ display: flex; gap: 40px; margin-top: 46px; }}
.sig {{ flex: 1; border-top: 1px solid {INK}; padding-top: 5px; font-size: 8pt; color: #555; }}
.foot {{ margin-top: 26px; padding-top: 12px; border-top: 1px solid #e6e2d6;
         text-align: center; font-size: 7.5pt; color: #777; line-height: 1.7; }}
.foot .strong {{ color: {INK}; font-weight: bold; }}
"""


def _esc(v) -> str:
    return _html.escape(str(v if v is not None else ""))


def _fmt_date(v: str) -> str:
    for f in ("%Y-%m-%d", "%d/%m/%Y", "%d %B %Y"):
        try:
            return datetime.strptime(str(v), f).strftime("%d %B %Y")
        except (ValueError, TypeError):
            pass
    return _esc(v)


def _rm(n) -> str:
    return f"RM {float(n):,.2f}"


def _header(doc_type: str, doc_no: str, meta_rows: list, status: tuple | None) -> str:
    addr = "<br>".join(_esc(l) for l in BUSINESS_ADDRESS)
    logo = f'<img class="logo" src="{LOGO_URI}">' if LOGO_URI else ""
    meta = "".join(f"<div>{_esc(k)}: <b>{_esc(v)}</b></div>" for k, v in meta_rows)
    status_html = ""
    if status:
        label, cls = status
        status_html = f'<div class="doc-meta">Status: <span class="status {cls}">{_esc(label)}</span></div>'
    return f"""
    <div class="head">
      <div>
        {logo}
        <div class="biz-name">{_esc(BUSINESS_NAME)}</div>
        <div class="biz-line">{_esc(BUSINESS_SSM)}</div>
        <div class="biz-line">{addr}</div>
        <div class="biz-line">{_esc(BUSINESS_CONTACT)}</div>
        <div class="biz-line">{_esc(BUSINESS_SITE)}</div>
      </div>
      <div class="doc-side">
        <div class="doc-type">{_esc(doc_type)}</div>
        <div class="doc-no">{_esc(doc_no)}</div>
        <div class="doc-meta">{meta}</div>
        {status_html}
      </div>
    </div>
    <div class="rule"></div>
    """


def _party_block(label: str, name: str, lines: list) -> str:
    extra = "".join(f'<div class="muted">{_esc(l)}</div>' for l in lines if l)
    return f'<h2 class="sec">{_esc(label)}</h2><div class="party-name">{_esc(name)}</div>{extra}'


def _items_table(rows: list, subnotes: list) -> str:
    body = ""
    for desc, qty, unit, amt in rows:
        body += (f'<tr><td>{_esc(desc)}</td><td class="r">{_esc(qty)}</td>'
                 f'<td class="r">{_rm(unit)}</td><td class="r">{_rm(amt)}</td></tr>')
    notes = "".join(f'<div class="subnote">{_esc(n)}</div>' for n in subnotes if n)
    return f"""
    <h2 class="sec">COURSE / SERVICE</h2>
    <table class="items">
      <tr><th>Description</th><th class="r">Qty</th><th class="r">Unit Price</th><th class="r">Amount</th></tr>
      {body}
    </table>
    {notes}
    """


def _totals(subtotal: float, total: float, paid: float | None, due_label: str, due: float | None) -> str:
    rows = [f'<div class="row"><span>Subtotal:</span><span>{_rm(subtotal)}</span></div>',
            f'<div class="row grand"><span>Total:</span><span>{_rm(total)}</span></div>']
    if paid is not None:
        rows.append(f'<div class="row"><span>Amount Paid:</span><span>{_rm(paid)}</span></div>')
    if due is not None:
        rows.append(f'<div class="row due"><span>{_esc(due_label)}</span><span>{_rm(due)}</span></div>')
    return f'<h2 class="sec">AMOUNT</h2><div class="totals">{"".join(rows)}</div>'


def _payment_block(reference: str) -> str:
    cells = "".join(f"<b>{_esc(k)}:</b><span>{_esc(v)}</span>" for k, v in BANK.items())
    cells += f'<b>Reference:</b><span>{_esc(reference)}</span>'
    return f'<h2 class="sec">PAYMENT</h2><div class="pay-grid">{cells}</div>'


def _footer(doc_no: str, extra_terms: str = "") -> str:
    today = _date.today().strftime("%d %B %Y")
    return f"""
    <div class="terms">
      {extra_terms}
      <div><b>Payment Terms:</b> Payment is due within 14 days from the issue date.</div>
      <div><b>Proof of Payment:</b> Kindly send your payment receipt via WhatsApp or email after payment.</div>
    </div>
    <div class="foot">
      <div><span class="strong">{_esc(BUSINESS_NAME)}</span> • SSM No.: 202603072017 (AS0511861-M)</div>
      <div>{_esc(BUSINESS_SITE)} • codencodemy@gmail.com • 0196811628</div>
      <div>Thank you for learning with us!</div>
      <div><i>This is a computer-generated document. No signature is required.</i></div>
      <div>{_esc(doc_no)} • Generated {today}</div>
    </div>
    """


def _page(*sections: str) -> bytes:
    body = "".join(sections)
    return _render(f"<html><head><meta charset='utf-8'><style>{BASE_CSS}</style></head>"
                   f"<body>{body}</body></html>")


# --- public API -------------------------------------------------------------

def render_receipt_pdf(receipt_no: str, date: str, payer: str, description: str, amount: float) -> bytes:
    d = _fmt_date(date)
    return _page(
        _header("RECEIPT", receipt_no,
                [("Issued", d), ("Date Paid", d)], ("PAID", "paid")),
        _party_block("BILL TO", payer or "—", []),
        _items_table([(description, 1, amount, amount)],
                     [f"Payment Method: Bank Transfer", f"Date Paid: {d}"]),
        _totals(amount, amount, amount, "Balance Due:", 0.0),
        _payment_block(receipt_no),
        _footer(receipt_no),
    )


def render_invoice_pdf(invoice_no: str, contact: str, date: str, due: str, amount: float,
                       description: str = None, status: str = "Pending") -> bytes:
    paid = (status or "").lower() == "paid"
    status_pill = ("PAID", "paid") if paid else ("PENDING", "pending")
    return _page(
        _header("INVOICE", invoice_no,
                [("Issued", _fmt_date(date)), ("Due", _fmt_date(due))], status_pill),
        _party_block("BILL TO", contact or "—", []),
        _items_table([(description or "Course / consulting services", 1, amount, amount)], []),
        _totals(amount, amount, amount if paid else 0.0, "Balance Due:", 0.0 if paid else amount),
        _payment_block(invoice_no),
        _footer(invoice_no),
    )


def render_voucher_pdf(voucher_no: str, voucher_type: str, date: str, party: str,
                       description: str, category: str, amount: float) -> bytes:
    is_payment = voucher_type == "payment"
    doc_type = "PAYMENT VOUCHER" if is_payment else "CASH VOUCHER"
    party_label = "PAID TO" if is_payment else "RECEIVED FROM"
    due_label = "Amount Paid:" if is_payment else "Amount Received:"
    sig = ""
    if is_payment:
        sig = ('<div class="sig-row"><div class="sig">Prepared By</div>'
               '<div class="sig">Approved By</div></div>')
    return _page(
        _header(doc_type, voucher_no, [("Date", _fmt_date(date))], None),
        _party_block(party_label, party or "—", [f"Account / Category: {category}"]),
        _items_table([(description, 1, amount, amount)], []),
        _totals(amount, amount, None, due_label, amount),
        _payment_block(voucher_no) if not is_payment else "",
        sig,
        _footer(voucher_no),
    )
