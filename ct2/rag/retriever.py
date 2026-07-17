"""RAG retriever — embed a query and find the most relevant chunks.

Features:
  - Cosine-similarity search via llama.cpp embeddings
  - Keyword-boosted scoring (exact term matches increase relevance)
  - Neighbor chunk expansion (pull in surrounding chunks for context)
  - Deduplication and source-aware grouping
"""

import re as _re
from pathlib import Path
from typing import Optional

import numpy as np

from ct2.rag.store import RAGStore
from ct2.rag.embedder import RAGEmbedder


# Characters that split keywords for exact-match boosting
_KEYWORD_SPLIT_RE = _re.compile(r"[^\w]+")
# Minimum keyword length to consider for boosting
_MIN_KEYWORD_LEN = 3


def _extract_keywords(query: str) -> set[str]:
    """Extract meaningful lowercase keywords from a query for boosting."""
    tokens = _KEYWORD_SPLIT_RE.split(query.lower())
    # Also collect quoted phrases
    quoted = _re.findall(r'"([^"]+)"', query)
    quoted += _re.findall(r"'([^']+)'", query)
    keywords = {t for t in tokens if len(t) >= _MIN_KEYWORD_LEN}
    keywords.update(q.lower() for q in quoted if len(q) >= _MIN_KEYWORD_LEN)
    return keywords


def _keyword_boost(chunk_text: str, keywords: set[str], boost: float = 0.15) -> float:
    """Return a score boost (0..1) based on how many keywords appear in the chunk."""
    if not keywords:
        return 0.0
    text_lower = chunk_text.lower()
    hits = sum(1 for kw in keywords if kw in text_lower)
    return min(boost, hits / max(len(keywords), 1) * boost)


class RAGRetriever:
    """Searches the RAG index for chunks relevant to a query.

    Parameters:
        store: RAGStore instance
        embedder: RAGEmbedder instance
        neighbor_radius: how many chunks before/after each hit to include
        keyword_boost: extra score (0..1) added per keyword match fraction
    """

    def __init__(self, store: RAGStore, embedder: RAGEmbedder,
                 neighbor_radius: int = 1,
                 keyword_boost: float = 0.15):
        self.store = store
        self.embedder = embedder
        self.neighbor_radius = neighbor_radius
        self.keyword_boost = keyword_boost

    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Find top-k most relevant chunks for a query.

        Returns list of dicts:
            {"text": str, "source": str, "tokens": int, "score": float,
             "chunk_id": int, "chunk_index": int}
        """
        embeddings = await self.store.get_all_embeddings()
        if embeddings is None or embeddings.size == 0:
            return []

        # Embed the query
        query_vec = await self.embedder.embed_single(query)
        query_vec = query_vec.reshape(1, -1)

        # Cosine similarity: normalize both, then dot product
        query_norm = query_vec / (np.linalg.norm(query_vec, axis=1, keepdims=True) + 1e-10)
        emb_norm = embeddings / (np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-10)
        scores = (query_norm @ emb_norm.T).flatten()

        # Keyword extraction for boosting
        keywords = _extract_keywords(query)

        # Fetch top-k*2 candidates so we have headroom after boosting re-ranks
        k_fetch = min(top_k * 3, len(scores))
        if k_fetch == 0:
            return []

        top_indices = np.argpartition(scores, -k_fetch)[-k_fetch:]
        top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]

        # Log raw top scores for debugging
        _raw_scores = [float(scores[i]) for i in top_indices[:top_k]]
        print(f"[rag] raw query scores (top-{min(top_k, len(_raw_scores))}): "
              f"{[round(s, 4) for s in _raw_scores]}")

        # Build candidate list with keyword boosting
        candidates: list[dict] = []
        seen_ids: set[int] = set()
        for idx in top_indices:
            score = float(scores[idx])
            chunk_id = int(idx)
            if chunk_id in seen_ids:
                continue
            seen_ids.add(chunk_id)
            chunk = await self.store.get_chunk(chunk_id)
            if not chunk:
                continue
            text = chunk.get("text", "")
            # Apply keyword boost
            if keywords:
                boost = _keyword_boost(text, keywords, self.keyword_boost)
                score += boost
            candidates.append({
                "text": text,
                "source": chunk.get("source", chunk.get("file_name", "")),
                "tokens": chunk["tokens"],
                "score": round(score, 4),
                "chunk_id": chunk_id,
                "chunk_index": chunk.get("chunk_index", 0),
            })

        # Sort by boosted score
        candidates.sort(key=lambda c: c["score"], reverse=True)

        # Filter very low scores (only near-zero / orthogonal)
        results = [c for c in candidates if c["score"] > 0.01][:top_k]
        return results

    async def format_context(self, query: str, top_k: int = 5,
                             expand_neighbors: bool = True) -> str:
        """Search, expand neighbors, and format results as a context block.

        Args:
            query: User query to search against.
            top_k: How many top chunks to retrieve by embedding similarity.
            expand_neighbors: If True, fetch ±neighbor_radius chunks from the
                              same file for each hit.

        Returns:
            Formatted context string for injection into the LLM prompt,
            or empty string if nothing was found.
        """
        results = await self.search(query, top_k=top_k)
        if not results:
            return ""

        # ── Neighbor expansion ──
        all_chunks: dict[int, dict] = {}  # chunk_id -> result dict
        for r in results:
            all_chunks[r["chunk_id"]] = r

        if expand_neighbors and self.neighbor_radius > 0:
            for r in list(results):  # iterate copy since we may modify
                try:
                    neighbors = await self.store.get_neighbor_chunks(
                        r["chunk_id"], radius=self.neighbor_radius,
                    )
                except Exception:
                    neighbors = []
                for n in neighbors:
                    nid = n["id"]
                    if nid not in all_chunks:
                        all_chunks[nid] = {
                            "text": n["text"],
                            "source": n.get("source", n.get("file_name", "")),
                            "tokens": n["tokens"],
                            "score": 0.0,  # neighbors get no score of their own
                            "chunk_id": nid,
                            "chunk_index": n["chunk_index"],
                        }

        # Sort all chunks by (source, chunk_index) so same-file chunks stay together
        sorted_chunks = sorted(
            all_chunks.values(),
            key=lambda c: (c["source"], c["chunk_index"]),
        )

        # ── Format ──
        blocks: list[str] = []
        last_source = ""
        total_tokens = 0
        for ch in sorted_chunks:
            source = ch["source"]
            if source != last_source:
                last_source = source
                # Show file-level context: how many chunks in this file, position
                blocks.append(f"\n=== {source} ===")
            ci = ch["chunk_index"]
            labeled = f"[section {ci}]" if ch["score"] > 0 else f"[nearby {ci}]"
            blocks.append(f"{labeled}\n{ch['text']}")
            total_tokens += ch["tokens"]

        header = (
            f"[RAG CONTEXT — {len(sorted_chunks)} snippets ({total_tokens} tokens) "
            f"from {len(set(c['source'] for c in sorted_chunks))} document(s)]\n"
        )
        return header + "\n".join(blocks)
