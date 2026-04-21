"""
Bank Statement Parser
=====================
Overhauled to use Hybrid Text-Vision extraction for maximum robustness.
"""

from __future__ import annotations
import sys
import json
import base64
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import fitz
from .pdf_utils import pdf_to_structured_text
from shared.llm_client import complete_with_system, complete_vision

@dataclass
class Transaction:
    date:        str
    description: str
    amount:      float
    category:    str   # "salary", "interest_savings", "interest_fd", "tax_deducted", "other"

@dataclass
class BankStatementData:
    bank_name:               Optional[str] = None
    account_number:          Optional[str] = None
    name:                    Optional[str] = None
    period_from:             Optional[str] = None
    period_to:               Optional[str] = None
    
    total_salary_credits:    float = 0.0
    total_savings_interest:  float = 0.0
    total_fd_interest:       float = 0.0
    total_tds_deducted:      float = 0.0
    
    transactions:            list[Transaction] = field(default_factory=list)
    parse_confidence:        float = 0.0
    warnings:                list  = field(default_factory=list)


def extract_pdf_images(pdf_path: str, max_pages: int = 5) -> list[str]:
    doc = fitz.open(pdf_path)
    b64_imgs = []
    zoom = fitz.Matrix(1.5, 1.5)
    for i in range(min(len(doc), max_pages)):
        page = doc.load_page(i)
        img_bytes = page.get_pixmap(matrix=zoom).tobytes("png")
        b64_imgs.append(base64.b64encode(img_bytes).decode("utf-8"))
    doc.close()
    return b64_imgs


def parse_bank_statement(pdf_path: str) -> BankStatementData:
    # 1. Try Structured Text Parsing first (Best for Digital PDFs)
    structured_text = pdf_to_structured_text(pdf_path)
    result_data = None
    
    system = """You are an elite bank statement extractor. 
Analyze the bank statement text (formatted as Markdown) and return ONLY a valid, raw JSON object. 
Fields: bank_name, account_number, name, period_from, period_to, total_salary_credits, total_savings_interest, total_fd_interest, total_tds_deducted.
Include a "transactions" list with: date, description, amount, category (salary|interest_savings|interest_fd|tax_deducted|other).
Convert all numbers to clean floats."""

    if len(structured_text.strip()) > 150:
        print("[BankStatement] Using Structured Text parsing...")
        try:
            response = complete_with_system(
                system=system,
                user=f"Extract data from this structured statement text:\n\n{structured_text[:12000]}"
            )
            cleaned = response.replace("```json", "").replace("```", "").strip()
            result_data = json.loads(cleaned)
        except Exception as e:
            print(f"[BankStatement] Text parsing failed: {e}")

    # 2. Vision Fallback (Only if Text Parsing failed or returned no data)
    if not result_data or not result_data.get("bank_name"):
        print("[BankStatement] Falling back to Vision AI (OCR)...")
        try:
            b64_images = extract_pdf_images(pdf_path, max_pages=5)
            response = complete_vision(
                prompt="Analyze this statement and return the requested JSON schema.",
                base64_images=b64_images,
                system=system
            )
            cleaned = response.replace("```json", "").replace("```", "").strip()
            result_data = json.loads(cleaned)
        except Exception as e:
            print(f"[BankStatement] Vision fallback failed: {e}")
            err = BankStatementData()
            err.warnings.append(f"Vision Parsing failed: {str(e)}")
            return err

    # 3. Build Final Object
    res = BankStatementData()
    txs = result_data.pop("transactions", [])
    
    # Fill basic fields
    for k, v in result_data.items():
        if hasattr(res, k) and v is not None:
            if isinstance(getattr(res, k), float):
                try:
                    clean_v = str(v).replace(",", "").replace(" ", "").strip()
                    setattr(res, k, float(clean_v) if clean_v else 0.0)
                except: pass
            else:
                setattr(res, k, str(v).strip())

    # Fill transactions
    for t in txs:
        try:
            res.transactions.append(Transaction(
                date=str(t.get("date", "")),
                description=str(t.get("description", "")),
                amount=float(str(t.get("amount", 0)).replace(",", "")),
                category=str(t.get("category", "other"))
            ))
        except: pass

    res.parse_confidence = 1.0
    return res


def bank_statement_to_dict(data: BankStatementData) -> dict:
    return asdict(data)
