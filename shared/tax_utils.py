"""
Tax Computation Utilities — AY 2024-25
=======================================
Slab rates, 87A rebate, surcharge, HRA computation, regime comparison.
All figures for AY 2024-25 (FY 2023-24). Update config for new AYs.
"""

from __future__ import annotations
import math


# ── AY Config (swap for new Assessment Year) ──────────────────────────────────

AY_CONFIG = {
    "AY2024-25": {
        "old_regime_slabs": [
            (250000,  0.00),
            (500000,  0.05),
            (1000000, 0.20),
            (math.inf, 0.30),
        ],
        "new_regime_slabs": [
            (300000,  0.00),
            (600000,  0.05),
            (900000,  0.10),
            (1200000, 0.15),
            (1500000, 0.20),
            (math.inf, 0.30),
        ],
        "old_regime_rebate_87a_limit":  500000,
        "old_regime_rebate_87a_amount": 12500,
        "new_regime_rebate_87a_limit":  700000,
        "new_regime_rebate_87a_amount": 25000,
        "standard_deduction_new_regime": 50000,  # introduced from AY 2024-25
        "cess_rate":                    0.04,
        "surcharge_slabs":  [
            (5000000,  0.00),
            (10000000, 0.10),
            (20000000, 0.15),
            (50000000, 0.25),
            (math.inf, 0.37),   # 37% applies only under old regime
        ],
        "surcharge_slabs_new": [
            (5000000,  0.00),
            (10000000, 0.10),
            (20000000, 0.15),
            (math.inf, 0.25),   # capped at 25% for new regime from AY 2023-24
        ],
        "standard_deduction_old": 50000,
        "hra_metro_pct": 0.50,
        "hra_nonmetro_pct": 0.40,
        "sec_80c_limit": 150000,
        "sec_80d_self_limit": 25000,
        "sec_80d_parents_limit": 25000,
        "sec_80d_self_senior": 50000,
        "sec_80d_parents_senior": 50000,
        "sec_80tta_limit": 10000,
        "sec_80ttb_limit": 50000,
        "sec_80ccd_1b_limit": 50000,
        "interest_24b_self_occupied_cap": 200000,
    }
}

METRO_CITIES = {"mumbai", "delhi", "kolkata", "chennai"}


def get_config(ay: str = "AY2024-25") -> dict:
    return AY_CONFIG.get(ay, AY_CONFIG["AY2024-25"])


# ── Core tax computation ───────────────────────────────────────────────────────

def compute_tax_on_slabs(income: float, slabs: list[tuple]) -> float:
    """Apply progressive tax slabs and return tax amount (before cess/surcharge)."""
    tax = 0.0
    prev_limit = 0.0
    for limit, rate in slabs:
        if income <= prev_limit:
            break
        taxable_in_slab = min(income, limit) - prev_limit
        tax += taxable_in_slab * rate
        prev_limit = limit
    return tax


def compute_surcharge(income: float, tax: float, slabs: list[tuple]) -> float:
    """Compute surcharge with marginal relief (simplified)."""
    rate = 0.0
    prev = 0.0
    for limit, s in slabs:
        if income > prev:
            rate = s
        prev = limit
    if rate == 0.0:
        return 0.0
    return tax * rate


def compute_tax_2025(
    taxable_income: float,
    ay: str = "AY2024-25",
) -> dict[str, float]:
    """
    Full tax computation strictly under 2025 (New) Regime.
    """
    cfg = get_config(ay)

    slabs           = cfg["new_regime_slabs"]
    rebate_limit    = cfg["new_regime_rebate_87a_limit"]
    rebate_max      = cfg["new_regime_rebate_87a_amount"]
    surcharge_slabs = cfg["surcharge_slabs_new"]

    tax_before_rebate = compute_tax_on_slabs(taxable_income, slabs)
    rebate_87a        = min(tax_before_rebate, rebate_max) if taxable_income <= rebate_limit else 0.0
    tax_after_rebate  = max(0.0, tax_before_rebate - rebate_87a)
    surcharge         = compute_surcharge(taxable_income, tax_after_rebate, surcharge_slabs)
    cess              = (tax_after_rebate + surcharge) * cfg["cess_rate"]
    total             = tax_after_rebate + surcharge + cess

    return {
        "tax_before_rebate":     round(tax_before_rebate, 2),
        "rebate_87a":            round(rebate_87a, 2),
        "tax_after_rebate":      round(tax_after_rebate, 2),
        "surcharge":             round(surcharge, 2),
        "health_education_cess": round(cess, 2),
        "total_tax":             round(total, 2),
    }

# (Regime comparison removed for strict 2025 new regime compliance)

# ── HRA computation ───────────────────────────────────────────────────────────

def compute_hra_exemption(
    hra_received:   float,
    basic_salary:   float,
    rent_paid:      float,
    city:           str,
    ay:             str = "AY2024-25",
) -> dict[str, float]:
    """
    HRA exemption = min of three:
      (a) Actual HRA received
      (b) Rent paid - 10% of basic
      (c) 50% of basic (metro) / 40% of basic (non-metro)
    """
    cfg       = get_config(ay)
    pct       = cfg["hra_metro_pct"] if city.lower() in METRO_CITIES else cfg["hra_nonmetro_pct"]
    component_a = hra_received
    component_b = max(0, rent_paid - 0.10 * basic_salary)
    component_c = basic_salary * pct
    exemption   = min(component_a, component_b, component_c)

    return {
        "component_a_hra_received":      component_a,
        "component_b_rent_minus_10pct":  component_b,
        "component_c_pct_of_basic":      component_c,
        "hra_exemption":                 round(exemption, 2),
        "hra_taxable":                   round(hra_received - exemption, 2),
        "city_type":                     "metro" if city.lower() in METRO_CITIES else "non-metro",
    }


# ── Deduction limit enforcement ───────────────────────────────────────────────

def enforce_deduction_limits(deductions: dict, ay: str = "AY2024-25") -> dict:
    """Under 2025 New Regime, only 80CCD(2) and standard deduction are allowed."""
    warnings = []
    
    # 80C, 80D, etc. are not allowed.
    if deductions.get("sec_80c", 0) > 0 or deductions.get("sec_80d", 0) > 0:
        warnings.append("80C, 80D and other Chapter VI-A deductions are not applicable under the 2025 New Tax Regime.")

    return {
        "sec_80ccd_2": deductions.get("sec_80ccd_2", 0),
        "total":       deductions.get("sec_80ccd_2", 0),
        "warnings":    warnings,
    }
