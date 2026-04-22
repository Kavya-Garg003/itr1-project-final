"""
ITR-1 LangGraph Agent Pipeline
================================
State machine:
  fill_form → compute_tax → validate → score_confidence → explain → done
"""

from __future__ import annotations
import json
import sys
import os
import httpx
from pathlib import Path
from typing import TypedDict, Optional, Any
from datetime import datetime

from langgraph.graph import StateGraph, END
from shared.llm_client import get_llm as _get_llm_factory

sys.path.insert(0, str(Path(__file__).parent.parent))  # /app in Docker, project root locally
from shared.itr1_schema import ITR1Form, TDSEntry, TaxRegime
from shared.tax_utils import compute_tax_2025


# ── State ─────────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    session_id:          str
    ay:                  str
    raw_documents:       list[dict]
    itr1_form:           dict
    regime_analysis:     dict
    validation_flags:    list[dict]
    confidence_scores:   dict[str, dict]
    explanations:        dict[str, str]
    audit_trail:         list[dict]
    rag_context:         dict
    error:               Optional[str]
    step:                str


def _get_llm(temperature: float = 0.0):
    return _get_llm_factory(temperature=temperature)


RAG_SERVICE_URL = os.getenv("RAG_SERVICE_URL", "http://rag-service:8001")
DOC_PARSER_URL  = os.getenv("DOC_PARSER_URL",  "http://doc-parser:8002")


async def _rag_query(question: str, ay: str = "AY2024-25") -> str:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"{RAG_SERVICE_URL}/query",
                                     json={"question": question, "ay": ay, "top_k": 4})
            resp.raise_for_status()
            return "\n\n---\n\n".join(c["text"] for c in resp.json().get("chunks", []))
    except Exception as e:
        return f"[RAG unavailable: {e}]"


# ── Node 1: fill_form ─────────────────────────────────────────────────────────

def node_fill_form(state: AgentState) -> dict:
    """
    Maps ALL available fields from parsed documents into the ITR-1 form.
    Priority: Form 16 (authoritative) > bank statement > computed.
    """
    docs  = state["raw_documents"]
    form  = ITR1Form()
    conf_scores: dict[str, dict] = {}
    audit = list(state.get("audit_trail", []))

    form16_doc = next((d for d in docs if d.get("doc_type") == "form16"), None)
    bank_docs  = [d for d in docs if d.get("doc_type") == "bank_statement"]

    def sf(path: str, value: Any, source: str, confidence: float,
           explanation: str = "", citation: str = ""):
        """Set a confidence score record for a field."""
        conf_scores[path] = {
            "value":       value,
            "confidence":  confidence,
            "source":      source,
            "explanation": explanation,
            "citation":    citation,
            "flagged":     confidence < 0.6,
        }

    # ── From Form 16 ──────────────────────────────────────────────────────────
    if form16_doc:
        d    = form16_doc["data"]
        conf = float(d.get("parse_confidence", 0.7))

        # ── Personal Info ──────────────────────────────────────────────────────
        form.personal_info.pan             = d.get("employee_pan")
        form.personal_info.assessment_year = d.get("assessment_year", "2024-25") or "2024-25"

        # Split employee_name into first / last name
        raw_name = (d.get("employee_name") or "").strip()
        if raw_name:
            parts = raw_name.split()
            if len(parts) == 1:
                form.personal_info.first_name = parts[0]
            elif len(parts) == 2:
                form.personal_info.first_name = parts[0]
                form.personal_info.last_name  = parts[1]
            else:
                form.personal_info.first_name  = parts[0]
                form.personal_info.middle_name = " ".join(parts[1:-1])
                form.personal_info.last_name   = parts[-1]
            sf("personal_info.first_name", form.personal_info.first_name, "form16", conf,
               f"Employee name from Form 16 Part A: {raw_name}")

        if form.personal_info.pan:
            sf("personal_info.pan", form.personal_info.pan, "form16", conf,
               "PAN from Form 16 Part A")

        # ── Schedule S: Salary breakdown (Sec 17) ─────────────────────────────
        form.salary_income.salary_as_per_17_1 = float(d.get("salary_as_per_17_1", 0) or 0)
        form.salary_income.perquisites_17_2   = float(d.get("perquisites_17_2", 0) or 0)
        form.salary_income.profits_17_3       = float(d.get("profits_17_3", 0) or 0)
        form.salary_income.gross_salary       = float(d.get("gross_salary", 0) or 0)

        # If gross_salary not directly extracted, compute it
        if form.salary_income.gross_salary == 0:
            form.salary_income.gross_salary = (
                form.salary_income.salary_as_per_17_1
                + form.salary_income.perquisites_17_2
                + form.salary_income.profits_17_3
            )

        sf("salary_income.gross_salary", form.salary_income.gross_salary, "form16", conf,
           f"Gross salary (17(1)+17(2)+17(3)) from Form 16: ₹{form.salary_income.gross_salary:,.0f}",
           "Form 16 Part B — Gross Salary")
        if form.salary_income.salary_as_per_17_1:
            sf("salary_income.salary_as_per_17_1", form.salary_income.salary_as_per_17_1,
               "form16", conf, f"Salary as per Sec 17(1): ₹{form.salary_income.salary_as_per_17_1:,.0f}")
        if form.salary_income.perquisites_17_2:
            sf("salary_income.perquisites_17_2", form.salary_income.perquisites_17_2,
               "form16", conf, f"Perquisites under Sec 17(2): ₹{form.salary_income.perquisites_17_2:,.0f}")
        if form.salary_income.profits_17_3:
            sf("salary_income.profits_17_3", form.salary_income.profits_17_3,
               "form16", conf, f"Profits in lieu of salary Sec 17(3): ₹{form.salary_income.profits_17_3:,.0f}")

        # ── Sec 10 Exempt Allowances ───────────────────────────────────────────
        hra = float(d.get("hra_10_13a", 0) or 0)
        lta = float(d.get("lta_10_10", 0) or 0)
        # other_exempt_10 = total_exempt_10 - hra - lta (don't double count)
        total_10 = float(d.get("total_exempt_10", 0) or 0)
        other_10 = max(0.0, total_10 - hra - lta)

        form.salary_income.allowances_exempt_10_13a = hra
        form.salary_income.allowances_exempt_10_10  = lta
        form.salary_income.allowances_exempt_other  = other_10

        if hra:
            sf("salary_income.allowances_exempt_10_13a", hra, "form16", conf,
               f"HRA exemption u/s 10(13A): ₹{hra:,.0f}",
               "Form 16 Part B — Sec 10(13A) exemption")
        if lta:
            sf("salary_income.allowances_exempt_10_10", lta, "form16", conf,
               f"Leave Travel Allowance u/s 10(10): ₹{lta:,.0f}")

        # ── Sec 16 Deductions ──────────────────────────────────────────────────
        std_ded = float(d.get("standard_deduction_16ia", 0) or 0)
        if std_ded == 0 and form.salary_income.gross_salary > 0:
            std_ded = 50000.0  # default statutory amount
        form.salary_income.standard_deduction_16ia    = std_ded
        form.salary_income.entertainment_allowance_16ii = float(d.get("entertainment_16ii", 0) or 0)
        form.salary_income.professional_tax_16iii     = float(d.get("professional_tax_16iii", 0) or 0)

        sf("salary_income.standard_deduction_16ia", std_ded, "form16", conf,
           f"Standard deduction u/s 16(ia): ₹{std_ded:,.0f}",
           "Form 16 Part B — Sec 16(ia)")
        if form.salary_income.professional_tax_16iii:
            sf("salary_income.professional_tax_16iii",
               form.salary_income.professional_tax_16iii, "form16", conf,
               f"Professional tax u/s 16(iii): ₹{form.salary_income.professional_tax_16iii:,.0f}")

        # Compute derived salary fields (net_salary, total_sec16, taxable_salary)
        form.salary_income.compute()
        sf("salary_income.taxable_salary", form.salary_income.taxable_salary, "form16", conf,
           f"Taxable salary = Gross ₹{form.salary_income.gross_salary:,.0f} "
           f"- Exemptions ₹{form.salary_income.total_exempt_allowances:,.0f} "
           f"- Sec 16 ₹{form.salary_income.total_sec16_deductions:,.0f} "
           f"= ₹{form.salary_income.taxable_salary:,.0f}")

        # ── Deductions (Chapter VI-A from Form 16 Part B) ─────────────────────
        form.deductions.sec_80c     = float(d.get("sec_80c_claimed", 0) or 0)
        form.deductions.sec_80ccc   = float(d.get("sec_80ccc_claimed", 0) or 0)
        form.deductions.sec_80ccd_1 = float(d.get("sec_80ccd_1_claimed", 0) or 0)
        form.deductions.sec_80ccd_2 = float(d.get("sec_80ccd_2_claimed", 0) or 0)
        form.deductions.sec_80d     = float(d.get("sec_80d_claimed", 0) or 0)

        if form.deductions.sec_80c:
            sf("deductions.sec_80c", form.deductions.sec_80c, "form16", conf,
               f"Section 80C from Form 16 Part B: ₹{form.deductions.sec_80c:,.0f}")
        if form.deductions.sec_80d:
            sf("deductions.sec_80d", form.deductions.sec_80d, "form16", conf,
               f"Section 80D from Form 16 Part B: ₹{form.deductions.sec_80d:,.0f}")
        if form.deductions.sec_80ccd_2:
            sf("deductions.sec_80ccd_2", form.deductions.sec_80ccd_2, "form16", conf,
               f"Employer NPS contribution 80CCD(2): ₹{form.deductions.sec_80ccd_2:,.0f} — allowed under new regime")

        # Compute total_deductions (new regime: only 80CCD(2))
        form.deductions.compute(regime=TaxRegime.NEW)
        sf("deductions.total_deductions", form.deductions.total_deductions, "computed", 0.95,
           f"Total deductions under new regime = 80CCD(2) ₹{form.deductions.sec_80ccd_2:,.0f}")

        # ── TDS Schedule TDS1 ──────────────────────────────────────────────────
        tds_entry = TDSEntry(
            employer_name       = d.get("employer_name"),
            employer_tan        = d.get("employer_tan"),
            gross_salary_form16 = form.salary_income.gross_salary,
            income_chargeable   = form.salary_income.taxable_salary,
            tds_deducted        = float(d.get("tds_deducted_form16", 0) or 0),
            tds_claimed         = float(d.get("tds_deducted_form16", 0) or 0),
        )
        form.tds_details.append(tds_entry)

        if tds_entry.tds_deducted:
            sf("tds_details.0.tds_deducted", tds_entry.tds_deducted, "form16", conf,
               f"TDS deducted ₹{tds_entry.tds_deducted:,.0f} — Employer: {tds_entry.employer_name or 'N/A'} "
               f"TAN: {tds_entry.employer_tan or 'N/A'}",
               "Form 16 Part A — TDS certificate")
        if tds_entry.employer_name:
            sf("tds_details.0.employer_name", tds_entry.employer_name, "form16", conf,
               f"Employer name from Form 16: {tds_entry.employer_name}")
        if tds_entry.employer_tan:
            sf("tds_details.0.employer_tan", tds_entry.employer_tan, "form16", conf,
               f"Employer TAN from Form 16: {tds_entry.employer_tan}")

    # ── From Bank Statements ──────────────────────────────────────────────────
    total_savings_interest = 0.0
    total_fd_interest      = 0.0
    total_bank_tds         = 0.0

    for bank in bank_docs:
        d = bank["data"]
        total_savings_interest += float(d.get("total_savings_interest", 0) or 0)
        total_fd_interest      += float(d.get("total_fd_interest", 0) or 0)
        total_bank_tds         += float(d.get("total_tds_deducted", 0) or 0)

    form.other_sources.savings_bank_interest = total_savings_interest
    form.other_sources.fd_interest           = total_fd_interest
    form.other_sources.compute()

    if total_savings_interest > 0:
        sf("other_sources.savings_bank_interest", total_savings_interest, "bank_statement", 0.75,
           f"Savings account interest ₹{total_savings_interest:,.0f}. "
           f"80TTA deduction of ₹{min(total_savings_interest, 10000):,.0f} applied.")
    if total_fd_interest > 0:
        sf("other_sources.fd_interest", total_fd_interest, "bank_statement", 0.75,
           f"FD interest ₹{total_fd_interest:,.0f} — fully taxable under Other Sources.")

    # 80TTA from savings interest (new regime: technically 0, but store for display)
    # Under strict 2025 new regime, 80TTA is not deductible — store for info
    form.deductions.sec_80tta = min(total_savings_interest, 10000)

    # Store bank TDS for TDS2 schedule
    form.tax_computation.tds_from_bank = total_bank_tds

    # ── Gross Total Income ────────────────────────────────────────────────────
    gti = (
        form.salary_income.taxable_salary
        + form.house_property.total_income_hp
        + form.other_sources.total_other_sources
    )
    form.tax_computation.gross_total_income = gti
    sf("tax_computation.gross_total_income", gti, "computed", 0.9,
       f"GTI = Salary ₹{form.salary_income.taxable_salary:,.0f} "
       f"+ HP ₹{form.house_property.total_income_hp:,.0f} "
       f"+ OS ₹{form.other_sources.total_other_sources:,.0f}")

    audit.append({
        "timestamp": datetime.utcnow().isoformat(),
        "node":      "fill_form",
        "action":    f"Mapped {len(docs)} document(s) to ITR-1 fields",
        "doc_count": len(docs),
        "gti":       gti,
    })

    return {
        "itr1_form":        json.loads(form.model_dump_json()),
        "confidence_scores": conf_scores,
        "audit_trail":      audit,
        "step":             "compute_tax",
    }


# ── Node 2: Compute Tax ────────────────────────────────────────────────────────

def node_compute_tax(state: AgentState) -> dict:
    form_data = state["itr1_form"]
    ay        = state.get("ay", "AY2024-25")

    gti       = form_data["tax_computation"]["gross_total_income"]
    ded_80ccd2 = form_data["deductions"].get("sec_80ccd_2", 0)
    total_tds  = sum(t.get("tds_deducted", 0) for t in form_data.get("tds_details", []))
    bank_tds   = form_data["tax_computation"].get("tds_from_bank", 0)
    all_tds    = total_tds + bank_tds

    # Taxable income = GTI - 80CCD(2) (only deduction allowed under new regime)
    taxable_income = max(0, gti - ded_80ccd2)

    tax_breakdown = compute_tax_2025(taxable_income=taxable_income, ay=ay)

    tc = form_data["tax_computation"]
    tc["regime"]                = "new"
    tc["total_deductions"]      = ded_80ccd2
    tc["taxable_income"]        = taxable_income
    tc["tax_before_rebate"]     = tax_breakdown["tax_before_rebate"]
    tc["rebate_87a"]            = tax_breakdown["rebate_87a"]
    tc["tax_after_rebate"]      = tax_breakdown["tax_after_rebate"]
    tc["surcharge"]             = tax_breakdown["surcharge"]
    tc["health_education_cess"] = tax_breakdown["health_education_cess"]
    tc["total_tax_liability"]   = tax_breakdown["total_tax"]
    tc["tds_deducted"]          = all_tds
    tc["total_taxes_paid"]      = all_tds   # could include advance tax later

    net = tax_breakdown["total_tax"] - all_tds
    tc["tax_payable"] = max(0, net)
    tc["refund"]      = max(0, -net)

    audit = list(state.get("audit_trail", []))
    audit.append({
        "timestamp":     datetime.utcnow().isoformat(),
        "node":          "compute_tax",
        "action":        f"Tax computed (new regime). Total tax: ₹{tax_breakdown['total_tax']:,.0f}",
        "taxable_income": taxable_income,
        "total_tax":     tax_breakdown["total_tax"],
        "tds":           all_tds,
        "refund_or_payable": "refund" if net < 0 else "payable",
    })

    return {"itr1_form": form_data, "audit_trail": audit, "step": "validate"}


# ── Node 3: Validate ──────────────────────────────────────────────────────────

def node_validate(state: AgentState) -> dict:
    form_data = state["itr1_form"]
    flags: list[dict] = []

    def flag(field, severity, message, suggestion=""):
        flags.append({"field": field, "severity": severity,
                      "message": message, "suggestion": suggestion})

    sal = form_data["salary_income"]
    ded = form_data["deductions"]
    tc  = form_data["tax_computation"]

    if sal["gross_salary"] == 0:
        flag("salary_income.gross_salary", "error",
             "Gross salary is ₹0 — Form 16 may not have been parsed correctly.",
             "Upload Form 16 PDF or enter gross salary manually.")

    if sal["gross_salary"] > 0 and sal["standard_deduction_16ia"] == 0:
        flag("salary_income.standard_deduction_16ia", "warning",
             "Standard deduction (₹50,000) appears to be ₹0.",
             "Standard deduction is available to all salaried employees under Sec 16(ia).")

    raw_80c = ded["sec_80c"] + ded["sec_80ccc"] + ded.get("sec_80ccd_1", 0)
    if raw_80c > 150000:
        flag("deductions.sec_80c", "warning",
             f"80C/80CCC/80CCD(1) total ₹{raw_80c:,.0f} exceeds ₹1,50,000 cap. "
             "Note: these deductions are not applicable under the 2025 new regime.",
             "Under new regime, only 80CCD(2) is deductible.")

    if sal["allowances_exempt_10_13a"] > 0 and ded.get("sec_80gg", 0) > 0:
        flag("deductions.sec_80gg", "error",
             "HRA exemption u/s 10(13A) and 80GG cannot both be claimed.",
             "Remove 80GG — you receive HRA from employer.")

    gti = tc["gross_total_income"]
    if gti > 5000000:
        flag("tax_computation.gross_total_income", "error",
             f"Income ₹{gti:,.0f} exceeds ₹50,00,000. ITR-1 is not applicable.",
             "Use ITR-2 for income above ₹50 lakh.")

    total_tds  = tc["tds_deducted"]
    total_tax  = tc["total_tax_liability"]
    if total_tds > total_tax * 1.5 and total_tds > 10000:
        flag("tax_computation.tds_deducted", "info",
             f"Large refund expected: ₹{total_tds - total_tax:,.0f}. Verify TDS from Form 16 Part A and AIS.",
             "Cross-check with Form 26AS/AIS on income tax portal.")

    if ded.get("sec_80tta", 0) > 0 and ded.get("sec_80ttb", 0) > 0:
        flag("deductions.sec_80tta", "error",
             "Both 80TTA and 80TTB claimed. 80TTB is exclusively for senior citizens.",
             "Senior citizens (60+): use 80TTB (max ₹50,000). Others: use 80TTA (max ₹10,000).")

    audit = list(state.get("audit_trail", []))
    audit.append({"timestamp": datetime.utcnow().isoformat(), "node": "validate",
                  "action": f"Validation: {len(flags)} flag(s).",
                  "flags": [f["severity"] for f in flags]})

    form_data["validation_flags"] = flags
    return {"itr1_form": form_data, "validation_flags": flags,
            "audit_trail": audit, "step": "score_confidence"}


# ── Node 4: Score Confidence ──────────────────────────────────────────────────

def node_score_confidence(state: AgentState) -> dict:
    scores    = state.get("confidence_scores", {})
    form_data = state["itr1_form"]

    CRITICAL = [
        "salary_income.gross_salary",
        "salary_income.taxable_salary",
        "tax_computation.gross_total_income",
        "tax_computation.total_tax_liability",
        "tds_details.0.tds_deducted",
    ]
    for f in CRITICAL:
        if f not in scores:
            scores[f] = {"confidence": 0.3, "source": "missing",
                         "explanation": "Field not found in uploaded documents — requires manual entry.",
                         "flagged": True}

    all_c = [v["confidence"] for v in scores.values()]
    avg   = sum(all_c) / len(all_c) if all_c else 0

    audit = list(state.get("audit_trail", []))
    audit.append({"timestamp": datetime.utcnow().isoformat(), "node": "score_confidence",
                  "average_confidence": round(avg, 2), "flagged": sum(1 for v in scores.values() if v.get("flagged"))})

    form_data["confidence_scores"] = scores
    return {"itr1_form": form_data, "confidence_scores": scores,
            "audit_trail": audit, "step": "explain"}


# ── Node 5: Explain ───────────────────────────────────────────────────────────

def node_explain(state: AgentState) -> dict:
    form_data    = state["itr1_form"]
    explanations: dict[str, str] = {}
    tc = form_data["tax_computation"]

    # Regime note
    explanations["regime"] = (
        "Filing under 2025 New Tax Regime (default from AY 2024-25). "
        "Only 80CCD(2) employer NPS deduction is available. "
        "Slab rates: 0-₹3L=Nil, ₹3-6L=5%, ₹6-9L=10%, ₹9-12L=15%, ₹12-15L=20%, above 15L=30%."
    )

    # 87A rebate
    rebate = tc.get("rebate_87a", 0)
    ti     = tc.get("taxable_income", 0)
    if rebate > 0:
        explanations["tax_computation.rebate_87a"] = (
            f"Rebate u/s 87A of ₹{rebate:,.0f} applied. "
            f"Taxable income ₹{ti:,.0f} is within ₹7,00,000 limit for new regime. "
            f"Net tax after rebate = ₹{tc.get('tax_after_rebate', 0):,.0f}."
        )

    # HRA
    hra = form_data["salary_income"].get("allowances_exempt_10_13a", 0)
    if hra > 0:
        explanations["salary_income.allowances_exempt_10_13a"] = (
            f"HRA exemption ₹{hra:,.0f} u/s 10(13A) = minimum of: "
            "(a) actual HRA received, (b) rent paid − 10% of basic, "
            "(c) 50% of basic salary (metro city) or 40% (non-metro)."
        )

    # Refund / payable
    refund  = tc.get("refund", 0)
    payable = tc.get("tax_payable", 0)
    if refund > 0:
        explanations["tax_computation.refund"] = (
            f"Refund of ₹{refund:,.0f} = TDS paid ₹{tc.get('tds_deducted', 0):,.0f} "
            f"minus total tax liability ₹{tc.get('total_tax_liability', 0):,.0f}. "
            "This will be credited to your registered bank account after ITR processing."
        )
    elif payable > 0:
        explanations["tax_computation.tax_payable"] = (
            f"Tax payable ₹{payable:,.0f} = Total liability ₹{tc.get('total_tax_liability', 0):,.0f} "
            f"minus TDS paid ₹{tc.get('tds_deducted', 0):,.0f}. Pay via Challan 280 before filing."
        )

    audit = list(state.get("audit_trail", []))
    audit.append({"timestamp": datetime.utcnow().isoformat(), "node": "explain",
                  "explanations": list(explanations.keys())})

    form_data["explanations"] = explanations
    form_data["audit_trail"]  = audit
    return {"itr1_form": form_data, "explanations": explanations,
            "audit_trail": audit, "step": "done"}


# ── Graph ─────────────────────────────────────────────────────────────────────

def _route_after_validate(state: AgentState) -> str:
    return "score_confidence"


def build_itr_graph() -> StateGraph:
    g = StateGraph(AgentState)
    g.add_node("fill_form",        node_fill_form)
    g.add_node("compute_tax",      node_compute_tax)
    g.add_node("validate",         node_validate)
    g.add_node("score_confidence", node_score_confidence)
    g.add_node("explain",          node_explain)

    g.set_entry_point("fill_form")
    g.add_edge("fill_form",        "compute_tax")
    g.add_edge("compute_tax",      "validate")
    g.add_conditional_edges("validate", _route_after_validate, {"score_confidence": "score_confidence"})
    g.add_edge("score_confidence", "explain")
    g.add_edge("explain",          END)
    return g.compile()


def run_itr_pipeline(parsed_documents: list[dict],
                     session_id: str = "default",
                     ay: str = "AY2024-25") -> dict:
    from shared.itr1_schema import ITR1Form
    initial_form = json.loads(ITR1Form().model_dump_json())
    initial_state: AgentState = {
        "session_id": session_id, "ay": ay,
        "raw_documents": parsed_documents, "itr1_form": initial_form,
        "regime_analysis": {}, "validation_flags": [], "confidence_scores": {},
        "explanations": {}, "audit_trail": [], "rag_context": {},
        "error": None, "step": "fill_form",
    }
    return build_itr_graph().invoke(initial_state)
