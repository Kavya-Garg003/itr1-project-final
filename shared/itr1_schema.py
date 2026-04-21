"""
ITR-1 (Sahaj) Form Schema — AY 2024-25
=======================================
Pydantic models for every field in the ITR-1 form.
Used by: doc-parser, agent-orchestrator, output-service.
"""

from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────────

class TaxRegime(str, Enum):
    NEW = "new"

class FilingStatus(str, Enum):
    ORIGINAL = "11"
    REVISED  = "12"
    BELATED  = "13"

class EmployerCategory(str, Enum):
    GOVT    = "GOV"
    PSU     = "PSU"
    OTHERS  = "OTH"
    PENSIONER = "PEN"
    NOT_APPLICABLE = "NA"

class ResidentialStatus(str, Enum):
    RESIDENT = "RES"
    NRI      = "NRI"
    RNOR     = "RNOR"


# ── Section: Personal Information ────────────────────────────────────────────

class PersonalInfo(BaseModel):
    pan:                Optional[str]  = None
    first_name:         Optional[str]  = None
    middle_name:        Optional[str]  = None
    last_name:          Optional[str]  = None
    dob:                Optional[str]  = None    # DD/MM/YYYY
    gender:             Optional[str]  = None    # M/F/T
    assessment_year:    str            = "2024-25"
    filing_status:      FilingStatus   = FilingStatus.ORIGINAL
    employer_category:  EmployerCategory = EmployerCategory.OTHERS
    residential_status: ResidentialStatus = ResidentialStatus.RESIDENT
    aadhaar:            Optional[str]  = None
    mobile:             Optional[str]  = None
    email:              Optional[str]  = None
    address_flat:       Optional[str]  = None
    address_street:     Optional[str]  = None
    address_city:       Optional[str]  = None
    address_state:      Optional[str]  = None
    address_pin:        Optional[str]  = None
    bank_account:       Optional[str]  = None    # for refund
    bank_ifsc:          Optional[str]  = None
    bank_name:          Optional[str]  = None


# ── Section: Salary Income (Schedule S) ──────────────────────────────────────

class SalaryIncome(BaseModel):
    """Maps to Schedule S of ITR-1."""

    # From Form 16 Part B / employer certificate
    gross_salary:                float = 0.0   # (a) Gross salary
    allowances_exempt_10_10:     float = 0.0   # Leave travel allowance (10(10))
    allowances_exempt_10_10a:    float = 0.0   # Death-cum-retirement (10(10A))
    allowances_exempt_10_13a:    float = 0.0   # HRA exemption (10(13A))
    allowances_exempt_10_14:     float = 0.0   # Special allowances (10(14))
    allowances_exempt_other:     float = 0.0   # Other exempt allowances
    total_exempt_allowances:     float = 0.0   # sum of above

    # Net values
    net_salary:                  float = 0.0   # gross - exempt
    standard_deduction_16ia:     float = 0.0   # Sec 16(ia) — ₹50,000 or salary, whichever less
    entertainment_allowance_16ii: float = 0.0  # Sec 16(ii) — only govt employees
    professional_tax_16iii:      float = 0.0   # Sec 16(iii)

    taxable_salary:              float = 0.0   # = net - standard deduction - prof tax

    # HRA working (for explainability)
    hra_received:                float = 0.0
    hra_basic_salary:            float = 0.0
    hra_rent_paid:               float = 0.0
    hra_city_type:               str   = "non-metro"  # metro/non-metro

    def compute(self):
        self.total_exempt_allowances = (
            self.allowances_exempt_10_10 + self.allowances_exempt_10_10a +
            self.allowances_exempt_10_13a + self.allowances_exempt_10_14 +
            self.allowances_exempt_other
        )
        self.net_salary = self.gross_salary - self.total_exempt_allowances
        self.standard_deduction_16ia = min(50000.0, self.net_salary)
        self.taxable_salary = max(
            0,
            self.net_salary - self.standard_deduction_16ia -
            self.entertainment_allowance_16ii - self.professional_tax_16iii
        )


# ── Section: House Property (Schedule HP) ────────────────────────────────────

class HousePropertyIncome(BaseModel):
    annual_value:             float = 0.0   # For self-occupied: 0
    municipal_tax_paid:       float = 0.0
    net_annual_value:         float = 0.0
    standard_deduction_30pct: float = 0.0   # 30% of NAV
    interest_on_loan_24b:     float = 0.0   # Sec 24(b) — max ₹2L for self-occupied
    total_income_hp:          float = 0.0   # Can be negative (loss)

    property_type: str = "self_occupied"   # self_occupied / let_out
    loan_outstanding: float = 0.0

    def compute(self):
        self.net_annual_value = max(0, self.annual_value - self.municipal_tax_paid)
        self.standard_deduction_30pct = self.net_annual_value * 0.30
        # Cap interest deduction for self-occupied at ₹2L
        cap = 200000.0 if self.property_type == "self_occupied" else float("inf")
        self.interest_on_loan_24b = min(self.interest_on_loan_24b, cap)
        self.total_income_hp = max(
            -200000.0,  # ITR-1 loss cap is ₹2L
            self.net_annual_value - self.standard_deduction_30pct - self.interest_on_loan_24b
        )


# ── Section: Other Sources Income (Schedule OS) ──────────────────────────────

class OtherSourcesIncome(BaseModel):
    savings_bank_interest:  float = 0.0   # 80TTA applies
    fd_interest:            float = 0.0
    recurring_deposit:      float = 0.0
    family_pension:         float = 0.0
    other_interest:         float = 0.0
    dividends:              float = 0.0
    other_income:           float = 0.0
    total_other_sources:    float = 0.0

    def compute(self):
        self.total_other_sources = (
            self.savings_bank_interest + self.fd_interest +
            self.recurring_deposit + self.family_pension +
            self.other_interest + self.dividends + self.other_income
        )


# ── Section: Chapter VI-A Deductions ─────────────────────────────────────────

class Deductions(BaseModel):
    """
    Deductions under Chapter VI-A.
    Note: Under new regime (115BAC), only 80CCD(2) and 80CCH are allowed.
    """
    # 80C family (total cap ₹1,50,000)
    sec_80c:           float = 0.0   # LIC, ELSS, PPF, tuition fees, home loan principal
    sec_80ccc:         float = 0.0   # Pension fund premium
    sec_80ccd_1:       float = 0.0   # Employee NPS contribution (within 80C cap)
    sec_80ccd_1b:      float = 0.0   # Additional NPS ₹50,000 (over 80C cap)
    sec_80ccd_2:       float = 0.0   # Employer NPS contribution (allowed in new regime)

    # Health
    sec_80d:           float = 0.0   # Health insurance premium (₹25K self + ₹25K parents)
    sec_80dd:          float = 0.0   # Disabled dependent
    sec_80ddb:         float = 0.0   # Medical treatment specified diseases

    # Education / other
    sec_80e:           float = 0.0   # Education loan interest
    sec_80ee:          float = 0.0   # Home loan interest (first-time buyer)
    sec_80gg:          float = 0.0   # House rent (no HRA)
    sec_80ggc:         float = 0.0   # Political party contribution
    sec_80tta:         float = 0.0   # Savings interest (non-senior) — max ₹10,000
    sec_80ttb:         float = 0.0   # Savings+FD interest (senior citizens) — max ₹50,000
    sec_80u:           float = 0.0   # Disabled person

    # Computed totals
    total_80c_family:  float = 0.0   # capped at ₹1,50,000
    total_deductions:  float = 0.0

    def compute(self, regime: TaxRegime = TaxRegime.NEW):
        # New regime: only 80CCD(2) allowed
        self.total_deductions = self.sec_80ccd_2
        self.total_80c_family = 0.0
        self.sec_80tta = 0.0
        self.sec_80ttb = 0.0


# ── Section: TDS Details (Schedule TDS1) ─────────────────────────────────────

class TDSEntry(BaseModel):
    employer_name:              Optional[str]   = None
    employer_tan:               Optional[str]   = None
    gross_salary_form16:        float           = 0.0
    tds_deducted:               float           = 0.0
    tds_claimed:                float           = 0.0


# ── Section: Tax Computation ──────────────────────────────────────────────────

class TaxComputation(BaseModel):
    regime:                  TaxRegime = TaxRegime.NEW
    gross_total_income:      float = 0.0
    total_deductions:        float = 0.0
    taxable_income:          float = 0.0
    tax_before_rebate:       float = 0.0
    rebate_87a:              float = 0.0
    tax_after_rebate:        float = 0.0
    surcharge:               float = 0.0
    health_education_cess:   float = 0.0
    total_tax_liability:     float = 0.0
    tds_deducted:            float = 0.0
    advance_tax_paid:        float = 0.0
    self_assessment_tax:     float = 0.0
    interest_234a:           float = 0.0
    interest_234b:           float = 0.0
    interest_234c:           float = 0.0
    fee_234f:                float = 0.0
    tax_payable:             float = 0.0
    refund:                  float = 0.0


# ── Confidence & Explainability ───────────────────────────────────────────────

class FieldConfidence(BaseModel):
    value:         float       # The filled value
    confidence:    float       # 0.0 to 1.0
    source:        str         # "form16", "bank_statement", "rag_inference", "manual"
    citation:      Optional[str] = None   # URL or document name
    explanation:   Optional[str] = None   # Why this value was filled
    flagged:       bool          = False  # Needs manual review


class ValidationFlag(BaseModel):
    field:       str
    severity:    str   # "error" / "warning" / "info"
    message:     str
    suggestion:  Optional[str] = None


# ── Master ITR-1 Form ─────────────────────────────────────────────────────────

class ITR1Form(BaseModel):
    """Complete ITR-1 form with all sections + confidence metadata."""

    # Form sections
    personal_info:        PersonalInfo           = Field(default_factory=PersonalInfo)
    salary_income:        SalaryIncome           = Field(default_factory=SalaryIncome)
    house_property:       HousePropertyIncome    = Field(default_factory=HousePropertyIncome)
    other_sources:        OtherSourcesIncome     = Field(default_factory=OtherSourcesIncome)
    deductions:           Deductions             = Field(default_factory=Deductions)
    tds_details:          list[TDSEntry]         = Field(default_factory=list)
    tax_computation:      TaxComputation         = Field(default_factory=TaxComputation)

    # Confidence & explainability (keyed by field path e.g. "salary_income.gross_salary")
    confidence_scores:    dict[str, FieldConfidence] = Field(default_factory=dict)
    validation_flags:     list[ValidationFlag]        = Field(default_factory=list)
    audit_trail:          list[dict]                  = Field(default_factory=list)

    # Metadata
    session_id:           Optional[str] = None
    created_at:           Optional[str] = None
    ay:                   str           = "AY2024-25"
