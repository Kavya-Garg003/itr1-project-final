"""
RAG Service — FastAPI
======================
FAISS + MMR + cross-encoder reranking + LLM answer generation.
Fixes: PDF sources now appear in citations even without a URL.
       Answer format now includes quoted paragraph from source.
"""

import os, json, re
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # /app in Docker

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

VECTOR_STORE_DIR = Path(os.getenv("VECTOR_STORE_DIR", "/app/vector_store"))
DEFAULT_AY       = os.getenv("DEFAULT_AY", "AY2024-25")

app = FastAPI(title="RAG Service", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_index_cache, _meta_cache, _embedder_cache = {}, {}, {}


# ── Source name normaliser ─────────────────────────────────────────────────────
# Converts raw source / chunk_id into a human-readable document name.

def _nice_source(chunk: dict) -> str:
    """Return a clean document name from chunk metadata."""
    raw = chunk.get("source", "") or ""

    # Already a good name (from web scraper)
    if raw and raw != "PDF Document":
        return raw

    # Try to derive from chunk_id  e.g. pdf_cbdt_e_filing_itr_1_validation_rules_ay__0000_xxx
    cid = chunk.get("chunk_id", "")
    if cid.startswith("pdf_"):
        stem = cid[4:].split("_0")[0]   # strip leading "pdf_" and trailing "_0000_..."
        # map common stems to nice names
        nice_map = {
            "a1961":                              "Income Tax Act 1961",
            "cbdt_e_filing_itr_1_validation":     "CBDT ITR-1 Validation Rules AY 2025-26",
            "circular_no_03_2025":                "CBDT Circular 03/2025 (TDS on Salary)",
            "income_tax_rules_2026":              "Income Tax Rules 2026",
            "itr_1_2026_eng":                     "ITR-1 Instructions Booklet 2026",
        }
        for key, label in nice_map.items():
            if key in stem:
                return label
        # Fallback: title-case the stem
        return stem.replace("_", " ").title()

    # Web scraped sources
    url = chunk.get("url", "")
    if "incometax.gov.in" in url:
        return "e-Filing Portal (Official)"
    if "cleartax.in" in url:
        return "ClearTax Guide"
    if "taxguru.in" in url:
        return "TaxGuru"

    return raw or "Tax Reference Document"


def _citation_id(chunk: dict) -> str:
    """Unique identifier for deduplication — URL if available, else chunk_id prefix."""
    url = chunk.get("url", "")
    if url:
        return url
    # For PDFs: use normalised source name as dedup key
    return _nice_source(chunk)


# ── Embedder ───────────────────────────────────────────────────────────────────

def _get_embedder(backend="huggingface"):
    if backend in _embedder_cache:
        return _embedder_cache[backend]
    if backend == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
        def embed(texts):
            resp = client.embeddings.create(model="text-embedding-3-small", input=texts)
            return np.array([r.embedding for r in resp.data], dtype=np.float32)
    else:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("BAAI/bge-small-en-v1.5")
        def embed(texts):
            return model.encode(texts, normalize_embeddings=True,
                                show_progress_bar=False).astype(np.float32)
    _embedder_cache[backend] = embed
    return embed


# ── Index loader ──────────────────────────────────────────────────────────────

def _load_index(ay=DEFAULT_AY):
    if ay in _index_cache:
        return _index_cache[ay], _meta_cache[ay]
    import faiss
    index_path = VECTOR_STORE_DIR / f"{ay}.faiss"
    meta_path  = VECTOR_STORE_DIR / f"{ay}.meta.json"
    if not index_path.exists():
        raise FileNotFoundError(
            f"FAISS index not found: {index_path}. "
            f"Run: python knowledge-base/embedder.py --ay {ay}")
    index = faiss.read_index(str(index_path))
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    _index_cache[ay] = index
    _meta_cache[ay]  = meta
    print(f"Loaded FAISS [{ay}] — {index.ntotal} vectors")
    return index, meta


# ── MMR retrieval ──────────────────────────────────────────────────────────────

def _mmr(query, index, meta, embed_fn, top_k=5, fetch_k=60, lam=0.6):
    q_emb = embed_fn([query])
    distances, ids = index.search(q_emb, fetch_k)
    candidates = []
    for dist, vid in zip(distances[0], ids[0]):
        if vid >= 0:
            c = dict(meta.get(str(vid), {}))
            c["_l2"] = float(dist)
            # Enrich with nice display name immediately
            c["_display_source"] = _nice_source(c)
            candidates.append(c)
    if not candidates:
        return []

    cand_embs = embed_fn([c["text"] for c in candidates])
    q_sims    = (cand_embs @ q_emb.T).flatten()

    # Slight boost for PDF sources (they contain authoritative statutory text)
    def _is_pdf(c):
        return c.get("doc_type", "") in ("official_instructions", "cbdt_circular",
                                          "legislation", "supplementary_guide") \
               or c.get("chunk_id", "").startswith("pdf_")

    selected, remaining = [], list(range(len(candidates)))
    for _ in range(min(top_k, len(candidates))):
        if not remaining:
            break
        if not selected:
            best = max(remaining, key=lambda i: q_sims[i] + (0.06 if _is_pdf(candidates[i]) else 0))
        else:
            sel_e  = cand_embs[selected]
            scores = []
            for i in remaining:
                boost    = 0.06 if _is_pdf(candidates[i]) else 0
                rel      = q_sims[i] + boost
                red      = float(np.max(cand_embs[i] @ sel_e.T))
                scores.append((i, lam * rel - (1 - lam) * red))
            best = max(scores, key=lambda x: x[1])[0]
        selected.append(best)
        remaining.remove(best)
    return [candidates[i] for i in selected]


# ── Cross-encoder reranker ─────────────────────────────────────────────────────

def _rerank(query, chunks):
    try:
        from sentence_transformers import CrossEncoder
        ce     = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        scores = ce.predict([[query, c["text"]] for c in chunks])
        for c, s in zip(chunks, scores):
            c["_score"] = float(s) + (1.5 if c.get("chunk_id", "").startswith("pdf_") else 0)
        chunks.sort(key=lambda x: x.get("_score", 0), reverse=True)
    except Exception as e:
        print(f"Rerank skipped: {e}")
    return chunks


# ── LLM answer ─────────────────────────────────────────────────────────────────

def _answer(query: str, chunks: list[dict], ay: str) -> str:
    # Build numbered context blocks with clear source labels
    ctx_parts = []
    for i, c in enumerate(chunks, 1):
        source_label = c.get("_display_source", _nice_source(c))
        section      = c.get("section", "")
        header       = f"[{i}] {source_label}" + (f" — {section}" if section else "")
        ctx_parts.append(f"{header}\n{c['text']}")
    ctx = "\n\n---\n\n".join(ctx_parts)

    system = (
        f"You are an expert Indian income tax assistant for ITR-1 (Sahaj), AY {ay}. "
        "Your knowledge base includes both official CBDT PDF documents and web sources. "
        "Answer based on the provided context. "
        "If the exact answer is in context, be precise and cite numbers (section, rupee amounts, AY). "
        "If not fully covered, give your best answer and note what's uncertain. "
        "Format your response as:\n\n"
        "**Answer**: <clear direct answer>\n"
        "**Why**: <reasoning based on tax law>\n"
        "**Source**: <quote the relevant line from the context, with source [N] reference>"
    )
    prompt = f"Context:\n{ctx}\n\nQuestion: {query}\n\nResponse:"

    try:
        from shared.llm_client import complete_with_system
        return complete_with_system(system=system, user=prompt, temperature=0.0)
    except Exception as e:
        print(f"LLM failed: {e}")
        # Fallback: return best chunk as plain answer with source
        if chunks:
            src = chunks[0].get("_display_source", _nice_source(chunks[0]))
            return (f"**Answer**: Based on {src}:\n\n"
                    f"{chunks[0]['text'][:600]}\n\n"
                    f"*(LLM unavailable — showing raw source text)*")
        return "No relevant information found in the knowledge base."


# ── Request / Response ─────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str
    ay:       str  = DEFAULT_AY
    top_k:    int  = 5
    backend:  str  = "huggingface"
    rerank:   bool = True

class QueryResponse(BaseModel):
    answer:    str
    citations: list[dict]
    chunks:    list[dict]
    ay:        str


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "rag-service", "default_ay": DEFAULT_AY}


@app.get("/indexes")
def list_indexes():
    if not VECTOR_STORE_DIR.exists():
        return {"indexes": []}
    return {"indexes": [f.stem for f in VECTOR_STORE_DIR.glob("*.faiss")]}


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    try:
        index, meta = _load_index(req.ay)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))

    embed_fn = _get_embedder(req.backend)
    chunks   = _mmr(req.question, index, meta, embed_fn, req.top_k)
    if req.rerank and chunks:
        chunks = _rerank(req.question, chunks)

    answer = _answer(req.question, chunks, req.ay)

    # Build citations — include ALL retrieved sources, URL or not
    seen, citations = set(), []
    for c in chunks:
        cid = _citation_id(c)
        if cid in seen:
            continue
        seen.add(cid)
        url = c.get("url", "")
        citations.append({
            "source":   c.get("_display_source", _nice_source(c)),
            "url":      url,                         # may be "" for PDFs
            "section":  c.get("section", ""),
            "doc_type": c.get("doc_type", ""),
            "is_pdf":   c.get("chunk_id", "").startswith("pdf_"),
            # Short excerpt from the chunk (first 200 chars) for display
            "excerpt":  c["text"][:200].strip() + ("…" if len(c["text"]) > 200 else ""),
        })

    return QueryResponse(
        answer=answer,
        citations=citations,
        ay=req.ay,
        chunks=[{
            "text":    c["text"],
            "source":  c.get("_display_source", _nice_source(c)),
            "section": c.get("section", ""),
            "score":   round(c.get("_score", 0), 3),
        } for c in chunks],
    )


@app.post("/query/chunks")
async def query_chunks_only(req: QueryRequest):
    try:
        index, meta = _load_index(req.ay)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    chunks = _mmr(req.question, index, meta, _get_embedder(req.backend), req.top_k)
    return {"chunks": chunks, "count": len(chunks)}


@app.on_event("startup")
async def startup():
    try:
        print(f"Pre-loading FAISS index [{DEFAULT_AY}]…")
        _load_index(DEFAULT_AY)
        print("Pre-loading embedding model…")
        _get_embedder("huggingface")
        print("Warming up reranker…")
        _rerank("warmup", [{"text": "warmup", "chunk_id": ""}])
        print("All RAG models ready.")
    except Exception as e:
        print(f"Startup warning: {e}")
