import asyncio
import json
import yaml
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ct1.core.orchestrator import Orchestrator
from ct1.server.health import check_server_health
from ct1.server.launcher import (
    load_raw_config, resolve_config,
    kill_existing_llama_servers, start_server, stop_server,
)
from ct1.memory.journal_reader import JournalReader
from ct1.memory.session_store import SessionStore
from ct1.memory.conversation_db import ConversationDB

_CONFIG_PATH = Path(__file__).parent.parent.parent / "ct1" / "server" / "model_config.yaml"

_raw_cfg: dict = load_raw_config(str(_CONFIG_PATH))
_cfg: dict = resolve_config(_raw_cfg, str(_CONFIG_PATH))
_orch: Orchestrator | None = None
_server_procs: list = []
_db: ConversationDB | None = None


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _orch, _server_procs, _db
    # Start llama-server processes, then create orchestrator
    _server_procs = await start_server(str(_CONFIG_PATH))
    _orch = Orchestrator(str(_CONFIG_PATH))
    _db = ConversationDB()
    await _db.init()
    yield
    if _db:
        await _db.close()
    if _orch:
        await _orch.close()
    if _server_procs:
        stop_server(_server_procs)


app = FastAPI(title="CT-2 API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/status")
async def get_status():
    director_url = f"http://localhost:{_cfg['llama_server']['port']}"
    director = await check_server_health(director_url)

    specialist = None
    if "llama_server_specialist" in _cfg:
        specialist_url = f"http://localhost:{_cfg['llama_server_specialist']['port']}"
        specialist = await check_server_health(specialist_url)

    return {"director": director, "specialist": specialist}


@app.get("/api/journal")
async def get_journal(limit: int = 50):
    reader = JournalReader(_cfg["journal"]["path"])
    entries = reader.journal.read_recent(limit)
    stats = reader.get_stats()
    return {"entries": entries, "stats": stats}


@app.get("/api/sessions")
async def get_sessions():
    store = SessionStore(_cfg.get("sessions", {}).get("path", "ct1/data/sessions"))
    sessions_dir = Path(store.dir)
    results = []
    if sessions_dir.exists():
        for f in sorted(sessions_dir.glob("*.txt"), reverse=True):
            results.append({
                "filename": f.name,
                "content": f.read_text(encoding="utf-8").strip(),
            })
    return results


@app.get("/api/config")
async def get_config():
    director_server = _cfg.get("llama_server", {})
    specialist_server = _cfg.get("llama_server_specialist", {})
    result = {
        "models": _cfg.get("models", {}),
        "servers": {
            "director": {
                "port": director_server.get("port"),
                "model": Path(director_server.get("model", "")).name,
                "context_size": director_server.get("context_size"),
                "gpu_layers": director_server.get("n_gpu_layers"),
            },
        },
        "preset": _cfg.get("_preset", "ct2"),
        "preset_info": _cfg.get("_preset_info", {}),
    }
    if specialist_server:
        result["servers"]["specialist"] = {
            "port": specialist_server.get("port"),
            "model": Path(specialist_server.get("model", "")).name,
            "context_size": specialist_server.get("context_size"),
            "gpu_layers": specialist_server.get("n_gpu_layers"),
        }
    return result


@app.get("/api/presets")
async def get_presets():
    """List available presets and the active one."""
    presets = {}
    for name, preset in _raw_cfg.get("presets", {}).items():
        director = preset.get("director", {})
        has_overrides = bool(director.get("task_overrides"))
        presets[name] = {
            "name": preset.get("name", name),
            "description": preset.get("description", ""),
            "best_for": preset.get("best_for", []),
            "not_for": preset.get("not_for", []),
            "solo": "specialist" not in preset,
            "director_model": director.get("model", ""),
            "specialist_model": preset.get("specialist", {}).get("model", "") if "specialist" in preset else None,
            "context_size": director.get("context_size", 0),
            "adaptive": has_overrides,
            "task_modes": list(director.get("task_overrides", {}).keys()) if has_overrides else [],
        }
    return {
        "active": _raw_cfg.get("active_preset", "ct2"),
        "presets": presets,
    }


class PresetSwitch(BaseModel):
    preset: str


@app.post("/api/preset")
async def switch_preset(body: PresetSwitch):
    """Switch to a different model preset. Restarts llama-server processes."""
    global _raw_cfg, _cfg, _orch, _server_procs

    preset_name = body.preset
    if preset_name not in _raw_cfg.get("presets", {}):
        return {"error": f"Unknown preset: {preset_name}"}, 400

    if preset_name == _raw_cfg.get("active_preset"):
        return {"status": "already_active", "preset": preset_name}

    # Update config file
    _raw_cfg["active_preset"] = preset_name
    _CONFIG_PATH.write_text(
        yaml.dump(_raw_cfg, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    # Resolve new config
    _cfg = resolve_config(_raw_cfg, str(_CONFIG_PATH))

    # Teardown old orchestrator
    if _orch:
        await _orch.close()

    # Kill and restart llama-server processes
    kill_existing_llama_servers()
    try:
        _server_procs = await start_server(str(_CONFIG_PATH))
    except Exception as e:
        return {"error": f"Failed to start servers: {e}"}

    # Create new orchestrator
    _orch = Orchestrator(str(_CONFIG_PATH))

    return {
        "status": "switched",
        "preset": preset_name,
        "info": _cfg.get("_preset_info", {}),
    }


@app.get("/api/conversations")
async def list_conversations(limit: int = 50):
    return await _db.list_conversations(limit)


@app.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    conv = await _db.get_conversation(conv_id)
    if not conv:
        return {"error": "Not found"}
    return conv


@app.post("/api/conversations")
async def create_conversation_endpoint(body: dict):
    title = body.get("title", "New conversation")
    preset = body.get("preset", _raw_cfg.get("active_preset", ""))
    conv_id = await _db.create_conversation(title, preset)
    return {"id": conv_id}


@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    deleted = await _db.delete_conversation(conv_id)
    return {"deleted": deleted}


class RenameBody(BaseModel):
    title: str


@app.patch("/api/conversations/{conv_id}")
async def rename_conversation(conv_id: str, body: RenameBody):
    renamed = await _db.rename_conversation(conv_id, body.title)
    return {"renamed": renamed}


class FeedbackBody(BaseModel):
    feedback: int


@app.post("/api/messages/{message_id}/feedback")
async def set_message_feedback(message_id: str, body: FeedbackBody):
    ok = await _db.set_feedback(message_id, body.feedback)
    return {"ok": ok}


@app.websocket("/ws/think")
async def ws_think(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            msg = await websocket.receive_json()
            if msg.get("type") == "think":
                goal = msg.get("goal", "")
                conversation = msg.get("conversation", [])
                queue: asyncio.Queue = asyncio.Queue()

                def on_event(event: str, **data):
                    queue.put_nowait({"event": event, **data})

                async def stream_events():
                    while True:
                        item = await queue.get()
                        await websocket.send_json(item)
                        if item.get("event") == "done":
                            break

                async def run_think():
                    result = await _orch.think(
                        goal, on_event=on_event, conversation=conversation
                    )
                    queue.put_nowait({
                        "event": "done",
                        "response": result["response"],
                        "thinking": result.get("thinking", ""),
                        "draft": result.get("draft", ""),
                        "draft_thinking": result.get("draft_thinking", ""),
                        "route": result.get("route", ""),
                        "specialist_data": result.get("specialist_data"),
                        "reflection": result.get("reflection", {}),
                    })

                    # Auto-persist conversation
                    if _db:
                        import json as _json
                        conv_id = msg.get("conversation_id")
                        if not conv_id:
                            # Auto-title from first ~40 chars of goal
                            title_text = goal if isinstance(goal, str) else (goal[0].get("text", "") if isinstance(goal, list) else str(goal))
                            title = title_text[:40].strip()
                            if len(title_text) > 40:
                                title += "..."
                            conv_id = await _db.create_conversation(title, _raw_cfg.get("active_preset", ""))
                            await websocket.send_json({"event": "conversation_id", "id": conv_id})

                        position = msg.get("position", 0)
                        user_content = goal if isinstance(goal, str) else _json.dumps(goal)
                        await _db.add_message(conv_id, "user", user_content, position)

                        await _db.add_message(
                            conv_id, "assistant", result["response"], position + 1,
                            thinking=result.get("thinking", ""),
                            draft=result.get("draft", ""),
                            route=result.get("route", ""),
                            specialist_data=_json.dumps(result.get("specialist_data") or {}),
                            reflection=_json.dumps(result.get("reflection") or {}),
                        )

                await asyncio.gather(run_think(), stream_events())

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"event": "error", "message": str(e)})
        except Exception:
            pass


# Serve SvelteKit build with SPA fallback
_WEB_BUILD = Path(__file__).parent.parent / "web" / "build"
if _WEB_BUILD.exists():
    from starlette.responses import FileResponse

    class SPAStaticFiles(StaticFiles):
        async def get_response(self, path: str, scope):
            try:
                return await super().get_response(path, scope)
            except Exception:
                # SPA fallback: serve index.html for any unmatched route
                return FileResponse(Path(self.directory) / "index.html")

    app.mount("/", SPAStaticFiles(directory=str(_WEB_BUILD), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000)
