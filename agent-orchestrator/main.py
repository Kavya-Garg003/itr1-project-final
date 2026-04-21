"""
Agent Orchestrator Service — FastAPI
=====================================
Exposes the LangGraph ITR-1 pipeline via REST.
Also handles Q&A chat with document context.
"""

import json
import os
import uuid
import sys
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent))

app = FastAPI(title="Agent Orchestrator", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Store results in memory (replace with Redis in production)
_session_store: dict[str, dict] = {}


# ── Request/response models ───────────────────────────────────────────────────

class RunPipelineRequest(BaseModel):
    parsed_documents: list[dict]
    session_id:       Optional[str] = None
    ay:               str           = "AY2024-25"

class ChatRequest(BaseModel):
    question:         str
    session_id:       Optional[str] = None
    ay:               str           = "AY2024-25"
    include_form_context: bool      = True

class UpdateFieldRequest(BaseModel):
    session_id: str
    field_path: str
    value:      float | str
    reason:     str = "manual_update"


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "agent-orchestrator"}


# ── Run full pipeline ─────────────────────────────────────────────────────────

@app.post("/pipeline/run")
async def run_pipeline(req: RunPipelineRequest):
    """
    Run the full ITR-1 agent pipeline:
    parse → fill → compare regimes → validate → score → explain
    """
    from graph.itr_graph import run_itr_pipeline

    session_id = req.session_id or str(uuid.uuid4())

    try:
        result = run_itr_pipeline(
            parsed_documents=req.parsed_documents,
            session_id=session_id,
            ay=req.ay,
        )
        _session_store[session_id] = result
        return {
            "success":    True,
            "session_id": session_id,
            "itr1_form":  result["itr1_form"],
            "regime_analysis":    result.get("regime_analysis", {}),
            "validation_flags":   result.get("validation_flags", []),
            "confidence_scores":  result.get("confidence_scores", {}),
            "explanations":       result.get("explanations", {}),
            "audit_trail":        result.get("audit_trail", []),
        }
    except Exception as e:
        import traceback
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)}\n{traceback.format_exc()}")


# ── Get session ───────────────────────────────────────────────────────────────

@app.get("/pipeline/session/{session_id}")
def get_session(session_id: str):
    if session_id not in _session_store:
        raise HTTPException(404, "Session not found")
    result = _session_store[session_id]
    return {
        "session_id":        session_id,
        "itr1_form":         result["itr1_form"],
        "confidence_scores": result.get("confidence_scores", {}),
        "validation_flags":  result.get("validation_flags", []),
        "explanations":      result.get("explanations", {}),
    }


# ── Manual field update ───────────────────────────────────────────────────────

@app.post("/pipeline/update-field")
def update_field(req: UpdateFieldRequest):
    """
    User manually corrects a field. Updates confidence to 1.0 (human-verified).
    """
    if req.session_id not in _session_store:
        raise HTTPException(404, "Session not found")

    result = _session_store[req.session_id]
    form   = result["itr1_form"]

    # Navigate dot-path and update
    parts = req.field_path.split(".")
    obj   = form
    for part in parts[:-1]:
        if isinstance(obj, dict):
            obj = obj.get(part, {})
        else:
            raise HTTPException(400, f"Invalid field path: {req.field_path}")

    last_key = parts[-1]
    if isinstance(obj, dict):
        obj[last_key] = req.value

    # Update confidence to human-verified
    result["confidence_scores"][req.field_path] = {
        "confidence":  1.0,
        "source":      "manual",
        "explanation": f"Manually updated by user. Reason: {req.reason}",
        "flagged":     False,
        "value":       req.value,
    }

    # Log in audit trail
    result["audit_trail"].append({
        "node":       "manual_update",
        "field":      req.field_path,
        "value":      req.value,
        "reason":     req.reason,
    })

    _session_store[req.session_id] = result
    return {"success": True, "field": req.field_path, "new_value": req.value}


# ── Chat / Q&A ────────────────────────────────────────────────────────────────

@app.post("/chat/query")
async def chat_query(req: ChatRequest):
    """
    Answer a tax question using RAG + form context.
    Optionally include the user's filled form as additional context.
    """
    import httpx

    RAG_URL = os.getenv("RAG_SERVICE_URL", "http://rag-service:8001")

    # Build enhanced question with form context if session exists
    question = req.question
    form_ctx  = ""
    if req.include_form_context and req.session_id and req.session_id in _session_store:
        form = _session_store[req.session_id]["itr1_form"]
        tc   = form.get("tax_computation", {})
        form_ctx = (
            f"\n\n--- INTERNAL USER TAX PROFILE ---\n"
            f"Gross Total Income (GTI) = ₹{tc.get('gross_total_income', 0):,.0f}\n"
            f"Recommended Regime = {tc.get('regime', 'new')}\n"
            f"Taxable income = ₹{tc.get('taxable_income', 0):,.0f}\n\n"
            f"Below is a JSON representation of EVERYTHING extracted from their uploaded Form 16 / Bank Statements:\n"
            f"{__import__('json').dumps(form, indent=2)}\n"
            f"Use this data strictly if their question explicitly pertains to their documents or tax specifics.\n"
            f"-----------------------------------\n"
        )
        question += form_ctx

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{RAG_URL}/query",
                json={"question": question, "ay": req.ay, "top_k": 5}
            )
            resp.raise_for_status()
            rag_result = resp.json()

        return {
            "success":   True,
            "answer":    rag_result.get("answer", ""),
            "citations": rag_result.get("citations", []),
            "chunks":    rag_result.get("chunks", []),
        }
    except httpx.HTTPError as e:
        raise HTTPException(502, f"RAG service unavailable: {e}")


# ── Export filled form as JSON ─────────────────────────────────────────────────

@app.get("/pipeline/export/{session_id}")
def export_form(session_id: str, format: str = "json"):
    """Export the filled ITR-1 form. Formats: json (more to come)."""
    if session_id not in _session_store:
        raise HTTPException(404, "Session not found")

    result = _session_store[session_id]
    return {
        "session_id": session_id,
        "ay":         result["itr1_form"].get("ay", "AY2024-25"),
        "itr1_form":  result["itr1_form"],
        "exported_at": __import__("datetime").datetime.utcnow().isoformat(),
    }
