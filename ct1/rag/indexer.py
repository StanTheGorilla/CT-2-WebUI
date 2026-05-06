"""RAG indexer — orchestrates the parse → chunk → embed → store pipeline."""

import asyncio
from pathlib import Path
from typing import Optional

import numpy as np

from ct1.rag.config import RAGConfig, SUPPORTED_EXTENSIONS
from ct1.rag.parser import parse_file
from ct1.rag.chunker import chunk_text
from ct1.rag.store import RAGStore
from ct1.rag.embedder import RAGEmbedder


class RAGIndexer:
    """Full RAG indexing pipeline: scan folder, parse files, chunk, embed, store."""

    def __init__(self, config: RAGConfig, store: RAGStore,
                 embedder: RAGEmbedder):
        self.config = config
        self.store = store
        self.embedder = embedder

    async def index_folder(self, progress_cb=None) -> dict:
        """Index all supported files in the RAG data directory.

        Skips files whose SHA256 hash hasn't changed since last indexing.
        Returns stats dict: {files_added, files_updated, files_removed,
                              files_skipped, chunks_total, errors}
        """
        data_path = self.config.data_path
        if not data_path.exists():
            if progress_cb:
                progress_cb("scan", 0, 0, f"RAG data folder not found: {data_path}")
            return {"files_added": 0, "files_updated": 0, "files_removed": 0,
                    "files_skipped": 0, "chunks_total": 0, "errors": 0}

        # Collect supported files
        all_files: list[Path] = []
        for ext in SUPPORTED_EXTENSIONS:
            all_files.extend(data_path.glob(f"**/*{ext}"))
        all_files.sort(key=lambda p: p.name.lower())

        # Get existing file hashes from DB
        existing = await self.store.list_files()
        existing_map: dict[str, dict] = {f["name"]: f for f in existing}

        stats = {
            "files_added": 0, "files_updated": 0, "files_removed": 0,
            "files_skipped": 0, "chunks_total": 0, "errors": 0,
        }

        # Detect removed files
        current_names = {f.name for f in all_files}
        for ex_name in existing_map:
            if ex_name not in current_names:
                await self.store.remove_file(ex_name)
                stats["files_removed"] += 1

        # Index each file
        max_bytes = self.config.max_file_mb * 1024 * 1024
        total = len(all_files)

        for idx, file_path in enumerate(all_files):
            name = file_path.name

            if progress_cb:
                progress_cb("index", idx + 1, total, name)

            # Skip oversized files
            size_bytes = file_path.stat().st_size
            if size_bytes > max_bytes:
                stats["errors"] += 1
                print(f"[rag] Skipping {name}: {size_bytes / 1024 / 1024:.1f}MB exceeds "
                      f"{self.config.max_file_mb}MB limit")
                continue

            # Hash check — skip unchanged files
            file_hash = RAGStore.hash_file(file_path)
            if name in existing_map and existing_map[name]["hash"] == file_hash:
                stats["files_skipped"] += 1
                stats["chunks_total"] += existing_map[name]["chunk_count"]
                continue

            # Parse
            text, char_count, error = parse_file(file_path)
            if error:
                stats["errors"] += 1
                print(f"[rag] Parse error: {error}")
                continue

            # Chunk
            chunks = chunk_text(
                text,
                chunk_size=self.config.chunk_size,
                chunk_overlap=self.config.chunk_overlap,
                source=name,
            )
            if not chunks:
                print(f"[rag] No chunks extracted from {name}")
                continue

            # Embed (batch)
            chunk_texts = [c["text"] for c in chunks]
            try:
                vectors = await self.embedder.embed_batch(
                    chunk_texts,
                    progress_cb=lambda i, t: print(
                        f"[rag]   embedding chunk {i + 1}/{len(chunks)} of {name}"
                    ) if i % 10 == 0 else None,
                )
            except Exception as e:
                stats["errors"] += 1
                print(f"[rag] Embedding failed for {name}: {e}")
                continue

            # Store
            file_id = await self.store.add_file(
                name, file_hash, size_bytes, len(chunks), char_count,
            )
            chunk_ids = await self.store.add_chunks(file_id, chunks)

            # Save embeddings — only for chunks that embedded successfully.
            # embed_batch returns aligned results so failed entries don't misalign.
            valid_vecs = []
            valid_cids = []
            for v, cid in zip(vectors, chunk_ids):
                if v is not None:
                    valid_vecs.append(v)
                    valid_cids.append(cid)
            if valid_vecs:
                await self.store.save_embeddings(
                    np.stack(valid_vecs, axis=0), valid_cids,
                )

            is_new = name not in existing_map
            if is_new:
                stats["files_added"] += 1
            else:
                stats["files_updated"] += 1
            stats["chunks_total"] += len(chunks)

            # Short breather between files to avoid hammering the server
            await asyncio.sleep(0.05)

        return stats

    async def index_file(self, file_path: Path) -> dict | None:
        """Index a single file. Returns file info dict or None on error."""
        name = file_path.name
        suffix = name.lower().rsplit(".", 1)[-1] if "." in name else ""
        if f".{suffix}" not in SUPPORTED_EXTENSIONS:
            return {"error": f"Unsupported file type: .{suffix}"}

        size_bytes = file_path.stat().st_size
        max_bytes = self.config.max_file_mb * 1024 * 1024
        if size_bytes > max_bytes:
            return {"error": f"File too large: {size_bytes/1024/1024:.1f}MB "
                             f"(limit: {self.config.max_file_mb}MB)"}

        file_hash = RAGStore.hash_file(file_path)

        text, char_count, error = parse_file(file_path)
        if error:
            return {"error": error}

        chunks = chunk_text(
            text,
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
            source=name,
        )
        if not chunks:
            return {"error": "No text chunks extracted"}

        chunk_texts = [c["text"] for c in chunks]
        try:
            vectors = await self.embedder.embed_batch(chunk_texts)
        except Exception as e:
            return {"error": f"Embedding failed: {e}"}

        file_id = await self.store.add_file(
            name, file_hash, size_bytes, len(chunks), char_count,
        )
        chunk_ids = await self.store.add_chunks(file_id, chunks)
        # Save embeddings — only for chunks that embedded successfully.
        valid_vecs = []
        valid_cids = []
        for v, cid in zip(vectors, chunk_ids):
            if v is not None:
                valid_vecs.append(v)
                valid_cids.append(cid)
        if valid_vecs:
            await self.store.save_embeddings(
                np.stack(valid_vecs, axis=0), valid_cids,
            )

        return {
            "name": name,
            "hash": file_hash,
            "size_bytes": size_bytes,
            "size_mb": round(size_bytes / 1024 / 1024, 2),
            "chunks": len(chunks),
            "char_count": char_count,
        }

    async def remove_file(self, name: str) -> bool:
        """Remove a file and its chunks from the index."""
        return await self.store.remove_file(name)
