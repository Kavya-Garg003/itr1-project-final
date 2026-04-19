"""
AIS (Annual Information Statement) & Form 26AS Parser
=======================================================
AIS is the new comprehensive statement on the income tax portal.
26AS is the older TDS credit statement.

Both are downloadable as PDFs from https://www.incometax.gov.in

Why this matters:
- Cross-verify TDS from Form 16 against what's actually deposited
- Catch mis-matches before filing (which trigger notices)
- Pick up TDS deducted by banks on FD interest (Schedule TDS2)
- Catch any high-value transactions flagged by portal (SFT data)

Usage:
    from parsers.ais import parse_ais
    data = parse_ais("ais_FY2023-24.pdf")
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


# ── Output schema ──────────────────────────────────────────────────────────────

@dataclass
class TDSCreditEntry:
    """One TDS deductor row — maps to Schedule TDS1 or TDS2 of ITR-1."""
    deductor_name:  str   = ""
    deductor_tan:   str   = ""
    deductor_pan:   str   = ""
    section:        str   = ""    # 192 (salary), 194A (interest), 194C, etc.
    gross_amount:   float = 0.0
    tds_deducted:   float = 0.0
    tds_deposited:  float = 0.0
    # Discrepancy flag: deducted ≠ deposited
    discrepancy:    float = 0.0
    quarter:        str   = ""    # Q1/Q2/Q3/Q4 or AY


@dataclass
class SFTEntry:
    """Specified Financial Transaction (high-value) from AIS Part D."""
    category:       str   = ""   # e.g., "Purchase of mutual funds"
    filer_name:     str   = ""
    filer_pan:      str   = ""
    amount:         float = 0.0
    remarks:        str   = ""


@dataclass
class AISData:
    # Header
    pan:                Optional[str] = None
    name:               Optional[str] = None
    assessment_year:    Optional[str] = None
    statement_type:     str           = "AIS"  # AIS or 26AS

    # TDS credits
    tds_salary:         list = field(default_factory=list)    # Sec 192 — Schedule TDS1
    tds_interest:       list = field(default_factory=list)    # Sec 194A — Schedule TDS2
    tds_other:          list = field(default_factory=list)

    # Totals
    total_tds_salary:      float = 0.0
    total_tds_interest:    float = 0.0
    total_tds_other:       float = 0.0

    # SFT / high-value transactions
    sft_entries:        list = field(default_factory=list)

    # Cross-check summary
    form16_salary_match: Optional[bool] = None   # set by reconciler
    discrepancies:       list = field(default_factory=list)

    parse_confidence:   float = 0.0
    warnings:           list  = field(default_factory=list)


# ── Regex patterns ─────────────────────────────────────────────────────────────

HEADER_PATTERNS = {
    "pan":             r"PAN[:\s]+([A-Z]{5}\d{4}[A-Z])",
    "name":            r"(?:Name\s+of\s+(?:Taxpayer|Assessee)|Taxpayer\s+Name)[:\s]+([^\n]+)",
    "assessment_year": r"Assessment\s+Year[:\s]+(20\d{2}-\d{2,4}|\d{4}-\d{2,4})",
}

# TDS table headers in 26AS / AIS PDFs
TDS_SECTION_PATTERNS = {
    "salary":   r"PART\s*A.*?(?=PART\s*B|PART\s*C|$)",
    "interest": r"PART\s*B.*?(?=PART\s*C|PART\s*D|$)",
}

TDS_ROW_PATTERN = re.compile(
    r"(?P<tan>[A-Z]{4}\d{5}[A-Z])\s+"       # TAN
    r"(?P<name>[A-Z][^\n]{4,50?}?)\s+"       # Deductor name (rough)
    r"(?P<section>1\d{2}[A-Z]?)\s+"          # Section (192, 194A, etc.)
    r"(?P<gross>[\d,]+\.?\d*)\s+"            # Gross amount
    r"(?P<tds>[\d,]+\.?\d*)"                 # TDS
)

AMOUNT_RE = re.compile(r"[\d,]+\.?\d*")


def _amount(s: str) -> float:
    try:
        return float(re.sub(r"[^\d.]", "", s))
    except (ValueError, TypeError):
        return 0.0


# ── Main parser ────────────────────────────────────────────────────────────────

def parse_ais(pdf_path: str) -> AISData:
    """Parse AIS or Form 26AS PDF and return structured data."""
    if pdfplumber is None:
        raise ImportError("pdfplumber required: pip install pdfplumber")

    result = AISData()
    full_text = ""
    all_tables = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
            full_text += text + "\n"
            for t in page.extract_tables():
                if t:
                    all_tables.append(t)

    # Detect statement type
    if "Annual Information Statement" in full_text:
        result.statement_type = "AIS"
    elif "26AS" in full_text or "Annual Tax Statement" in full_text:
        result.statement_type = "26AS"

    # Header extraction
    for field_name, pat in HEADER_PATTERNS.items():
        m = re.search(pat, full_text, re.IGNORECASE)
        if m:
            setattr(result, field_name, m.group(1).strip())

    # ── Table-based extraction ─────────────────────────────────────────────────
    for table in all_tables:
        if not table or len(table) < 2:
            continue

        header = [str(c or "").lower().strip() for c in (table[0] or [])]

        # Determine if this is a TDS table
        is_tds = any(k in " ".join(header) for k in ["tan", "deductor", "tds", "deducted"])
        is_sft = any(k in " ".join(header) for k in ["sft", "transaction", "specified"])

        def col(keywords: list[str]) -> Optional[int]:
            for kw in keywords:
                for i, h in enumerate(header):
                    if kw in h:
                        return i
            return None

        if is_tds:
            tan_col      = col(["tan"])
            name_col     = col(["deductor", "name"])
            section_col  = col(["section"])
            gross_col    = col(["gross", "amount paid", "total"])
            tds_col      = col(["tds", "tax deducted", "deducted"])
            dep_col      = col(["deposited", "remitted"])

            for row in table[1:]:
                if not row:
                    continue
                def cell(idx: Optional[int]) -> str:
                    if idx is None or idx >= len(row):
                        return ""
                    return str(row[idx] or "").strip()

                tan     = cell(tan_col)
                section = cell(section_col)
                gross   = _amount(cell(gross_col))
                tds     = _amount(cell(tds_col))
                dep     = _amount(cell(dep_col)) if dep_col else tds

                if not (re.match(r"[A-Z]{4}\d{5}[A-Z]", tan) or gross > 0):
                    continue

                entry = TDSCreditEntry(
                    deductor_tan  = tan,
                    deductor_name = cell(name_col),
                    section       = section,
                    gross_amount  = gross,
                    tds_deducted  = tds,
                    tds_deposited = dep,
                    discrepancy   = abs(tds - dep),
                )

                if entry.discrepancy > 1:
                    result.discrepancies.append({
                        "tan":        tan,
                        "name":       entry.deductor_name,
                        "deducted":   tds,
                        "deposited":  dep,
                        "difference": entry.discrepancy,
                    })

                # Route to salary vs interest
                if section in ("192", "192A"):
                    result.tds_salary.append(asdict(entry))
                    result.total_tds_salary += dep
                elif section in ("194A", "194",):
                    result.tds_interest.append(asdict(entry))
                    result.total_tds_interest += dep
                else:
                    result.tds_other.append(asdict(entry))
                    result.total_tds_other += dep

        if is_sft:
            cat_col    = col(["category", "type", "transaction"])
            name_col   = col(["filer", "name", "party"])
            amount_col = col(["amount", "value"])

            for row in table[1:]:
                if not row:
                    continue
                def cell(idx: Optional[int]) -> str:
                    if idx is None or idx >= len(row):
                        return ""
                    return str(row[idx] or "").strip()

                amt = _amount(cell(amount_col))
                if amt == 0:
                    continue
                result.sft_entries.append(asdict(SFTEntry(
                    category  = cell(cat_col),
                    filer_name= cell(name_col),
                    amount    = amt,
                )))

    # ── Fallback: regex on full text if tables empty ───────────────────────────
    if not result.tds_salary and not result.tds_interest:
        for m in TDS_ROW_PATTERN.finditer(full_text):
            section = m.group("section")
            entry = TDSCreditEntry(
                deductor_tan  = m.group("tan"),
                deductor_name = m.group("name").strip(),
                section       = section,
                gross_amount  = _amount(m.group("gross")),
                tds_deducted  = _amount(m.group("tds")),
                tds_deposited = _amount(m.group("tds")),
            )
            if section == "192":
                result.tds_salary.append(asdict(entry))
                result.total_tds_salary += entry.tds_deposited
            elif section == "194A":
                result.tds_interest.append(asdict(entry))
                result.total_tds_interest += entry.tds_deposited

    # ── Confidence ────────────────────────────────────────────────────────────
    checks = [
        result.pan is not None,
        len(result.tds_salary) > 0 or len(result.tds_interest) > 0,
        result.assessment_year is not None,
    ]
    result.parse_confidence = sum(checks) / len(checks)

    if result.discrepancies:
        result.warnings.append(
            f"{len(result.discrepancies)} TDS discrepancy(ies) found — "
            "tax deducted by employer ≠ amount deposited with govt. "
            "File only after employer rectifies via revised TDS return."
        )

    if result.parse_confidence < 0.5:
        result.warnings.append(
            "Low parse confidence — AIS/26AS may be image-based or in an unusual format. "
            "Download AIS as PDF (not JSON) from the income tax portal."
        )

    return result


# ── Reconciler: cross-check Form 16 vs AIS ────────────────────────────────────

def reconcile_form16_vs_ais(form16_data: dict, ais_data: AISData) -> dict:
    """
    Compare TDS from Form 16 with what AIS shows.
    Returns a reconciliation report used by the validator agent.
    """
    f16_tds = form16_data.get("tds_deducted_form16", 0)
    ais_tds = ais_data.total_tds_salary

    diff    = abs(f16_tds - ais_tds)
    matched = diff < 100   # Allow ₹100 rounding tolerance

    issues = []
    if not matched:
        issues.append(
            f"Form 16 shows TDS ₹{f16_tds:,.0f} but AIS shows ₹{ais_tds:,.0f} "
            f"(difference: ₹{diff:,.0f}). "
            "File only after the discrepancy is resolved. "
            "Contact your employer to check if TDS was deposited correctly."
        )

    if ais_data.discrepancies:
        for d in ais_data.discrepancies:
            issues.append(
                f"TDS discrepancy at {d['name']} (TAN: {d['tan']}): "
                f"deducted ₹{d['deducted']:,.0f} but deposited ₹{d['deposited']:,.0f}."
            )

    return {
        "form16_tds":    f16_tds,
        "ais_tds":       ais_tds,
        "difference":    diff,
        "matched":       matched,
        "issues":        issues,
        "bank_tds":      ais_data.total_tds_interest,   # goes to Schedule TDS2
        "sft_count":     len(ais_data.sft_entries),
        "sft_entries":   ais_data.sft_entries,
    }
