"""
Form 16 Parser (Vision OCR via Free LLM Tier)
================================================
Overhauled to use GPT-4o style vision payloads over local PyMuPDF images.
"""

from __future__ import annotations
import sys
import json
import base64
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

# Setup absolute imports for shared library
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from shared.llm_client import complete_vision

import fitz  # PyMuPDF

@dataclass
class Form16Data:
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

    gross_salary:                     float = 0.0
    salary_as_per_17_1:               float = 0.0
    perquisites_17_2:                 float = 0.0
    profits_17_3:                     float = 0.0
    allowances_not_exempt:            float = 0.0

    hra_10_13a:            float = 0.0
    lta_10_10:             float = 0.0
    other_exempt_10:       float = 0.0
    total_exempt_10:       float = 0.0

    standard_deduction_16ia: float = 0.0
    entertainment_16ii:      float = 0.0
    professional_tax_16iii:  float = 0.0
    income_under_salary:     float = 0.0

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

    parse_confidence:      float = 0.0
    raw_text_snippet:      str   = ""
    warnings:              list  = field(default_factory=list)


def extract_pdf_images(pdf_path: str, max_pages: int = 3) -> list[str]:
    doc = fitz.open(pdf_path)
    b64_imgs = []
    zoom_matrix = fitz.Matrix(1.5, 1.5)
    for i in range(min(len(doc), max_pages)):
        page = doc.load_page(i)
        pix = page.get_pixmap(matrix=zoom_matrix)
        img_bytes = pix.tobytes("png")
        b64_imgs.append(base64.b64encode(img_bytes).decode("utf-8"))
    doc.close()
    return b64_imgs


def parse_form16(pdf_path: str) -> Form16Data:
    b64_images = extract_pdf_images(pdf_path, max_pages=3)
    
    system = """You are an expert tax document OCR extractor. Extract the requested fields from the uploaded Form 16 images.
Return ONLY a raw JSON object matching the requested schema exactly. Do not include markdown blocks like ```json.
Fields needed (return all keys exactly, value 0.0 or null if not found):
{
    "employer_name": "", "employer_tan": "", "employer_pan": "", 
    "employee_name": "", "employee_pan": "", "assessment_year": "AY2024-25",
    "period_from": "", "period_to": "", "total_tds_deposited": 0.0,
    "gross_salary": 0.0, "salary_as_per_17_1": 0.0, "perquisites_17_2": 0.0, "profits_17_3": 0.0,
    "hra_10_13a": 0.0, "lta_10_10": 0.0, "other_exempt_10": 0.0, "total_exempt_10": 0.0,
    "standard_deduction_16ia": 0.0, "professional_tax_16iii": 0.0,
    "income_under_salary": 0.0,
    "sec_80c_claimed": 0.0, "sec_80d_claimed": 0.0, "total_vi_a_claimed": 0.0,
    "taxable_income_form16": 0.0, "tax_payable_form16": 0.0,
    "rebate_87a_form16": 0.0, "tds_deducted_form16": 0.0
}
Extract all numeric values as clean floats (no commas).
"""
    
    prompt = "Extract the complete structured JSON representation of this Form 16."
    
    try:
        response_text = complete_vision(
            prompt=prompt,
            base64_images=b64_images,
            system=system,
            temperature=0.0
        )
        
        cleaned = response_text.replace("```json", "").replace("```", "").strip()
        data_dict = json.loads(cleaned)
        
        result = Form16Data(**{k: v for k, v in data_dict.items() if hasattr(Form16Data, k)})
        
        required = [result.gross_salary, result.income_under_salary, result.tds_deducted_form16]
        filled = sum(1 for v in required if v and v > 0)
        result.parse_confidence = (filled / len(required)) + 0.1
        
        if result.parse_confidence < 0.5:
            result.warnings.append("Vision model lacked confidence on core figures.")
            
        return result
        
    except Exception as e:
        err = Form16Data()
        err.warnings.append(f"Vision Parsing failed: {str(e)}")
        return err


def form16_to_dict(data: Form16Data) -> dict:
    return asdict(data)
