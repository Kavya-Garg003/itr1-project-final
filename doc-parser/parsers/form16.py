"""
Form 16 Parser (Part A + Part B)
==================================
Extracts salary, TDS, deductions from Form 16 PDF.
Handles both text-based and table-based Form 16 layouts.
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


def _compute_derived_form16(result: Form16Data):
    """Compute calculated fields based on extracted raw values."""
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

    # ── LLM-Powered Structured Extraction ──────────────────────────────────────────
    from .pdf_utils import pdf_to_structured_text
    structured_content = pdf_to_structured_text(pdf_path)
    
    if len(structured_content.strip()) > 100:
        print("[Form16] Using Structured LLM-on-Text parsing...")
        from shared.llm_client import complete_with_system
        
        prompt = f"Extract all Form 16 tax details from this structured text (Markdown tables included):\n\n{structured_content[:20000]}"
        system_prompt = (
            "You are an expert Indian tax document parser. "
            "Extract details into strict JSON. Return ONLY raw JSON. "
            "IMPORTANT: 'Gross Salary' is usually listed as 'Salary as per provisions contained in section 17(1)'. "
            "Keys: employer_name, employer_tan, employer_pan, employee_pan, employee_name, assessment_year, "
            "period_from, period_to, total_tds_deposited, gross_salary, salary_as_per_17_1, "
            "perquisites_17_2, profits_17_3, hra_10_13a, total_exempt_10, "
            "standard_deduction_16ia, entertainment_16ii, professional_tax_16iii, income_under_salary, "
            "sec_80c_claimed, sec_80ccc_claimed, sec_80ccd_1_claimed, sec_80ccd_2_claimed, sec_80d_claimed, "
            "total_vi_a_claimed, taxable_income_form16, tax_payable_form16, rebate_87a_form16, tds_deducted_form16. "
            "Use 0.0 for missing numeric fields."
        )

        def validate_llm_text(ans_str: str) -> bool:
            try:
                ans_str = ans_str.replace("```json", "").replace("```", "").strip()
                data = json.loads(ans_str)
                # Success if we find either Gross Salary OR Total TDS (minimum evidence of parsing)
                return float(str(data.get("gross_salary", 0)).replace(",", "")) > 0 or \
                       float(str(data.get("total_tds_deposited", 0)).replace(",", "")) > 0
            except: return False

        try:
            ans = complete_with_system(system_prompt, prompt, validate_fn=validate_llm_text)
            ans = ans.replace("```json", "").replace("```", "").strip()
            data = json.loads(ans)
            for k, v in data.items():
                if hasattr(result, k) and v is not None:
                    if isinstance(getattr(result, k), float):
                        try:
                            clean_v = str(v).replace(",", "").replace(" ", "").strip()
                            setattr(result, k, float(clean_v) if clean_v else 0.0)
                        except: pass
                    else:
                        setattr(result, k, str(v).strip())
            result.parse_confidence = 1.0
        except Exception as e:
            print(f"[Form16] LLM-on-Text failed: {e}")

    _compute_derived_form16(result)

    # ── Vision Fallback (Only if Text Parsing failed to find Salary) ────────────────
    if result.gross_salary == 0:
        print("[Form16] Gross Salary is still 0. Falling back to Vision AI (OCR)...")
        vision_result = _fallback_vision_form16(pdf_path)
        if vision_result and vision_result.gross_salary > 0:
            return vision_result
            
    # Final cross-check: if gross salary is 0 but we have income under salary, use that
    if result.gross_salary == 0 and result.income_under_salary > 0:
        result.gross_salary = result.income_under_salary + result.standard_deduction_16ia

    return result


def _fallback_vision_form16(pdf_path: str) -> Optional[Form16Data]:
    import fitz
    import base64
    from shared.llm_client import complete_vision
    
    try:
        import traceback
        doc = fitz.open(pdf_path)
        b64_images = []
        # Support longer Form 16s where Part B might be on page 3-5
        for i in range(min(6, len(doc))):
            pix = doc[i].get_pixmap(dpi=120)
            b64_images.append(base64.b64encode(pix.tobytes("jpeg")).decode("utf-8"))
        doc.close()
        
        system_prompt = (
            "You are an expert Indian tax document parser. "
            "Extract Form 16 details into strict JSON matching the requested keys. "
            "Return ONLY raw JSON, no markdown, no explanation. "
            "Keys: employer_name, employer_tan, employer_pan, employee_pan, employee_name, assessment_year, "
            "period_from, period_to, tds_q1, tds_q2, tds_q3, tds_q4, total_tds_deposited, gross_salary, "
            "salary_as_per_17_1, perquisites_17_2, profits_17_3, hra_10_13a, lta_10_10, total_exempt_10, "
            "standard_deduction_16ia, entertainment_16ii, professional_tax_16iii, income_under_salary, "
            "sec_80c_claimed, sec_80ccc_claimed, sec_80ccd_1_claimed, sec_80ccd_2_claimed, sec_80d_claimed, "
            "total_vi_a_claimed, taxable_income_form16, tax_payable_form16, rebate_87a_form16, tds_deducted_form16. "
            "Use 0.0 for missing numeric fields, null for missing strings."
        )
        
        def validate_form16_json(ans_str: str) -> bool:
            try:
                # Clean and parse JSON
                clean_ans = ans_str.replace("```json", "").replace("```", "").strip()
                data = json.loads(clean_ans)
                # We expect gross_salary to be non-zero for a valid Form 16 Part B
                gs = float(str(data.get("gross_salary", 0)).replace(",", ""))
                if gs > 0:
                    return True
                # Also check constituent fields if gross_salary is 0
                s171 = float(str(data.get("salary_as_per_17_1", 0)).replace(",", ""))
                if s171 > 0:
                    return True
                return False
            except:
                return False

        ans = complete_vision(
            "Extract Form 16 data as JSON. CRITICAL: Do NOT miss the Gross Salary (Sec 17(1)) usually found in Part B.",
            b64_images,
            system=system_prompt,
            validate_fn=validate_form16_json
        )
        ans = ans.replace("```json", "").replace("```", "").strip()
        data = json.loads(ans)
        
        result = Form16Data()
        for k, v in data.items():
            if hasattr(result, k) and v is not None:
                if isinstance(getattr(result, k), float):
                    try:
                        clean_v = str(v).replace(",", "").replace(" ", "").strip()
                        setattr(result, k, float(clean_v) if clean_v else 0.0)
                    except ValueError:
                        pass
                else:
                    setattr(result, k, str(v))
                    
        _compute_derived_form16(result)
        
        result.parse_confidence = 0.95
        result.warnings.append("Parsed using Vision AI Fallback (OpenRouter/Gemma-3).")
        return result
    except Exception as e:
        print(f"[Form16 Vision Fallback Error] {e}")
        import traceback
        traceback.print_exc()
        return None


def form16_to_dict(data: Form16Data) -> dict:
    return asdict(data)
