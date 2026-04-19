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


def compute_tax(
    taxable_income: float,
    regime: str = "new",
    ay:     str = "AY2024-25",
) -> dict[str, float]:
    """
    Full tax computation for a given taxable income and regime.
    Returns a breakdown dict.
    """
    cfg = get_config(ay)

    if regime == "new":
        slabs           = cfg["new_regime_slabs"]
        rebate_limit    = cfg["new_regime_rebate_87a_limit"]
        rebate_max      = cfg["new_regime_rebate_87a_amount"]
        surcharge_slabs = cfg["surcharge_slabs_new"]
    else:
        slabs           = cfg["old_regime_slabs"]
        rebate_limit    = cfg["old_regime_rebate_87a_limit"]
        rebate_max      = cfg["old_regime_rebate_87a_amount"]
        surcharge_slabs = cfg["surcharge_slabs"]

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


# ── Regime comparison ─────────────────────────────────────────────────────────

def compare_regimes(
    gross_total_income:   float,
    deductions_old:       float,  # total deductions available under old regime
    tds_deducted:         float   = 0.0,
    ay:                   str     = "AY2024-25",
) -> dict:
    """
    Compare old vs new regime tax liability and recommend.
    Returns breakdown + recommendation with reasoning.
    """
    cfg = get_config(ay)

    # Old regime
    taxable_old = max(0, gross_total_income - deductions_old)
    tax_old_breakdown = compute_tax(taxable_old, regime="old", ay=ay)
    tax_old = tax_old_breakdown["total_tax"]

    # New regime — standard deduction from AY 2024-25
    taxable_new = max(0, gross_total_income - cfg["standard_deduction_new_regime"])
    tax_new_breakdown = compute_tax(taxable_new, regime="new", ay=ay)
    tax_new = tax_new_breakdown["total_tax"]

    saving = tax_old - tax_new
    recommended = "new" if tax_new <= tax_old else "old"

    # Build reasoning
    if recommended == "new":
        reason = (
            f"New regime saves ₹{abs(saving):,.0f}. "
            f"Your deductions of ₹{deductions_old:,.0f} are not enough to make the old regime "
            f"more beneficial. The new regime's simplified slabs result in lower tax."
        )
    else:
        reason = (
            f"Old regime saves ₹{abs(saving):,.0f}. "
            f"Your deductions of ₹{deductions_old:,.0f} significantly reduce your taxable income. "
            f"Maximise 80C (₹{cfg['sec_80c_limit']:,.0f}), 80D, and NPS (80CCD 1B ₹{cfg['sec_80ccd_1b_limit']:,.0f}) "
            f"to keep old regime advantageous."
        )

    return {
        "old_regime": {
            "deductions":     deductions_old,
            "taxable_income": taxable_old,
            **tax_old_breakdown,
        },
        "new_regime": {
            "deductions":     cfg["standard_deduction_new_regime"],
            "taxable_income": taxable_new,
            **tax_new_breakdown,
        },
        "recommended_regime": recommended,
        "saving":             abs(saving),
        "reasoning":          reason,
        "net_payable_old":    max(0, tax_old - tds_deducted),
        "net_payable_new":    max(0, tax_new - tds_deducted),
        "refund_old":         max(0, tds_deducted - tax_old),
        "refund_new":         max(0, tds_deducted - tax_new),
    }


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
    """Apply all statutory caps to deductions dict. Returns corrected dict + warnings."""
    cfg = get_config(ay)
    warnings = []

    # 80C family cap
    raw_80c_family = deductions.get("sec_80c", 0) + deductions.get("sec_80ccc", 0) + deductions.get("sec_80ccd_1", 0)
    if raw_80c_family > cfg["sec_80c_limit"]:
        warnings.append(f"80C/80CCC/80CCD(1) total ₹{raw_80c_family:,.0f} exceeds cap ₹{cfg['sec_80c_limit']:,.0f}. Capped.")

    capped_80c_family = min(raw_80c_family, cfg["sec_80c_limit"])

    # 80CCD(1B) cap
    raw_1b = deductions.get("sec_80ccd_1b", 0)
    if raw_1b > cfg["sec_80ccd_1b_limit"]:
        warnings.append(f"80CCD(1B) ₹{raw_1b:,.0f} exceeds cap ₹{cfg['sec_80ccd_1b_limit']:,.0f}.")
    capped_1b = min(raw_1b, cfg["sec_80ccd_1b_limit"])

    # 80TTA / 80TTB (mutually exclusive — 80TTB is for seniors)
    if deductions.get("sec_80tta", 0) > 0 and deductions.get("sec_80ttb", 0) > 0:
        warnings.append("Both 80TTA and 80TTB claimed — 80TTB is only for senior citizens. Remove 80TTA.")
    tta = min(deductions.get("sec_80tta", 0), cfg["sec_80tta_limit"])
    ttb = min(deductions.get("sec_80ttb", 0), cfg["sec_80ttb_limit"])

    return {
        "capped_80c_family":   capped_80c_family,
        "capped_80ccd_1b":     capped_1b,
        "capped_80d":          deductions.get("sec_80d", 0),
        "capped_80tta":        tta,
        "capped_80ttb":        ttb,
        "sec_80ccd_2":         deductions.get("sec_80ccd_2", 0),
        "sec_80e":             deductions.get("sec_80e", 0),
        "sec_80gg":            deductions.get("sec_80gg", 0),
        "total":               (capped_80c_family + capped_1b + deductions.get("sec_80d", 0) +
                                tta + ttb + deductions.get("sec_80ccd_2", 0) +
                                deductions.get("sec_80e", 0) + deductions.get("sec_80gg", 0)),
        "warnings":            warnings,
    }
