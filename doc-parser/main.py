"""
Doc Parser Service — FastAPI
==============================
Accepts uploaded documents (Form 16, bank statements, salary slips)
and returns structured JSON for downstream agent consumption.
"""

import os
import uuid
import json
import tempfile
import shutil
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from parsers.form16 import parse_form16, form16_to_dict
from parsers.bank_statement import parse_bank_statement, bank_statement_to_dict

app = FastAPI(title="Doc Parser Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/tmp/itr1-uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_MIMETYPES = {"application/pdf", "image/jpeg", "image/png"}
MAX_FILE_SIZE_MB  = 20


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "doc-parser"}


# ── Upload & Parse endpoints ──────────────────────────────────────────────────

@app.post("/parse/form16")
async def parse_form16_endpoint(
    file:       UploadFile = File(...),
    session_id: Optional[str] = Form(default=None),
):
    """Upload Form 16 PDF and get structured salary + TDS data."""
    await _validate_file(file)
    path = await _save_upload(file)

    try:
        data = parse_form16(str(path))
        result = form16_to_dict(data)
        return {
            "success":    True,
            "doc_type":   "form16",
            "session_id": session_id or str(uuid.uuid4()),
            "data":       result,
            "confidence": result["parse_confidence"],
            "warnings":   result["warnings"],
        }
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Parse failed: {str(e)}")
    finally:
        path.unlink(missing_ok=True)


@app.post("/parse/bank-statement")
async def parse_bank_statement_endpoint(
    file:       UploadFile = File(...),
    session_id: Optional[str] = Form(default=None),
):
    """Upload bank statement PDF and extract interest income, salary credits."""
    await _validate_file(file)
    path = await _save_upload(file)

    try:
        data = parse_bank_statement(str(path))
        result = bank_statement_to_dict(data)
        return {
            "success":    True,
            "doc_type":   "bank_statement",
            "session_id": session_id or str(uuid.uuid4()),
            "data":       result,
            "confidence": result["parse_confidence"],
            "warnings":   result["warnings"],
        }
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Parse failed: {str(e)}")
    finally:
        path.unlink(missing_ok=True)


@app.post("/parse/auto")
async def auto_parse(
    file:       UploadFile = File(...),
    session_id: Optional[str] = Form(default=None),
    hint:       Optional[str] = Form(default=None),  # "form16" / "bank_statement" / "salary_slip"
):
    """
    Auto-detect document type and parse.
    Uses filename + content heuristics to route to correct parser.
    """
    await _validate_file(file)
    path = await _save_upload(file)

    try:
        doc_type = hint or _detect_doc_type(file.filename or "", path)

        if doc_type == "form16":
            data = parse_form16(str(path))
            result = form16_to_dict(data)
        elif doc_type == "bank_statement":
            data = parse_bank_statement(str(path))
            result = bank_statement_to_dict(data)
        else:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown document type '{doc_type}'. Provide hint='form16' or 'bank_statement'."
            )

        return {
            "success":    True,
            "doc_type":   doc_type,
            "session_id": session_id or str(uuid.uuid4()),
            "data":       result,
            "confidence": result.get("parse_confidence", 0),
            "warnings":   result.get("warnings", []),
        }
    finally:
        path.unlink(missing_ok=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _validate_file(file: UploadFile):
    if file.content_type not in ALLOWED_MIMETYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {file.content_type}. Use PDF, JPEG, or PNG."
        )


async def _save_upload(file: UploadFile) -> Path:
    suffix = Path(file.filename or "upload").suffix or ".pdf"
    path   = UPLOAD_DIR / f"{uuid.uuid4()}{suffix}"
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        path.unlink()
        raise HTTPException(400, f"File too large: {size_mb:.1f}MB. Max {MAX_FILE_SIZE_MB}MB.")

    return path


def _detect_doc_type(filename: str, path: Path) -> str:
    name = filename.lower()
    if "form16" in name or "form_16" in name or "16" in name:
        return "form16"
    if "bank" in name or "statement" in name or "passbook" in name:
        return "bank_statement"
    if "salary" in name or "payslip" in name or "payroll" in name:
        return "salary_slip"

    # Content-based detection (read first 2KB)
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            text = (pdf.pages[0].extract_text() or "").lower()
            if "form 16" in text or "tds certificate" in text:
                return "form16"
            if any(k in text for k in ["savings account", "current account", "transaction"]):
                return "bank_statement"
    except Exception:
        pass

    return "unknown"
