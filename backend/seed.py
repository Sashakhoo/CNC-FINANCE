"""
One-time historical seed: the 5 months (Apr–Aug 2026) of Maybank Islamic
transactions reconciled line-by-line from the bank statements. This is the
same data that used to be hardcoded into frontend/dashboard.html.

Runs automatically on startup only when the transactions table is empty
(see storage.is_empty).

Reclassified per the owner (Sep 2026):
  - Gao Carey Yueming RM6,000  -> Course Revenue (Python + ML, Vanessa & Henry)
  - Lim Ban Soon      RM1,549  -> Course Revenue (Python Fundamentals)
  - Foon Yew / "NSJB" RM174/522 -> Course Revenue (Foon Yew evening school)
  - all former "Consulting Revenue" rows split into Course Revenue
    (Vibe Coding / Python: Firdaus, Haifa, Restoran Tong #156, CC Crest #117)
    or the new Workshop Revenue category ("AI for ..." / AI Automation:
    Koh Wen Han, Ooi Kah Seong, Restoran Tong #157, Constance).
    See migrations.py for the same fix applied to already-seeded databases.
Still bucketed generically (not confirmed): Khor Yee Ran RM150 in,
Muhamad Afiq Omar RM150 out.
"""
import storage

# (date, description, type, category, amount, payer_or_payee)
TRANSACTIONS = [
    ("2026-08-30", "Teacher payment — Tan Rou Ka (Vibe Coding, BJ Eng)", "out", "Payroll", 240.00, "Tan Rou Ka"),
    ("2026-08-29", "Balance transfer — Wong Yoke Soon", "out", "Other Expense", 12.00, "Wong Yoke Soon"),
    ("2026-08-28", "Rental — Havona Management (September)", "out", "Rental", 336.00, "Havona Management"),
    ("2026-08-25", "Invoice #159 — Muhammad Firdaus", "in", "Course Revenue", 1350.00, "Muhammad Firdaus"),
    ("2026-08-25", "Payment gateway fee — Bayarcash", "out", "Payment Gateway", 80.00, "Bayarcash"),
    ("2026-08-24", "Invoice #161 — Siti Hajar Binti (Haifa Adelea)", "in", "Course Revenue", 1500.00, "Siti Hajar Binti"),
    ("2026-08-21", "Invoice #162 — Koh Wen Han (AI for Workplace)", "in", "Workshop Revenue", 388.00, "Koh Wen Han"),
    ("2026-08-20", "QR payment (unidentified merchant)", "out", "Other Expense", 1.70, None),
    ("2026-08-19", "Shopee Mobile Malaysia purchase", "out", "Supplies", 10.20, "Shopee Mobile Malaysia"),
    ("2026-08-19", "Merchandise — Hive United (Polo tee custom)", "out", "Merchandise", 210.00, "Hive United"),
    ("2026-08-17", "Invoice #156 — Restoran Tong", "in", "Course Revenue", 800.00, "Restoran Tong"),
    ("2026-08-17", "Invoice #157 — Restoran Tong", "in", "Workshop Revenue", 488.00, "Restoran Tong"),
    ("2026-08-16", "Invoice #155 — Ooi Kah Seong (AI for Work)", "in", "Workshop Revenue", 388.00, "Ooi Kah Seong"),
    ("2026-08-10", "Refund — Mohd Zaid Bin Awi (Syasya, 4th class)", "out", "Refund Given", 250.00, "Mohd Zaid Bin Awi"),
    ("2026-08-09", "Printing — TNT Instant Print", "out", "Printing", 7.00, "TNT Instant Print"),
    ("2026-08-04", "Teaching fee — Foon Yew evening school (NSJB, July)", "in", "Course Revenue", 522.00, "Foon Yew Evening School"),
    ("2026-08-01", "Teacher salary — Tan Rou Ka (Python Fundamental)", "out", "Payroll", 330.00, "Tan Rou Ka"),
    ("2026-08-01", "Invoice #117 — CC Crest Consultancy", "in", "Course Revenue", 800.00, "CC Crest Consultancy"),
    ("2026-07-31", "Vibe Coding course fee — Lim Yoke Lian", "in", "Course Revenue", 800.00, "Lim Yoke Lian"),
    ("2026-07-30", "AI Automation project — Constance (Chan Siew Fuin)", "in", "Workshop Revenue", 488.00, "Chan Siew Fuin"),
    ("2026-07-28", "FPX refund (buyer)", "in", "Refund", 21.17, None),
    ("2026-07-28", "Shopee Mobile Malaysia purchase", "out", "Supplies", 30.25, "Shopee Mobile Malaysia"),
    ("2026-07-27", "Invoice #117 — CC Crest Consultancy", "in", "Course Revenue", 800.00, "CC Crest Consultancy"),
    ("2026-07-27", "Shopee Mobile Malaysia purchase", "out", "Supplies", 21.17, "Shopee Mobile Malaysia"),
    ("2026-07-24", "Payment received — Khor Yee Ran (Yoke Soon)", "in", "Other Income", 150.00, "Khor Yee Ran"),
    ("2026-07-24", "Class fee — Mohd Zaid Bin Awi (Class 4)", "in", "Course Revenue", 250.00, "Mohd Zaid Bin Awi"),
    ("2026-07-23", "Vibe Coding course fee — Wei De Luxury Car", "in", "Course Revenue", 800.00, "Wei De Luxury Car"),
    ("2026-07-22", "Rental — Havona Management (Aug, move-in)", "out", "Rental", 1243.93, "Havona Management"),
    ("2026-07-19", "Vibe Coding course fee — Eng Buan Jeng", "in", "Course Revenue", 500.00, "Eng Buan Jeng"),
    ("2026-07-18", "Courier — I&E Express", "out", "Courier/Postage", 7.00, "I&E Express"),
    ("2026-07-16", "Class fee — Mohd Zaid Bin Awi (Syasya)", "in", "Course Revenue", 250.00, "Mohd Zaid Bin Awi"),
    ("2026-07-14", "Withdrawal — Natasya Izzaty Khoo (Name card balance)", "out", "Marketing", 20.00, "Natasya Izzaty Khoo"),
    ("2026-07-14", "Withdrawal — Natasya Izzaty Khoo (Clothes)", "out", "Owner Withdrawal", 118.00, "Natasya Izzaty Khoo"),
    ("2026-07-07", "FPX M2U refund", "in", "Refund", 8.50, None),
    ("2026-07-07", "Class fee — Mohd Zaid Bin Awi (Syasya)", "in", "Course Revenue", 250.00, "Mohd Zaid Bin Awi"),
    ("2026-07-04", "Shopee Mobile Malaysia purchase", "out", "Supplies", 57.95, "Shopee Mobile Malaysia"),
    ("2026-07-04", "Shopee Mobile Malaysia purchase", "out", "Supplies", 33.00, "Shopee Mobile Malaysia"),
    ("2026-07-03", "Shopee Mobile Malaysia purchase", "out", "Supplies", 8.50, "Shopee Mobile Malaysia"),
    ("2026-07-02", "Shopee Mobile Malaysia purchase", "out", "Supplies", 8.50, "Shopee Mobile Malaysia"),
    ("2026-07-02", "Teaching fee — Foon Yew evening school (NSJB, June)", "in", "Course Revenue", 174.00, "Foon Yew Evening School"),
    ("2026-07-01", "Wage payout — Tan Rou Ka (June)", "out", "Payroll", 570.00, "Tan Rou Ka"),
    ("2026-07-01", "Wage payout — June (received back, internal)", "in", "Payroll", 570.00, None),
    ("2026-07-01", "Wage payout — June (reversed, internal)", "out", "Payroll", 570.00, None),
    ("2026-06-29", "Wage payment — Nurin Aisyah Najwa (Vibe Coding)", "out", "Payroll", 240.00, "Nurin Aisyah Najwa"),
    ("2026-06-26", "Shopee Mobile Malaysia purchase", "out", "Supplies", 64.82, "Shopee Mobile Malaysia"),
    ("2026-06-17", "Python class fee — Zaidawi Enterprise (Syasya)", "in", "Course Revenue", 250.00, "Zaidawi Enterprise"),
    ("2026-06-07", "Referral fee paid — Michael Cheah Hou Yang", "out", "Referral Expense", 1200.00, "Michael Cheah Hou Yang"),
    ("2026-06-07", "Referral fee reversed (internal)", "out", "Referral Income", 1200.00, None),
    ("2026-06-07", "Referral fee received (Code N Code Solution)", "in", "Referral Income", 1200.00, None),
    ("2026-05-28", "Python + ML course — Vanessa & Henry (Gao Carey Yueming)", "in", "Course Revenue", 6000.00, "Gao Carey Yueming"),
    ("2026-05-16", "Vibe Coding course fee — Muhammad Firdaus (Fathi)", "in", "Course Revenue", 800.00, "Muhammad Firdaus"),
    ("2026-05-15", "Transfer to Ngoifongting (DuitNow QR)", "out", "Other Expense", 12.00, "Ngoifongting"),
    ("2026-04-23", "Transfer to Muhamad Afiq Omar B (MAE QR)", "out", "Other Expense", 150.00, "Muhamad Afiq Omar B"),
    ("2026-04-15", "Annual bank card fee", "out", "Bank Charges", 8.00, None),
    ("2026-04-14", "Python Fundamentals course fee — Lim Ban Soon (DuitNow QR)", "in", "Course Revenue", 1549.00, "Lim Ban Soon"),
    ("2026-04-14", "Transfer received — Mohd Khairul Afzan (DuitNow QR)", "in", "Other Income", 0.01, "Mohd Khairul Afzan"),
]

# Invoices recovered from invoice-number references in the memos — all Paid
# (the bank statement confirms the money landed).
INVOICES = [
    ("INV-117", "CC Crest Consultancy", "2026-07-27", "2026-07-27", 800.00, "Paid"),
    ("INV-117", "CC Crest Consultancy", "2026-08-01", "2026-08-01", 800.00, "Paid"),
    ("INV-155", "Ooi Kah Seong", "2026-08-16", "2026-08-16", 388.00, "Paid"),
    ("INV-156", "Restoran Tong", "2026-08-17", "2026-08-17", 800.00, "Paid"),
    ("INV-157", "Restoran Tong", "2026-08-17", "2026-08-17", 488.00, "Paid"),
    ("INV-159", "Muhammad Firdaus", "2026-08-25", "2026-08-25", 1350.00, "Paid"),
    ("INV-161", "Siti Hajar Binti (Haifa Adelea)", "2026-08-24", "2026-08-24", 1500.00, "Paid"),
    ("INV-162", "Koh Wen Han", "2026-08-21", "2026-08-21", 388.00, "Paid"),
]


def seed_if_empty():
    if not storage.is_empty():
        return False
    for date, desc, ttype, cat, amt, party in TRANSACTIONS:
        storage.insert_transaction(date, desc, ttype, cat, amt, payer_payee=party)
    for number, contact, date, due, amount, status in INVOICES:
        storage.insert_invoice(number, contact, date, due, amount, status=status)
    # Advance the INV counter past the recovered numbers so new invoices
    # don't collide (highest recovered is 162).
    with storage.get_conn() as conn:
        conn.execute(
            "INSERT INTO counters(name, value) VALUES ('INV', 162) "
            "ON CONFLICT(name) DO UPDATE SET value = MAX(value, 162)"
        )
    return True


if __name__ == "__main__":
    storage.init_db()
    print("seeded" if seed_if_empty() else "already populated")
