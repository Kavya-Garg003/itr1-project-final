"""
ITR-1 Excel Form Filler
========================
Takes parsed form data (from the agent pipeline) and fills the official
ITR1_AY_25-26_V1.7.xlsm spreadsheet, then exports it as a downloadable file.

Usage:
    from itr1_excel_filler import fill_itr1_excel
    output_path = fill_itr1_excel(itr_data, session_id)
"""

from __future__ import annotations
import copy
import shutil
import warnings
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore")

# Paths
PROJECT_ROOT  = Path(__file__).parent.parent
TEMPLATE_XLSM = PROJECT_ROOT / "knowledge-base" / "form_files" / "ITR1_AY_25-26_V1.7.xlsm"
OUTPUT_DIR    = PROJECT_ROOT / "agent-orchestrator" / "filled_forms"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ─── Cell mapping: (sheet_name, cell) → itr_data dot-path ──────────────────────
# Discovered by inspecting the actual xlsm structure.
# Format: "sheet.cell" → "json.path"

CELL_MAP: list[tuple[str, str, str]] = [

    # ── Part A: Personal Info ──────────────────────────────────────────────────
    # (These are in the 'Income Details' sheet header area — rows 1-34)
    ("Income Details", "AO9",  "personal_info.pan"),
    ("Income Details", "AO10", "personal_info.first_name"),
    ("Income Details", "AO11", "personal_info.last_name"),
    ("Income Details", "AO12", "personal_info.dob"),
    ("Income Details", "AO15", "personal_info.mobile"),
    ("Income Details", "AO16", "personal_info.email"),
    ("Income Details", "AO17", "personal_info.aadhaar"),
    ("Income Details", "AO19", "personal_info.address_flat"),
    ("Income Details", "AO20", "personal_info.address_street"),
    ("Income Details", "AO21", "personal_info.address_city"),
    ("Income Details", "AO22", "personal_info.address_state"),
    ("Income Details", "AO23", "personal_info.address_pin"),

    # ── Schedule S: Salary Income (rows 35-57) ─────────────────────────────────
    ("Income Details", "AO36", "salary_income.salary_as_per_17_1"),
    ("Income Details", "AO37", "salary_income.perquisites_17_2"),
    ("Income Details", "AO38", "salary_income.profits_17_3"),
    ("Income Details", "AO35", "salary_income.gross_salary"),      # Gross Salary = i
    ("Income Details", "AO50", "salary_income.allowances_exempt_10_13a"),  # HRA 10(13A)
    ("Income Details", "AO45", "salary_income.total_exempt_allowances"),   # Total allowances exempt
    ("Income Details", "AO52", "salary_income.net_salary"),        # Net Salary = iii
    ("Income Details", "AO54", "salary_income.standard_deduction_16ia"),   # Std ded 16(ia)
    ("Income Details", "AO55", "salary_income.entertainment_allowance_16ii"),
    ("Income Details", "AO56", "salary_income.professional_tax_16iii"),
    ("Income Details", "AO53", "salary_income.total_sec16_deductions"),
    ("Income Details", "AO57", "salary_income.taxable_salary"),    # v = income from salaries

    # ── Schedule HP: House Property (rows 58-65) ───────────────────────────────
    ("Income Details", "AO61", "house_property.net_annual_value"),
    ("Income Details", "AO62", "house_property.standard_deduction_30pct"),
    ("Income Details", "AO63", "house_property.interest_on_loan_24b"),
    ("Income Details", "AO65", "house_property.total_income_hp"),

    # ── Schedule OS: Other Sources (rows 66-91) ────────────────────────────────
    ("Income Details", "AO66", "other_sources.total_other_sources"),

    # ── Gross Total Income (row 92) ────────────────────────────────────────────
    ("Income Details", "AO92", "tax_computation.gross_total_income"),

    # ── Chapter VI-A Deductions (rows 96-120) ─────────────────────────────────
    ("Income Details", "AB96",  "deductions.sec_80c"),
    ("Income Details", "AB97",  "deductions.sec_80ccc"),
    ("Income Details", "AB98",  "deductions.sec_80ccd_1"),
    ("Income Details", "AB99",  "deductions.sec_80ccd_1b"),
    ("Income Details", "AN101", "deductions.sec_80ccd_2"),
    ("Income Details", "AB104", "deductions.sec_80d"),
    ("Income Details", "AB111", "deductions.sec_80e"),
    ("Income Details", "AB112", "deductions.sec_80ee"),
    ("Income Details", "AB115", "deductions.sec_80gg"),
    ("Income Details", "AB119", "deductions.sec_80ggc"),

    # ── Part B ATI: Tax Computation ────────────────────────────────────────────
    ("Part B ATI", "AO5",  "deductions.total_deductions"),       # Total Ch VI-A
    ("Part B ATI", "AO6",  "tax_computation.taxable_income"),    # Total Income
    ("Part B ATI", "AO9",  "tax_computation.tax_before_rebate"),
    ("Part B ATI", "AO11", "tax_computation.rebate_87a"),
    ("Part B ATI", "AO12", "tax_computation.tax_after_rebate"),
    ("Part B ATI", "AO14", "tax_computation.surcharge"),
    ("Part B ATI", "AO15", "tax_computation.health_education_cess"),
    ("Part B ATI", "AO16", "tax_computation.total_tax_liability"),

    # ── TDS Schedule TDS1 (employer TDS) ──────────────────────────────────────
    ("TDS", "E10",  "tds_details.0.employer_tan"),
    ("TDS", "N10",  "tds_details.0.employer_name"),
    ("TDS", "V10",  "tds_details.0.income_chargeable"),
    ("TDS", "Z10",  "tds_details.0.tds_deducted"),
    ("TDS", "AD10", "tds_details.0.tds_claimed"),

    # ── Taxes Paid and Verification ────────────────────────────────────────────
    ("Taxes Paid and Verification", "AO5",  "tax_computation.tds_deducted"),   # Total TDS claimed
    ("Taxes Paid and Verification", "AO7",  "tax_computation.total_taxes_paid"),
    ("Taxes Paid and Verification", "AO8",  "tax_computation.tax_payable"),
    ("Taxes Paid and Verification", "AO9",  "tax_computation.refund"),
    ("Taxes Paid and Verification", "AO12", "personal_info.bank_account_number"),
    ("Taxes Paid and Verification", "AO13", "personal_info.bank_ifsc"),

    # ── 80C sheet (detailed deductions) ───────────────────────────────────────
    # Row 9 is where user-entered 80C items go
]


def _get_nested(data: dict, dot_path: str) -> Any:
    """Traverse a dict using a dot-path like 'salary_income.gross_salary'."""
    parts = dot_path.split(".")
    cur = data
    for p in parts:
        if isinstance(cur, dict):
            cur = cur.get(p)
        elif isinstance(cur, list):
            try:
                cur = cur[int(p)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if cur is None:
            return None
    return cur


def _fmt(val: Any, is_numeric: bool = False) -> Any:
    """Format value for Excel cell."""
    if val is None:
        return "" if not is_numeric else 0
    if is_numeric:
        try:
            return round(float(val))
        except (ValueError, TypeError):
            return 0
    return str(val)


def fill_itr1_excel(itr_data: dict, session_id: str) -> Path:
    """
    Fill the official ITR-1 xlsm form with extracted data.
    Returns the path to the filled .xlsm file.

    itr_data should have the same structure as the pipeline output:
    {
        "itr1_form": { ... full ITR1Form dict ... },
        "confidence_scores": { ... },
        ...
    }
    """
    import uuid
    import win32com.client
    import pythoncom

    if not TEMPLATE_XLSM.exists():
        raise FileNotFoundError(f"Template not found: {TEMPLATE_XLSM}")

    unique_id = uuid.uuid4().hex[:8]
    out_path = OUTPUT_DIR / f"ITR1_filled_{session_id}_{unique_id}.xlsm"
    shutil.copy2(TEMPLATE_XLSM, out_path)

    form = itr_data.get("itr1_form", itr_data)

    pythoncom.CoInitialize()
    try:
        excel = win32com.client.Dispatch("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        excel.AutomationSecurity = 3

        wb = excel.Workbooks.Open(str(out_path.resolve()))
        
        filled_count = 0
        skipped = []
        
        def write_cell(sheet_name, cell_addr, value):
            try:
                wb.Sheets(sheet_name).Range(cell_addr).Value = value
                return True
            except Exception as e:
                skipped.append(str(e))
                return False

        for sheet_name, cell_addr, dot_path in CELL_MAP:
            val = _get_nested(form, dot_path)
            numeric_keys = {
                "salary", "income", "tax", "deduction", "tds", "rebate",
                "cess", "surcharge", "refund", "total", "gross", "net",
                "allowance", "exempt", "interest", "pension", "dividend",
            }
            is_num = any(k in dot_path for k in numeric_keys)
            formatted = _fmt(val, is_numeric=is_num)
            
            if formatted == 0 or formatted == "":
                continue

            if write_cell(sheet_name, cell_addr, formatted):
                filled_count += 1

        first = _get_nested(form, "personal_info.first_name") or ""
        last  = _get_nested(form, "personal_info.last_name")  or ""
        full_name = f"{first} {last}".strip()
        if full_name:
            write_cell("Taxes Paid and Verification", "AO2", full_name)

        pan = _get_nested(form, "personal_info.pan") or ""
        if pan:
            write_cell("Taxes Paid and Verification", "AO3", pan)

        sec_80c = _get_nested(form, "deductions.sec_80c") or 0
        if sec_80c and float(sec_80c) > 0:
            write_cell("80C", "D9", "Various (from Form 16)")
            write_cell("80C", "H9", round(float(sec_80c)))

        sec_80d = _get_nested(form, "deductions.sec_80d") or 0
        if sec_80d and float(sec_80d) > 0:
            write_cell("80D", "H5", round(float(sec_80d)))

        sbi  = _get_nested(form, "other_sources.savings_bank_interest") or 0
        fd   = _get_nested(form, "other_sources.fd_interest")           or 0
        div  = _get_nested(form, "other_sources.dividends")             or 0
        
        os_items = []
        if sbi and float(sbi) > 0: os_items.append(("Interest from Savings Bank", round(float(sbi))))
        if fd and float(fd) > 0:   os_items.append(("Interest from Deposits", round(float(fd))))
        if div and float(div) > 0: os_items.append(("Dividend Income", round(float(div))))

        rows = [68, 69, 70, 71]
        for i, (nature, amt) in enumerate(os_items[:4]):
            write_cell("Income Details", f"J{rows[i]}", nature)
            write_cell("Income Details", f"AO{rows[i]}", amt)
            filled_count += 2

        wb.Save()
        wb.Close(SaveChanges=False)
        excel.Quit()
        print(f"[ITR1Filler] Filled {filled_count} cells -> {out_path}")
    except Exception as e:
        print(f"[ITR1Filler] Excel COM Error: {e}")
        try:
            excel.Quit()
        except Exception:
            pass
    finally:
        pythoncom.CoUninitialize()

    return out_path


def get_filled_form_path(session_id: str) -> Path | None:
    """Return path to previously generated filled form, if it exists."""
    p = OUTPUT_DIR / f"ITR1_filled_{session_id}.xlsm"
    return p if p.exists() else None

def export_to_pdf_win32(excel_path: Path) -> Path:
    """Uses Excel COM object to save the filled XLSM as a PDF."""
    import win32com.client
    import pythoncom
    
    pdf_path = excel_path.with_suffix(".pdf")
    if pdf_path.exists():
        pdf_path.unlink()
        
    pythoncom.CoInitialize()
    excel = None
    try:
        excel = win32com.client.Dispatch("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        excel.AutomationSecurity = 3  # Disable macros to prevent popup
        
        wb = excel.Workbooks.Open(str(excel_path.resolve()))
        # Select sheets to print (excluding Help, Database, etc)
        sheets_to_print = ["Income Details", "TDS", "Taxes Paid and Verification", "SUMMARY"]
        # Filter to only existing sheets
        valid_sheets = [s.Name for s in wb.Sheets if s.Name in sheets_to_print]
        
        if valid_sheets:
            wb.WorkSheets(valid_sheets).Select()
            # 0 is the constant for xlTypePDF
            wb.ActiveSheet.ExportAsFixedFormat(0, str(pdf_path.resolve()))
        
        wb.Close(SaveChanges=False)
    except Exception as e:
        print(f"Failed to export PDF via win32com: {e}")
        raise
    finally:
        if excel:
            excel.Quit()
        pythoncom.CoUninitialize()
        
    return pdf_path
