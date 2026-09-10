"""
Renders receipts, payment/cash vouchers, and invoices to PDF bytes using
WeasyPrint, with the same letterhead and layout language as the CmPro
dashboard mockup (dark IDE mint accent, Space Grotesk headings).
"""
def _render(html: str) -> bytes:
    # Imported lazily so the app can boot (and the dashboard/API run) on a
    # machine without the native Pango/Cairo libs — only PDF calls need them.
    from weasyprint import HTML
    return HTML(string=html).write_pdf()


BUSINESS_NAME = "Code N Code Solution"
BUSINESS_SUB = "Reg. No. AS0511861-M · 1st Floor, Room 16/117, Jalan Mutiara Emas 10/19, Taman Mount Austin, 81100 Johor Bahru, Johor"

BASE_CSS = """
@page { size: A5; margin: 18mm; }
body { font-family: 'DejaVu Sans', sans-serif; color: #15141a; font-size: 11pt; }
.brand { display:flex; align-items:center; gap:10px; margin-bottom:18px; }
.brand .mark { width:34px; height:34px; border-radius:9px; background:#0a0e14; color:#00dcb4;
  display:flex; align-items:center; justify-content:center; font-weight:bold; font-size:15pt; }
.brand .name { font-weight:bold; font-size:14pt; }
.brand .sub { font-size:8pt; color:#666; margin-top:2px; }
.title { text-align:center; font-weight:bold; font-size:11pt; letter-spacing:1px;
  text-transform:uppercase; color:#666; margin:18px 0 4px 0; }
.docno { text-align:center; font-family:monospace; font-size:9pt; color:#666; margin-bottom:16px; }
table.rows { width:100%; border-collapse:collapse; margin-bottom:16px; }
table.rows td { padding:6px 0; border-bottom:1px dashed #ddd; font-size:10pt; }
table.rows td.label { color:#888; width:40%; }
table.rows td.value { text-align:right; font-weight:bold; }
.amount-box { text-align:center; background:#f2efe8; border-radius:10px; padding:14px; margin:16px 0; }
.amount-box .lbl { font-size:8pt; color:#888; text-transform:uppercase; letter-spacing:1px; }
.amount-box .val { font-size:20pt; font-weight:bold; margin-top:4px; }
.foot { text-align:center; font-size:8pt; color:#888; margin-top:18px; line-height:1.5; }
.sig-row { display:flex; margin-top:36px; }
.sig-box { flex:1; text-align:center; margin:0 10px; }
.sig-line { border-top:1px solid #333; padding-top:4px; font-size:8pt; color:#888; }
.stamp { display:inline-block; font-size:9pt; font-weight:bold; padding:4px 10px; border-radius:20px;
  text-transform:uppercase; letter-spacing:0.5px; }
.stamp.pv { background:#ffb7a6; color:#5c2213; }
.stamp.cv { background:#d7f26d; color:#3a4408; }
"""


def _header_html():
    return f"""
    <div class="brand">
      <div class="mark">C</div>
      <div><div class="name">{BUSINESS_NAME}</div><div class="sub">{BUSINESS_SUB}</div></div>
    </div>
    """


def render_receipt_pdf(receipt_no: str, date: str, payer: str, description: str, amount: float) -> bytes:
    html = f"""
    <html><head><style>{BASE_CSS}</style></head><body>
      {_header_html()}
      <div class="title">Official Receipt</div>
      <div class="docno">{receipt_no}</div>
      <table class="rows">
        <tr><td class="label">Date</td><td class="value">{date}</td></tr>
        <tr><td class="label">Received From</td><td class="value">{payer}</td></tr>
        <tr><td class="label">Description</td><td class="value">{description}</td></tr>
        <tr><td class="label">Payment Method</td><td class="value">Bank Transfer</td></tr>
      </table>
      <div class="amount-box">
        <div class="lbl">Amount Received</div>
        <div class="val">RM {amount:,.2f}</div>
      </div>
      <div class="foot">This receipt is computer-generated and confirms payment received.<br>Thank you for learning with Codencode.</div>
    </body></html>
    """
    return _render(html)


def render_voucher_pdf(voucher_no: str, voucher_type: str, date: str, party: str,
                        description: str, category: str, amount: float) -> bytes:
    is_payment = voucher_type == "payment"
    stamp_class = "pv" if is_payment else "cv"
    title = "Payment Voucher" if is_payment else "Cash Voucher"
    party_label = "Paid To" if is_payment else "Received From"
    amount_label = "Amount Paid" if is_payment else "Amount Received"
    html = f"""
    <html><head><style>{BASE_CSS}</style></head><body>
      <div class="brand">
        <div class="mark">C</div>
        <div><div class="name">{BUSINESS_NAME}</div><div class="sub">{BUSINESS_SUB}</div></div>
        <span class="stamp {stamp_class}" style="margin-left:auto;">{title}</span>
      </div>
      <div class="docno">{voucher_no}</div>
      <table class="rows">
        <tr><td class="label">Date</td><td class="value">{date}</td></tr>
        <tr><td class="label">{party_label}</td><td class="value">{party}</td></tr>
        <tr><td class="label">Description</td><td class="value">{description}</td></tr>
        <tr><td class="label">Account / Category</td><td class="value">{category}</td></tr>
      </table>
      <div class="amount-box">
        <div class="lbl">{amount_label}</div>
        <div class="val">RM {amount:,.2f}</div>
      </div>
      <div class="sig-row">
        <div class="sig-box"><div class="sig-line">Prepared By</div></div>
        <div class="sig-box"><div class="sig-line">Approved By</div></div>
      </div>
    </body></html>
    """
    return _render(html)


def render_invoice_pdf(invoice_no: str, contact: str, date: str, due: str, amount: float) -> bytes:
    html = f"""
    <html><head><style>{BASE_CSS}</style></head><body>
      {_header_html()}
      <div class="title">Invoice</div>
      <div class="docno">{invoice_no}</div>
      <table class="rows">
        <tr><td class="label">Invoice Date</td><td class="value">{date}</td></tr>
        <tr><td class="label">Due Date</td><td class="value">{due}</td></tr>
        <tr><td class="label">Bill To</td><td class="value">{contact}</td></tr>
      </table>
      <div class="amount-box">
        <div class="lbl">Amount Due</div>
        <div class="val">RM {amount:,.2f}</div>
      </div>
      <div class="foot">Please make payment by the due date above. Thank you for your business.</div>
    </body></html>
    """
    return _render(html)
