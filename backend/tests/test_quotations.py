"""Saved quotations: create, edit, status, convert to invoice, never touch the ledger."""
import storage
from test_stamp import ORIGIN, app_client, boss, reader  # noqa: F401


def quote(c, **kw):
    body = {"contact": "Sinar Retail", "date": "2026-11-05", "valid_until": "2026-11-19",
            "items": [{"description": "AI for Automation", "qty": 3, "unit_price": 288},
                      {"description": "Vibe Coding", "qty": 1, "unit_price": 800}],
            "discount_pct": 10, "remarks": "Saturday sessions", "attention": "Ms Lim", **kw}
    r = c.post("/api/quotations", json=body, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()


def test_create_list_edit_and_never_touch_the_ledger(boss):
    before = len(storage.list_transactions())
    q = quote(boss)
    assert q["number"].startswith("QUO-") and q["status"] == "Sent"
    assert q["subtotal"] == 1664 and q["total"] == 1497.6            # 10% off
    assert any(x["id"] == q["id"] for x in boss.get("/api/state").json()["quotations"])
    assert len(storage.list_transactions()) == before
    r = boss.put(f"/api/quotations/{q['id']}", headers=ORIGIN, json={
        "contact": "Sinar Retail", "date": "2026-11-05", "valid_until": "2026-11-30", "tax_pct": 8,
        "items": [{"description": "Vibe Coding", "qty": 2, "unit_price": 800}]})
    assert r.status_code == 200 and r.json()["total"] == 1728 and r.json()["valid_until"] == "2026-11-30"
    assert boss.post("/api/quotations", headers=ORIGIN, json={"contact": "X", "date": "2026-11-05",
                                                                "items": []}).status_code == 422


def test_convert_to_invoice(boss):
    q = quote(boss, contact="Convert Me Sdn Bhd", tax_pct=8)
    r = boss.post(f"/api/quotations/{q['id']}/convert", headers=ORIGIN)
    assert r.status_code == 200, r.text
    inv, done = r.json()["invoice"], r.json()["quotation"]
    assert inv["number"].startswith("INV-") and inv["contact"] == "Convert Me Sdn Bhd"
    assert [i["description"] for i in inv["items"]] == ["AI for Automation", "Vibe Coding"]
    assert inv["discount_pct"] == 10 and inv["tax_pct"] == 8 and inv["status"] == "Pending"
    assert inv["reference_no"] == q["number"] and q["number"] in inv["remarks"]
    assert done["status"] == "Accepted" and done["invoice_id"] == inv["id"]
    assert boss.post(f"/api/quotations/{q['id']}/convert", headers=ORIGIN).status_code == 409
    assert boss.put(f"/api/quotations/{q['id']}", headers=ORIGIN, json={
        "contact": "x", "date": "2026-11-05", "items": [{"description": "a", "qty": 1, "unit_price": 1}]}).status_code == 409


def test_status_delete_and_permissions(boss, reader):
    q = quote(boss)
    assert boss.patch(f"/api/quotations/{q['id']}/status", json={"status": "Declined"},
                      headers=ORIGIN).json()["status"] == "Declined"
    assert boss.patch(f"/api/quotations/{q['id']}/status", json={"status": "Paid"}, headers=ORIGIN).status_code == 422
    assert reader.get("/api/quotations").status_code == 403          # Document Centre viewers see no finance
    assert reader.post("/api/quotations", json={}, headers=ORIGIN).status_code in (403, 422)
    assert boss.delete(f"/api/quotations/{q['id']}", headers=ORIGIN).status_code == 200
    assert storage.get_quotation(q["id"]) is None
