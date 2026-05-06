"""RAG store — SQLite for metadata + numpy .npy file for embeddings.

Tables:
  files        — indexed file metadata (name, hash, size, chunk_count, indexed_at)
  chunks       — chunk text and metadata (file_id, chunk_index, tokens, source)

Embeddings are stored as a float32 numpy array rows=chunks, cols=embedding_dim.
They're memory-mapped from disk for fast startup.
"""

import asyncio as _asyncio
import gc as _gc
import hashlib as _hashlib
import io as _io
import os as _os
import time as _time
from pathlib import Path
from typing import Optional

import aiosqlite
import numpy as np


_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    hash        TEXT    NOT NULL,
    size_bytes  INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    char_count  INTEGER NOT NULL DEFAULT 0,
    indexed_at  REAL    NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    tokens      INTEGER NOT NULL DEFAULT 0,
    text        TEXT    NOT NULL,
    source      TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_id);
CREATE INDEX IF NOT EXISTS idx_files_name  ON files(name);
"""


class RAGStore:
    """Manages the RAG SQLite database and numpy embedding array."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).resolve()
        self.embeddings_path = self.db_path.with_suffix(".npy")
        self._conn: aiosqlite.Connection | None = None
        self._embeddings: np.ndarray | None = None
        self._embedding_dim: int = 0
        self._write_lock = _asyncio.Lock()

    # ── Lifecycle ───────────────────────────────────────────────────

    async def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Clean up stale temp file from a previous crashed write
        _tmp = self.embeddings_path.with_suffix(".npy.tmp")
        if _tmp.exists():
            try:
                _tmp.unlink()
            except OSError:
                pass
        self._conn = await aiosqlite.connect(str(self.db_path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(_SCHEMA)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.commit()
        await self._load_embeddings()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    # ── Embeddings ──────────────────────────────────────────────────

    def _release_mmap(self) -> None:
        """Force-close the memory-mapped backing file on Windows.

        Setting self._embeddings = None drops the Python reference but does
        *not* guarantee the underlying mmap handle is closed immediately.
        On Windows this keeps the file locked, which causes PermissionError
        when os.replace() tries to overwrite it.

        We walk the base object to find and close the mmap, then force a GC
        cycle so any remaining references the numpy C layer held are swept.
        """
        emb = self._embeddings
        if emb is not None:
            # numpy memmap wraps a plain ndarray when loaded with mmap_mode='r';
            # the actual mmap is stored as ._mmap on the memmap object.
            # Walk the chain: base -> base -> ... until we hit a memmap or bottom.
            obj = emb
            for _ in range(4):  # at most 4 levels of .base indirection
                if hasattr(obj, '_mmap'):
                    try:
                        obj._mmap.close()
                    except Exception:
                        pass
                    break
                if hasattr(obj, 'base') and obj.base is not None:
                    obj = obj.base
                else:
                    break
        self._embeddings = None
        _gc.collect()

    def _save_npy(self, arr: np.ndarray) -> None:
        """Write a numpy array to disk atomically via a temp file.

        Writing directly to the .npy path fails on Windows (errno 22) when
        that file is (or recently was) memory-mapped. Writing to a sibling
        temp file and using os.replace() sidesteps the lock entirely — but
        only if the mmap backing the old file has been fully released first.

        Call _release_mmap() before calling this.
        """
        buf = _io.BytesIO()
        np.save(buf, arr)
        tmp = self.embeddings_path.with_suffix(".npy.tmp")
        # Remove any leftover temp file from a previous crashed write
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        tmp.write_bytes(buf.getvalue())

        # Retry with backoff — on Windows, transient locks from AV or
        # other processes can cause spurious PermissionError.
        last_err = None
        for attempt in range(3):
            try:
                _os.replace(tmp, self.embeddings_path)
                return
            except PermissionError:
                last_err = _os.strerror(13)
                # On Windows, try deleting the target first as a fallback
                if _os.name == 'nt':
                    try:
                        self.embeddings_path.unlink(missing_ok=True)
                        _os.replace(tmp, self.embeddings_path)
                        return
                    except OSError:
                        pass
                _time.sleep(0.2 * (attempt + 1))
            except OSError as e:
                last_err = str(e)
                _time.sleep(0.2 * (attempt + 1))

        # If all retries failed, try one last hail-mary: copy + delete
        import shutil as _shutil
        try:
            _shutil.copy2(tmp, self.embeddings_path)
            tmp.unlink()
            return
        except OSError:
            pass

        raise OSError(f"Failed to save embeddings after 3 retries: {last_err}")

    async def _load_embeddings(self) -> None:
        if self.embeddings_path.exists():
            self._embeddings = np.load(str(self.embeddings_path), mmap_mode="r")
            self._embedding_dim = self._embeddings.shape[1] if self._embeddings.ndim == 2 else 0
        else:
            self._embeddings = None
            self._embedding_dim = 0

    async def save_embeddings(self, vectors: np.ndarray, chunk_ids: list[int]) -> None:
        """Save embeddings array to disk. vectors[i] corresponds to chunk_ids[i].

        The array is indexed by SQLite chunk ID (1-based), so row 0 is unused.
        Array size = max(chunk_ids) + 1 to accommodate the highest ID.
        """
        if vectors.size == 0 or not chunk_ids:
            return

        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)

        dim = vectors.shape[1]
        required_rows = max(chunk_ids) + 1  # IDs are 1-based; row 0 stays zeroed

        async with self._write_lock:
            cur = self._embeddings
            cur_ok = (cur is not None and cur.ndim == 2
                      and cur.shape[0] >= required_rows and cur.shape[1] == dim)

            if cur_ok:
                new_emb = np.array(cur, dtype=np.float32)
            else:
                new_emb = np.zeros((required_rows, dim), dtype=np.float32)
                if cur is not None and cur.ndim == 2 and cur.shape[1] == dim:
                    min_rows = min(required_rows, cur.shape[0])
                    new_emb[:min_rows] = cur[:min_rows]

            for i, cid in enumerate(chunk_ids):
                if i < len(vectors):
                    new_emb[cid] = vectors[i]

            self._release_mmap()
            self._save_npy(new_emb)
            await self._load_embeddings()

    async def get_all_embeddings(self) -> np.ndarray | None:
        """Return the full embedding matrix (memory-mapped, read-only)."""
        return self._embeddings

    @property
    def embedding_dim(self) -> int:
        return self._embedding_dim

    # ── Files ───────────────────────────────────────────────────────

    @staticmethod
    def hash_file(path: Path) -> str:
        """SHA256 of file contents."""
        h = _hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    async def add_file(self, name: str, file_hash: str,
                       size_bytes: int, chunk_count: int,
                       char_count: int) -> int:
        """Insert or replace a file entry. Returns file_id."""
        c = self._conn
        await c.execute(
            "DELETE FROM files WHERE name = ?", (name,)
        )
        cur = await c.execute(
            "INSERT INTO files (name, hash, size_bytes, chunk_count, char_count, indexed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, file_hash, size_bytes, chunk_count, char_count, _time.time()),
        )
        await c.commit()
        return cur.lastrowid

    async def remove_file(self, name: str) -> bool:
        """Remove a file and its chunks. Returns True if a file was deleted."""
        c = self._conn
        cur = await c.execute("DELETE FROM files WHERE name = ?", (name,))
        await c.commit()
        deleted = cur.rowcount > 0
        if deleted:
            await self._rebuild_embeddings_from_db()
        return deleted

    async def get_file(self, name: str) -> dict | None:
        cur = await self._conn.execute(
            "SELECT * FROM files WHERE name = ?", (name,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_file_hash(self, name: str) -> str | None:
        row = await self.get_file(name)
        return row["hash"] if row else None

    async def list_files(self) -> list[dict]:
        cur = await self._conn.execute(
            "SELECT * FROM files ORDER BY name"
        )
        return [dict(row) for row in await cur.fetchall()]

    async def count_files(self) -> int:
        cur = await self._conn.execute("SELECT COUNT(*) as n FROM files")
        row = await cur.fetchone()
        return row["n"] if row else 0

    # ── Chunks ──────────────────────────────────────────────────────

    async def add_chunks(self, file_id: int,
                         chunks: list[dict]) -> list[int]:
        """Insert chunks. Returns list of chunk row IDs."""
        ids: list[int] = []
        for ch in chunks:
            cur = await self._conn.execute(
                "INSERT INTO chunks (file_id, chunk_index, tokens, text, source) "
                "VALUES (?, ?, ?, ?, ?)",
                (file_id, ch["chunk_index"], ch["tokens"],
                 ch["text"], ch.get("source", "")),
            )
            ids.append(cur.lastrowid)
        await self._conn.commit()
        return ids

    async def remove_chunks_for_file(self, file_id: int) -> None:
        await self._conn.execute(
            "DELETE FROM chunks WHERE file_id = ?", (file_id,)
        )
        await self._conn.commit()

    async def get_chunk(self, chunk_id: int) -> dict | None:
        cur = await self._conn.execute(
            "SELECT c.*, f.name as file_name FROM chunks c "
            "JOIN files f ON c.file_id = f.id "
            "WHERE c.id = ?", (chunk_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_neighbor_chunks(self, chunk_id: int, radius: int = 1) -> list[dict]:
        """Fetch N chunks before and after the given chunk from the same file.

        Returns chunks sorted by chunk_index (ascending). The reference chunk
        itself is NOT included — only its neighbors.
        """
        # First find the file_id and chunk_index of the reference chunk
        cur = await self._conn.execute(
            "SELECT file_id, chunk_index FROM chunks WHERE id = ?", (chunk_id,)
        )
        ref = await cur.fetchone()
        if not ref:
            return []
        file_id = ref["file_id"]
        ci = ref["chunk_index"]
        cur = await self._conn.execute(
            "SELECT c.*, f.name as file_name FROM chunks c "
            "JOIN files f ON c.file_id = f.id "
            "WHERE c.file_id = ? AND c.id != ? "
            "  AND c.chunk_index >= ? AND c.chunk_index <= ? "
            "ORDER BY c.chunk_index ASC",
            (file_id, chunk_id, ci - radius, ci + radius),
        )
        return [dict(row) for row in await cur.fetchall()]

    async def count_chunks(self) -> int:
        cur = await self._conn.execute("SELECT COUNT(*) as n FROM chunks")
        row = await cur.fetchone()
        return row["n"] if row else 0

    async def avg_chunk_tokens(self) -> float:
        cur = await self._conn.execute("SELECT AVG(tokens) as a FROM chunks")
        row = await cur.fetchone()
        return float(row["a"]) if row and row["a"] else 0.0

    async def all_chunk_ids(self) -> list[int]:
        cur = await self._conn.execute("SELECT id FROM chunks ORDER BY id")
        return [row["id"] for row in await cur.fetchall()]

    # ── Internal ─────────────────────────────────────────────────────

    async def _rebuild_embeddings_from_db(self) -> None:
        """Rebuild embeddings array after chunk deletions. Dropped chunks get
        removed, remaining chunks keep their vectors."""
        if self._embeddings is None or self._embeddings.size == 0:
            return
        async with self._write_lock:
            ids = await self.all_chunk_ids()
            if not ids:
                self._release_mmap()
                self._save_npy(np.array([], dtype=np.float32))
                await self._load_embeddings()
                return

            max_id = max(ids)
            dim = self._embedding_dim
            new_emb = np.zeros((max_id + 1, dim), dtype=np.float32)
            for cid in ids:
                if cid < len(self._embeddings):
                    new_emb[cid] = self._embeddings[cid]
            self._release_mmap()
            self._save_npy(new_emb)
            await self._load_embeddings()
