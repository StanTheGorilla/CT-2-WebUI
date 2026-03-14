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
