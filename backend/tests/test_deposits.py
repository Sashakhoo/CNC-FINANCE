"""Invoice deposits: Mark Paid posts only the balance, PDFs show it, and the
one-off Oct 2026 correction (Yap Wee Lee / Teh Boon Kian)."""
import migrations
import storage
from test_stamp import ORIGIN, app_client, boss  # noqa: F401


def make_invoice(c, contact, amount, **kw):
    r = c.post("/api/invoices", json={"contact": contact, "date": "2026-10-01", "due": "2026-10-31",
                                      "amount": amount, **kw}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()


def cash_in_for(number):
    return [t for t in storage.list_transactions() if number in t["description"] and t["type"] == "in"]


def test_deposit_then_paid_posts_only_the_balance(boss):
    inv = make_invoice(boss, "Deposit Tester", 750)
    r = boss.post(f"/api/invoices/{inv['id']}/deposit", json={"amount": 100, "date": "2026-10-09"}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert r.json()["deposit"] == 100 and r.json()["status"] == "Deposit"
    # a second part-payment adds up; paying more than is owed is refused
    assert boss.post(f"/api/invoices/{inv['id']}/deposit", json={"amount": 50}, headers=ORIGIN).json()["deposit"] == 150
    bad = boss.post(f"/api/invoices/{inv['id']}/deposit", json={"amount": 700}, headers=ORIGIN)
    assert bad.status_code == 422 and "still owed" in bad.json()["detail"]
    assert boss.post(f"/api/invoices/{inv['id']}/pay", headers=ORIGIN).status_code == 200
    rows = cash_in_for(inv["number"])
    assert sorted(t["amount"] for t in rows) == [50, 100, 600]          # 100 + 50 + 600 = 750, not 900
    assert sum(t["amount"] for t in rows) == 750
    assert any("balance after RM150 deposit" in t["description"] for t in rows)
    # on a paid invoice a deposit can't exceed what the invoice was for
    assert boss.post(f"/api/invoices/{inv['id']}/deposit", json={"amount": 700}, headers=ORIGIN).status_code == 422


def test_deposit_already_entered_by_hand_is_not_posted_twice(boss):
    inv = make_invoice(boss, "Hand Entered", 750)
    r = boss.post(f"/api/invoices/{inv['id']}/deposit", json={"amount": 100, "post_to_ledger": False}, headers=ORIGIN)
    assert r.json()["deposit"] == 100
    boss.post(f"/api/invoices/{inv['id']}/pay", headers=ORIGIN)
    assert [t["amount"] for t in cash_in_for(inv["number"])] == [650]


def test_paid_uses_total_after_discount_and_tax(boss):
    inv = make_invoice(boss, "Discount Tester", 0, discount_pct=10,
                       items=[{"description": "Python", "qty": 2, "unit_price": 500}])
    boss.post(f"/api/invoices/{inv['id']}/pay", headers=ORIGIN)
    assert [t["amount"] for t in cash_in_for(inv["number"])] == [900]


def test_invoice_totals_show_deposit_and_balance():
    import pdf_generator
    html = pdf_generator._totals(750, 750, 100, "Balance Due:", 650, paid_label="Less: Deposit Paid:")
    assert "Less: Deposit Paid:" in html and "650" in html and "750" in html


def test_oct_2026_correction(boss):
    """Recreate the mistake as it happened, then run the one-off fix."""
    a = make_invoice(boss, "Yap Wee Lee", 750)
    b = make_invoice(boss, "Teh Boon Kian", 750)
    with storage.get_conn() as conn:
        conn.execute("UPDATE invoices SET number = 'INV-1133' WHERE id = ?", (a["id"],))
        conn.execute("UPDATE invoices SET number = 'INV-1132' WHERE id = ?", (b["id"],))
        conn.execute("DELETE FROM _migrations WHERE id = '2026-10-fix-vibe-coding-deposits'")
    storage.insert_transaction(date="2026-10-09", description="Vibe Coding deposit — Yap Wee Lee (ref 01979)",
                               tx_type="in", category="Course Revenue", amount=200, payer_payee="Yap Wee Lee")
    boss.post(f"/api/invoices/{a['id']}/pay", headers=ORIGIN)       # deposit 0 -> posts 750, like the old code
    boss.post(f"/api/invoices/{b['id']}/pay", headers=ORIGIN)
    before = sum(t["amount"] for t in cash_in_for("INV-113")) + 200
    assert before == 1700

    migrations._fix_vibe_coding_deposits_2026_10()
    yap, teh = cash_in_for("INV-1133"), cash_in_for("INV-1132")
    assert [t["amount"] for t in yap] == [650] and "RM100 deposit paid 9 Oct" in yap[0]["description"]
    assert [t["amount"] for t in teh] == [650] and "paid by Yap Wee Lee" in teh[0]["description"]
    dep = [t for t in storage.list_transactions() if t["description"].startswith("Vibe Coding deposit")]
    assert dep[0]["description"] == "Vibe Coding deposit — Yap Wee Lee RM100 + Teh Boon Kian RM100 (ref 01979)"
    assert sum(t["amount"] for t in yap + teh) + dep[0]["amount"] == 1500
    assert storage.get_invoice(a["id"])["deposit"] == 100 and storage.get_invoice(b["id"])["deposit"] == 100

    # running it again changes nothing
    with storage.get_conn() as conn:
        conn.execute("DELETE FROM _migrations WHERE id = '2026-10-fix-vibe-coding-deposits'")
    migrations._fix_vibe_coding_deposits_2026_10()
    assert [t["amount"] for t in cash_in_for("INV-1133")] == [650]


def test_paid_invoice_totals_split_deposit_and_balance():
    import pdf_generator
    html = pdf_generator._totals(750, 750, 750, "Balance Due:", 0,
                                 paid_rows=[("Deposit Paid:", 100), ("Balance Paid:", 650)])
    assert "Deposit Paid:" in html and "Balance Paid:" in html and "Amount Paid" not in html


def test_deposit_on_already_paid_invoice_takes_it_off_the_cash_in(boss):
    """The INV-1133 situation: paid in full at RM750 though RM100 had come in
    earlier as its own entry. Recording the deposit corrects the entry."""
    inv = make_invoice(boss, "Already Paid", 750)
    boss.post(f"/api/invoices/{inv['id']}/pay", headers=ORIGIN)
    assert [t["amount"] for t in cash_in_for(inv["number"])] == [750]
    r = boss.post(f"/api/invoices/{inv['id']}/deposit", json={"amount": 100}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["deposit"] == 100 and out["status"] == "Paid"
    assert out["adjusted"]["from"] == 750 and out["adjusted"]["to"] == 650
    rows = cash_in_for(inv["number"])
    assert [t["amount"] for t in rows] == [650] and "RM100 deposit received separately" in rows[0]["description"]
    assert boss.post(f"/api/invoices/{inv['id']}/deposit", json={"amount": 700}, headers=ORIGIN).status_code == 422
