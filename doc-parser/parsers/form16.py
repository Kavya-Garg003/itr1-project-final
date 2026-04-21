"""
Form 16 Parser (Part A + Part B)
==================================
Extracts salary, TDS, deductions from Form 16 PDF.
Handles both text-based and table-based Form 16 layouts.

Banks/Employers usually issue Form 16 in one of these formats:
  - TRACES-generated (standard govt format) — text-rich, predictable labels
  - Employer-generated — variable format, needs fuzzy matching
"""

from __future__ import annotations
import re
import json
from dataclasses import dataclass, field, asdict
from typing import Optional

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


# ── Output schema ──────────────────────────────────────────────────────────────

@dataclass
class Form16Data:
    # Part A — Employer / TDS certificate
    employer_name:         Optional[str]   = None
    employer_tan:          Optional[str]   = None
    employer_pan:          Optional[str]   = None
    employee_pan:          Optional[str]   = None
    employee_name:         Optional[str]   = None
    assessment_year:       Optional[str]   = None
    period_from:           Optional[str]   = None
    period_to:             Optional[str]   = None
    tds_q1:                float           = 0.0
    tds_q2:                float           = 0.0
    tds_q3:                float           = 0.0
    tds_q4:                float           = 0.0
    total_tds_deposited:   float           = 0.0

    # Part B — Salary breakdown
    gross_salary:                     float = 0.0
    salary_as_per_17_1:               float = 0.0   # Salary as per 17(1)
    perquisites_17_2:                 float = 0.0   # Perquisites under 17(2)
    profits_17_3:                     float = 0.0   # Profits in lieu of salary 17(3)
    allowances_not_exempt:            float = 0.0

    # Exempt allowances (Sec 10)
    hra_10_13a:            float = 0.0
    lta_10_10:             float = 0.0
    other_exempt_10:       float = 0.0
    total_exempt_10:       float = 0.0

    # Deductions under Sec 16
    standard_deduction_16ia: float = 0.0
    entertainment_16ii:      float = 0.0
    professional_tax_16iii:  float = 0.0

    # Income under head salary (net)
    income_under_salary:   float = 0.0

    # Deductions claimed via employer (in Form 16 Part B)
    sec_80c_claimed:       float = 0.0
    sec_80ccc_claimed:     float = 0.0
    sec_80ccd_1_claimed:   float = 0.0
    sec_80ccd_2_claimed:   float = 0.0
    sec_80d_claimed:       float = 0.0
    total_vi_a_claimed:    float = 0.0

    taxable_income_form16: float = 0.0
    tax_payable_form16:    float = 0.0
    tds_deducted_form16:   float = 0.0
    rebate_87a_form16:     float = 0.0

    # Extraction metadata
    parse_confidence:      float = 0.0   # 0.0–1.0
    raw_text_snippet:      str   = ""
    warnings:              list  = field(default_factory=list)


# ── Label patterns (works for TRACES standard format) ─────────────────────────

PART_A_PATTERNS = {
    "employer_name":       [r"Name\s+of\s+(?:the\s+)?(?:Employer|Deductor)[:\s]+([^\n]+)"],
    "employer_tan":        [r"TAN\s+of\s+(?:the\s+)?(?:Employer|Deductor)[:\s]+([\w\d]+)"],
    "employer_pan":        [r"PAN\s+of\s+(?:the\s+)?(?:Employer|Deductor)[:\s]+([\w\d]+)"],
    "employee_pan":        [r"PAN\s+of\s+(?:the\s+)?(?:Employee|Deductee)[:\s]+([\w\d]+)"],
    "employee_name":       [r"Name\s+of\s+(?:the\s+)?(?:Employee|Deductee)[:\s]+([^\n]+)"],
    "assessment_year":     [r"Assessment\s+Year[:\s]+(20\d{2}-\d{2,4}|\d{4}-\d{2,4})"],
    "period_from":         [r"Period\s+From[:\s]+([^\n]+?)\s+To"],
    "period_to":           [r"Period\s+.*?To[:\s]+([^\n]+)"],
    "total_tds_deposited": [r"Total\s+amount\s+of\s+tax\s+deposited[:\s]+([\d,]+\.?\d*)"],
}

PART_B_PATTERNS = {
    "salary_as_per_17_1":         [r"Salary\s+as\s+per\s+provisions\s+contained\s+in\s+section\s+17\(1\)[:\s]*([\d,]+\.?\d*)"],
    "perquisites_17_2":           [r"Value\s+of\s+perquisites\s+under\s+section\s+17\(2\)[:\s]*([\d,]+\.?\d*)"],
    "profits_17_3":               [r"Profits\s+in\s+lieu\s+of\s+salary\s+under\s+section\s+17\(3\)[:\s]*([\d,]+\.?\d*)"],
    "gross_salary":               [r"Gross\s+Salary[:\s]+\(a\+b\+c\)[:\s]*([\d,]+\.?\d*)",
                                   r"Gross\s+Salary[:\s]*([\d,]+\.?\d*)"],
    "hra_10_13a":                 [r"House\s+Rent\s+Allowance\s+(?:u/s|under\s+section)\s+10\(13A\)[:\s]*([\d,]+\.?\d*)"],
    "lta_10_10":                  [r"Leave\s+Travel\s+(?:Allowance|Concession)[:\s]*([\d,]+\.?\d*)"],
    "total_exempt_10":            [r"Total\s+amount\s+of\s+(?:salary|exemptions)\s+exempt\s+under\s+[Ss]ection\s+10[:\s]*([\d,]+\.?\d*)"],
    "standard_deduction_16ia":    [r"Standard\s+[Dd]eduction\s+u/s\s+16\(ia\)[:\s]*([\d,]+\.?\d*)",
                                   r"Standard\s+[Dd]eduction[:\s]*([\d,]+\.?\d*)"],
    "entertainment_16ii":         [r"Entertainment\s+allowance\s+u/s\s+16\(ii\)[:\s]*([\d,]+\.?\d*)"],
    "professional_tax_16iii":     [r"Professional\s+[Tt]ax\s+u/s\s+16\(iii\)[:\s]*([\d,]+\.?\d*)",
                                   r"Tax\s+on\s+employment[:\s]*([\d,]+\.?\d*)"],
    "income_under_salary":        [r"Income\s+(?:chargeable\s+)?under\s+(?:the\s+)?head\s+[\"']?Salaries[\"']?[:\s]*([\d,]+\.?\d*)"],
    "sec_80c_claimed":            [r"80C[:\s]*([\d,]+\.?\d*)"],
    "sec_80ccc_claimed":          [r"80CCC[:\s]*([\d,]+\.?\d*)"],
    "sec_80ccd_1_claimed":        [r"80CCD\(1\)[:\s]*([\d,]+\.?\d*)"],
    "sec_80ccd_2_claimed":        [r"80CCD\(2\)[:\s]*([\d,]+\.?\d*)"],
    "sec_80d_claimed":            [r"80D[:\s]*([\d,]+\.?\d*)"],
    "total_vi_a_claimed":         [r"(?:Total|Aggregate)\s+(?:of\s+)?(?:deductions|deduction)\s+(?:under\s+)?Chapter\s+VI-A[:\s]*([\d,]+\.?\d*)"],
    "taxable_income_form16":      [r"(?:Total\s+)?taxable\s+income[:\s]*([\d,]+\.?\d*)",
                                   r"Net\s+income\s+taxable[:\s]*([\d,]+\.?\d*)"],
    "tax_payable_form16":         [r"Tax\s+(?:on\s+)?total\s+income[:\s]*([\d,]+\.?\d*)"],
    "rebate_87a_form16":          [r"Rebate\s+u/s\s+87A[:\s]*([\d,]+\.?\d*)"],
    "tds_deducted_form16":        [r"(?:Total\s+)?(?:Amount\s+of\s+)?TDS\s+(?:deducted|deposited)[:\s]*([\d,]+\.?\d*)"],
}


def _parse_amount(text: str) -> float:
    """Convert '1,23,456.78' or '123456' to float."""
    clean = re.sub(r"[^\d.]", "", text)
    try:
        return float(clean)
    except ValueError:
        return 0.0


def _extract_field(patterns: list[str], text: str) -> Optional[str]:
    """Try multiple regex patterns, return first match."""
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
        if m:
            return m.group(1).strip()
    return None


def _extract_tds_quarters(text: str) -> tuple[float, float, float, float]:
    """Extract quarterly TDS from TRACES Part A table."""
    q = [0.0, 0.0, 0.0, 0.0]
    # Pattern: Q1 / Q2 / Q3 / Q4 rows or columns
    for i, label in enumerate(["Q1", "Q2", "Q3", "Q4"]):
        m = re.search(rf"{label}.*?([\d,]+\.?\d*)", text, re.IGNORECASE)
        if m:
            q[i] = _parse_amount(m.group(1))
    return tuple(q)


# ── Main parser ───────────────────────────────────────────────────────────────

def parse_form16(pdf_path: str) -> Form16Data:
    """
    Parse Form 16 PDF and return structured Form16Data.
    Supports TRACES-generated and employer-generated formats.
    """
    if pdfplumber is None:
        raise ImportError("pdfplumber required: pip install pdfplumber")

    result = Form16Data()
    full_text = ""
    tables_data = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
            full_text += text + "\n"
            for table in page.extract_tables():
                if table:
                    tables_data.append(table)

    result.raw_text_snippet = full_text[:500]

    # ── Part A extraction ──────────────────────────────────────────────────────
    for field_name, patterns in PART_A_PATTERNS.items():
        val = _extract_field(patterns, full_text)
        if val:
            if field_name == "total_tds_deposited":
                setattr(result, field_name, _parse_amount(val))
            else:
                setattr(result, field_name, val.strip())

    q1, q2, q3, q4 = _extract_tds_quarters(full_text)
    result.tds_q1, result.tds_q2, result.tds_q3, result.tds_q4 = q1, q2, q3, q4
    if not result.total_tds_deposited:
        result.total_tds_deposited = q1 + q2 + q3 + q4

    # ── Part B extraction ──────────────────────────────────────────────────────
    for field_name, patterns in PART_B_PATTERNS.items():
        val = _extract_field(patterns, full_text)
        if val:
            setattr(result, field_name, _parse_amount(val))

    # ── Table-based extraction (fallback / cross-check) ────────────────────────
    for table in tables_data:
        for row in table:
            if not row or len(row) < 2:
                continue
            label = str(row[0] or "").strip().lower()
            value_cell = None
            for cell in row[1:]:
                if cell and re.search(r"[\d,]+", str(cell)):
                    value_cell = cell
                    break
            if value_cell is None:
                continue
            amount = _parse_amount(str(value_cell))

            if "gross salary" in label and result.gross_salary == 0:
                result.gross_salary = amount
            elif "standard deduction" in label and result.standard_deduction_16ia == 0:
                result.standard_deduction_16ia = amount
            elif "professional tax" in label and result.professional_tax_16iii == 0:
                result.professional_tax_16iii = amount
            elif "rebate" in label and "87" in label:
                result.rebate_87a_form16 = amount

    # ── Derived / fallback calculations ───────────────────────────────────────
    if result.gross_salary == 0:
        result.gross_salary = result.salary_as_per_17_1 + result.perquisites_17_2 + result.profits_17_3
    if result.total_exempt_10 == 0:
        result.total_exempt_10 = result.hra_10_13a + result.lta_10_10 + result.other_exempt_10
    if result.standard_deduction_16ia == 0 and result.gross_salary:
        result.standard_deduction_16ia = min(50000, result.gross_salary)
    if result.income_under_salary == 0:
        result.income_under_salary = (
            result.gross_salary
            - result.total_exempt_10
            - result.standard_deduction_16ia
            - result.entertainment_16ii
            - result.professional_tax_16iii
        )
    if result.tds_deducted_form16 == 0:
        result.tds_deducted_form16 = result.total_tds_deposited

    # ── Confidence scoring ─────────────────────────────────────────────────────
    required = [result.gross_salary, result.income_under_salary, result.tds_deducted_form16]
    filled   = sum(1 for v in required if v > 0)
    result.parse_confidence = filled / len(required)

    if result.parse_confidence < 0.5:
        result.warnings.append(
            "Low confidence parse — Form 16 may be scanned/image-based or in an unusual format. "
            "Consider running OCR pre-processing (e.g. pdf2image + pytesseract)."
        )

    return result


def form16_to_dict(data: Form16Data) -> dict:
    return asdict(data)
