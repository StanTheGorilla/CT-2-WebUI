"""Conversation, search, feedback and component-cache endpoints.

Shared state (_db, _cache, _raw_cfg) lives in ct2.server.api; read at
call time through the module object.
"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ct2.memory.component_cache import ComponentCache

router = APIRouter()


def _core():
    from ct2.server import api
    return api


@router.get("/api/conversations")
async def list_conversations(limit: int = 50):
    return await _core()._db.list_conversations(limit)


@router.get("/api/search")
async def search_conversations(q: str = "", limit: int = 20):
    if not q.strip():
        return []
    return await _core()._db.search(q.strip(), limit)


@router.get("/api/web-search")
async def web_search_endpoint(q: str = "", max_results: int = 5):
    """Run a DuckDuckGo web search and return structured results."""
    from ct2.core.web_searcher import search_web
    if not q.strip():
        return {"query": q, "results": [], "error": "Empty query"}
    resp = await search_web(q.strip(), max_results=max(1, min(max_results, 20)))
    return {
        "query": resp.query,
        "results": [{"title": r.title, "url": r.url, "snippet": r.snippet} for r in resp.results],
        "error": resp.error,
    }


@router.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    conv = await _core()._db.get_conversation(conv_id)
    if not conv:
        return {"error": "Not found"}
    return conv


class CreateConversationBody(BaseModel):
    title: str = "New conversation"
    preset: str = ""


@router.post("/api/conversations")
async def create_conversation_endpoint(body: CreateConversationBody):
    core = _core()
    preset = body.preset or core._raw_cfg.get("active_preset", "")
    conv_id = await core._db.create_conversation(body.title, preset)
    return {"id": conv_id}


class ForkConversationBody(BaseModel):
    upto_position: int | None = None
    title: str | None = None
    conversation: list[dict] | None = None


@router.post("/api/conversations/{conv_id}/fork")
async def fork_conversation_endpoint(conv_id: str, body: ForkConversationBody):
    db = _core()._db
    if body.conversation is not None:
        forked = await db.fork_conversation_from_messages(
            conv_id, body.conversation, body.title
        )
    elif body.upto_position is not None:
        forked = await db.fork_conversation(conv_id, body.upto_position, body.title)
    else:
        raise HTTPException(status_code=400, detail="Missing fork source")
    if forked is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return forked


@router.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    deleted = await _core()._db.delete_conversation(conv_id)
    return {"deleted": deleted}


class RenameBody(BaseModel):
    title: str


@router.patch("/api/conversations/{conv_id}")
async def rename_conversation(conv_id: str, body: RenameBody):
    renamed = await _core()._db.rename_conversation(conv_id, body.title)
    return {"renamed": renamed}


class FeedbackBody(BaseModel):
    feedback: int


@router.post("/api/messages/{message_id}/feedback")
async def set_message_feedback(message_id: str, body: FeedbackBody):
    core = _core()
    ok = await core._db.set_feedback(message_id, body.feedback)

    # Auto-cache on thumbs up for code messages
    if body.feedback == 1 and core._cache:
        try:
            cursor = await core._db._conn.execute(
                "SELECT content, route, specialist_data FROM messages WHERE id = ?",
                (message_id,),
            )
            row = await cursor.fetchone()
            if row and row["route"] in ("ROUTE_DESIGN", "ROUTE_CODE"):
                sp_data = None
                try:
                    sp_data = json.loads(row["specialist_data"]) if row["specialist_data"] else None
                except Exception:
                    pass
                tags = ComponentCache.extract_tags(row["content"][:200], sp_data)
                category = ComponentCache.categorize(row["content"][:200])
                await core._cache.save_component(
                    category, tags, row["content"], 0.9, "(thumbs up)"
                )
        except Exception as e:
            print(f"[api] cache save on feedback error: {e}")

    return {"ok": ok}


@router.get("/api/cache")
async def list_cached_components(limit: int = 20):
    cache = _core()._cache
    if not cache:
        return []
    return await cache.list_all(limit)


@router.delete("/api/cache/{comp_id}")
async def delete_cached_component(comp_id: str):
    cache = _core()._cache
    if not cache:
        return {"deleted": False}
    return {"deleted": await cache.delete(comp_id)}
