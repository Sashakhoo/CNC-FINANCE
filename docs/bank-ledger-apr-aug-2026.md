# Reconciled bank ledger — April to August 2026

Source: 5 Maybank Islamic statements (account 551276106077, "Code N Code
Solution"), manually reconciled line-by-line. Every monthly total below
ties out exactly to each statement's own TOTAL DEBIT / TOTAL CREDIT /
ENDING BALANCE. This is the same data currently hardcoded into
`frontend/dashboard.html`'s `transactions` array.

- Opening balance (1 Apr 2026): RM 0.00 (account was newly opened)
- Closing balance (31 Aug 2026): RM 14,056.66
- Total revenue: RM 21,096.68
- Total expenses: RM 7,040.02
- Net profit: RM 14,056.66 (ties to closing balance since opening was RM 0)

| Month | Revenue | Expenses | Net Profit | Closing Balance |
|---|---|---|---|---|
| April 2026 | 1,549.01 | 158.00 | 1,391.01 | 1,391.01 |
| May 2026 | 6,800.00 | 12.00 | 6,788.00 | 8,179.01 |
| June 2026 | 1,450.00 | 2,704.82 | −1,254.82 | 6,924.19 |
| July 2026 | 5,061.67 | 2,688.30 | 2,373.37 | 9,297.56 |
| August 2026 | 6,236.00 | 1,476.90 | 4,759.10 | 14,056.66 |

## Previously unclear — reclassified by the owner (Sep 2026)

- 14 Apr: RM 1,549.00 in from "Lim Ban Soon" (DuitNow QR) — **Python
  Fundamentals course fee** → Course Revenue
- 28 May: RM 6,000.00 in from "Gao Carey Yueming" — **Python + ML course
  for Vanessa & Henry** → Course Revenue
- 02 Jul & 04 Aug: RM 174.00 and RM 522.00 in from "Johore Bahru Foon Y"
  ("NSJB") — **teaching fees from Foon Yew evening school** → Course Revenue

## Still unclear — do not reclassify without asking the user

- 24 Jul: RM 150.00 in from "Khor Yee Ran" (Yoke Soon) — bucketed as
  "Other Income"
- 23 Apr: RM 150.00 out to "Muhamad Afiq Omar B" (MAE QR) — bucketed as
  "Other Expense"

## Internal/wash entries (net to zero, kept for ledger completeness)

- 07 Jun: RM 1,200 referral fee received then reversed same day
  (both legs present in the seed data, net effect zero)
- 01 Jul: RM 570 wage payout reversed and re-paid same day (both legs
  present, net effect zero)

## Full category list currently in use

**Income:** Course Revenue, Consulting Revenue, Referral Income, Other Income, Refund
**Expense:** Payroll, Rental, Bank Charges, Supplies, Referral Expense,
Marketing, Merchandise, Courier/Postage, Owner Withdrawal, Refund Given,
Payment Gateway, Printing, Other Expense

These map to account codes in `backend/storage.py`'s
`KNOWN_INCOME_CODES` / `KNOWN_EXPENSE_CODES` — any new category typed
into the dashboard or sent via Telegram gets auto-assigned the next code
in the 4100+ (income) or 6100+ (expense) series.
