"""
RAG Retriever — ITR-1 Knowledge Base
======================================
MMR retrieval + cross-encoder reranking, as specified in the project PDF.

Usage:
    python retriever.py --query "what is the 80C limit?" --ay AY2024-25 --top_k 5

Or import as a module in your LangChain FastAPI service:
    from retriever import ITRRetriever
    retriever = ITRRetriever(ay="AY2024-25", backend="huggingface")
    results = retriever.retrieve("what is the 80C limit?")
"""

import argparse
import json
import os
import numpy as np
from pathlib import Path
from dataclasses import dataclass

VECTOR_STORE = Path("vector_store")


@dataclass
class RetrievedChunk:
    chunk_id:       str
    source:         str
    doc_type:       str
    applicable_ay:  str
    section:        str
    url:            str
    text:           str
    token_count:    int
    l2_distance:    float
    rerank_score:   float | None = None


class ITRRetriever:
    """
    ITR-1 RAG retriever.

    Pipeline:
        query → embed → FAISS top-k*3 candidates → MMR diversity filter
               → cross-encoder rerank → return top-k

    The MMR step ensures we don't return 5 near-identical chunks about the
    same topic. The cross-encoder rerank step meaningfully improves precision.
    """

    def __init__(
        self,
        ay:       str  = "AY2024-25",
        backend:  str  = "huggingface",  # "openai" or "huggingface"
        top_k:    int  = 5,
        mmr_lambda: float = 0.6,         # 1.0 = pure relevance, 0.0 = pure diversity
        rerank:   bool = True,
    ):
        self.ay        = ay
        self.backend   = backend
        self.top_k     = top_k
        self.mmr_lambda = mmr_lambda
        self.rerank    = rerank

        self._load_index()
        self._load_embedder()
        if rerank:
            self._load_reranker()

    # ── Index loading ──────────────────────────────────────────────────────────

    def _load_index(self):
        import faiss
        index_path = VECTOR_STORE / f"{self.ay}.faiss"
        meta_path  = VECTOR_STORE / f"{self.ay}.meta.json"

        if not index_path.exists():
            raise FileNotFoundError(
                f"FAISS index not found: {index_path}\n"
                "Run embedder.py first."
            )

        self.index = faiss.read_index(str(index_path))
        with open(meta_path, encoding="utf-8") as f:
            self.meta = json.load(f)
        print(f"✓ Loaded FAISS index [{self.ay}] — {self.index.ntotal} vectors")

    # ── Embedding backend ──────────────────────────────────────────────────────

    def _load_embedder(self):
        if self.backend == "huggingface":
            from sentence_transformers import SentenceTransformer
            self._st_model = SentenceTransformer("BAAI/bge-small-en-v1.5")
            self._embed_fn = self._embed_hf
        else:
            from openai import OpenAI
            self._oa_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
            self._embed_fn = self._embed_openai

    def _embed_hf(self, texts: list[str]) -> np.ndarray:
        embs = self._st_model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return embs.astype(np.float32)

    def _embed_openai(self, texts: list[str]) -> np.ndarray:
        response = self._oa_client.embeddings.create(
            model="text-embedding-3-small", input=texts
        )
        return np.array([r.embedding for r in response.data], dtype=np.float32)

    # ── Reranker ───────────────────────────────────────────────────────────────

    def _load_reranker(self):
        try:
            from sentence_transformers import CrossEncoder
            print("  Loading cross-encoder/ms-marco-MiniLM-L-6-v2 ...")
            self._cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        except Exception as e:
            print(f"  ⚠ Cross-encoder load failed ({e}), reranking disabled")
            self.rerank = False

    # ── MMR ────────────────────────────────────────────────────────────────────

    def _mmr(
        self,
        query_emb:     np.ndarray,    # (1, dim)
        candidate_embs: np.ndarray,   # (n, dim)
        candidates:    list[dict],
        k:             int,
    ) -> list[dict]:
        """
        Maximum Marginal Relevance — selects k diverse & relevant chunks.
        Relevance: cosine similarity to query
        Diversity: penalise candidates similar to already-selected ones
        """
        selected_indices = []
        remaining_indices = list(range(len(candidates)))

        # Precompute query similarities (cosine — embeddings are L2-normalised for HF backend)
        query_sims = (candidate_embs @ query_emb.T).flatten()  # (n,)

        for _ in range(min(k, len(candidates))):
            if not remaining_indices:
                break

            if not selected_indices:
                # First pick: most similar to query
                best = max(remaining_indices, key=lambda i: query_sims[i])
            else:
                # Subsequent picks: MMR score = λ*relevance - (1-λ)*max_redundancy
                selected_embs = candidate_embs[selected_indices]  # (s, dim)
                scores = []
                for i in remaining_indices:
                    relevance  = query_sims[i]
                    redundancy = float(np.max(candidate_embs[i] @ selected_embs.T))
                    mmr_score  = self.mmr_lambda * relevance - (1 - self.mmr_lambda) * redundancy
                    scores.append((i, mmr_score))
                best = max(scores, key=lambda x: x[1])[0]

            selected_indices.append(best)
            remaining_indices.remove(best)

        return [candidates[i] for i in selected_indices]

    # ── Main retrieve ──────────────────────────────────────────────────────────

    def retrieve(self, query: str) -> list[RetrievedChunk]:
        # 1. Embed query
        q_emb = self._embed_fn([query])   # (1, dim)

        # 2. Retrieve top-k*3 candidates from FAISS (so MMR has enough to choose from)
        fetch_k = min(self.top_k * 3, self.index.ntotal)
        distances, ids = self.index.search(q_emb, fetch_k)

        candidates = []
        candidate_embs = []
        for dist, vid in zip(distances[0], ids[0]):
            if vid < 0:
                continue
            chunk_meta = self.meta[str(vid)]
            candidates.append({**chunk_meta, "l2_distance": float(dist)})

        # Get embeddings for MMR (re-embed candidate texts)
        cand_texts = [c["text"] for c in candidates]
        cand_embs  = self._embed_fn(cand_texts)   # (n, dim)

        # 3. MMR diversity filter
        diverse_candidates = self._mmr(q_emb, cand_embs, candidates, k=self.top_k)

        # 4. Cross-encoder reranking
        if self.rerank and hasattr(self, "_cross_encoder"):
            pairs = [[query, c["text"]] for c in diverse_candidates]
            rerank_scores = self._cross_encoder.predict(pairs)
            for c, score in zip(diverse_candidates, rerank_scores):
                c["rerank_score"] = float(score)
            diverse_candidates.sort(key=lambda x: x["rerank_score"], reverse=True)

        # 5. Build result objects
        results = []
        for c in diverse_candidates:
            results.append(RetrievedChunk(
                chunk_id      = c["chunk_id"],
                source        = c["source"],
                doc_type      = c["doc_type"],
                applicable_ay = c["applicable_ay"],
                section       = c["section"],
                url           = c["url"],
                text          = c["text"],
                token_count   = c["token_count"],
                l2_distance   = c["l2_distance"],
                rerank_score  = c.get("rerank_score"),
            ))

        return results


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query",   required=True)
    parser.add_argument("--ay",      default="AY2024-25")
    parser.add_argument("--backend", default="huggingface", choices=["openai", "huggingface"])
    parser.add_argument("--top_k",   type=int, default=5)
    parser.add_argument("--no-rerank", action="store_true")
    args = parser.parse_args()

    retriever = ITRRetriever(
        ay=args.ay,
        backend=args.backend,
        top_k=args.top_k,
        rerank=not args.no_rerank,
    )

    print(f'\n🔍 Query: "{args.query}"\n')
    results = retriever.retrieve(args.query)

    for i, chunk in enumerate(results, 1):
        print(f"{'─'*60}")
        print(f"[{i}] {chunk.source} | {chunk.section}")
        print(f"     L2 dist: {chunk.l2_distance:.4f}", end="")
        if chunk.rerank_score is not None:
            print(f" | Rerank score: {chunk.rerank_score:.4f}", end="")
        print(f"\n     URL: {chunk.url}")
        print(f"\n{chunk.text[:400]}{'...' if len(chunk.text) > 400 else ''}\n")


if __name__ == "__main__":
    main()
