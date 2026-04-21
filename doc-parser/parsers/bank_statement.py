"""
Bank Statement Parser
=====================
Overhauled to use Vision model context window over heuristic PDF scraping.
"""

from __future__ import annotations
import sys
import json
import base64
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from shared.llm_client import complete_vision

import fitz

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
    b64_images = extract_pdf_images(pdf_path, max_pages=5)

    system = """You are an elite bank statement OCR extractor. 
Analyze the uploaded bank statement pages and return ONLY a valid, raw JSON object representing the aggregated data. 
Do not use markdown blocks like ```json.
Fields needed:
{
    "bank_name": "string (e.g. HDFC Bank, SBI)",
    "account_number": "string",
    "name": "string",
    "period_from": "string",
    "period_to": "string",
    "total_salary_credits": 0.0,
    "total_savings_interest": 0.0,
    "total_fd_interest": 0.0,
    "total_tds_deducted": 0.0,
    "transactions": [{"date": "string", "description": "string", "amount": 0.0, "category": "salary|interest_savings|interest_fd|tax_deducted|other"}]
}
For `transactions`, extract up to 5 defining entries related to your aggregate summations.
Convert all numbers to clean floats.
"""

    prompt = "Analyze this statement and calculate the aggregated income totals exactly matching the requested JSON schema."

    try:
        response_text = complete_vision(
            prompt=prompt,
            base64_images=b64_images,
            system=system,
            temperature=0.0
        )
        
        cleaned = response_text.replace("```json", "").replace("```", "").strip()
        data_dict = json.loads(cleaned)
        
        # Convert nested transactions
        txs = data_dict.pop("transactions", [])
        tx_objects = [Transaction(**t) for t in txs if isinstance(t, dict)]
        
        result = BankStatementData(**{k: v for k, v in data_dict.items() if hasattr(BankStatementData, k)})
        result.transactions = tx_objects
        
        result.parse_confidence = 0.9 if result.bank_name else 0.4
        
        return result
        
    except Exception as e:
        err = BankStatementData()
        err.warnings.append(f"Vision Parsing failed: {str(e)}")
        return err


def bank_statement_to_dict(data: BankStatementData) -> dict:
    return asdict(data)
