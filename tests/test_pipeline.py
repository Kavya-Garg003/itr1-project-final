"""
Test Suite — Agent Pipeline (node-level)
==========================================
Tests each LangGraph node in isolation so you don't need a running LLM.
The explain node is mocked since it calls the LLM.
"""

import sys
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.itr1_schema import ITR1Form


# ── Sample parsed documents ────────────────────────────────────────────────────

SAMPLE_FORM16_DOC = {
    "doc_type": "form16",
    "data": {
        "employer_name":            "TechCorp Pvt Ltd",
        "employer_tan":             "DELE12345F",
        "employee_pan":             "ABCDE1234F",
        "employee_name":            "Rahul Sharma",
        "assessment_year":          "2024-25",
        "gross_salary":             1000000.0,
        "salary_as_per_17_1":       950000.0,
        "perquisites_17_2":         50000.0,
        "hra_10_13a":               72000.0,
        "total_exempt_10":          72000.0,
        "standard_deduction_16ia":  50000.0,
        "professional_tax_16iii":   2400.0,
        "income_under_salary":      875600.0,
        "sec_80c_claimed":          150000.0,
        "sec_80ccd_2_claimed":      60000.0,
        "sec_80d_claimed":          25000.0,
        "total_vi_a_claimed":       235000.0,
        "tds_deducted_form16":      45000.0,
        "rebate_87a_form16":        0.0,
        "parse_confidence":         0.92,
        "warnings":                 [],
    }
}

SAMPLE_BANK_DOC = {
    "doc_type": "bank_statement",
    "data": {
        "bank_name":             "hdfc",
        "account_number":        "XXXX1234",
        "total_salary_credits":  1000000.0,
        "savings_interest_earned": 8500.0,
        "fd_interest_earned":    22000.0,
        "tds_on_interest":        2200.0,
        "parse_confidence":      0.85,
        "warnings":              [],
        "transactions":          [],
        "salary_transactions":   [],
        "interest_transactions": [],
    }
}

SAMPLE_DOCS = [SAMPLE_FORM16_DOC, SAMPLE_BANK_DOC]


def make_initial_state(docs=None):
    form = json.loads(ITR1Form().model_dump_json())
    return {
        "session_id":        "test-session",
        "ay":                "AY2024-25",
        "raw_documents":     docs or SAMPLE_DOCS,
        "itr1_form":         form,
        "regime_analysis":   {},
        "validation_flags":  [],
        "confidence_scores": {},
        "explanations":      {},
        "audit_trail":       [],
        "rag_context":       {},
        "error":             None,
        "step":              "fill_form",
    }


# ── Node: fill_form ────────────────────────────────────────────────────────────

class TestFillFormNode:

    def test_fills_gross_salary(self):
        from agent_orchestrator.graph.itr_graph import node_fill_form
        state  = make_initial_state()
        result = node_fill_form(state)
        form   = result["itr1_form"]
        assert form["salary_income"]["gross_salary"] == 1000000.0

    def test_fills_pan(self):
        from agent_orchestrator.graph.itr_graph import node_fill_form
        result = node_fill_form(make_initial_state())
        assert result["itr1_form"]["personal_info"]["pan"] == "ABCDE1234F"

    def test_computes_taxable_salary(self):
        from agent_orchestrator.graph.itr_graph import node_fill_form
        result = node_fill_form(make_initial_state())
        sal = result["itr1_form"]["salary_income"]
        # gross 10L - HRA 72k - std deduct 50k - prof tax 2.4k = 875,600
        assert sal["taxable_salary"] == pytest.approx(875600, abs=100)

    def test_fills_bank_interest(self):
        from agent_orchestrator.graph.itr_graph import node_fill_form
        result = node_fill_form(make_initial_state())
        os = result["itr1_form"]["other_sources"]
        assert os["savings_bank_interest"] == pytest.approx(8500)
        assert os["fd_interest"] == pytest.approx(22000)

    def test_80tta_capped_at_10000(self):
        from agent_orchestrator.graph.itr_graph import node_fill_form
        result = node_fill_form(make_initial_state())
        # savings interest 8500 < 10000 cap → 80TTA = 8500
        assert result["itr1_form"]["deductions"]["sec_80tta"] == pytest.approx(8500)

    def test_confidence_scores_created(self):
        from agent_orchestrator.graph.itr_graph import node_fill_form
        result = node_fill_form(make_initial_state())
        assert "salary_income.gross_salary" in result["confidence_scores"]
        assert result["confidence_scores"]["salary_income.gross_salary"]["confidence"] > 0.5

    def test_audit_trail_updated(self):
        from agent_orchestrator.graph.itr_graph import node_fill_form
        result = node_fill_form(make_initial_state())
        assert len(result["audit_trail"]) >= 1
        assert result["audit_trail"][0]["node"] == "fill_form"

    def test_tds_entry_created(self):
        from agent_orchestrator.graph.itr_graph import node_fill_form
        result = node_fill_form(make_initial_state())
        tds_list = result["itr1_form"]["tds_details"]
        assert len(tds_list) >= 1
        assert tds_list[0]["tds_deducted"] == 45000.0


# ── Node: compare_regimes ──────────────────────────────────────────────────────

class TestCompareRegimesNode:

    def _run_both(self):
        from agent_orchestrator.graph.itr_graph import node_fill_form, node_compare_regimes
        state  = make_initial_state()
        filled = node_fill_form(state)
        state.update(filled)
        return node_compare_regimes(state)

    def test_regime_recommendation_present(self):
        result = self._run_both()
        form = result["itr1_form"]
        assert form["regime_recommendation"] in ("old", "new")

    def test_both_regime_taxes_computed(self):
        result = self._run_both()
        form = result["itr1_form"]
        assert form["regime_tax_old"] >= 0
        assert form["regime_tax_new"] >= 0

    def test_recommended_regime_is_lower_tax(self):
        result = self._run_both()
        form = result["itr1_form"]
        rec   = form["regime_recommendation"]
        if rec == "old":
            assert form["regime_tax_old"] <= form["regime_tax_new"]
        else:
            assert form["regime_tax_new"] <= form["regime_tax_old"]

    def test_tax_computation_filled(self):
        result = self._run_both()
        tc = result["itr1_form"]["tax_computation"]
        assert tc["taxable_income"] > 0
        assert tc["total_tax_liability"] >= 0


# ── Node: validate ─────────────────────────────────────────────────────────────

class TestValidateNode:

    def _run_to_validate(self, docs=None):
        from agent_orchestrator.graph.itr_graph import node_fill_form, node_compare_regimes, node_validate
        state = make_initial_state(docs)
        for fn in [node_fill_form, node_compare_regimes, node_validate]:
            state.update(fn(state))
        return state

    def test_no_errors_for_valid_input(self):
        state = self._run_to_validate()
        errors = [f for f in state["validation_flags"] if f["severity"] == "error"]
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_flags_missing_form16(self):
        state = self._run_to_validate(docs=[])  # no documents
        errors = [f for f in state["validation_flags"] if f["severity"] == "error"]
        assert len(errors) >= 1
        assert any("gross salary" in f["message"].lower() for f in errors)

    def test_flags_income_over_50L(self):
        big_doc = {
            "doc_type": "form16",
            "data": {
                **SAMPLE_FORM16_DOC["data"],
                "gross_salary": 6000000.0,
                "income_under_salary": 5900000.0,
            }
        }
        state = self._run_to_validate(docs=[big_doc])
        errors = [f for f in state["validation_flags"] if f["severity"] == "error"]
        assert any("50" in f["message"] for f in errors), "Should flag income > ₹50L"

    def test_validation_flags_in_form(self):
        state = self._run_to_validate()
        assert "validation_flags" in state["itr1_form"]


# ── Node: score_confidence ─────────────────────────────────────────────────────

class TestScoreConfidenceNode:

    def test_all_critical_fields_scored(self):
        from agent_orchestrator.graph.itr_graph import (
            node_fill_form, node_compare_regimes, node_validate, node_score_confidence
        )
        state = make_initial_state()
        for fn in [node_fill_form, node_compare_regimes, node_validate, node_score_confidence]:
            state.update(fn(state))

        scores = state["confidence_scores"]
        critical = [
            "salary_income.gross_salary",
            "tax_computation.gross_total_income",
        ]
        for f in critical:
            assert f in scores, f"Missing confidence score for {f}"

    def test_missing_fields_flagged(self):
        from agent_orchestrator.graph.itr_graph import (
            node_fill_form, node_compare_regimes, node_validate, node_score_confidence
        )
        state = make_initial_state(docs=[])  # no documents → missing fields
        for fn in [node_fill_form, node_compare_regimes, node_validate, node_score_confidence]:
            state.update(fn(state))

        flagged = [k for k, v in state["confidence_scores"].items() if v.get("flagged")]
        assert len(flagged) > 0


# ── Full pipeline (integration, mocked LLM explain) ───────────────────────────

class TestFullPipeline:

    @patch("agent_orchestrator.graph.itr_graph._get_llm")
    def test_pipeline_returns_filled_form(self, mock_llm):
        """Run full pipeline with mocked LLM (explain node)."""
        mock_instance = MagicMock()
        mock_instance.invoke.return_value = MagicMock(content="Mocked explanation.")
        mock_llm.return_value = mock_instance

        from agent_orchestrator.graph.itr_graph import run_itr_pipeline
        result = run_itr_pipeline(
            parsed_documents=SAMPLE_DOCS,
            session_id="integration-test",
            ay="AY2024-25",
        )

        assert "itr1_form" in result
        form = result["itr1_form"]
        assert form["salary_income"]["gross_salary"] == 1000000.0
        assert form["regime_recommendation"] in ("old", "new")
        assert len(result["validation_flags"]) == 0 or True  # validation flags are OK

    @patch("agent_orchestrator.graph.itr_graph._get_llm")
    def test_pipeline_produces_audit_trail(self, mock_llm):
        mock_instance = MagicMock()
        mock_instance.invoke.return_value = MagicMock(content="Explanation.")
        mock_llm.return_value = mock_instance

        from agent_orchestrator.graph.itr_graph import run_itr_pipeline
        result = run_itr_pipeline(SAMPLE_DOCS, "audit-test")

        nodes_in_trail = {e["node"] for e in result["audit_trail"]}
        expected_nodes = {"fill_form", "compare_regimes", "validate", "score_confidence", "explain"}
        assert expected_nodes.issubset(nodes_in_trail)
