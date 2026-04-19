"""
Bank Statement Parser
======================
Extracts interest income, salary credits, and financial data from bank statement PDFs.
Supports: SBI, HDFC, ICICI, Axis (add patterns for other banks).

Why this matters for ITR-1:
  - Savings account interest → Section 80TTA deduction
  - FD interest → taxable under Other Sources
  - Salary credit cross-check against Form 16
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from typing import Optional

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


# ── Transaction model ─────────────────────────────────────────────────────────

@dataclass
class Transaction:
    date:        Optional[date] = None
    description: str           = ""
    debit:       float         = 0.0
    credit:      float         = 0.0
    balance:     float         = 0.0
    category:    str           = "unknown"   # salary/interest_savings/interest_fd/tax_deducted/other


# ── Output schema ─────────────────────────────────────────────────────────────

@dataclass
class BankStatementData:
    bank_name:           str           = "unknown"
    account_number:      Optional[str] = None
    account_holder:      Optional[str] = None
    ifsc:                Optional[str] = None
    statement_from:      Optional[str] = None
    statement_to:        Optional[str] = None

    # Extracted income items
    total_salary_credits:    float = 0.0
    savings_interest_earned: float = 0.0   # → 80TTA
    fd_interest_earned:      float = 0.0   # taxable other sources
    rd_interest_earned:      float = 0.0
    tds_on_interest:         float = 0.0   # → Schedule TDS2

    # All transactions
    transactions:            list = field(default_factory=list)
    salary_transactions:     list = field(default_factory=list)
    interest_transactions:   list = field(default_factory=list)

    parse_confidence:        float = 0.0
    warnings:                list  = field(default_factory=list)


# ── Bank-specific config ──────────────────────────────────────────────────────

BANK_PATTERNS = {
    "sbi": {
        "detect":      r"State\s+Bank\s+of\s+India|SBI",
        "header_row":  r"(Date|Txn\s+Date)\s+(Description|Narration|Particulars)",
        "date_format": ["%d/%m/%Y", "%d-%b-%Y", "%d %b %Y"],
        "col_order":   ["date", "description", "debit", "credit", "balance"],
    },
    "hdfc": {
        "detect":      r"HDFC\s+Bank|HDFC Bank Ltd",
        "header_row":  r"Date\s+Narration",
        "date_format": ["%d/%m/%y", "%d/%m/%Y"],
        "col_order":   ["date", "description", "debit", "credit", "balance"],
    },
    "icici": {
        "detect":      r"ICICI\s+Bank|ICICI Bank Ltd",
        "header_row":  r"(Transaction\s+Date|Value\s+Date)\s+(Transaction\s+Remarks|Narration)",
        "date_format": ["%d-%m-%Y", "%d/%m/%Y", "%d %b %Y"],
        "col_order":   ["date", "description", "debit", "credit", "balance"],
    },
    "axis": {
        "detect":      r"Axis\s+Bank|UTI\s+Bank",
        "header_row":  r"(Tran\s+Date|Transaction\s+Date)",
        "date_format": ["%d-%m-%Y", "%d %b %Y"],
        "col_order":   ["date", "description", "debit", "credit", "balance"],
    },
}


# ── Category classifiers ──────────────────────────────────────────────────────

SALARY_KEYWORDS = [
    r"\bsal(ary)?\b", r"\bneft\b.*sal", r"\bsal.*neft\b",
    r"\bmonthly\s+salary\b", r"\bbasic\b", r"\bemolument\b",
    r"\bpayroll\b", r"\bhr\d{4,}\b",  # common NEFT reference prefixes
]

SAVINGS_INTEREST_KEYWORDS = [
    r"\bint(erest)?\s+credited\b", r"\bsb\s+int(erest)?\b",
    r"\bsavings\s+interest\b", r"\binterest\s+on\s+sb\b",
    r"\bquarterly\s+int\b", r"\bmonthly\s+int\b",
    r"\btransferred\s+interest\b",
]

FD_INTEREST_KEYWORDS = [
    r"\bfd\s+int(erest)?\b", r"\bfixed\s+dep(osit)?\s+int\b",
    r"\bterm\s+dep(osit)?\s+int\b", r"\btd\s+int(erest)?\b",
    r"\bmaturity\s+int\b", r"\bfdr\s+int\b",
]

RD_INTEREST_KEYWORDS = [
    r"\brd\s+int(erest)?\b", r"\brecurring\s+dep(osit)?\s+int\b",
]

TDS_KEYWORDS = [
    r"\btds\s+deducted\b", r"\btax\s+deducted\s+at\s+source\b",
    r"\btds\s+on\s+int\b", r"\btax\s+deducted\b",
]


def _classify(description: str) -> str:
    desc = description.lower()
    for pat in SALARY_KEYWORDS:
        if re.search(pat, desc):
            return "salary"
    for pat in FD_INTEREST_KEYWORDS:
        if re.search(pat, desc):
            return "interest_fd"
    for pat in RD_INTEREST_KEYWORDS:
        if re.search(pat, desc):
            return "interest_rd"
    for pat in SAVINGS_INTEREST_KEYWORDS:
        if re.search(pat, desc):
            return "interest_savings"
    for pat in TDS_KEYWORDS:
        if re.search(pat, desc):
            return "tax_deducted"
    return "other"


# ── Table row parser ──────────────────────────────────────────────────────────

DATE_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%b-%Y", "%d %b %Y", "%d %b %y"]


def _parse_date(s: str) -> Optional[date]:
    s = s.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount_cell(s: str) -> float:
    if not s:
        return 0.0
    s = str(s).strip()
    # Remove Dr/Cr suffixes
    s = re.sub(r"\s*(Dr|Cr)\.?\s*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"[^\d.]", "", s)
    try:
        return float(s)
    except ValueError:
        return 0.0


def _detect_bank(text: str) -> str:
    for bank, cfg in BANK_PATTERNS.items():
        if re.search(cfg["detect"], text, re.IGNORECASE):
            return bank
    return "generic"


# ── Extract header info ────────────────────────────────────────────────────────

def _extract_header_info(text: str, result: BankStatementData):
    # Account number
    m = re.search(r"(?:Account\s+(?:No|Number)[.:\s]+)([\d\s\-X*]+)", text, re.IGNORECASE)
    if m:
        result.account_number = re.sub(r"\s", "", m.group(1)).strip()

    # Account holder
    m = re.search(r"(?:Name|Account\s+Holder)[:\s]+([A-Z][A-Z\s]+?)(?:\n|$)", text)
    if m:
        result.account_holder = m.group(1).strip()

    # IFSC
    m = re.search(r"IFSC[:\s]+([A-Z]{4}0[A-Z0-9]{6})", text, re.IGNORECASE)
    if m:
        result.ifsc = m.group(1)

    # Statement period
    m = re.search(r"(?:From|Period\s+From)[:\s]+(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", text, re.IGNORECASE)
    if m:
        result.statement_from = m.group(1)
    m = re.search(r"(?:To|Period\s+To)[:\s]+(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", text, re.IGNORECASE)
    if m:
        result.statement_to = m.group(1)


# ── Parse tables from pdfplumber ──────────────────────────────────────────────

def _parse_tables(tables: list, result: BankStatementData):
    """
    Try to find transaction table(s) and extract rows.
    pdfplumber returns: list of tables, each table = list of rows, each row = list of cell strings.
    """
    for table in tables:
        if not table or len(table) < 3:
            continue

        # Find header row
        header_idx = None
        for i, row in enumerate(table):
            row_text = " ".join(str(c or "") for c in row).lower()
            if any(k in row_text for k in ["date", "narration", "description", "debit", "credit"]):
                header_idx = i
                break

        if header_idx is None:
            continue

        header = [str(c or "").lower().strip() for c in table[header_idx]]

        # Map column indices
        def find_col(*keywords):
            for kw in keywords:
                for j, h in enumerate(header):
                    if kw in h:
                        return j
            return None

        date_col   = find_col("date", "txn date", "value date")
        desc_col   = find_col("narration", "description", "particulars", "remarks", "details")
        debit_col  = find_col("debit", "withdrawal", "dr")
        credit_col = find_col("credit", "deposit", "cr")
        bal_col    = find_col("balance", "bal")

        if date_col is None or desc_col is None:
            continue

        for row in table[header_idx + 1:]:
            if not row or all(c is None or str(c).strip() == "" for c in row):
                continue

            def safe(idx):
                if idx is None or idx >= len(row):
                    return ""
                return str(row[idx] or "").strip()

            txn_date = _parse_date(safe(date_col))
            if txn_date is None:
                continue

            desc   = safe(desc_col)
            debit  = _parse_amount_cell(safe(debit_col)) if debit_col is not None else 0.0
            credit = _parse_amount_cell(safe(credit_col)) if credit_col is not None else 0.0
            bal    = _parse_amount_cell(safe(bal_col)) if bal_col is not None else 0.0

            txn = Transaction(
                date=txn_date, description=desc,
                debit=debit, credit=credit, balance=bal,
                category=_classify(desc),
            )
            result.transactions.append(txn)


# ── Aggregate by category ─────────────────────────────────────────────────────

def _aggregate(result: BankStatementData):
    for txn in result.transactions:
        cat = txn.category
        if cat == "salary" and txn.credit > 0:
            result.total_salary_credits += txn.credit
            result.salary_transactions.append({
                "date": str(txn.date), "description": txn.description, "amount": txn.credit
            })
        elif cat == "interest_savings" and txn.credit > 0:
            result.savings_interest_earned += txn.credit
            result.interest_transactions.append({
                "date": str(txn.date), "type": "savings", "amount": txn.credit
            })
        elif cat == "interest_fd" and txn.credit > 0:
            result.fd_interest_earned += txn.credit
            result.interest_transactions.append({
                "date": str(txn.date), "type": "fd", "amount": txn.credit
            })
        elif cat == "interest_rd" and txn.credit > 0:
            result.rd_interest_earned += txn.credit
        elif cat == "tax_deducted" and txn.debit > 0:
            result.tds_on_interest += txn.debit


# ── Main entry point ──────────────────────────────────────────────────────────

def parse_bank_statement(pdf_path: str) -> BankStatementData:
    if pdfplumber is None:
        raise ImportError("pdfplumber required: pip install pdfplumber")

    result = BankStatementData()
    full_text = ""

    with pdfplumber.open(pdf_path) as pdf:
        all_tables = []
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
            full_text += text + "\n"
            tables = page.extract_tables()
            if tables:
                all_tables.extend(tables)

    result.bank_name = _detect_bank(full_text)
    _extract_header_info(full_text, result)
    _parse_tables(all_tables, result)

    # Fallback text-based extraction if tables empty
    if not result.transactions:
        result.warnings.append(
            "Could not extract transaction table via pdfplumber. "
            "Bank statement may be image-based. Run OCR first."
        )

    _aggregate(result)

    # Confidence
    checks = [
        result.total_salary_credits > 0,
        len(result.transactions) > 0,
        result.account_number is not None,
    ]
    result.parse_confidence = sum(checks) / len(checks)

    return result


def bank_statement_to_dict(data: BankStatementData) -> dict:
    d = asdict(data)
    # Convert date objects
    for txn in d.get("transactions", []):
        if txn.get("date"):
            txn["date"] = str(txn["date"])
    return d
