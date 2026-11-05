"""Quotation builder: Type A (Non-HRDC, QUO-) and Type B (HRDC claimable, QHR-)."""
from datetime import date, timedelta

import quote_store as qs
import storage
from test_stamp import ORIGIN, app_client, boss, staff, reader  # noqa: F401


def std(**kw):
    return {"qtype": "standard", "company": "Sinar Retail", "attention": "Ms Lim", "date": date.today().isoformat(),
            "validity_days": 30, "items": [
                {"kind": "course", "title": "AI for Automation", "qty": 3, "unit_price": 288},
                {"kind": "course", "title": "Vibe Coding from Scratch", "qty": 1, "unit_price": 800}], **kw}


def programme(status="Approved"):
    return next(p for p in qs.list_programmes() if p["status"] == status)


def hrdc(**kw):
    p = programme()
    soon = (date.today() + timedelta(days=30)).isoformat()
    return {"qtype": "hrdc", "company": "Pine Tree Sdn Bhd", "date": date.today().isoformat(),
            "items": [{"kind": "course", "title": p["title"], "qty": 5, "unit_price": p["fee_cap"], "claimable": True},
                      {"kind": "materials", "title": "Training materials", "qty": 5, "unit_price": 50, "claimable": True},
                      {"kind": "travel", "title": "Trainer travel", "qty": 1, "unit_price": 120, "claimable": False}],
            "hrdc": {"programme_id": p["id"], "pax": 5, "dates": [soon], "grant_scheme": "SBL-Khas",
                     "participants": [{"name": "Ali", "ic": "900101-01-1234", "designation": "Clerk"}]}, **kw}


def test_standard_quote_numbers_totals_and_ledger(boss):
    before = len(storage.list_transactions())
    r = boss.post("/api/quotes", json=std(sst=True, discount_rm=64), headers=ORIGIN)
    assert r.status_code == 200, r.text
    q = r.json()["quote"]
    assert q["number"].startswith("QUO-") and q["status"] == "Draft"
    assert q["valid_until"] == (date.today() + timedelta(days=30)).isoformat()
    t = q["totals"]
    assert t["subtotal"] == 1664 and t["discount"] == 64 and t["sst"] == 128 and t["grand"] == 1728
    assert len(storage.list_transactions()) == before                    # never touches the ledger
    assert any(x["id"] == q["id"] for x in boss.get("/api/state").json()["quotations"])


def test_number_is_editable_but_unique(boss):
    a = boss.post("/api/quotes", json=std(number="QUO-900"), headers=ORIGIN).json()["quote"]
    assert a["number"] == "QUO-900"
    assert boss.post("/api/quotes", json=std(number="quo-900"), headers=ORIGIN).status_code == 409


def test_hrdc_quote_claimable_split_and_masked_ic(boss):
    r = boss.post("/api/quotes", json=hrdc(), headers=ORIGIN)
    assert r.status_code == 200, r.text
    q = r.json()["quote"]
    assert q["number"].startswith("QHR-")
    t = q["totals"]
    fee = programme()["fee_cap"]
    assert t["claimable"] == 5 * fee + 250 and t["non_claimable"] == 120 and t["grand"] == 5 * fee + 370
    assert q["hrdc"]["participants"][0]["ic"] == "XXXXXX-XX-1234"         # full IC never stored
    assert "900101" not in str(boss.get(f"/api/quotes/{q['id']}").json())


def test_hrdc_rules(boss):
    p = programme()
    over = hrdc()
    over["items"][0]["unit_price"] = p["fee_cap"] + 100
    r = boss.post("/api/quotes", json={**over, "status": "Sent"}, headers=ORIGIN)
    assert r.status_code == 422 and "above the approved" in r.json()["detail"]
    # a pending programme can be drafted but not sent, and the PDF is watermarked
    pend = boss.post("/api/quotes-admin/programmes", headers=ORIGIN, json={
        "title": "Test Pending Programme", "fee_cap": 900, "status": "Pending"}).json()
    body = hrdc()
    body["hrdc"]["programme_id"] = pend["id"]
    body["items"][0].update(title=pend["title"], unit_price=pend["fee_cap"])
    d = boss.post("/api/quotes", json=body, headers=ORIGIN)
    assert d.status_code == 200
    assert boss.patch(f"/api/quotes/{d.json()['quote']['id']}/status", json={"status": "Sent"},
                      headers=ORIGIN).status_code == 422
    html = boss.post("/api/quotes/preview", json=body, headers=ORIGIN).json()["html"]
    assert "SUBJECT TO HRD CORP APPROVAL" in html
    # warnings: lead time and TP validity
    late = hrdc()
    late["hrdc"]["dates"] = [(date.today() + timedelta(days=2)).isoformat(), "2027-12-01"]
    w = " ".join(boss.post("/api/quotes/preview", json=late, headers=ORIGIN).json()["check"]["warnings"])
    assert "lead time" in w and "TP registration ends" in w


def test_preview_pages_and_content(boss):
    body = std(claude_block=True, tier_note=True)
    py = next(c for c in qs.list_courses() if c["name"] == "Python for Beginners")
    body["items"].append({"kind": "course", "course_id": py["id"], "title": "Python for Beginners", "qty": 1, "unit_price": 900})
    html = boss.post("/api/quotes/preview", json=body, headers=ORIGIN).json()["html"]
    assert "Course content" in html and "Data structures" in html and "Claude comes in three ways" in html
    assert "For 2 pax add RM 388" in html
    assert "Jalan Mutiara Emas" not in html                                   # address hidden by default
    assert "Jalan Mutiara Emas" in boss.post("/api/quotes/preview", json={**body, "show_address": True},
                                             headers=ORIGIN).json()["html"]
    detailed = boss.post("/api/quotes/preview", json={**body, "plain_language": False}, headers=ORIGIN).json()["html"]
    assert "comprehensions" in detailed
    hr = boss.post("/api/quotes/preview", json=hrdc(), headers=ORIGIN).json()["html"]
    assert "HRD Corp claimable under SBL-Khas" in hr and "Trainer profile" in hr and "76085" in hr
    assert "001129" not in hr                                                 # trainer IC never appears


def test_duplicate_status_and_convert(boss):
    q = boss.post("/api/quotes", json=hrdc(), headers=ORIGIN).json()["quote"]
    dup = boss.post(f"/api/quotes/{q['id']}/duplicate", headers=ORIGIN).json()["quote"]
    assert dup["number"] != q["number"] and dup["status"] == "Draft" and dup["items"] == q["items"]
    g = boss.patch(f"/api/quotes/{q['id']}/grant", json={"grant_status": "Grant approved", "grant_id": "GA-123"},
                   headers=ORIGIN)
    assert g.status_code == 200 and g.json()["hrdc"]["grant_id"] == "GA-123"
    r = boss.post(f"/api/quotes/{q['id']}/convert", headers=ORIGIN)
    assert r.status_code == 200, r.text
    inv = r.json()["invoice"]
    assert inv["reference_no"] == "GA-123" and "GA-123" in inv["remarks"]
    assert round(sum(i["qty"] * i["unit_price"] for i in inv["items"]), 2) == q["totals"]["grand"]
    assert r.json()["quote"]["status"] == "Accepted" and r.json()["quote"]["hrdc"]["grant_status"] == "Invoiced"
    assert boss.post(f"/api/quotes/{q['id']}/convert", headers=ORIGIN).status_code == 409
    assert boss.put(f"/api/quotes/{q['id']}", json=hrdc(), headers=ORIGIN).status_code == 409


def test_permissions_and_settings(boss, staff, reader):
    assert reader.get("/api/quotes").status_code == 403
    assert staff.get("/api/quotes").status_code == 200
    assert staff.put("/api/quotes-admin/settings", json={"tp_number": "X"}, headers=ORIGIN).status_code == 403
    r = boss.put("/api/quotes-admin/settings", json={"tp_number": "TP-0001", "lead_days": 10, "bogus": 1}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["tp_number"] == "TP-0001" and "bogus" not in r.json()
    assert staff.put(f"/api/quotes-admin/programmes/{programme()['id']}", json={"title": "x"},
                     headers=ORIGIN).status_code == 403


def test_old_style_quotation_still_listed(boss):
    storage.insert_quotation({"contact": "Telegram Co", "date": "2026-11-01", "valid_until": "2026-11-15",
                              "discount_pct": 10}, [{"description": "Vibe Coding", "qty": 1, "unit_price": 800}])
    q = next(x for x in boss.get("/api/quotes").json() if x["contact"] == "Telegram Co")
    assert q["items"][0]["title"] == "Vibe Coding" and q["total"] == 720 and q["qtype"] == "standard"


def _fake_weasyprint(monkeypatch):
    """WeasyPrint only exists in the server image; stand in a one-page PDF per HTML."""
    import sys
    import types
    from test_stamp import make_pdf

    class HTML:
        def __init__(self, string, base_url=None):
            self.n = max(1, string.count('<section class="sheet"'))

        def write_pdf(self):
            return make_pdf(self.n, text="GENERATED")
    monkeypatch.setitem(sys.modules, "weasyprint", types.SimpleNamespace(HTML=HTML))


def test_official_pdfs_are_attached_to_hrdc_quotes(boss, staff, monkeypatch):
    import io
    from pypdf import PdfReader
    from test_stamp import make_pdf
    _fake_weasyprint(monkeypatch)
    p = programme()
    up = lambda kind, ref, pages, who=boss: who.post(
        f"/api/quotes-admin/attachments?kind={kind}&ref={ref}&filename={kind}.pdf",
        content=make_pdf(pages, text=kind.upper()), headers={**ORIGIN, "Content-Type": "application/pdf"})
    assert up("tp", "", 1, staff).status_code == 403                          # director only
    assert up("tp", "", 1).status_code == 200
    assert up("trainer", "Natasya Khoo", 2).status_code == 200
    assert up("programme", p["id"], 2).status_code == 200
    assert up("trainer", "Nobody", 1).status_code == 404
    assert boss.post("/api/quotes-admin/attachments?kind=tp", content=b"not a pdf" * 50,
                     headers={**ORIGIN, "Content-Type": "application/pdf"}).status_code == 400
    # settings can't point attachments at other stored files
    boss.put("/api/quotes-admin/settings", json={"attachments": {"tp_certificate": {"key": "x" * 32 + ".pdf"}}},
             headers=ORIGIN)
    assert qs.get_settings()["attachments"]["tp_certificate"]["name"] == "tp.pdf"

    body = hrdc()
    html = boss.post("/api/quotes/preview", json=body, headers=ORIGIN).json()["html"]
    assert "Attached official documents" in html and "programme.pdf" in html and "trainer.pdf" in html
    q = boss.post("/api/quotes", json=body, headers=ORIGIN).json()["quote"]
    pdf = boss.get(f"/api/quotes/{q['id']}/pdf")
    assert pdf.status_code == 200
    pages = [pg.extract_text() for pg in PdfReader(io.BytesIO(pdf.content)).pages]
    # quote page, official outline (2), trainer profile (2), TP certificate (1), participants page
    order = [("GENERATED" in t and "GENERATED") or next((k for k in ("PROGRAMME", "TRAINER", "TP") if k in t), "?")
             for t in pages]
    assert order == ["GENERATED", "PROGRAMME", "PROGRAMME", "TRAINER", "TRAINER", "TP", "GENERATED"], order
    assert boss.get(f"/api/quotes-admin/attachments/file?kind=programme&ref={p['id']}").content[:5] == b"%PDF-"
    assert boss.delete("/api/quotes-admin/attachments?kind=tp", headers=ORIGIN).status_code == 200
    assert qs.get_settings()["attachments"]["tp_certificate"] is None
