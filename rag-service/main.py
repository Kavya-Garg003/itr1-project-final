"""
RAG Service — FastAPI
======================
Loads the FAISS index built by knowledge-base/embedder.py and answers
tax questions using MMR retrieval + cross-encoder reranking + GPT-4o-mini.

Compatible with the raw FAISS format saved by embedder.py
(files: vector_store/AY2024-25.faiss + AY2024-25.meta.json)

Exposes:
  GET  /health
  GET  /indexes
  POST /query
  POST /query/chunks
"""

import os
import json
import numpy as np
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))  # /app in Docker
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

VECTOR_STORE_DIR = Path(os.getenv("VECTOR_STORE_DIR", "/app/vector_store"))
DEFAULT_AY       = os.getenv("DEFAULT_AY", "AY2024-25")
OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY", "")

app = FastAPI(title="RAG Service", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_index_cache, _meta_cache, _embedder_cache = {}, {}, {}


def _get_embedder(backend="huggingface"):
    if backend in _embedder_cache:
        return _embedder_cache[backend]
    if backend == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        def embed(texts):
            resp = client.embeddings.create(model="text-embedding-3-small", input=texts)
            return np.array([r.embedding for r in resp.data], dtype=np.float32)
    else:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("BAAI/bge-small-en-v1.5")
        def embed(texts):
            return model.encode(texts, normalize_embeddings=True, show_progress_bar=False).astype(np.float32)
    _embedder_cache[backend] = embed
    return embed


def _load_index(ay=DEFAULT_AY):
    if ay in _index_cache:
        return _index_cache[ay], _meta_cache[ay]
    import faiss
    index_path = VECTOR_STORE_DIR / f"{ay}.faiss"
    meta_path  = VECTOR_STORE_DIR / f"{ay}.meta.json"
    if not index_path.exists():
        raise FileNotFoundError(f"FAISS index not found: {index_path}. Run: python knowledge-base/embedder.py --ay {ay}")
    index = faiss.read_index(str(index_path))
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    _index_cache[ay] = index
    _meta_cache[ay]  = meta
    print(f"Loaded FAISS [{ay}] — {index.ntotal} vectors")
    return index, meta


def _mmr(query, index, meta, embed_fn, top_k=5, fetch_k=15, lam=0.6):
    q_emb = embed_fn([query])
    distances, ids = index.search(q_emb, fetch_k)
    candidates = []
    for dist, vid in zip(distances[0], ids[0]):
        if vid >= 0:
            c = dict(meta.get(str(vid), {}))
            c["_l2"] = float(dist)
            candidates.append(c)
    if not candidates:
        return []
    cand_embs = embed_fn([c["text"] for c in candidates])
    q_sims = (cand_embs @ q_emb.T).flatten()
    selected, remaining = [], list(range(len(candidates)))
    for _ in range(min(top_k, len(candidates))):
        if not remaining: break
        if not selected:
            best = max(remaining, key=lambda i: q_sims[i])
        else:
            sel_e = cand_embs[selected]
            scores = [(i, lam*q_sims[i] - (1-lam)*float(np.max(cand_embs[i] @ sel_e.T))) for i in remaining]
            best = max(scores, key=lambda x: x[1])[0]
        selected.append(best); remaining.remove(best)
    return [candidates[i] for i in selected]


def _rerank(query, chunks):
    try:
        from sentence_transformers import CrossEncoder
        ce = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        scores = ce.predict([[query, c["text"]] for c in chunks])
        for c, s in zip(chunks, scores): c["_score"] = float(s)
        chunks.sort(key=lambda x: x.get("_score", 0), reverse=True)
    except Exception:
        pass
    return chunks


def _answer(query, chunks, ay):
    ctx = "\n\n---\n\n".join(f"[{c.get('source','')} | {c.get('section','')}]\n{c['text']}" for c in chunks)
    system = (
        f"You are an expert ITR-1 tax assistant for {ay}. "
        "Answer using ONLY the provided context. Do NOT hallucinate or guess. "
        "You MUST structure your response strictly in the following format:\n"
        "**Answer**: <your direct final answer>\n"
        "**Reasoning**: <why you concluded this based on the tax law context>\n"
        "**Source Quote**: <the exact snippet from the text you used>\n"
        "**Citation**: <source file/URL and section>"
    )
    prompt = f"Context:\n{ctx}\n\nQuestion: {query}\n\nResponse:"
    try:
        from shared.llm_client import complete_with_system
        return complete_with_system(system=system, user=prompt, temperature=0.0)
    except Exception as e:
        # All LLM providers failed — return best chunk as plain text answer
        print(f"LLM fallback exhausted: {e}")
        return chunks[0]["text"] if chunks else "No answer found in knowledge base."


class QueryRequest(BaseModel):
    question: str
    ay:       str  = DEFAULT_AY
    top_k:    int  = 5
    backend:  str  = "huggingface"
    rerank:   bool = True

class QueryResponse(BaseModel):
    answer: str; citations: list[dict]; chunks: list[dict]; ay: str


@app.get("/health")
def health():
    return {"status": "ok", "service": "rag-service", "default_ay": DEFAULT_AY}

@app.get("/indexes")
def list_indexes():
    if not VECTOR_STORE_DIR.exists(): return {"indexes": []}
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
    answer   = _answer(req.question, chunks, req.ay)
    seen, citations = set(), []
    for c in chunks:
        url = c.get("url","")
        if url and url not in seen:
            citations.append({"source":c.get("source",""),"url":url,"section":c.get("section","")})
            seen.add(url)
    return QueryResponse(
        answer=answer, citations=citations, ay=req.ay,
        chunks=[{"text":c["text"],"source":c.get("source",""),"section":c.get("section","")} for c in chunks])

@app.post("/query/chunks")
async def query_chunks_only(req: QueryRequest):
    try: index, meta = _load_index(req.ay)
    except FileNotFoundError as e: raise HTTPException(404, str(e))
    chunks = _mmr(req.question, index, meta, _get_embedder(req.backend), req.top_k)
    return {"chunks": chunks, "count": len(chunks)}

@app.on_event("startup")
async def startup():
    try: _load_index(DEFAULT_AY)
    except Exception as e: print(f"Warning: Could not pre-load {DEFAULT_AY}: {e}")
