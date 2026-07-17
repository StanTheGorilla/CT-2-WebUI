"""RAG endpoints — status, file management, indexing, search.

Shared state (stores, indexer, progress flags) lives in ct2.server.api;
read and written through the module object at call time.
"""
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

router = APIRouter()


def _core():
    from ct2.server import api
    return api


@router.get("/api/rag/status")
async def rag_status():
    """Return RAG status: enabled, file count, chunk count, context cost."""
    core = _core()
    if not core._rag_store:
        return {"enabled": False, "initialized": core._rag_initialized, "indexing": core._rag_indexing,
                "files": 0, "chunks": 0, "context_cost": 0, "embedding_dim": 0}
    cfg = core._rag_config
    return {
        "enabled": cfg.enabled,
        "initialized": core._rag_initialized,
        "indexing": core._rag_indexing,
        "files": await core._rag_store.count_files(),
        "chunks": (actual_chunks := await core._rag_store.count_chunks()),
        "context_cost": round(min(actual_chunks, cfg.chunks_per_query) * await core._rag_store.avg_chunk_tokens()),
        "embedding_dim": core._rag_store.embedding_dim,
        "chunk_size": cfg.chunk_size,
        "chunks_per_query": cfg.chunks_per_query,
        "data_dir": str(cfg.data_path.resolve()),
        "supported_extensions": sorted(core._RAG_SUPPORTED_EXT),
        "max_file_mb": cfg.max_file_mb,
    }


@router.get("/api/rag/files")
async def rag_list_files():
    """List all indexed files with metadata."""
    core = _core()
    if not core._rag_store:
        return {"files": []}
    files = await core._rag_store.list_files()
    return {
        "files": [
            {
                "name": f["name"],
                "hash": f.get("hash", ""),
                "size_bytes": f.get("size_bytes", 0),
                "size_mb": round(f.get("size_bytes", 0) / 1024 / 1024, 2),
                "chunk_count": f.get("chunk_count", 0),
                "char_count": f.get("char_count", 0),
                "indexed_at": f.get("indexed_at"),
            }
            for f in files
        ]
    }


@router.delete("/api/rag/files/{name}")
async def rag_remove_file(name: str):
    """Remove a file and its chunks from the RAG index."""
    core = _core()
    if not core._rag_indexer:
        raise HTTPException(503, "RAG not initialised")
    ok = await core._rag_indexer.remove_file(name)
    return {"removed": ok, "name": name}


@router.post("/api/rag/upload")
async def rag_upload_file(file: UploadFile = File(...)):
    """Upload a file to the RAG data folder and index it."""
    core = _core()
    if not core._rag_indexer:
        raise HTTPException(503, "RAG not initialised")
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    # Validate extension
    suffix = file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else ""
    if f".{suffix}" not in core._RAG_SUPPORTED_EXT:
        raise HTTPException(400, f"Unsupported file type: .{suffix}. Supported: {', '.join(sorted(core._RAG_SUPPORTED_EXT))}")

    # Save to data folder
    data_path = core._rag_config.data_path
    data_path.mkdir(parents=True, exist_ok=True)
    dest = data_path / file.filename

    content = await file.read()
    size_mb = len(content) / 1024 / 1024
    if size_mb > core._rag_config.max_file_mb:
        raise HTTPException(400, f"File too large: {size_mb:.1f}MB (limit: {core._rag_config.max_file_mb}MB)")

    dest.write_bytes(content)

    # Index the file
    core._rag_indexing = True
    try:
        result = await core._rag_indexer.index_file(dest)
        if result and "error" in result:
            # Keep the file on disk but report the indexing error
            raise HTTPException(500, f"Indexing failed: {result['error']}")
        return {"uploaded": file.filename, "indexed": result}
    finally:
        core._rag_indexing = False


@router.post("/api/rag/reindex")
async def rag_reindex():
    """Rebuild the entire RAG index from files in the data folder."""
    core = _core()
    if not core._rag_indexer:
        raise HTTPException(503, "RAG not initialised")
    if core._rag_indexing:
        raise HTTPException(409, "Indexing already in progress")
    core._rag_indexing = True
    core._rag_progress = {"running": True, "current": 0, "total": 0, "file": "", "stage": "scanning"}
    try:
        def _progress(stage: str, current: int, total: int, file: str = ""):
            core._rag_progress = {"running": True, "current": current, "total": total, "file": file, "stage": stage}
        stats = await core._rag_indexer.index_folder(progress_cb=_progress)
        return {"ok": True, **stats}
    except Exception as e:
        raise HTTPException(500, f"Re-index failed: {e}")
    finally:
        core._rag_indexing = False
        core._rag_progress = {"running": False, "current": 0, "total": 0, "file": "", "stage": "idle"}


@router.get("/api/rag/reindex/progress")
async def rag_reindex_progress():
    """Poll for current reindexing progress."""
    return _core()._rag_progress


@router.get("/api/rag/data-files")
async def rag_data_files():
    """List all files in the RAG uploads folder (not just indexed ones)."""
    core = _core()
    from ct2.rag.config import SUPPORTED_EXTENSIONS as _REXT
    data_path = core._rag_config.data_path
    if not data_path.exists():
        return {"files": [], "data_dir": str(data_path.resolve())}
    files = []
    for ext in sorted(_REXT):
        for p in sorted(data_path.glob(f"**/*{ext}")):
            try:
                st = p.stat()
                files.append({
                    "name": p.name,
                    "rel_path": str(p.relative_to(data_path)),
                    "size_bytes": st.st_size,
                    "size_mb": round(st.st_size / 1024 / 1024, 2),
                    "modified": st.st_mtime,
                })
            except OSError:
                pass
    return {"files": files, "data_dir": str(data_path.resolve())}


@router.delete("/api/rag/data-files/{name}")
async def rag_delete_data_file(name: str):
    """Delete a file from the RAG uploads folder and remove it from the index."""
    core = _core()
    data_path = core._rag_config.data_path
    target = data_path / name
    # Prevent path traversal
    try:
        target.resolve().relative_to(data_path.resolve())
    except ValueError:
        raise HTTPException(400, "Invalid filename")
    if not target.exists():
        raise HTTPException(404, "File not found")
    if core._rag_indexer:
        await core._rag_indexer.remove_file(name)
    target.unlink()
    return {"deleted": name}


class RAGSearchRequest(BaseModel):
    query: str
    top_k: int = 5


@router.post("/api/rag/search")
async def rag_search(body: RAGSearchRequest):
    """Test search: embed a query and return top chunks."""
    core = _core()
    if not core._rag_retriever:
        raise HTTPException(503, "RAG not initialised")
    results = await core._rag_retriever.search(body.query, top_k=body.top_k)
    return {"query": body.query, "results": results}
