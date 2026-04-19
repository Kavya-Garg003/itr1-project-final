"""
ITR Form Schema Loader
========================
Reads the official ITR-1 JSON schema and Excel field map you downloaded
from the income tax portal and wires them into the form-filling agent.

Files it reads from knowledge-base/form_files/:
  itr1_schema_AY2024-25.json     ← official JSON schema (from ITD utility)
  itr1_fields_AY2024-25.xlsx     ← field map / validation rules (Excel)
  ITR1.pdf                       ← the actual blank Sahaj form (for reference)

What it produces:
  knowledge-base/form_files/field_map.json  ← canonical field → path mapping
  Used by: agent-orchestrator/graph/itr_graph.py (node_fill_form)

Run standalone to inspect:
    python itr_form_schema_loader.py
    python itr_form_schema_loader.py --inspect   # prints all field paths
"""

from __future__ import annotations
import json
import re
import argparse
from pathlib import Path
from typing import Optional, Any

FORM_DIR = Path("knowledge-base/form_files")
FORM_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_FIELD_MAP = FORM_DIR / "field_map.json"


# ── Official ITR-1 field → our schema path mapping ────────────────────────────
# This is the authoritative mapping that connects the ITR XML/JSON field names
# (as used in the official ITD offline utility) to our itr1_schema.py paths.
# If your downloaded JSON schema has different field names, update this dict.

OFFICIAL_FIELD_TO_SCHEMA_PATH: dict[str, str] = {
    # Part A — Personal Info
    "PAN":                          "personal_info.pan",
    "FirstName":                    "personal_info.first_name",
    "MiddleName":                   "personal_info.middle_name",
    "SurNameOrOrgName":             "personal_info.last_name",
    "DOB":                          "personal_info.dob",
    "AadhaarCardNo":                "personal_info.aadhaar",
    "MobileNo":                     "personal_info.mobile",
    "EmailAddress":                 "personal_info.email",
    "FlatDoorBlockNo":              "personal_info.address_flat",
    "NameBuildingVillage":          "personal_info.address_street",
    "CityOrTownOrDistrict":         "personal_info.address_city",
    "StateCd":                      "personal_info.address_state",
    "PinCode":                      "personal_info.address_pin",

    # Part B — Salary Schedule S
    "GrossSalary":                  "salary_income.gross_salary",
    "Salary17_1":                   "salary_income.salary_as_per_17_1",
    "ValueOfPerquisites17_2":       "salary_income.perquisites_17_2",
    "ProfitsInLieuOfSalary17_3":    "salary_income.profits_17_3",
    "ExemptAllowances":             "salary_income.total_exempt_allowances",
    "HRAExemption":                 "salary_income.allowances_exempt_10_13a",
    "LTAExemption":                 "salary_income.allowances_exempt_10_10",
    "NetSalary":                    "salary_income.net_salary",
    "DeductionUs16ia":              "salary_income.standard_deduction_16ia",
    "EntertainmentAllow16ii":       "salary_income.entertainment_allowance_16ii",
    "ProfessionalTaxUs16iii":       "salary_income.professional_tax_16iii",
    "IncomeFromSalaries":           "salary_income.taxable_salary",

    # HP Schedule
    "AnnualLetableValue":           "house_property.annual_value",
    "TaxPaidLocalAuthorities":      "house_property.municipal_tax_paid",
    "AnnualValueOfHP":              "house_property.net_annual_value",
    "StandardDeduction":            "house_property.standard_deduction_30pct",
    "InterestPayable":              "house_property.interest_on_loan_24b",
    "IncomeFromHP":                 "house_property.total_income_hp",

    # OS Schedule
    "GrossIncomeOS":                "other_sources.total_other_sources",
    "IntrstFrmSavingBank":          "other_sources.savings_bank_interest",
    "IntrstFrmDeposits":            "other_sources.fd_interest",
    "IntrstFrmTaxRefund":           "other_sources.other_interest",
    "FamilyPension":                "other_sources.family_pension",
    "DividendGross":                "other_sources.dividends",

    # Gross Total Income
    "GrossTotalIncome":             "tax_computation.gross_total_income",

    # Deductions Chapter VI-A
    "Section80C":                   "deductions.sec_80c",
    "Section80CCC":                 "deductions.sec_80ccc",
    "Section80CCD1":                "deductions.sec_80ccd_1",
    "Section80CCD1B":               "deductions.sec_80ccd_1b",
    "Section80CCD2":                "deductions.sec_80ccd_2",
    "Section80D":                   "deductions.sec_80d",
    "Section80DD":                  "deductions.sec_80dd",
    "Section80DDB":                 "deductions.sec_80ddb",
    "Section80E":                   "deductions.sec_80e",
    "Section80EE":                  "deductions.sec_80ee",
    "Section80G":                   "deductions.sec_80gg",
    "Section80GGC":                 "deductions.sec_80ggc",
    "Section80TTA":                 "deductions.sec_80tta",
    "Section80TTB":                 "deductions.sec_80ttb",
    "Section80U":                   "deductions.sec_80u",
    "TotalChapVIADeductions":       "deductions.total_deductions",

    # Tax computation
    "TotalIncome":                  "tax_computation.taxable_income",
    "TaxAtNormalRatesOnAI":         "tax_computation.tax_before_rebate",
    "RebateUnderSection87A":        "tax_computation.rebate_87a",
    "TaxAfterRebate":               "tax_computation.tax_after_rebate",
    "Surcharge":                    "tax_computation.surcharge",
    "HealthAndEduCess":             "tax_computation.health_education_cess",
    "TotalTaxPayable":              "tax_computation.total_tax_liability",
    "TaxPayable":                   "tax_computation.tax_payable",
    "Refund":                       "tax_computation.refund",

    # TDS Schedule TDS1
    "TDS1_TotalTaxDeducted":        "tds_details.0.tds_deducted",
    "TDS1_TotalTaxClaimed":         "tds_details.0.tds_claimed",
    "TDS1_EmployerName":            "tds_details.0.employer_name",
    "TDS1_TANOfDeductor":           "tds_details.0.employer_tan",
}


# ── Validation rules (extracted from Excel / ITD utility) ──────────────────────
# These match the official ITR-1 validation rules published by ITD.

VALIDATION_RULES: dict[str, dict] = {
    "personal_info.pan": {
        "pattern": r"^[A-Z]{5}\d{4}[A-Z]$",
        "message": "PAN must be 10 characters: 5 letters, 4 digits, 1 letter (e.g. ABCDE1234F)",
    },
    "personal_info.aadhaar": {
        "pattern": r"^\d{12}$",
        "message": "Aadhaar must be exactly 12 digits",
    },
    "salary_income.gross_salary": {
        "min": 0,
        "max": 50000000,
        "message": "Gross salary must be between ₹0 and ₹5 crore for ITR-1",
    },
    "tax_computation.gross_total_income": {
        "min": 0,
        "max": 50000000,
        "message": "Total income above ₹50 lakh — use ITR-2, not ITR-1",
    },
    "deductions.sec_80c": {
        "min": 0,
        "max": 150000,
        "message": "80C deduction cannot exceed ₹1,50,000",
    },
    "deductions.sec_80ccd_1b": {
        "min": 0,
        "max": 50000,
        "message": "80CCD(1B) additional NPS deduction cannot exceed ₹50,000",
    },
    "deductions.sec_80tta": {
        "min": 0,
        "max": 10000,
        "message": "80TTA deduction cannot exceed ₹10,000",
    },
    "deductions.sec_80ttb": {
        "min": 0,
        "max": 50000,
        "message": "80TTB deduction cannot exceed ₹50,000 (available only to senior citizens)",
    },
    "salary_income.standard_deduction_16ia": {
        "min": 0,
        "max": 50000,
        "message": "Standard deduction cannot exceed ₹50,000",
    },
    "house_property.interest_on_loan_24b": {
        "min": -200000,
        "max": 0,
        "when": "property_type == self_occupied",
        "message": "Interest on home loan for self-occupied property is capped at ₹2,00,000 loss",
    },
}


# ── JSON schema reader ─────────────────────────────────────────────────────────

def load_json_schema(json_path: Path) -> dict:
    """
    Read the official ITR-1 JSON schema downloaded from ITD utility.
    Returns a normalized dict: { official_field_name → {"type": ..., "required": ...} }
    """
    try:
        with open(json_path, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        print(f"  ✗ Could not read {json_path}: {e}")
        return {}

    # ITD JSON schemas vary in structure — handle both flat and nested
    fields: dict[str, dict] = {}

    def _walk(obj: Any, prefix: str = ""):
        if isinstance(obj, dict):
            if "type" in obj or "description" in obj:
                fields[prefix.lstrip(".")] = {
                    "type":     obj.get("type", "string"),
                    "required": obj.get("required", False),
                    "desc":     obj.get("description", ""),
                    "min":      obj.get("minimum", None),
                    "max":      obj.get("maximum", None),
                }
            for k, v in obj.items():
                if k not in ("type", "description", "required", "minimum", "maximum", "enum"):
                    _walk(v, f"{prefix}.{k}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _walk(item, f"{prefix}[{i}]")

    _walk(raw)
    return fields


# ── Excel field map reader ─────────────────────────────────────────────────────

def load_excel_field_map(xlsx_path: Path) -> dict:
    """
    Read Excel field map downloaded from ITD / CBDT.
    Typically has columns: Field Name | Schedule | Description | Min | Max | Validation
    """
    try:
        import openpyxl
        wb = openpyxl.load_workbook(str(xlsx_path), read_only=True, data_only=True)
    except ImportError:
        print("  openpyxl not installed. Run: pip install openpyxl")
        return {}
    except Exception as e:
        print(f"  ✗ Could not read {xlsx_path}: {e}")
        return {}

    result: dict[str, dict] = {}
    for sheet in wb.worksheets:
        headers: list[str] = []
        for i, row in enumerate(sheet.iter_rows(values_only=True)):
            if i == 0:
                headers = [str(c or "").lower().strip() for c in row]
                continue
            if not any(row):
                continue
            entry: dict[str, Any] = {}
            for j, val in enumerate(row):
                if j < len(headers) and headers[j]:
                    entry[headers[j]] = val

            # Extract field name (first non-empty column usually)
            name = str(entry.get("field name", "") or entry.get("field", "") or "").strip()
            if name:
                result[name] = entry

    wb.close()
    return result


# ── Generate merged field map ──────────────────────────────────────────────────

def build_field_map(
    json_schema: dict = None,
    excel_map:   dict = None,
) -> dict:
    """
    Merge official field map + your schema path mapping.
    Output: { official_field → { schema_path, type, required, validation, ... } }
    """
    field_map: dict[str, dict] = {}

    for official_name, schema_path in OFFICIAL_FIELD_TO_SCHEMA_PATH.items():
        entry: dict[str, Any] = {
            "official_name": official_name,
            "schema_path":   schema_path,
            "type":          "number" if any(k in schema_path for k in
                             ["salary", "income", "tax", "deduction", "tds", "rebate", "cess"]) else "string",
            "required":      official_name in ("PAN", "GrossTotalIncome", "TotalIncome", "TotalTaxPayable"),
        }

        # Merge from JSON schema if available
        if json_schema and official_name in json_schema:
            js = json_schema[official_name]
            entry.update({k: v for k, v in js.items() if v is not None})

        # Merge from Excel if available
        if excel_map and official_name in excel_map:
            em = excel_map[official_name]
            entry.update({k: v for k, v in em.items() if v is not None})

        # Add validation rule if we have one
        if schema_path in VALIDATION_RULES:
            entry["validation"] = VALIDATION_RULES[schema_path]

        field_map[official_name] = entry

    return field_map


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inspect", action="store_true", help="Print all field mappings")
    args = parser.parse_args()

    print(f"\n📋 ITR Form Schema Loader")
    print(f"   Looking in: {FORM_DIR}/\n")

    # Load JSON schema if present
    json_schema = {}
    for json_path in sorted(FORM_DIR.glob("*.json")):
        if "field_map" in json_path.name:
            continue
        print(f"  Loading JSON schema: {json_path.name}")
        js = load_json_schema(json_path)
        json_schema.update(js)
        print(f"  → {len(js)} fields extracted")

    # Load Excel field map if present
    excel_map = {}
    for xlsx_path in sorted(FORM_DIR.glob("*.xlsx")):
        print(f"  Loading Excel field map: {xlsx_path.name}")
        em = load_excel_field_map(xlsx_path)
        excel_map.update(em)
        print(f"  → {len(em)} rows extracted")

    # Build merged field map
    field_map = build_field_map(json_schema, excel_map)

    # Save
    with open(OUTPUT_FIELD_MAP, "w", encoding="utf-8") as f:
        json.dump(field_map, f, ensure_ascii=False, indent=2)
    print(f"\n✓ Field map saved → {OUTPUT_FIELD_MAP}")
    print(f"  {len(field_map)} fields mapped")

    if args.inspect:
        print("\nField mapping table:")
        print(f"{'Official Field':<35} {'Schema Path':<45} {'Required'}")
        print("-" * 90)
        for name, info in sorted(field_map.items()):
            req = "✓" if info.get("required") else ""
            print(f"{name:<35} {info['schema_path']:<45} {req}")

    print("\nThis field_map.json is used automatically by the agent when filling ITR-1 fields.")
    print("No other changes needed — the agent imports it on startup.")


# ── Import-friendly getter ─────────────────────────────────────────────────────

def get_field_map() -> dict:
    """
    Called by itr_graph.py at startup.
    Returns the field map, loading from file if it exists, else building from defaults.
    """
    if OUTPUT_FIELD_MAP.exists():
        with open(OUTPUT_FIELD_MAP, encoding="utf-8") as f:
            return json.load(f)
    return build_field_map()


def get_validation_rules() -> dict:
    return VALIDATION_RULES


def get_schema_path(official_field: str) -> Optional[str]:
    """Convert an official ITR-1 field name to our schema dot-path."""
    return OFFICIAL_FIELD_TO_SCHEMA_PATH.get(official_field)


if __name__ == "__main__":
    main()
