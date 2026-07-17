"""RAG embedder — call llama-server /v1/embeddings to embed text chunks.

Supports two modes:
  1. Chat model    — same server as inference (port from model_config)
  2. Dedicated model — separate llama-server on embedding_port
"""

import asyncio
from typing import Optional

import httpx
import numpy as np


class RAGEmbedder:
    """Embeds text via llama.cpp's /v1/embeddings endpoint."""

    def __init__(self, base_url: str = "http://localhost:8080",
                 max_chunk_chars: int = 4000):
        self.base_url = base_url.rstrip("/")
        self.max_chunk_chars = max_chunk_chars
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120.0)
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def embed_single(self, text: str, _retries: int = 20,
                           _retry_delay: float = 3.0) -> np.ndarray:
        """Embed a single text and return a float32 vector.

        Retries up to _retries times on 503 (model still loading).
        """
        client = await self._get_client()
        for attempt in range(_retries + 1):
            r = await client.post(
                f"{self.base_url}/v1/embeddings",
                json={"input": text[:self.max_chunk_chars]},
            )
            if r.status_code == 503 and attempt < _retries:
                await asyncio.sleep(_retry_delay)
                continue
            if not r.is_success:
                try:
                    detail = r.json()
                except Exception:
                    detail = r.text
                raise RuntimeError(
                    f"Embedding server returned {r.status_code}: {detail}\n"
                    "Make sure the model server was restarted after enabling RAG "
                    "(it needs --embeddings --pooling last to be passed at startup)."
                )
            data = r.json()["data"]
            return np.array(data[0]["embedding"], dtype=np.float32)
        raise RuntimeError("Embedding server not ready after waiting (repeated 503)")

    async def embed_batch(self, texts: list[str],
                          concurrency: int = 4,
                          progress_cb=None) -> list[Optional[np.ndarray]]:
        """Embed multiple texts in parallel batches.

        Args:
            texts: List of text strings to embed.
            concurrency: Max parallel embedding calls.
            progress_cb: Optional callback(idx, total) for each completed embedding.

        Returns:
            List of numpy arrays aligned with `texts`. Failed embeddings are None.
            Callers should zip with their metadata to skip failed entries.
        """
        if not texts:
            return []

        semaphore = asyncio.Semaphore(concurrency)
        results: list[Optional[np.ndarray]] = [None] * len(texts)

        async def _embed_one(idx: int, text: str) -> None:
            async with semaphore:
                try:
                    vec = await self.embed_single(text)
                    results[idx] = vec
                    if progress_cb:
                        progress_cb(idx, len(texts))
                except Exception as e:
                    print(f"[rag] embed failed for chunk {idx}: {e}")
                    results[idx] = None

        tasks = [_embed_one(i, t) for i, t in enumerate(texts)]
        await asyncio.gather(*tasks)

        valid_count = sum(1 for v in results if v is not None)
        if valid_count == 0:
            raise RuntimeError("All embeddings failed — is the model server running?")

        return results

    async def health_check(self) -> bool:
        """Check if the embedding server is reachable."""
        try:
            client = await self._get_client()
            r = await client.get(f"{self.base_url}/health", timeout=httpx.Timeout(3.0))
            return r.status_code == 200
        except Exception:
            return False
