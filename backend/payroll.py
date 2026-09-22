"""
Malaysian statutory payroll deduction calculations — EPF, SOCSO, EIS — plus
gross/net computation for a payroll_items row.

⚠️ IMPORTANT — these are percentage APPROXIMATIONS, not the official ringgit
lookup tables:
  - EPF's actual contribution amounts come from the KWSP Third Schedule, a
    wage-banded table (not a pure percentage), so official amounts can differ
    from this by a ringgit or two at some wage levels.
  - SOCSO and EIS similarly use PERKESO's banded contribution tables
    (RM100-wide wage bands, each with its own fixed ringgit contribution),
    not a flat percentage of wage.
  - PCB (monthly tax deduction) is NOT calculated here at all — it depends on
    each employee's personal tax reliefs (marital status, children, other
    exemptions) which this system has no record of. It's a manual entry per
    payroll item (see storage.payroll_items.pcb) — get it from LHDN's PCB
    calculator or the employee's usual figure.

Rates below are the standard current rates for a Malaysian citizen/PR
employee under 60. Before relying on this for real payroll, verify against:
  - EPF: https://www.kwsp.gov.my  (Third Schedule contribution table)
  - SOCSO/EIS: https://www.perkeso.gov.my  (contribution table, wage ceiling)
Rates and the wage ceiling change from time to time — re-check before use
if this module hasn't been touched in a while.

VERIFIED 2026-09-22 against current published rates (EPF 11%/13%-or-12% at
the RM5,000 band; SOCSO 0.5%/1.75%; EIS 0.2%/0.2%; wage ceiling RM6,000,
raised from RM5,000 on 1 Oct 2024) — all match what's hardcoded below. One
gap this check surfaced and this module does NOT handle: employees aged
60+ are on different rates entirely (EPF: employee 0%, employer 4%; SOCSO
Category 2: employer-only ~1.25%, no EIS) — there's no age field on
`teachers` to branch on, so every employee is currently computed as
under-60. Add an age/DOB field and an age check before running payroll for
anyone 60 or older.
"""

# EPF (KWSP) — employee always 11% of wages (citizen/PR, under 60).
# Employer: 13% up to and including RM5,000 wages, 12% above RM5,000.
EPF_EMPLOYEE_RATE = 0.11
EPF_EMPLOYER_RATE_LOW = 0.13   # wages <= RM5,000
EPF_EMPLOYER_RATE_HIGH = 0.12  # wages > RM5,000
EPF_EMPLOYER_THRESHOLD = 5000.0

# SOCSO (PERKESO) — Employment Injury + Invalidity Scheme, citizen/PR under
# 60. Approximated as a flat percentage of wages up to the wage ceiling.
SOCSO_EMPLOYEE_RATE = 0.005   # ~0.5%
SOCSO_EMPLOYER_RATE = 0.0175  # ~1.75%

# EIS (Employment Insurance System) — both sides 0.2% of wages, same ceiling.
EIS_EMPLOYEE_RATE = 0.002
EIS_EMPLOYER_RATE = 0.002

# Wage ceiling SOCSO and EIS contributions are capped at (per current
# PERKESO schedule — was raised from RM4,000 to RM5,000 to RM6,000 over
# 2022-2024; re-verify this hasn't moved again).
SOCSO_EIS_WAGE_CEILING = 6000.0


def _round2(n: float) -> float:
    return round(n + 1e-9, 2)


def compute_epf(gross: float) -> tuple[float, float]:
    """Returns (employee_epf, employer_epf) for a monthly gross wage."""
    employee = gross * EPF_EMPLOYEE_RATE
    employer_rate = EPF_EMPLOYER_RATE_LOW if gross <= EPF_EMPLOYER_THRESHOLD else EPF_EMPLOYER_RATE_HIGH
    employer = gross * employer_rate
    return _round2(employee), _round2(employer)


def compute_socso(gross: float) -> tuple[float, float]:
    """Returns (employee_socso, employer_socso). Wages above the ceiling
    contribute as if capped at the ceiling."""
    capped = min(gross, SOCSO_EIS_WAGE_CEILING)
    return _round2(capped * SOCSO_EMPLOYEE_RATE), _round2(capped * SOCSO_EMPLOYER_RATE)


def compute_eis(gross: float) -> tuple[float, float]:
    """Returns (employee_eis, employer_eis). Same wage ceiling as SOCSO."""
    capped = min(gross, SOCSO_EIS_WAGE_CEILING)
    return _round2(capped * EIS_EMPLOYEE_RATE), _round2(capped * EIS_EMPLOYER_RATE)


def compute_payroll_item(gross: float, employment_type: str, pcb: float = 0.0) -> dict:
    """Computes the full breakdown for one payroll_items row.

    employment_type: 'freelance' -> no statutory deductions at all, net =
    gross (freelancers/contractors aren't on EPF/SOCSO/EIS payroll).
    'employee' -> EPF/SOCSO/EIS computed as above; pcb is whatever manual
    figure was supplied (0 if none given — caller/UI should prompt for it
    rather than silently assume 0 owed).
    """
    gross = float(gross or 0)
    if employment_type == "freelance":
        return {
            "gross": _round2(gross), "epf_employee": 0.0, "epf_employer": 0.0,
            "socso_employee": 0.0, "socso_employer": 0.0,
            "eis_employee": 0.0, "eis_employer": 0.0, "pcb": 0.0,
            "net": _round2(gross), "employer_cost": _round2(gross),
        }

    epf_e, epf_r = compute_epf(gross)
    socso_e, socso_r = compute_socso(gross)
    eis_e, eis_r = compute_eis(gross)
    pcb = _round2(float(pcb or 0))
    net = _round2(gross - epf_e - socso_e - eis_e - pcb)
    employer_cost = _round2(gross + epf_r + socso_r + eis_r)
    return {
        "gross": _round2(gross),
        "epf_employee": epf_e, "epf_employer": epf_r,
        "socso_employee": socso_e, "socso_employer": socso_r,
        "eis_employee": eis_e, "eis_employer": eis_r,
        "pcb": pcb, "net": net, "employer_cost": employer_cost,
    }
