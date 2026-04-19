"""
PDF Ingester — RAG Knowledge Base
====================================
Takes your locally downloaded PDFs and ingests them into the same FAISS
vector store that the scraper.py web chunks go into.

Your downloaded files it expects:
  knowledge-base/pdfs/
    itr1_instructions_AY2024-25.pdf    ← CBDT ITR-1 instructions booklet
    itr1_instructions_AY2025-26.pdf    ← next year if downloaded
    circular_03_2025.pdf               ← CBDT Circular 03/2025 (TDS on salary)
    circular_20_2024.pdf               ← any other CBDT circulars
    income_tax_act_sections.pdf        ← IT Act relevant sections
    finance_act_2023.pdf               ← Finance Act
    *.pdf                              ← any other PDFs you add

Run AFTER scraper.py has already created rag_output/combined/all_chunks.jsonl:
    python pdf_ingester.py                    # ingests all PDFs in pdfs/ folder
    python pdf_ingester.py --ay AY2025-26     # different AY namespace
    python pdf_ingester.py --file path/to/specific.pdf --source "CBDT Circular 05/2025"

Then re-embed everything:
    python embedder.py --backend huggingface
"""

from __future__ import annotations
import argparse
import json
import hashlib
import re
from pathlib import Path
from dataclasses import dataclass, asdict

import tiktoken

try:
    import pdfplumber
except ImportError:
    raise ImportError("Run: pip install pdfplumber")

try:
    import fitz          # PyMuPDF — better text extraction for multi-column PDFs
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

enc = tiktoken.get_encoding("cl100k_base")

CHUNK_SIZE    = 512
CHUNK_OVERLAP = 64

PDF_DIR      = Path("knowledge-base/pdfs")
CHUNKS_DIR   = Path("rag_output/chunks")
COMBINED     = Path("rag_output/combined/all_chunks.jsonl")

for d in [PDF_DIR, CHUNKS_DIR, COMBINED.parent]:
    d.mkdir(parents=True, exist_ok=True)


# ── Per-file metadata config ───────────────────────────────────────────────────
# Maps filename patterns to metadata. Edit this to match your actual filenames.

PDF_METADATA_MAP = [
    {
        "pattern":     r"itr.?1.*(instruction|booklet|sahaj)",
        "source":      "CBDT — ITR-1 Instructions Booklet",
        "doc_type":    "official_instructions",
        "section":     "Filing Instructions",
        "authority":   "CBDT",
    },
    {
        "pattern":     r"circular.*(03|3).*(2025)",
        "source":      "CBDT Circular 03/2025 — TDS on Salary",
        "doc_type":    "cbdt_circular",
        "section":     "TDS Computation",
        "authority":   "CBDT",
    },
    {
        "pattern":     r"circular.*(20|twenty).*(2024)",
        "source":      "CBDT Circular 20/2024",
        "doc_type":    "cbdt_circular",
        "section":     "CBDT Notification",
        "authority":   "CBDT",
    },
    {
        "pattern":     r"(income.?tax.?act|it.?act|ita)",
        "source":      "Income Tax Act 1961 — Relevant Sections",
        "doc_type":    "legislation",
        "section":     "Statutory Text",
        "authority":   "Parliament of India",
    },
    {
        "pattern":     r"finance.?act",
        "source":      "Finance Act 2023",
        "doc_type":    "legislation",
        "section":     "Budget Changes",
        "authority":   "Parliament of India",
    },
    {
        "pattern":     r"form.?16",
        "source":      "Form 16 — TDS Certificate Format",
        "doc_type":    "official_form",
        "section":     "TDS",
        "authority":   "CBDT",
    },
    {
        "pattern":     r"(26as|ais|annual.?information)",
        "source":      "AIS / Form 26AS Reference",
        "doc_type":    "official_form",
        "section":     "TDS Credits",
        "authority":   "Income Tax Department",
    },
    {
        "pattern":     r"(80c|80d|deduction|chapter.?vi)",
        "source":      "Deductions Guide — Chapter VI-A",
        "doc_type":    "supplementary_guide",
        "section":     "Deductions",
        "authority":   "CBDT",
    },
    {
        "pattern":     r"(slab|rate|regime|115bac)",
        "source":      "Tax Slab Rates & Regime Guide",
        "doc_type":    "supplementary_guide",
        "section":     "Tax Rates",
        "authority":   "CBDT",
    },
]

FALLBACK_METADATA = {
    "source":    "PDF Document",
    "doc_type":  "supplementary_guide",
    "section":   "General",
    "authority": "Unknown",
}


def _detect_metadata(filename: str) -> dict:
    name = filename.lower()
    for rule in PDF_METADATA_MAP:
        if re.search(rule["pattern"], name, re.IGNORECASE):
            return {k: v for k, v in rule.items() if k != "pattern"}
    return FALLBACK_METADATA.copy()


# ── Text extraction ────────────────────────────────────────────────────────────

def extract_text_pdfplumber(path: Path) -> str:
    """
    pdfplumber — good for text-layer PDFs (most govt PDFs).
    Falls back to PyMuPDF if available for scanned/complex layouts.
    """
    text_pages = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            # Try regular text extraction
            text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""

            # Also try table extraction and append any table text
            for table in page.extract_tables():
                if not table:
                    continue
                for row in table:
                    if row:
                        row_text = " | ".join(str(c or "").strip() for c in row if c)
                        if row_text.strip():
                            text += "\n" + row_text

            if text.strip():
                text_pages.append(f"[Page {i+1}]\n{text.strip()}")

    return "\n\n".join(text_pages)


def extract_text_pymupdf(path: Path) -> str:
    """PyMuPDF — better for multi-column and complex layout PDFs."""
    doc = fitz.open(str(path))
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text("text")
        if text.strip():
            pages.append(f"[Page {i+1}]\n{text.strip()}")
    doc.close()
    return "\n\n".join(pages)


def extract_text(path: Path) -> str:
    """Try PyMuPDF first (better quality), fall back to pdfplumber."""
    if HAS_PYMUPDF:
        try:
            text = extract_text_pymupdf(path)
            if len(text) > 200:
                return text
        except Exception:
            pass
    return extract_text_pdfplumber(path)


# ── Cleaning ───────────────────────────────────────────────────────────────────

NOISE_PATTERNS = [
    r"^\s*\d+\s*$",                        # page numbers alone on a line
    r"^\s*Page\s+\d+\s+of\s+\d+\s*$",     # "Page 3 of 12"
    r"^\s*FORM\s+ITR.?\d\s*$",             # just "FORM ITR-1"
    r"^\s*www\.[^\s]+\s*$",                # lone URLs
    r"^\s*incometax(india)?\.gov\.in\s*$", # domain names
    r"^\[Page\s+\d+\]$",                   # our own page markers (keep surrounding text)
]


def clean_pdf_text(text: str) -> str:
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        skip = any(re.match(pat, line, re.IGNORECASE) for pat in NOISE_PATTERNS)
        if not skip:
            cleaned.append(line)

    text = "\n".join(cleaned)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


# ── Chunking ───────────────────────────────────────────────────────────────────

def chunk_pdf_text(
    text: str,
    file_id: str,
    metadata: dict,
    ay: str,
    source_url: str = "",
) -> list[dict]:
    """
    Chunking strategy for govt PDFs:
    1. Split on section headings (numbered sections like "1.", "2.1", or "PART A")
    2. If a section > CHUNK_SIZE, slide a window with overlap
    """
    # Split on section headings — common in CBDT PDFs
    section_splitters = re.split(
        r"(?=\n(?:\d+[\.\d]*\s+[A-Z]|PART\s+[A-Z]|SCHEDULE\s+[A-Z]|SECTION\s+\d|Sec(?:tion)?\s+\d))",
        text
    )

    raw_chunks: list[str] = []
    for block in section_splitters:
        block = block.strip()
        if not block:
            continue
        tokens = enc.encode(block)
        if len(tokens) <= CHUNK_SIZE:
            raw_chunks.append(block)
        else:
            start = 0
            while start < len(tokens):
                end = min(start + CHUNK_SIZE, len(tokens))
                raw_chunks.append(enc.decode(tokens[start:end]))
                if end == len(tokens):
                    break
                start += CHUNK_SIZE - CHUNK_OVERLAP

    chunks = []
    total = len(raw_chunks)
    for i, ct in enumerate(raw_chunks):
        ct = ct.strip()
        if len(enc.encode(ct)) < 30:
            continue

        uid = hashlib.md5(f"{file_id}:{i}:{ct[:50]}".encode()).hexdigest()[:12]
        chunks.append({
            "chunk_id":       f"{file_id}_{i:04d}_{uid}",
            "source":         metadata["source"],
            "doc_type":       metadata["doc_type"],
            "applicable_ay":  ay,
            "section":        metadata["section"],
            "url":            source_url,
            "authority":      metadata.get("authority", ""),
            "text":           ct,
            "token_count":    len(enc.encode(ct)),
            "chunk_index":    i,
            "total_chunks":   total,
        })
    return chunks


# ── Main ───────────────────────────────────────────────────────────────────────

def ingest_pdf(
    pdf_path: Path,
    ay:       str  = "AY2024-25",
    source_override: str = "",
) -> list[dict]:
    print(f"\n  Processing: {pdf_path.name}")

    meta = _detect_metadata(pdf_path.name)
    if source_override:
        meta["source"] = source_override

    print(f"  Detected: {meta['source']} [{meta['doc_type']}]")

    # Extract text
    text = extract_text(pdf_path)
    if not text or len(text) < 100:
        print(f"  ✗ Could not extract text from {pdf_path.name} — may be image-based (scanned)")
        print("     → Run OCR: pip install ocrmypdf && ocrmypdf input.pdf output.pdf")
        return []

    text = clean_pdf_text(text)
    token_count = len(enc.encode(text))
    print(f"  ✓ Extracted {len(text):,} chars / ~{token_count:,} tokens")

    # Chunk
    file_id = re.sub(r"[^\w]", "_", pdf_path.stem.lower())[:40]
    chunks  = chunk_pdf_text(text, file_id, meta, ay)
    print(f"  ✓ {len(chunks)} chunks created")

    # Save individual chunk file
    out_path = CHUNKS_DIR / f"pdf_{file_id}_chunks.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    print(f"  ✓ Saved → {out_path}")

    return chunks


def rebuild_combined():
    """Merge ALL chunk files (web + PDF) into single JSONL for embedding."""
    all_chunks = []
    for path in sorted(CHUNKS_DIR.glob("*_chunks.json")):
        with open(path, encoding="utf-8") as f:
            chunks = json.load(f)
            all_chunks.extend(chunks)

    with open(COMBINED, "w", encoding="utf-8") as f:
        for c in all_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"\n✓ Combined JSONL rebuilt → {COMBINED}")
    print(f"  Total chunks: {len(all_chunks)}")

    # Source breakdown
    by_source: dict[str, int] = {}
    for c in all_chunks:
        src = c.get("source", "Unknown")
        by_source[src] = by_source.get(src, 0) + 1
    print("\nChunks by source:")
    for src, n in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"  {n:4d}  {src}")


def main():
    parser = argparse.ArgumentParser(description="Ingest PDF files into RAG knowledge base")
    parser.add_argument("--dir",    default=str(PDF_DIR), help="Directory of PDFs to ingest")
    parser.add_argument("--file",   help="Single PDF file to ingest")
    parser.add_argument("--source", help="Override source name for --file")
    parser.add_argument("--ay",     default="AY2024-25", help="Assessment Year namespace")
    args = parser.parse_args()

    print(f"\n📄 PDF Ingester — ITR-1 Knowledge Base")
    print(f"   AY namespace: {args.ay}")

    all_chunks: list[dict] = []

    if args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"File not found: {path}")
            return
        chunks = ingest_pdf(path, args.ay, args.source or "")
        all_chunks.extend(chunks)
    else:
        pdf_dir = Path(args.dir)
        pdfs    = sorted(pdf_dir.glob("*.pdf"))
        if not pdfs:
            print(f"\nNo PDFs found in {pdf_dir}/")
            print("Put your downloaded PDFs there and re-run.")
            print(f"\nExpected files (names don't need to match exactly):")
            print("  itr1_instructions_AY2024-25.pdf")
            print("  circular_03_2025.pdf")
            print("  income_tax_act_sections.pdf")
            return

        print(f"\nFound {len(pdfs)} PDF(s) in {pdf_dir}/\n")
        for pdf in pdfs:
            try:
                chunks = ingest_pdf(pdf, args.ay)
                all_chunks.extend(chunks)
            except Exception as e:
                print(f"  ✗ Error: {e}")

    if all_chunks:
        rebuild_combined()
        print(f"\n✅ Done. Now run:")
        print(f"   python embedder.py --backend huggingface --ay {args.ay}")
        print(f"\nThis will embed ALL chunks (web + PDF) into FAISS/{args.ay}/")
    else:
        print("\nNo chunks produced. Check PDF text extraction above.")


if __name__ == "__main__":
    main()
