"""
FAISS Embedder — RAG Knowledge Base
=====================================
Takes the chunks produced by scraper.py and embeds them into a FAISS index.

Supports two embedding backends:
  1. OpenAI  text-embedding-3-small  (default — best quality, needs API key)
  2. HuggingFace  BAAI/bge-small-en-v1.5  (free, runs locally, nearly as good)

Run:
    # OpenAI (recommended for production)
    OPENAI_API_KEY=sk-... python embedder.py --backend openai

    # Free local model (recommended for dev / viva demo)
    python embedder.py --backend huggingface

Output:
    vector_store/
        AY2024-25.faiss     — FAISS index (flat L2)
        AY2024-25.meta.json — chunk metadata indexed by vector position
"""

import argparse
import json
import os
import pickle
from pathlib import Path
from typing import Optional

import numpy as np

# ── Config ────────────────────────────────────────────────────────────────────
CHUNKS_JSONL = Path("rag_output/combined/all_chunks.jsonl")
VECTOR_STORE  = Path("vector_store")
AY_NAMESPACE  = "AY2024-25"    # change per assessment year

VECTOR_STORE.mkdir(exist_ok=True)


# ── Load chunks ───────────────────────────────────────────────────────────────
def load_chunks(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(
            f"Chunks file not found: {path}\n"
            "Run scraper.py first to generate chunks."
        )
    chunks = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    print(f"Loaded {len(chunks)} chunks from {path}")
    return chunks


# ── OpenAI embeddings ─────────────────────────────────────────────────────────
def embed_openai(texts: list[str], batch_size: int = 100) -> np.ndarray:
    """Embed using text-embedding-3-small. Cost: ~$0.02 per 1M tokens."""
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("Run: pip install openai")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("Set OPENAI_API_KEY environment variable")

    client = OpenAI(api_key=api_key)
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        print(f"  Embedding batch {i // batch_size + 1}/{(len(texts) - 1) // batch_size + 1} ...")
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=batch,
        )
        batch_embs = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embs)

    return np.array(all_embeddings, dtype=np.float32)


# ── HuggingFace embeddings (free) ─────────────────────────────────────────────
def embed_huggingface(texts: list[str], batch_size: int = 32) -> np.ndarray:
    """
    Embed using BAAI/bge-small-en-v1.5 — excellent free model, 384-dim.
    First run downloads ~130MB model weights.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise ImportError("Run: pip install sentence-transformers")

    print("  Loading BAAI/bge-small-en-v1.5 model (downloads ~130MB on first run)...")
    model = SentenceTransformer("BAAI/bge-small-en-v1.5")

    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        print(f"  Embedding batch {i // batch_size + 1}/{(len(texts) - 1) // batch_size + 1} ...")
        embs = model.encode(
            batch,
            normalize_embeddings=True,   # important for BGE models
            show_progress_bar=False,
        )
        all_embeddings.append(embs)

    return np.vstack(all_embeddings).astype(np.float32)


# ── Build FAISS index ─────────────────────────────────────────────────────────
def build_faiss_index(embeddings: np.ndarray, chunks: list[dict], namespace: str):
    try:
        import faiss
    except ImportError:
        raise ImportError("Run: pip install faiss-cpu")

    dim = embeddings.shape[1]
    print(f"\nBuilding FAISS flat-L2 index | dim={dim} | vectors={len(embeddings)}")

    index = faiss.IndexFlatL2(dim)
    # Wrap with IDMap so we can retrieve by chunk_id later
    index_id = faiss.IndexIDMap(index)
    ids = np.arange(len(embeddings), dtype=np.int64)
    index_id.add_with_ids(embeddings, ids)

    # Save index
    index_path = VECTOR_STORE / f"{namespace}.faiss"
    faiss.write_index(index_id, str(index_path))
    print(f"  ✓ FAISS index saved → {index_path}")

    # Save metadata (maps vector ID → chunk metadata)
    meta = {str(i): chunks[i] for i in range(len(chunks))}
    meta_path = VECTOR_STORE / f"{namespace}.meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"  ✓ Metadata saved → {meta_path}")

    return index_path, meta_path


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Embed ITR-1 chunks into FAISS")
    parser.add_argument(
        "--backend", choices=["openai", "huggingface"], default="huggingface",
        help="Embedding backend (default: huggingface — free, no API key needed)"
    )
    parser.add_argument(
        "--ay", default=AY_NAMESPACE,
        help=f"Assessment Year namespace (default: {AY_NAMESPACE})"
    )
    args = parser.parse_args()

    print(f"\n🔢 FAISS Embedder — ITR-1 RAG Knowledge Base")
    print(f"   Backend:   {args.backend}")
    print(f"   Namespace: {args.ay}\n")

    # 1. Load chunks
    chunks = load_chunks(CHUNKS_JSONL)
    texts = [c["text"] for c in chunks]

    # 2. Embed
    print(f"\nEmbedding {len(texts)} chunks using {args.backend}...")
    if args.backend == "openai":
        embeddings = embed_openai(texts)
    else:
        embeddings = embed_huggingface(texts)

    print(f"  ✓ Embeddings shape: {embeddings.shape}")

    # 3. Build + save index
    index_path, meta_path = build_faiss_index(embeddings, chunks, args.ay)

    print(f"\n✅ DONE")
    print(f"\nTo query the index, use retriever.py:")
    print(f"  python retriever.py --query 'What is the 80C deduction limit?' --ay {args.ay}")


if __name__ == "__main__":
    main()
