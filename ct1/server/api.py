import asyncio
import json
import yaml
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from ct1.core.orchestrator import Orchestrator
from ct1.server.health import check_server_health
from ct1.memory.journal_reader import JournalReader
from ct1.memory.session_store import SessionStore

_CONFIG_PATH = Path(__file__).parent.parent.parent / "ct1" / "server" / "model_config.yaml"

_cfg: dict = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8"))
_orch: Orchestrator | None = None


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _orch
    _orch = Orchestrator(str(_CONFIG_PATH))
    yield
    if _orch:
        await _orch.close()


app = FastAPI(title="CT-1 API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/status")
async def get_status():
    brain_url = f"http://localhost:{_cfg['llama_server']['port']}"
    minds_url = f"http://localhost:{_cfg['llama_server_minds']['port']}"
    brain = await check_server_health(brain_url)
    minds = await check_server_health(minds_url)
    return {"brain": brain, "minds": minds}


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
    return {
        "models": _cfg.get("models", {}),
        "deliberation": _cfg.get("deliberation", {}),
    }


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
                        "rounds": result["rounds"],
                        "complexity": result["complexity"],
                        "reflection": result.get("reflection", {}),
                        "dialogue": result.get("dialogue", []),
                    })

                await asyncio.gather(run_think(), stream_events())

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"event": "error", "message": str(e)})
        except Exception:
            pass


# Serve SvelteKit build in production
_WEB_BUILD = Path(__file__).parent.parent / "web" / "build"
if _WEB_BUILD.exists():
    app.mount("/", StaticFiles(directory=str(_WEB_BUILD), html=True), name="static")
