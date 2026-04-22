"""
fix_chunks.py — Run once to repair the existing all_chunks.jsonl
=================================================================
Fixes:
  1. source="PDF Document" → actual document name based on chunk_id
  2. url="" for PDFs → adds a local file reference so citations appear

Run from project root:
    python fix_chunks.py

Backs up original to rag_output/combined/all_chunks_backup.jsonl
"""

import json
import shutil
from pathlib import Path

JSONL_PATH   = Path("rag_output/combined/all_chunks.jsonl")
BACKUP_PATH  = Path("rag_output/combined/all_chunks_backup.jsonl")

# Map chunk_id prefix → (nice_source, doc_type, local_file_ref)
PDF_SOURCE_MAP = {
    "pdf_a1961":                        ("Income Tax Act 1961", "legislation",            "file://a1961-43.pdf"),
    "pdf_cbdt_e_filing_itr_1_valid":    ("CBDT ITR-1 Validation Rules AY 2025-26",
                                         "official_instructions",
                                         "file://CBDT_e-Filing_ITR1_Validation_Rules_AY2025-26.pdf"),
    "pdf_circular_no_03_2025":          ("CBDT Circular 03/2025 — TDS on Salary",
                                         "cbdt_circular",
                                         "file://circular-no-03-2025.pdf"),
    "pdf_income_tax_rules_2026":        ("Income Tax Rules 2026", "legislation",           "file://Income-Tax-Rules-2026.pdf"),
    "pdf_itr_1_2026_eng":               ("ITR-1 Instructions Booklet 2026",
                                         "official_instructions",
                                         "file://ITR-1-2026-Eng.pdf"),
}

def get_pdf_meta(chunk_id: str):
    for prefix, (source, doc_type, file_ref) in PDF_SOURCE_MAP.items():
        if chunk_id.startswith(prefix):
            return source, doc_type, file_ref
    # Generic fallback for unknown PDFs
    stem = chunk_id[4:].split("_0")[0].replace("_", " ").title()
    return stem, "supplementary_guide", f"file://{stem}.pdf"


def fix():
    if not JSONL_PATH.exists():
        print(f"File not found: {JSONL_PATH}")
        return

    # Backup
    shutil.copy2(JSONL_PATH, BACKUP_PATH)
    print(f"Backed up to: {BACKUP_PATH}")

    fixed = 0
    lines_out = []

    with open(JSONL_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            chunk = json.loads(line)
            cid   = chunk.get("chunk_id", "")

            if cid.startswith("pdf_") and (
                chunk.get("source") in ("PDF Document", "", None)
                or not chunk.get("url")
            ):
                source, doc_type, file_ref = get_pdf_meta(cid)
                chunk["source"]   = source
                chunk["doc_type"] = doc_type
                # Only set URL if not already set
                if not chunk.get("url"):
                    chunk["url"] = file_ref
                fixed += 1

            lines_out.append(json.dumps(chunk, ensure_ascii=False))

    with open(JSONL_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines_out) + "\n")

    print(f"Fixed {fixed} PDF chunks out of {len(lines_out)} total.")
    print(f"Saved to: {JSONL_PATH}")
    print()
    print("IMPORTANT: You must re-embed after this fix for FAISS metadata to update:")
    print("  python knowledge-base/embedder.py --backend huggingface")


if __name__ == "__main__":
    fix()
