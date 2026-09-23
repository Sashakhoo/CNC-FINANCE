"""
Form B (sole proprietor) tax figures, computed from the ledger.

Same calculation as the dashboard's Tax screen (renderTax in
frontend/dashboard.html): resident individual bands, RM9,000 individual
relief plus capped reliefs, RM400 rebate when chargeable income is
<= RM35,000, zakat paid as a rebate against tax. Keep the two in step.

The ledger is cash-basis and not double-entry, so the balance-sheet
side of the worksheet uses the same plug approach as the dashboard's
Balance Sheet: capital carried forward = assets - liabilities, and the
capital brought forward is the balancing figure.
"""
import storage

# Resident individual rates (YA 2023 onwards). (upper limit, rate)
TAX_BANDS = [(5000, 0.0), (20000, 0.01), (35000, 0.03), (50000, 0.06), (70000, 0.11),
             (100000, 0.19), (400000, 0.25), (600000, 0.26), (2000000, 0.28), (float("inf"), 0.30)]
PERSONAL_RELIEF = 9000.0
TAX_REBATE = 400.0
REBATE_LIMIT = 35000.0
RELIEF_CAPS = {"epf": 7000.0, "socso": 350.0, "lifestyle": 2500.0}

DRAWINGS = "Owner Withdrawal"
SALES_CATEGORIES = {"Course Revenue", "Workshop Revenue", "Consulting Revenue"}
SALES_RETURNS = {"Refund Given"}

# Ledger expense category -> Form B profit & loss expense line.
EXPENSE_LINES = [
    ("Salaries and wages", {"Payroll"}),
    ("Rental / lease", {"Rental"}),
    ("Commissions", {"Referral Expense"}),
    ("Promotion and advertisement", {"Marketing", "Merchandise", "Printing"}),
]
OTHER_EXPENSES = "Other expenses"


def band_tax(ci: float) -> float:
    tax, lower = 0.0, 0.0
    for upper, rate in TAX_BANDS:
        if ci <= lower:
            break
        tax += (min(ci, upper) - lower) * rate
        lower = upper
    return tax


def band_rows(ci: float) -> list:
    rows, lower = [], 0.0
    for upper, rate in TAX_BANDS:
        in_band = max(0.0, min(ci, upper) - lower)
        if in_band:
            rows.append((lower, upper, rate, in_band * rate))
        lower = upper
    return rows


def compute_tax(adjusted: float, reliefs: float, zakat_paid: float) -> dict:
    ci = max(0.0, adjusted - reliefs)
    gross = band_tax(ci)
    rebate = min(TAX_REBATE, gross) if ci <= REBATE_LIMIT else 0.0
    zakat = min(zakat_paid, gross - rebate)
    return {"chargeable": ci, "gross": gross, "rebate": rebate, "zakat": zakat,
            "payable": gross - rebate - zakat}


def _is_income(category: str, codes: dict, fallback_type: str) -> bool:
    code = codes.get(category) or storage.KNOWN_INCOME_CODES.get(category) \
        or storage.KNOWN_EXPENSE_CODES.get(category)
    return code.startswith("4") if code else fallback_type == "in"


def form_b_worksheet(year: int, epf: float = 0, socso: float = 0, lifestyle: float = 0,
                     other_reliefs: float = 0, zakat_paid: float = 0) -> dict:
    ya = str(year)
    txs = storage.list_transactions()
    codes = storage.list_category_codes()

    # Net each category (wash entries such as reversed wages cancel out),
    # signed so income categories are in - out and expenses are out - in.
    net: dict = {}
    for t in txs:
        if not str(t["date"]).startswith(ya):
            continue
        cat = t["category"]
        amt = float(t["amount"])
        income = _is_income(cat, codes, t["type"])
        sign = 1 if (t["type"] == "in") == income else -1
        entry = net.setdefault(cat, {"income": income, "amount": 0.0})
        entry["amount"] += sign * amt

    drawings = net.pop(DRAWINGS, {"amount": 0.0})["amount"]
    gross_sales = sum(v["amount"] for c, v in net.items() if c in SALES_CATEGORIES)
    returns = sum(v["amount"] for c, v in net.items() if c in SALES_RETURNS)
    turnover = gross_sales - returns
    other_income = [(c, v["amount"]) for c, v in sorted(net.items())
                    if v["income"] and c not in SALES_CATEGORIES and round(v["amount"], 2)]

    expenses = {label: [] for label, _ in EXPENSE_LINES}
    expenses[OTHER_EXPENSES] = []
    for c, v in sorted(net.items()):
        if v["income"] or c in SALES_RETURNS or not round(v["amount"], 2):
            continue
        label = next((l for l, cats in EXPENSE_LINES if c in cats), OTHER_EXPENSES)
        expenses[label].append((c, v["amount"]))
    expense_lines = [(label, sum(a for _, a in items), items) for label, items in expenses.items()]

    total_other_income = sum(a for _, a in other_income)
    total_expenses = sum(a for _, a, _ in expense_lines)
    net_profit = turnover + total_other_income - total_expenses
    adjusted = max(0.0, net_profit)

    # Balance sheet at year end (cash-basis; debtors/creditors/assets are current values).
    cash = sum(float(t["amount"]) * (1 if t["type"] == "in" else -1)
               for t in txs if str(t["date"])[:4] <= ya)
    contacts = storage.list_contacts()
    debtors = sum(float(c["balance"]) for c in contacts if c["type"] == "debtor")
    creditors = sum(float(c["balance"]) for c in contacts if c["type"] == "creditor")
    fixed_assets = sum(float(a["cost"]) - float(a["dep"]) for a in storage.list_assets())
    total_assets = fixed_assets + debtors + cash
    capital_cf = total_assets - creditors
    capital_bf = capital_cf - net_profit + drawings

    capped = {k: min(max(0.0, v), RELIEF_CAPS[k]) for k, v in
              (("epf", epf), ("socso", socso), ("lifestyle", lifestyle))}
    other_reliefs = max(0.0, other_reliefs)
    total_reliefs = PERSONAL_RELIEF + sum(capped.values()) + other_reliefs
    tax = compute_tax(adjusted, total_reliefs, max(0.0, zakat_paid))

    return {
        "year": year,
        "pl": {"gross_sales": gross_sales, "returns": returns, "turnover": turnover,
               "other_income": other_income, "total_other_income": total_other_income,
               "expense_lines": expense_lines, "total_expenses": total_expenses,
               "net_profit": net_profit},
        "adjustment": {"net_profit": net_profit, "drawings": drawings, "adjusted": adjusted},
        "reliefs": {"individual": PERSONAL_RELIEF, **capped, "other": other_reliefs,
                    "total": total_reliefs},
        "tax": {**tax, "bands": band_rows(tax["chargeable"])},
        "balance_sheet": {"fixed_assets": fixed_assets, "debtors": debtors, "cash": cash,
                          "total_assets": total_assets, "creditors": creditors,
                          "capital_bf": capital_bf, "net_profit": net_profit,
                          "drawings": drawings, "capital_cf": capital_cf},
    }
