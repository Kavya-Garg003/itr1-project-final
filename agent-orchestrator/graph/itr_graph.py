"""
ITR-1 LangGraph Agent Pipeline
================================
State machine:
  parse_docs → fill_form → compare_regimes → validate → score_confidence → explain → done

Each node is a callable that receives the shared State dict and returns updates.
LangGraph handles routing, retries, and state accumulation.
"""

from __future__ import annotations
import json
import sys
import os
import httpx
from pathlib import Path
from typing import TypedDict, Annotated, Optional, Any
from datetime import datetime

from langgraph.graph import StateGraph, END
from shared.llm_client import get_llm as _get_llm_factory


sys.path.insert(0, str(Path(__file__).parent.parent))  # /app in Docker, project root locally
from shared.itr1_schema import ITR1Form, ValidationFlag, FieldConfidence, TaxRegime
from shared.tax_utils import enforce_deduction_limits, compute_tax_2025

# ── Shared state schema ───────────────────────────────────────────────────────

class AgentState(TypedDict):
    session_id:          str
    ay:                  str
    raw_documents:       list[dict]    # outputs from doc-parser
    itr1_form:           dict          # serialised ITR1Form
    regime_analysis:     dict
    validation_flags:    list[dict]
    confidence_scores:   dict[str, dict]
    explanations:        dict[str, str]
    audit_trail:         list[dict]
    rag_context:         dict          # cached RAG responses
    error:               Optional[str]
    step:                str


# ── LLM setup ─────────────────────────────────────────────────────────────────

def _get_llm(temperature: float = 0.0):
    """Returns a FallbackLLM — tries Groq, OpenRouter, OpenAI in order."""
    return _get_llm_factory(temperature=temperature)


RAG_SERVICE_URL      = os.getenv("RAG_SERVICE_URL",      "http://rag-service:8001")
DOC_PARSER_URL       = os.getenv("DOC_PARSER_URL",        "http://doc-parser:8002")


# ── Helper: call RAG service ───────────────────────────────────────────────────

async def _rag_query(question: str, ay: str = "AY2024-25") -> str:
    """Fetch RAG answer for a tax question. Returns formatted context string."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{RAG_SERVICE_URL}/query",
                json={"question": question, "ay": ay, "top_k": 4}
            )
            resp.raise_for_status()
            data = resp.json()
            # Return context chunks concatenated
            chunks = data.get("chunks", [])
            return "\n\n---\n\n".join(c["text"] for c in chunks)
    except Exception as e:
        return f"[RAG unavailable: {e}]"


# ── Node 1: Merge documents into ITR-1 form ────────────────────────────────────

def node_fill_form(state: AgentState) -> dict:
    """
    Maps parsed document data onto ITR-1 fields.
    Priority: Form 16 > bank statement > LLM inference.
    """
    docs = state["raw_documents"]
    form = ITR1Form()
    confidence_scores = {}
    audit = list(state.get("audit_trail", []))

    form16_doc = next((d for d in docs if d.get("doc_type") == "form16"), None)
    bank_docs  = [d for d in docs if d.get("doc_type") == "bank_statement"]

    def set_field(field_path: str, value: Any, source: str, confidence: float, explanation: str, citation: str = ""):
        confidence_scores[field_path] = {
            "value":       value,
            "confidence":  confidence,
            "source":      source,
            "explanation": explanation,
            "citation":    citation,
            "flagged":     confidence < 0.6,
        }

    # ── From Form 16 ──────────────────────────────────────────────────────────
    if form16_doc:
        d = form16_doc["data"]
        conf = d.get("parse_confidence", 0.7)

        form.personal_info.pan          = d.get("employee_pan")
        form.personal_info.pan and set_field("personal_info.pan", form.personal_info.pan, "form16", conf, "PAN from Form 16 Part A")

        form.salary_income.gross_salary = d.get("gross_salary", 0)
        set_field("salary_income.gross_salary", form.salary_income.gross_salary, "form16", conf,
                  f"Gross salary from Form 16 Part B, Sec 17(1): ₹{form.salary_income.gross_salary:,.0f}",
                  "Form 16 Part B — Row: Salary as per Sec 17(1)")

        form.salary_income.allowances_exempt_10_13a = d.get("hra_10_13a", 0)
        set_field("salary_income.allowances_exempt_10_13a", form.salary_income.allowances_exempt_10_13a,
                  "form16", conf, f"HRA exemption under Sec 10(13A) from Form 16: ₹{d.get('hra_10_13a', 0):,.0f}")

        form.salary_income.professional_tax_16iii = d.get("professional_tax_16iii", 0)
        form.salary_income.standard_deduction_16ia = d.get("standard_deduction_16ia", 50000)
        form.salary_income.compute()

        set_field("salary_income.taxable_salary", form.salary_income.taxable_salary, "form16", conf,
                  f"Taxable salary = Gross ₹{form.salary_income.gross_salary:,.0f} - "
                  f"Exempt ₹{form.salary_income.total_exempt_allowances:,.0f} - "
                  f"Std deduction ₹{form.salary_income.standard_deduction_16ia:,.0f} - "
                  f"Prof tax ₹{form.salary_income.professional_tax_16iii:,.0f}")

        # Deductions from Form 16 Part B
        form.deductions.sec_80c       = d.get("sec_80c_claimed", 0)
        form.deductions.sec_80ccc     = d.get("sec_80ccc_claimed", 0)
        form.deductions.sec_80ccd_1   = d.get("sec_80ccd_1_claimed", 0)
        form.deductions.sec_80ccd_2   = d.get("sec_80ccd_2_claimed", 0)
        form.deductions.sec_80d       = d.get("sec_80d_claimed", 0)

        # TDS
        from shared.itr1_schema import TDSEntry
        tds = TDSEntry(
            employer_name=d.get("employer_name"),
            employer_tan=d.get("employer_tan"),
            gross_salary_form16=d.get("gross_salary", 0),
            tds_deducted=d.get("tds_deducted_form16", 0),
            tds_claimed=d.get("tds_deducted_form16", 0),
        )
        form.tds_details.append(tds)
        set_field("tds_details.0.tds_deducted", tds.tds_deducted, "form16", conf,
                  f"TDS of ₹{tds.tds_deducted:,.0f} from Form 16 Part A. Employer: {tds.employer_name}")

    # ── From bank statements ───────────────────────────────────────────────────
    total_savings_interest = 0.0
    total_fd_interest      = 0.0
    total_bank_tds         = 0.0

    for bank in bank_docs:
        d = bank["data"]
        conf = d.get("parse_confidence", 0.6)
        total_savings_interest += d.get("total_savings_interest", 0)
        total_fd_interest      += d.get("total_fd_interest", 0)
        total_bank_tds         += d.get("total_tds_deducted", 0)

    form.other_sources.savings_bank_interest = total_savings_interest
    form.other_sources.fd_interest           = total_fd_interest
    form.other_sources.compute()

    if total_savings_interest > 0:
        set_field("other_sources.savings_bank_interest", total_savings_interest, "bank_statement", 0.75,
                  f"Savings account interest ₹{total_savings_interest:,.0f} from bank statement(s). "
                  f"80TTA deduction will apply (max ₹10,000).")
    if total_fd_interest > 0:
        set_field("other_sources.fd_interest", total_fd_interest, "bank_statement", 0.75,
                  f"Fixed deposit interest ₹{total_fd_interest:,.0f} from bank statement. "
                  f"Fully taxable under Other Sources.")

    # 80TTA from savings interest
    form.deductions.sec_80tta = min(total_savings_interest, 10000)
    if total_savings_interest > 0:
        set_field("deductions.sec_80tta", form.deductions.sec_80tta, "computed", 0.9,
                  f"80TTA = min(savings interest ₹{total_savings_interest:,.0f}, ₹10,000 cap) = "
                  f"₹{form.deductions.sec_80tta:,.0f}",
                  "Section 80TTA — Interest on savings account, max ₹10,000")

    # ── Gross total income ─────────────────────────────────────────────────────
    gti = (
        form.salary_income.taxable_salary
        + form.house_property.total_income_hp
        + form.other_sources.total_other_sources
    )

    form.tax_computation.gross_total_income = gti
    set_field("tax_computation.gross_total_income", gti, "computed", 0.85,
              f"GTI = Salary ₹{form.salary_income.taxable_salary:,.0f} + "
              f"HP ₹{form.house_property.total_income_hp:,.0f} + "
              f"OS ₹{form.other_sources.total_other_sources:,.0f}")

    audit.append({
        "timestamp": datetime.utcnow().isoformat(),
        "node":      "fill_form",
        "action":    "Mapped documents to ITR-1 fields",
        "doc_count": len(docs),
    })

    return {
        "itr1_form":       json.loads(form.model_dump_json()),
        "confidence_scores": confidence_scores,
        "audit_trail":     audit,
        "step":            "compute_tax",
    }


# ── Node 2: Compute Tax (2025 New Regime) ────────────────────────────────────

def node_compute_tax(state: AgentState) -> dict:
    form_data = state["itr1_form"]
    ay        = state.get("ay", "AY2024-25")

    gti       = form_data["tax_computation"]["gross_total_income"]
    total_tds = sum(t["tds_deducted"] for t in form_data.get("tds_details", []))

    # Calculate tax strictly under the New Regime
    tax_breakdown = compute_tax_2025(
        taxable_income=gti,
        ay=ay,
    )

    form_data["tax_computation"]["regime"] = "new"

    # Fill tax computation
    tc = form_data["tax_computation"]
    tc["taxable_income"]          = gti
    tc["tax_before_rebate"]       = tax_breakdown["tax_before_rebate"]
    tc["rebate_87a"]              = tax_breakdown["rebate_87a"]
    tc["tax_after_rebate"]        = tax_breakdown["tax_after_rebate"]
    tc["surcharge"]               = tax_breakdown["surcharge"]
    tc["health_education_cess"]   = tax_breakdown["health_education_cess"]
    tc["total_tax_liability"]     = tax_breakdown["total_tax"]
    tc["tds_deducted"]            = total_tds
    
    net = tax_breakdown["total_tax"] - total_tds
    tc["tax_payable"] = max(0, net)
    tc["refund"]      = max(0, -net)

    audit = list(state.get("audit_trail", []))
    audit.append({
        "timestamp":  datetime.utcnow().isoformat(),
        "node":       "compute_tax",
        "action":     f"Tax computed strictly under 2025 New Regime. Total Tax: ₹{tax_breakdown['total_tax']:,.0f}",
        "new_tax":    tax_breakdown["total_tax"],
    })

    return {
        "itr1_form":      form_data,
        "audit_trail":    audit,
        "step":           "validate",
    }


# ── Node 3: Validate ──────────────────────────────────────────────────────────

def node_validate(state: AgentState) -> dict:
    form_data = state["itr1_form"]
    flags: list[dict] = []

    def flag(field: str, severity: str, message: str, suggestion: str = ""):
        flags.append({
            "field": field, "severity": severity,
            "message": message, "suggestion": suggestion
        })

    # Check: gross salary present
    gs = form_data["salary_income"]["gross_salary"]
    if gs == 0:
        flag("salary_income.gross_salary", "error",
             "Gross salary is ₹0 — Form 16 may not have been uploaded or parsed correctly.",
             "Upload Form 16 PDF or enter gross salary manually.")

    # Check: standard deduction applied
    sd = form_data["salary_income"]["standard_deduction_16ia"]
    if gs > 0 and sd == 0:
        flag("salary_income.standard_deduction_16ia", "warning",
             "Standard deduction (₹50,000) appears to be ₹0.",
             "Standard deduction of ₹50,000 is available to all salaried employees under Sec 16(ia).")

    # Check: 80C limit
    ded = form_data["deductions"]
    raw_80c = ded["sec_80c"] + ded["sec_80ccc"] + ded.get("sec_80ccd_1", 0)
    if raw_80c > 150000:
        flag("deductions.sec_80c", "warning",
             f"80C/80CCC/80CCD(1) total ₹{raw_80c:,.0f} exceeds ₹1,50,000 cap.",
             "Only ₹1,50,000 is allowable. Excess will be ignored.")

    # Check: HRA + 80GG (can't claim both)
    if form_data["salary_income"]["allowances_exempt_10_13a"] > 0 and ded.get("sec_80gg", 0) > 0:
        flag("deductions.sec_80gg", "error",
             "HRA exemption under 10(13A) and 80GG cannot both be claimed.",
             "Remove 80GG if you receive HRA from employer.")

    # Check: income > ₹50L (ITR-1 not applicable)
    gti = form_data["tax_computation"]["gross_total_income"]
    if gti > 5000000:
        flag("tax_computation.gross_total_income", "error",
             f"Income ₹{gti:,.0f} exceeds ₹50,00,000. ITR-1 is not applicable.",
             "Use ITR-2 or ITR-3 for income above ₹50 lakh.")

    # Check: TDS not higher than total tax (large refund warning)
    total_tds  = form_data["tax_computation"]["tds_deducted"]
    total_tax  = form_data["tax_computation"]["total_tax_liability"]
    if total_tds > total_tax * 1.5 and total_tds > 10000:
        flag("tax_computation.tds_deducted", "info",
             f"Large refund expected: ₹{total_tds - total_tax:,.0f}. "
             "Verify TDS amount from Form 16 Part A and AIS.",
             "Cross-check with Form 26AS/AIS on the income tax portal.")

    # Check: 80TTA not for senior citizens (should use 80TTB)
    if ded.get("sec_80tta", 0) > 0 and ded.get("sec_80ttb", 0) > 0:
        flag("deductions.sec_80tta", "error",
             "Both 80TTA and 80TTB claimed. 80TTB is exclusively for senior citizens.",
             "Senior citizens (60+): use 80TTB (max ₹50,000). Others: use 80TTA (max ₹10,000).")

    audit = list(state.get("audit_trail", []))
    audit.append({
        "timestamp": datetime.utcnow().isoformat(),
        "node":      "validate",
        "action":    f"Validation complete. {len(flags)} flag(s) raised.",
        "flags":     [f["severity"] for f in flags],
    })

    form_data["validation_flags"] = flags

    return {
        "itr1_form":       form_data,
        "validation_flags": flags,
        "audit_trail":     audit,
        "step":            "score_confidence",
    }


# ── Node 4: Confidence scoring ────────────────────────────────────────────────

def node_score_confidence(state: AgentState) -> dict:
    """
    Aggregate confidence scores and mark low-confidence fields.
    Fields below 0.6 are flagged for manual review.
    """
    scores = state.get("confidence_scores", {})
    form_data = state["itr1_form"]

    # Fields that were NOT explicitly set get a low baseline confidence
    CRITICAL_FIELDS = [
        "salary_income.gross_salary",
        "salary_income.taxable_salary",
        "tax_computation.gross_total_income",
        "tax_computation.total_tax_liability",
        "tds_details.0.tds_deducted",
    ]

    for f in CRITICAL_FIELDS:
        if f not in scores:
            scores[f] = {
                "confidence":  0.3,
                "source":      "missing",
                "explanation": "Field not found in uploaded documents — requires manual entry.",
                "flagged":     True,
            }

    # Summary stats
    all_confs   = [v["confidence"] for v in scores.values()]
    avg_conf    = sum(all_confs) / len(all_confs) if all_confs else 0
    flagged_count = sum(1 for v in scores.values() if v.get("flagged"))

    audit = list(state.get("audit_trail", []))
    audit.append({
        "timestamp":    datetime.utcnow().isoformat(),
        "node":         "score_confidence",
        "average_conf": round(avg_conf, 2),
        "flagged":      flagged_count,
        "total_fields": len(scores),
    })

    form_data["confidence_scores"] = scores

    return {
        "itr1_form":       form_data,
        "confidence_scores": scores,
        "audit_trail":     audit,
        "step":            "explain",
    }


# ── Node 5: Explainability ────────────────────────────────────────────────────

def node_explain(state: AgentState) -> dict:
    """
    Uses LLM + RAG context to generate plain-English explanations
    for complex filled fields (HRA, 87A rebate, regime choice).
    """
    llm       = _get_llm()
    form_data = state["itr1_form"]
    ay        = state.get("ay", "AY2024-25")
    explanations: dict[str, str] = {}

    # Explain regime recommendation
    regime_analysis = state.get("regime_analysis", {})
    if regime_analysis:
        rec = regime_analysis.get("recommended_regime", "new")
        explanations["regime_recommendation"] = (
            f"**{rec.title()} tax regime recommended.** "
            f"{regime_analysis.get('reasoning', '')} "
            f"Old regime tax: ₹{regime_analysis.get('old_regime', {}).get('total_tax', 0):,.0f} | "
            f"New regime tax: ₹{regime_analysis.get('new_regime', {}).get('total_tax', 0):,.0f} | "
            f"Saving: ₹{regime_analysis.get('saving', 0):,.0f}"
        )

    # Explain 87A rebate
    rebate = form_data["tax_computation"].get("rebate_87a", 0)
    ti     = form_data["tax_computation"].get("taxable_income", 0)
    regime = form_data["tax_computation"].get("regime", "new")
    limit  = 700000 if regime == "new" else 500000
    if rebate > 0:
        explanations["tax_computation.rebate_87a"] = (
            f"Tax rebate under Sec 87A of ₹{rebate:,.0f} applied. "
            f"Your taxable income ₹{ti:,.0f} is within the ₹{limit:,.0f} limit for the {regime} regime. "
            f"This effectively means zero tax liability."
        )

    # Explain HRA (if non-zero)
    hra = form_data["salary_income"].get("allowances_exempt_10_13a", 0)
    if hra > 0:
        explanations["salary_income.allowances_exempt_10_13a"] = (
            f"HRA exemption of ₹{hra:,.0f} under Sec 10(13A). "
            "Calculated as minimum of: (a) actual HRA received, "
            "(b) rent paid minus 10% of basic, "
            "(c) 50% of basic for metro / 40% for non-metro cities."
        )

    audit = list(state.get("audit_trail", []))
    audit.append({
        "timestamp":   datetime.utcnow().isoformat(),
        "node":        "explain",
        "explanations": list(explanations.keys()),
    })

    form_data["audit_trail"] = audit
    form_data["explanations"] = explanations

    return {
        "itr1_form":   form_data,
        "explanations": explanations,
        "audit_trail": audit,
        "step":        "done",
    }


# ── Route: check for errors ───────────────────────────────────────────────────

def route_after_validate(state: AgentState) -> str:
    flags = state.get("validation_flags", [])
    errors = [f for f in flags if f.get("severity") == "error"]
    # Even with errors, continue to scoring (errors are surfaced in output)
    return "score_confidence"


# ── Build graph ───────────────────────────────────────────────────────────────

def build_itr_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("fill_form",        node_fill_form)
    graph.add_node("compute_tax",      node_compute_tax)
    graph.add_node("validate",         node_validate)
    graph.add_node("score_confidence", node_score_confidence)
    graph.add_node("explain",          node_explain)

    graph.set_entry_point("fill_form")
    graph.add_edge("fill_form",        "compute_tax")
    graph.add_edge("compute_tax",      "validate")
    graph.add_conditional_edges("validate", route_after_validate, {"score_confidence": "score_confidence"})
    graph.add_edge("score_confidence", "explain")
    graph.add_edge("explain",          END)

    return graph.compile()


# ── Convenience runner ─────────────────────────────────────────────────────────

def run_itr_pipeline(
    parsed_documents: list[dict],
    session_id:       str  = "default",
    ay:               str  = "AY2024-25",
) -> dict:
    """
    Run the full ITR-1 agent pipeline.

    Args:
        parsed_documents: list of outputs from doc-parser service
        session_id:       unique session identifier
        ay:               Assessment Year (e.g. "AY2024-25")

    Returns:
        Completed AgentState dict with filled ITR-1 form + metadata
    """
    from shared.itr1_schema import ITR1Form
    initial_form = json.loads(ITR1Form().model_dump_json())

    initial_state: AgentState = {
        "session_id":      session_id,
        "ay":              ay,
        "raw_documents":   parsed_documents,
        "itr1_form":       initial_form,
        "regime_analysis": {},
        "validation_flags": [],
        "confidence_scores": {},
        "explanations":    {},
        "audit_trail":     [],
        "rag_context":     {},
        "error":           None,
        "step":            "fill_form",
    }

    graph  = build_itr_graph()
    result = graph.invoke(initial_state)
    return result
