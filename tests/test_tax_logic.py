"""
Test Suite — ITR-1 RAG Agent
==============================
Covers: tax computation, HRA, regime comparison, deduction limits, validator.

Run:
    pytest tests/ -v
    pytest tests/ -v -k "test_regime"    # run specific tests
"""

import sys
import json
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.tax_utils import (
    compute_tax,
    compare_regimes,
    compute_hra_exemption,
    enforce_deduction_limits,
)
from shared.itr1_schema import (
    ITR1Form,
    SalaryIncome,
    Deductions,
    HousePropertyIncome,
    OtherSourcesIncome,
    TaxRegime,
)


# ── Tax computation ────────────────────────────────────────────────────────────

class TestTaxComputation:

    def test_zero_income_zero_tax(self):
        result = compute_tax(0, regime="new")
        assert result["total_tax"] == 0.0

    def test_new_regime_rebate_7L(self):
        """Income exactly ₹7L should have zero tax under new regime (87A rebate)."""
        result = compute_tax(700000, regime="new")
        assert result["rebate_87a"] == result["tax_before_rebate"]
        assert result["total_tax"] == 0.0

    def test_new_regime_above_7L_taxable(self):
        """₹7,00,001 should have some tax under new regime (rebate not available)."""
        result = compute_tax(700001, regime="new")
        assert result["rebate_87a"] == 0.0
        assert result["total_tax"] > 0

    def test_old_regime_rebate_5L(self):
        """Income ₹5L should have zero tax under old regime (87A rebate ₹12,500)."""
        result = compute_tax(500000, regime="old")
        assert result["total_tax"] == 0.0
        assert result["rebate_87a"] > 0

    def test_old_regime_above_5L(self):
        """₹5,00,001 should attract tax (no 87A rebate)."""
        result = compute_tax(500001, regime="old")
        assert result["rebate_87a"] == 0.0
        assert result["total_tax"] > 0

    def test_cess_rate_4_percent(self):
        """Health & education cess should be exactly 4% of (tax + surcharge)."""
        result = compute_tax(1200000, regime="new")
        expected_cess = round((result["tax_after_rebate"] + result["surcharge"]) * 0.04, 2)
        assert abs(result["health_education_cess"] - expected_cess) < 0.01

    def test_new_regime_slabs_correctness(self):
        """₹12L income: 0-3L=0, 3-6L=5%=15k, 6-9L=10%=30k, 9-12L=15%=45k → ₹90,000"""
        result = compute_tax(1200000, regime="new")
        assert result["tax_before_rebate"] == pytest.approx(90000, abs=1)

    def test_old_regime_slabs_correctness(self):
        """₹10L income old regime: 0-2.5L=0, 2.5-5L=5%=12.5k, 5-10L=20%=100k → ₹1,12,500"""
        result = compute_tax(1000000, regime="old")
        assert result["tax_before_rebate"] == pytest.approx(112500, abs=1)

    def test_surcharge_50L(self):
        """Income above ₹50L should attract 10% surcharge."""
        result = compute_tax(6000000, regime="new")
        assert result["surcharge"] > 0

    def test_all_fields_present(self):
        result = compute_tax(800000, regime="new")
        required_keys = [
            "tax_before_rebate", "rebate_87a", "tax_after_rebate",
            "surcharge", "health_education_cess", "total_tax"
        ]
        for k in required_keys:
            assert k in result, f"Missing key: {k}"


# ── Regime comparison ──────────────────────────────────────────────────────────

class TestRegimeComparison:

    def test_high_deductions_old_regime_better(self):
        """
        At ₹8L income with ₹2.5L deductions (80C+std+80D), old regime is better.
        Old: 8L - 2.5L = 5.5L taxable → ₹22,500 tax
        New: 8L - 0.5L std = 7.5L taxable → ₹30,000 tax
        """
        result = compare_regimes(
            gross_total_income=800000,
            deductions_old=250000,   # 80C 1.5L + std 50k + 80D 50k
        )
        assert result["recommended_regime"] == "old"

    def test_no_deductions_new_regime_better(self):
        """With zero deductions, new regime is always better."""
        result = compare_regimes(
            gross_total_income=1000000,
            deductions_old=50000,   # only standard deduction
        )
        assert result["recommended_regime"] == "new"

    def test_saving_is_positive(self):
        result = compare_regimes(800000, 150000)
        assert result["saving"] >= 0

    def test_recommended_regime_is_lower_tax(self):
        result = compare_regimes(1200000, 250000)
        rec = result["recommended_regime"]
        other = "new" if rec == "old" else "old"
        assert result[f"{rec}_regime"]["total_tax"] <= result[f"{other}_regime"]["total_tax"]

    def test_output_has_reasoning(self):
        result = compare_regimes(900000, 175000)
        assert "reasoning" in result
        assert len(result["reasoning"]) > 20

    def test_refund_computed_correctly(self):
        result = compare_regimes(
            gross_total_income=700000,
            deductions_old=50000,
            tds_deducted=10000,
        )
        # Under new regime, income 6.5L is below 7L rebate → zero tax → full refund
        assert result["refund_new"] == pytest.approx(10000, abs=1)


# ── HRA computation ────────────────────────────────────────────────────────────

class TestHRA:

    def test_metro_hra_50_percent(self):
        """Metro city: 50% of basic is component C."""
        r = compute_hra_exemption(
            hra_received=120000,
            basic_salary=500000,
            rent_paid=180000,
            city="mumbai",
        )
        assert r["component_c_pct_of_basic"] == 250000   # 50% of 5L

    def test_nonmetro_hra_40_percent(self):
        r = compute_hra_exemption(
            hra_received=60000,
            basic_salary=300000,
            rent_paid=84000,
            city="pune",
        )
        assert r["component_c_pct_of_basic"] == 120000   # 40% of 3L

    def test_hra_min_of_three(self):
        """Exemption = minimum of all three components."""
        r = compute_hra_exemption(
            hra_received=50000,    # component A
            basic_salary=600000,
            rent_paid=90000,       # component B = 90k - 60k = 30k
            city="hyderabad",
        )
        # A=50k, B=30k, C=240k → min is B=30k
        assert r["hra_exemption"] == 30000

    def test_zero_rent_zero_exemption(self):
        r = compute_hra_exemption(60000, 300000, 0, "chennai")
        assert r["hra_exemption"] == 0

    def test_no_hra_if_rent_less_than_10pct_basic(self):
        """Rent < 10% of basic → component B is 0 → exemption is 0."""
        r = compute_hra_exemption(
            hra_received=60000,
            basic_salary=600000,
            rent_paid=50000,  # 50k < 10% of 6L (60k)
            city="delhi",
        )
        assert r["hra_exemption"] == 0

    def test_taxable_hra_is_hra_minus_exemption(self):
        r = compute_hra_exemption(100000, 400000, 150000, "bangalore")
        assert r["hra_taxable"] == pytest.approx(r["component_a_hra_received"] - r["hra_exemption"])


# ── Deduction limits ───────────────────────────────────────────────────────────

class TestDeductionLimits:

    def test_80c_cap_at_150000(self):
        result = enforce_deduction_limits({
            "sec_80c": 200000,   # over limit
            "sec_80ccc": 0,
            "sec_80ccd_1": 0,
        })
        assert result["capped_80c_family"] == 150000

    def test_80c_below_cap_unchanged(self):
        result = enforce_deduction_limits({
            "sec_80c": 100000,
            "sec_80ccc": 30000,
            "sec_80ccd_1": 10000,
        })
        # Total = 140k < 150k → unchanged
        assert result["capped_80c_family"] == 140000

    def test_80ccd_1b_cap_50000(self):
        result = enforce_deduction_limits({"sec_80ccd_1b": 75000})
        assert result["capped_80ccd_1b"] == 50000

    def test_80tta_cap_10000(self):
        result = enforce_deduction_limits({"sec_80tta": 15000})
        assert result["capped_80tta"] == 10000

    def test_80ttb_cap_50000(self):
        result = enforce_deduction_limits({"sec_80ttb": 60000})
        assert result["capped_80ttb"] == 50000

    def test_both_80tta_and_80ttb_warns(self):
        result = enforce_deduction_limits({
            "sec_80tta": 10000,
            "sec_80ttb": 40000,
        })
        assert len(result["warnings"]) >= 1
        assert "80TTB" in result["warnings"][0]

    def test_total_computed_correctly(self):
        result = enforce_deduction_limits({
            "sec_80c": 150000,
            "sec_80d": 25000,
            "sec_80tta": 8000,
        })
        assert result["total"] == pytest.approx(150000 + 25000 + 8000, abs=1)


# ── ITR-1 schema ───────────────────────────────────────────────────────────────

class TestITR1Schema:

    def test_default_form_creates_without_error(self):
        form = ITR1Form()
        assert form is not None

    def test_salary_compute(self):
        sal = SalaryIncome(
            gross_salary=800000,
            allowances_exempt_10_13a=60000,
            professional_tax_16iii=2400,
        )
        sal.compute()
        # Standard deduction = min(50000, net_salary)
        assert sal.standard_deduction_16ia == 50000
        assert sal.taxable_salary == pytest.approx(800000 - 60000 - 50000 - 2400)

    def test_hp_self_occupied_cap(self):
        hp = HousePropertyIncome(
            property_type="self_occupied",
            interest_on_loan_24b=350000,  # over 2L cap
        )
        hp.compute()
        assert hp.interest_on_loan_24b == 200000   # capped at 2L

    def test_hp_loss_cap_at_2L(self):
        hp = HousePropertyIncome(
            property_type="self_occupied",
            interest_on_loan_24b=300000,
        )
        hp.compute()
        # Loss should be capped at -200000 (₹2L)
        assert hp.total_income_hp >= -200000

    def test_form_serializable(self):
        form = ITR1Form()
        d = json.loads(form.model_dump_json())
        assert "personal_info" in d
        assert "salary_income" in d
        assert "tax_computation" in d

    def test_deductions_new_regime_zeroed(self):
        ded = Deductions(sec_80c=150000, sec_80d=25000, sec_80ccd_2=80000)
        ded.compute(regime=TaxRegime.NEW)
        # Under new regime only 80CCD(2) counts (handled separately)
        assert ded.total_deductions == 0   # old-regime deductions not applied


# ── Integration: full tax scenario ────────────────────────────────────────────

class TestIntegration:

    def test_salaried_no_deductions_new_regime(self):
        """
        Salary ₹10L, no deductions → new regime should be recommended.
        Tax (new regime): 3L@0 + 3L@5% + 3L@10% + 1L@15% = 15k+30k+15k = 60k
        After standard deduction 50k: taxable = 9.5L
        """
        result = compare_regimes(
            gross_total_income=1000000,
            deductions_old=50000,   # only standard deduction
        )
        assert result["recommended_regime"] == "new"

    def test_max_deductions_old_regime(self):
        """
        Salary ₹12L with full deductions (1.5L 80C + 50k 80D + 50k NPS 1B + 50k std)
        Total deductions = 3L → taxable = 9L under old regime
        """
        result = compare_regimes(
            gross_total_income=1200000,
            deductions_old=300000,
        )
        # Both regimes should produce a result
        assert result["old_regime"]["taxable_income"] == 900000
        assert result["new_regime"]["taxable_income"] == 1150000  # 12L - 50k std deduction

    def test_zero_tax_scenario_87a(self):
        """₹7L income, new regime → zero tax after 87A rebate."""
        result = compare_regimes(
            gross_total_income=750000,   # after standard deduction = 7L
            deductions_old=50000,
        )
        # New regime: 7.5L - 50k = 7L → exact 87A limit → zero tax
        assert result["new_regime"]["total_tax"] == 0.0
