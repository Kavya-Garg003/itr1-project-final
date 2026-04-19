"""
pytest configuration
=====================
Shared fixtures available to all test files.
"""

import sys
import json
import pytest
from pathlib import Path

# Make shared/ and service directories importable
ROOT = Path(__file__).parent.parent
for sub in ["", "shared", "doc-parser", "rag-service", "agent-orchestrator"]:
    p = ROOT / sub
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))


@pytest.fixture
def sample_form16_data():
    return {
        "employer_name":            "TechCorp Pvt Ltd",
        "employer_tan":             "DELE12345F",
        "employee_pan":             "ABCDE1234F",
        "employee_name":            "Rahul Sharma",
        "assessment_year":          "2024-25",
        "gross_salary":             1000000.0,
        "hra_10_13a":               72000.0,
        "total_exempt_10":          72000.0,
        "standard_deduction_16ia":  50000.0,
        "professional_tax_16iii":   2400.0,
        "income_under_salary":      875600.0,
        "sec_80c_claimed":          150000.0,
        "sec_80d_claimed":          25000.0,
        "tds_deducted_form16":      45000.0,
        "parse_confidence":         0.92,
        "warnings":                 [],
    }


@pytest.fixture
def sample_bank_data():
    return {
        "bank_name":               "hdfc",
        "savings_interest_earned": 8500.0,
        "fd_interest_earned":      22000.0,
        "tds_on_interest":         2200.0,
        "total_salary_credits":    1000000.0,
        "parse_confidence":        0.85,
        "warnings":                [],
        "transactions":            [],
        "salary_transactions":     [],
        "interest_transactions":   [],
    }
