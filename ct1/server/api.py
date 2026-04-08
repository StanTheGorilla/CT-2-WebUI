import asyncio
import json
import yaml
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from ct1.core.orchestrator import Orchestrator, _get_mode_registry
from ct1.prompts.manager import _get_prompt_manager as _get_pm
from ct1.server.health import check_server_health
from ct1.server.launcher import (
    load_raw_config, resolve_config,
    kill_existing_llama_servers, start_server, stop_server,
)
from ct1.memory.journal_reader import JournalReader
from ct1.memory.session_store import SessionStore
from ct1.memory.conversation_db import ConversationDB
from ct1.memory.component_cache import ComponentCache
from ct1.server.workspace import WorkspaceManager, is_command_safe

_CONFIG_PATH = Path(__file__).parent.parent.parent / "ct1" / "server" / "model_config.yaml"
_MODES_DIR = Path(__file__).parent.parent / "modes"
_BUILTIN_MODES: frozenset[str] = frozenset({"direct", "code", "design", "computer"})

_raw_cfg: dict = load_raw_config(str(_CONFIG_PATH))
try:
    _cfg: dict = resolve_config(_raw_cfg, str(_CONFIG_PATH))
except Exception as _cfg_err:
    print(f"[api] WARNING: Config not loaded: {_cfg_err}")
    print("[api]    Open Settings in the web UI to assign a model file to your preset.")
    _cfg = {}
_orch: Orchestrator | None = None
_server_procs: list = []
_db: ConversationDB | None = None
_cache: ComponentCache | None = None
_workspace: WorkspaceManager | None = None
_swapping: bool = False          # True while model swap is in progress
_shutting_down: bool = False     # True during application shutdown
_active_think_tasks: set = set() # Active /ws/think asyncio tasks
_health_task: asyncio.Task | None = None  # Background health monitor task
_WS_QUEUE_MAX = 500  # Max buffered events per WebSocket session (~1-2 full responses)


async def _health_monitor(port: int = 8080, interval: float = 30.0) -> None:
    """Periodically check llama-server health and auto-restart if unresponsive.

    Runs as a background task for the application lifetime. Checks every
    `interval` seconds. After 3 consecutive failures, attempts auto-restart.
    """
    global _server_procs, _orch, _swapping
    import httpx
    consecutive_failures = 0

    while True:
        await asyncio.sleep(interval)

        # Skip checks during model swap or shutdown
        if _swapping or _shutting_down:
            consecutive_failures = 0
            continue

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"http://localhost:{port}/health")
            if resp.status_code == 200:
                consecutive_failures = 0
                continue
        except Exception:
            pass

        consecutive_failures += 1
        print(f"[health] llama-server health check failed ({consecutive_failures}/3)")

        if consecutive_failures >= 3:
            consecutive_failures = 0
            # Re-check swap/shutdown state before acting — a user-triggered swap may
            # have started after we accumulated 3 failures
            if _swapping or _shutting_down:
                continue
            print("[health] 3 consecutive failures — attempting auto-restart")
            _swapping = True
            try:
                stop_server(_server_procs)
                _server_procs = await start_server(str(_CONFIG_PATH))
                if _orch:
                    await _orch.reset_engine_client()
                print("[health] Auto-restart successful")
            except Exception as e:
                print(f"[health] Auto-restart failed: {e}")
                # _orch may be stale after failed restart — next request will timeout
            finally:
                _swapping = False


def _npm_run(args: list, cwd: str) -> "subprocess.CompletedProcess":
    """Run an npm command cross-platform.

    On Windows, .cmd scripts cannot be executed directly by CreateProcess —
    they must be dispatched through cmd.exe via shell=True.
    On Linux/macOS shell=False is fine; npm is a real executable.
    """
    import subprocess
    import sys as _sys
    return subprocess.run(
        ["npm"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        shell=(_sys.platform == "win32"),
    )


def _ensure_frontend_built() -> None:
    """Run npm install (if needed) then npm run build on every startup."""
    import shutil
    if not shutil.which("npm"):
        print("[api] WARNING: npm not found — install Node.js to build the frontend.")
        return
    web_dir = Path(__file__).parent.parent / "web"
    # Install dependencies if node_modules is missing
    if not (web_dir / "node_modules").exists():
        print("[api] Installing frontend dependencies (npm install)...")
        result = _npm_run(["install"], str(web_dir))
        if result.returncode != 0:
            print(f"[api] WARNING: npm install failed:\n{result.stderr[-1000:]}")
            return

    print("[api] Building frontend...")
    result = _npm_run(["run", "build"], str(web_dir))
    if result.returncode != 0:
        print(f"[api] WARNING: npm build failed:\n{result.stderr[-1000:]}")
    else:
        print("[api] Frontend ready.")


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _orch, _server_procs, _db, _cache, _workspace, _shutting_down
    try:
        _server_procs = await start_server(str(_CONFIG_PATH))
    except Exception as e:
        print(f"[api] WARNING: Model server failed to start: {e}")
        print("[api]    Open Settings in the web UI to assign a model file to your preset.")
    _cache = ComponentCache()
    await _cache.init()
    try:
        _orch = Orchestrator(str(_CONFIG_PATH), component_cache=_cache)
    except Exception as e:
        print(f"[api] WARNING: Orchestrator init failed: {e}")
    _db = ConversationDB()
    await _db.init()
    _workspace = WorkspaceManager()
    global _health_task
    _health_task = asyncio.create_task(_health_monitor(port=_cfg.get("llama_server", {}).get("port", 8080)))
    yield
    _shutting_down = True
    if _health_task:
        _health_task.cancel()
        try:
            await _health_task
        except asyncio.CancelledError:
            pass
    # Drain active generations (max 30s)
    snapshot = set(_active_think_tasks)
    if snapshot:
        print(f"[api] Shutdown: waiting for {len(snapshot)} active generation(s)...")
        try:
            _done, _pending = await asyncio.wait(snapshot, timeout=30.0)
            if _pending:
                print(f"[api] Shutdown: {len(_pending)} generation(s) did not finish in 30s — cancelling")
                for task in _pending:
                    task.cancel()
                # Await cancellation to complete before tearing down resources
                await asyncio.gather(*_pending, return_exceptions=True)
        except Exception:
            pass
    if _db:
        await _db.close()
    if _cache:
        await _cache.close()
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
    port = _cfg.get("llama_server", {}).get("port", 8080)
    model_url = f"http://localhost:{port}"
    model = await check_server_health(model_url)
    return {"model": model}


## ── llama-server update ──────────────────────────────────────────────────────

_update_state: dict[str, dict] = {}  # backend → {status, message, log}

def _run_update(backend: str, project_root):
    from pathlib import Path
    from ct1.server.downloader import download_llama_server
    from ct1.server.launcher import stop_server
    _update_state[backend] = {"status": "downloading", "message": "Starting download...", "log": []}
    log = _update_state[backend]["log"]
    def _cb(msg: str):
        log.append(msg)
        _update_state[backend]["message"] = msg
    try:
        # Stop the running server so Windows releases the DLL file locks
        if _server_procs:
            _cb("[update] Stopping llama-server to release file locks...")
            stop_server(_server_procs)

        download_llama_server(
            Path(project_root), backends=[backend], force=True, progress_cb=_cb
        )
        _update_state[backend]["status"] = "done"
        _update_state[backend]["message"] = f"{backend.upper()} updated successfully. Reload a model in Settings to restart."
    except Exception as e:
        _update_state[backend]["status"] = "error"
        _update_state[backend]["message"] = str(e)


@app.post("/api/llama/update/{backend}")
async def start_llama_update(backend: str):
    if backend not in ("vulkan", "cuda"):
        from fastapi import HTTPException
        raise HTTPException(400, "backend must be 'vulkan' or 'cuda'")
    if _update_state.get(backend, {}).get("status") == "downloading":
        return {"error": "Update already in progress"}
    import threading
    project_root = Path(__file__).parent.parent.parent
    t = threading.Thread(target=_run_update, args=(backend, project_root), daemon=True)
    t.start()
    return {"started": True, "backend": backend}


@app.get("/api/llama/update/{backend}/status")
async def get_llama_update_status(backend: str):
    return _update_state.get(backend, {"status": "idle", "message": "", "log": []})


@app.get("/api/journal")
async def get_journal(limit: int = 50):
    journal_path = _cfg.get("journal", {}).get("path", "ct1/data/journals")
    reader = JournalReader(journal_path)
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
    server = _cfg.get("llama_server", {})
    model_params = _cfg.get("models", {}).get("director", {})
    preset_info = _cfg.get("_preset_info", {})
    return {
        "preset": _cfg.get("_preset", ""),
        "preset_name": preset_info.get("name", ""),
        "tier": preset_info.get("tier"),
        "model": Path(server.get("model", "")).name,
        "context_size": server.get("context_size"),
        "gguf_context_length": _cfg.get("_gguf_context_length"),
        "port": server.get("port"),
        "gpu_layers": server.get("n_gpu_layers"),
        "enable_thinking": model_params.get("enable_thinking", True),
        "temperature": model_params.get("temperature", 0.6),
        "top_p": model_params.get("top_p", 0.9),
        "top_k": model_params.get("top_k", 40),
        "presence_penalty": model_params.get("presence_penalty", 0),
        "frequency_penalty": model_params.get("frequency_penalty", 0),
        "max_tokens": model_params.get("max_tokens", 100000),
        "thinking_budget": model_params.get("thinking_budget", -1),
        "vision_supported": model_params.get("vision_supported", False),
        "backend": _raw_cfg.get("backend", "vulkan"),
    }


@app.get("/api/model")
async def get_model_info():
    """Return current active model info."""
    from ct1.core.gguf_reader import read_context_length
    from ct1.server.launcher import _detect_thinking_support

    models_dir_rel = _raw_cfg.get("models_dir", "models")
    project_root = _CONFIG_PATH.resolve().parent.parent.parent
    models_dir = project_root / models_dir_rel

    model_name = _raw_cfg.get("active_model") or ""
    model_path = (models_dir / model_name) if model_name else None
    model_found = bool(model_path and model_path.exists())
    gguf_ctx = read_context_length(model_path) if model_path and model_found else None
    yaml_ctx = _raw_cfg.get("context_size")
    thinking = _detect_thinking_support(model_name) if model_name else False

    return {
        "active_model": model_name,
        "model_found": model_found,
        "enable_thinking": thinking,
        "context_size": yaml_ctx or gguf_ctx or 0,
        "gguf_context_length": gguf_ctx,
    }


# Legacy endpoint — frontend may still call this
@app.get("/api/presets")
async def get_presets():
    """Return model info in a format compatible with legacy frontend."""
    from ct1.core.gguf_reader import read_context_length
    from ct1.server.launcher import _detect_thinking_support

    models_dir_rel = _raw_cfg.get("models_dir", "models")
    project_root = _CONFIG_PATH.resolve().parent.parent.parent
    models_dir = project_root / models_dir_rel

    model_name = _raw_cfg.get("active_model") or ""
    model_path = (models_dir / model_name) if model_name else None
    model_found = bool(model_path and model_path.exists())
    gguf_ctx = read_context_length(model_path) if model_path and model_found else None
    yaml_ctx = _raw_cfg.get("context_size")
    thinking = _detect_thinking_support(model_name) if model_name else False

    return {
        "active_model": model_name,
        "model_found": model_found,
        "enable_thinking": thinking,
        "context_size": yaml_ctx or gguf_ctx or 0,
        "gguf_context_length": gguf_ctx,
    }


@app.get("/api/models")
async def list_models():
    """List .gguf files found in the configured models directory, with file sizes and capabilities."""
    from ct1.server.launcher import _detect_thinking_support
    from ct1.core.gguf_reader import read_context_length

    models_dir_rel = _raw_cfg.get("models_dir", "models")
    models_dir = _CONFIG_PATH.resolve().parent.parent.parent / models_dir_rel
    if not models_dir.exists():
        return {"models": [], "models_dir": str(models_dir)}
    files = []
    for p in sorted(models_dir.glob("*.gguf")):
        try:
            size_gb = round(p.stat().st_size / (1024 ** 3), 2)
        except OSError:
            size_gb = 0.0
        gguf_ctx = read_context_length(p)
        files.append({
            "name": p.name,
            "size_gb": size_gb,
            "thinking": _detect_thinking_support(p.name),
            "context_length": gguf_ctx,
        })
    return {"models": files, "models_dir": str(models_dir)}


class ModelSelect(BaseModel):
    model: str
    context_size: int | None = None


class ModeUpdate(BaseModel):
    """Partial update for a mode definition.

    Note: `priority` and `route_id` are intentionally excluded — they can only
    be set at creation time. To change priority, delete and recreate the mode.
    """

    description: str | None = None
    patterns: list[str] | None = None
    negative_patterns: list[str] | None = None
    lang_patterns: list[str] | None = None
    detected_lang: str | None = None
    task_overrides: dict | None = None


class ModeCreate(BaseModel):
    name: str
    route_id: str
    description: str = ""
    priority: int = 99
    patterns: list[str] = Field(default_factory=list)
    negative_patterns: list[str] = Field(default_factory=list)
    lang_patterns: list[str] = Field(default_factory=list)
    detected_lang: str = "text"
    task_overrides: dict = Field(default_factory=dict)


class PromptUpdate(BaseModel):
    """Update a prompt's content. Content replaces the full prompt text."""
    content: str


@app.get("/api/modes")
async def list_modes():
    """List all loaded mode definitions."""
    registry = _get_mode_registry()
    return {"modes": [
        {
            "name": m.name,
            "route_id": m.route_id,
            "description": m.description,
            "priority": m.priority,
            "patterns": m.patterns,
            "negative_patterns": m.negative_patterns,
            "lang_patterns": m.lang_patterns,
            "detected_lang": m.detected_lang,
            "task_overrides": m.task_overrides,
        }
        for m in registry.get_all()
    ]}


@app.get("/api/modes/{name}")
async def get_mode(name: str):
    """Get a single mode definition by name."""
    registry = _get_mode_registry()
    for m in registry.get_all():
        if m.name == name:
            return {
                "name": m.name,
                "route_id": m.route_id,
                "description": m.description,
                "priority": m.priority,
                "patterns": m.patterns,
                "negative_patterns": m.negative_patterns,
                "lang_patterns": m.lang_patterns,
                "detected_lang": m.detected_lang,
                "task_overrides": m.task_overrides,
            }
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail=f"Mode '{name}' not found")


@app.put("/api/modes/{name}")
async def update_mode(name: str, body: ModeUpdate):
    """Update an existing mode's config and persist to YAML. Reloads registry."""
    import os, tempfile
    yaml_path = (_MODES_DIR / f"{name}.yaml").resolve()
    if yaml_path.parent != _MODES_DIR.resolve():
        raise HTTPException(status_code=400, detail="Invalid mode name")
    if not yaml_path.exists():
        raise HTTPException(status_code=404, detail=f"Mode file '{name}.yaml' not found")
    with yaml_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    # Apply only fields that were provided
    if body.description is not None:
        data["description"] = body.description
    if body.patterns is not None:
        data["patterns"] = body.patterns
    if body.negative_patterns is not None:
        data["negative_patterns"] = body.negative_patterns
    if body.lang_patterns is not None:
        data["lang_patterns"] = body.lang_patterns
    if body.detected_lang is not None:
        data["detected_lang"] = body.detected_lang
    if body.task_overrides is not None:
        data["task_overrides"] = body.task_overrides
    content = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(_MODES_DIR), suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, str(yaml_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    _get_mode_registry().reload()
    return {"ok": True, "name": name}


@app.post("/api/modes")
async def create_mode(body: ModeCreate):
    """Create a new mode definition YAML file. Reloads registry."""
    import os, tempfile
    yaml_path = (_MODES_DIR / f"{body.name}.yaml").resolve()
    if yaml_path.parent != _MODES_DIR.resolve():
        raise HTTPException(status_code=400, detail="Invalid mode name")
    if yaml_path.exists():
        raise HTTPException(status_code=409, detail=f"Mode '{body.name}' already exists")
    data = {
        "name": body.name,
        "route_id": body.route_id,
        "description": body.description,
        "priority": body.priority,
        "patterns": body.patterns,
        "negative_patterns": body.negative_patterns,
        "lang_patterns": body.lang_patterns,
        "detected_lang": body.detected_lang,
        "task_overrides": body.task_overrides,
    }
    content = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(_MODES_DIR), suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, str(yaml_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    _get_mode_registry().reload()
    return {"ok": True, "name": body.name}


@app.delete("/api/modes/{name}")
async def delete_mode(name: str):
    """Delete a mode YAML file and reload the registry."""
    # Protect built-in modes from deletion
    if name in _BUILTIN_MODES:
        raise HTTPException(status_code=403, detail=f"Built-in mode '{name}' cannot be deleted")
    yaml_path = (_MODES_DIR / f"{name}.yaml").resolve()
    if yaml_path.parent != _MODES_DIR.resolve():
        raise HTTPException(status_code=400, detail="Invalid mode name")
    if not yaml_path.exists():
        raise HTTPException(status_code=404, detail=f"Mode '{name}' not found")
    yaml_path.unlink()
    _get_mode_registry().reload()
    return {"ok": True, "name": name}


@app.get("/api/prompts")
async def list_prompts():
    """List all loaded prompts with their content."""
    return {"prompts": _get_pm().list_all()}


@app.get("/api/prompts/{name}")
async def get_prompt(name: str):
    """Get a single prompt by name."""
    pm = _get_pm()
    all_prompts = pm.list_all()
    if name not in all_prompts:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' not found")
    return {"name": name, "content": all_prompts[name]}


@app.put("/api/prompts/{name}")
async def update_prompt(name: str, body: PromptUpdate):
    """Update a prompt's content. Persists to disk and updates the in-memory cache."""
    pm = _get_pm()
    # Only allow updating existing prompts (no creating new ones via PUT)
    if name not in pm.list_all():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' not found")
    try:
        pm.save(name, body.content)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "name": name, "restart_required": True}


@app.post("/api/prompts/{name}/reset")
async def reset_prompt(name: str):
    """Reset a prompt to its shipped default content."""
    pm = _get_pm()
    try:
        content = pm.reset(name)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True, "name": name, "content": content, "restart_required": True}


@app.post("/api/model/select")
async def select_model(body: ModelSelect):
    """Select a model file and restart the server.

    On failure: reverts config to the previous model and attempts to restart
    with it, so the server is never left in a permanently broken state.
    """
    global _raw_cfg, _cfg, _orch, _server_procs, _swapping, _active_think_tasks

    # Validate model exists
    models_dir_rel = _raw_cfg.get("models_dir", "models")
    models_dir = _CONFIG_PATH.resolve().parent.parent.parent / models_dir_rel
    model_path = models_dir / body.model
    if not model_path.exists():
        return {"error": f"Model file not found: {body.model}"}

    # Save previous config for rollback
    prev_model = _raw_cfg.get("active_model")
    prev_context = _raw_cfg.get("context_size")

    _swapping = True
    try:
        # Drain active generation tasks (max 30s)
        snapshot = set(_active_think_tasks)
        if snapshot:
            print(f"[api] Waiting for {len(snapshot)} active generation(s) to complete...")
            try:
                _done, _pending = await asyncio.wait(snapshot, timeout=30.0)
                if _pending:
                    print(f"[api] WARNING: {len(_pending)} generation(s) did not finish in 30s — proceeding with swap")
            except Exception:
                pass

        # Update config
        _raw_cfg["active_model"] = body.model
        if body.context_size is not None:
            _raw_cfg["context_size"] = body.context_size
        _CONFIG_PATH.write_text(
            yaml.dump(_raw_cfg, default_flow_style=False, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

        # Resolve config
        try:
            _cfg = resolve_config(_raw_cfg, str(_CONFIG_PATH),
                                  context_size_override=body.context_size)
        except Exception as e:
            _rollback_model_config(prev_model, prev_context)
            return {"error": str(e)}

        # Teardown old orchestrator
        if _orch:
            await _orch.close()
            _orch = None  # Prevent stale calls if start_server fails below

        # Restart llama-server
        if _server_procs:
            stop_server(_server_procs)
            _server_procs = []
        try:
            _server_procs = await start_server(str(_CONFIG_PATH),
                                               context_size_override=body.context_size)
        except Exception as e:
            # Model failed to load — revert config and try to restart with previous model
            err_msg = str(e)
            print(f"[api] Model '{body.model}' failed to load: {err_msg}")
            reverted = await _rollback_and_restart(prev_model, prev_context)
            suffix = f" Reverted to {prev_model}." if reverted else " No working model available — select a different model."
            return {"error": f"Model failed to load: {err_msg}.{suffix}"}

        # New orchestrator
        _orch = Orchestrator(str(_CONFIG_PATH),
                             context_size_override=body.context_size,
                             component_cache=_cache)
        await _orch.reset_engine_client()  # Flush stale TCP connections from prior server

        return {
            "status": "ok",
            "model": body.model,
            "info": _cfg.get("_preset_info", {}),
        }
    finally:
        _swapping = False


def _rollback_model_config(prev_model, prev_context):
    """Revert model_config.yaml to the previous model."""
    global _raw_cfg
    if prev_model:
        _raw_cfg["active_model"] = prev_model
    if prev_context is not None:
        _raw_cfg["context_size"] = prev_context
    _CONFIG_PATH.write_text(
        yaml.dump(_raw_cfg, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"[api] Config reverted to model: {prev_model}")


async def _rollback_and_restart(prev_model, prev_context) -> bool:
    """Revert config and try to restart llama-server with the previous model.
    Returns True if recovery succeeded."""
    global _server_procs, _orch, _cfg
    _rollback_model_config(prev_model, prev_context)
    if not prev_model:
        return False
    try:
        _cfg = resolve_config(_raw_cfg, str(_CONFIG_PATH))
        _server_procs = await start_server(str(_CONFIG_PATH))
        _orch = Orchestrator(str(_CONFIG_PATH), component_cache=_cache)
        await _orch.reset_engine_client()
        print(f"[api] Recovery successful — running on {prev_model}")
        return True
    except Exception as re:
        print(f"[api] Recovery with previous model also failed: {re}")
        return False


class BackendSelect(BaseModel):
    backend: str  # "vulkan" | "cuda"


@app.post("/api/backend/select")
async def select_backend(body: BackendSelect):
    """Switch active backend (vulkan/cuda) and restart llama-server."""
    global _raw_cfg, _cfg, _orch, _server_procs, _swapping, _active_think_tasks

    if body.backend not in ("vulkan", "cuda"):
        return {"error": f"Invalid backend '{body.backend}'. Must be 'vulkan' or 'cuda'."}

    _swapping = True
    try:
        # Drain active generation tasks (max 30s)
        snapshot = set(_active_think_tasks)
        if snapshot:
            print(f"[api] Waiting for {len(snapshot)} active generation(s) to complete...")
            try:
                _done, _pending = await asyncio.wait(snapshot, timeout=30.0)
                if _pending:
                    print(f"[api] WARNING: {len(_pending)} generation(s) did not finish in 30s — proceeding with swap")
            except Exception:
                pass

        _raw_cfg["backend"] = body.backend
        _CONFIG_PATH.write_text(
            yaml.dump(_raw_cfg, default_flow_style=False, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

        try:
            _cfg = resolve_config(_raw_cfg, str(_CONFIG_PATH))
        except Exception as e:
            return {"error": str(e)}

        if _orch:
            await _orch.close()
            _orch = None  # Prevent stale calls if start_server fails below

        stop_server(_server_procs)
        _server_procs = []
        try:
            _server_procs = await start_server(str(_CONFIG_PATH))
            _orch = Orchestrator(str(_CONFIG_PATH), component_cache=_cache)
            await _orch.reset_engine_client()  # Flush stale TCP connections from prior server
            return {"ok": True, "backend": body.backend}
        except Exception as e:
            return {"error": str(e)}
    finally:
        _swapping = False


class RestartBody(BaseModel):
    context_size: int | None = None


@app.post("/api/restart")
async def restart_model(body: RestartBody):
    """Restart the current model with an optional context_size override."""
    global _raw_cfg, _cfg, _orch, _server_procs, _swapping, _active_think_tasks

    _swapping = True
    try:
        # Drain active generation tasks (max 30s)
        snapshot = set(_active_think_tasks)
        if snapshot:
            print(f"[api] Waiting for {len(snapshot)} active generation(s) to complete...")
            try:
                _done, _pending = await asyncio.wait(snapshot, timeout=30.0)
                if _pending:
                    print(f"[api] WARNING: {len(_pending)} generation(s) did not finish in 30s — proceeding with swap")
            except Exception:
                pass

        if body.context_size is not None:
            _raw_cfg["context_size"] = body.context_size
            _CONFIG_PATH.write_text(
                yaml.dump(_raw_cfg, default_flow_style=False, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )

        try:
            _cfg = resolve_config(_raw_cfg, str(_CONFIG_PATH),
                                  context_size_override=body.context_size)
        except Exception as e:
            return {"error": str(e)}

        if _orch:
            await _orch.close()
            _orch = None  # Prevent stale calls if start_server fails below

        if _server_procs:
            stop_server(_server_procs)
            _server_procs = []
        try:
            _server_procs = await start_server(str(_CONFIG_PATH),
                                               context_size_override=body.context_size)
        except Exception as e:
            return {"error": f"Failed to start server: {e}"}

        _orch = Orchestrator(str(_CONFIG_PATH),
                             context_size_override=body.context_size,
                             component_cache=_cache)
        await _orch.reset_engine_client()  # Flush stale TCP connections from prior server

        return {"status": "ok", "info": _cfg.get("_preset_info", {})}
    finally:
        _swapping = False


# Legacy endpoint — kept for backward compat
class PresetSwitch(BaseModel):
    preset: str = ""
    context_size: int | None = None


@app.post("/api/preset")
async def switch_preset(body: PresetSwitch):
    """Legacy: restart model with optional context_size override."""
    restart = RestartBody(context_size=body.context_size)
    return await restart_model(restart)


@app.get("/api/conversations")
async def list_conversations(limit: int = 50):
    return await _db.list_conversations(limit)


@app.get("/api/search")
async def search_conversations(q: str = "", limit: int = 20):
    if not q.strip():
        return []
    return await _db.search(q.strip(), limit)


@app.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    conv = await _db.get_conversation(conv_id)
    if not conv:
        return {"error": "Not found"}
    return conv


class CreateConversationBody(BaseModel):
    title: str = "New conversation"
    preset: str = ""

@app.post("/api/conversations")
async def create_conversation_endpoint(body: CreateConversationBody):
    preset = body.preset or _raw_cfg.get("active_preset", "")
    conv_id = await _db.create_conversation(body.title, preset)
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

    # Auto-cache on thumbs up for code messages
    if body.feedback == 1 and _cache:
        try:
            cursor = await _db._conn.execute(
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
                await _cache.save_component(
                    category, tags, row["content"], 0.9, "(thumbs up)"
                )
        except Exception as e:
            print(f"[api] cache save on feedback error: {e}")

    return {"ok": ok}


@app.get("/api/cache")
async def list_cached_components(limit: int = 20):
    if not _cache:
        return []
    return await _cache.list_all(limit)


@app.delete("/api/cache/{comp_id}")
async def delete_cached_component(comp_id: str):
    if not _cache:
        return {"deleted": False}
    return {"deleted": await _cache.delete(comp_id)}


@app.websocket("/ws/think")
async def ws_think(websocket: WebSocket):
    if _swapping or _shutting_down:
        await websocket.close(code=1013, reason="Server busy — try again shortly")
        return
    await websocket.accept()
    current_think_task: asyncio.Task | None = None
    current_task = asyncio.current_task()
    _active_think_tasks.add(current_task)
    try:
        while True:
            msg = await websocket.receive_json()

            if msg.get("type") == "cancel":
                if current_think_task and not current_think_task.done():
                    current_think_task.cancel()
                    current_think_task = None
                continue

            if msg.get("type") == "think":
                if _orch is None:
                    await websocket.send_json({
                        "event": "error",
                        "message": "No model loaded. Open Settings and assign a .gguf file to your preset, then restart the model."
                    })
                    continue

                goal = msg.get("goal", "")
                conversation = msg.get("conversation", [])
                queue: asyncio.Queue = asyncio.Queue(maxsize=_WS_QUEUE_MAX)

                def on_event(event: str, **data):
                    try:
                        queue.put_nowait({"event": event, **data})
                    except asyncio.QueueFull:
                        pass  # Client not consuming events (likely disconnected)

                async def stream_events():
                    while True:
                        item = await queue.get()
                        try:
                            await websocket.send_json(item)
                        except Exception:
                            break
                        if item.get("event") == "done":
                            break
                    # Drain any remaining items so the queue can be GC'd
                    while not queue.empty():
                        try:
                            queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break

                async def run_think():
                    mode_override = msg.get("mode_override")
                    skip_refinement = msg.get("skip_refinement", False)
                    atlas_settings = msg.get("atlas")
                    actual_goal = goal
                    ws_id = msg.get("workspace_id")

                    # ── Computer mode: inject existing workspace files into context ──
                    if mode_override == "computer" and ws_id and _workspace:
                        try:
                            tree = _workspace.get_file_tree(ws_id)
                            existing = [f["path"] for f in tree if not f["is_dir"]]
                            if existing:
                                file_list = "\n".join(f"  - {p}" for p in existing[:60])
                                ctx_prefix = (
                                    f"[EXISTING WORKSPACE FILES]\n{file_list}\n\n"
                                    "Only output files that need to be created or changed. "
                                    "Files not listed in your output remain unchanged.\n\n"
                                )
                                if isinstance(actual_goal, str):
                                    actual_goal = ctx_prefix + actual_goal
                                elif isinstance(actual_goal, list):
                                    for part in actual_goal:
                                        if part.get("type") == "text":
                                            part["text"] = ctx_prefix + part["text"]
                                            break
                        except Exception as ws_ctx_err:
                            print(f"[api] workspace context inject error: {ws_ctx_err}")

                    # ── User-selected context files: inject full content ──
                    context_files = msg.get("context_files", [])
                    if not isinstance(context_files, list):
                        context_files = []
                    if context_files and ws_id and _workspace:
                        blocks = []
                        for path in context_files[:20]:  # hard cap: 20 files
                            try:
                                content = _workspace.read_file(ws_id, path)
                                if len(content) > 8000:
                                    content = content[:8000] + "\n... [truncated]"
                                blocks.append(
                                    f"[CONTEXT FILE: {path}]\n{content}\n[END CONTEXT FILE]"
                                )
                            except Exception as _cf_err:
                                print(f"[api] context file read failed ({path}): {_cf_err}")
                        if blocks:
                            file_ctx = "\n\n".join(blocks) + "\n\n"
                            if isinstance(actual_goal, str):
                                actual_goal = file_ctx + actual_goal
                            elif isinstance(actual_goal, list):
                                for part in actual_goal:
                                    if part.get("type") == "text":
                                        part["text"] = file_ctx + part["text"]
                                        break

                    # ── URL content fetching ──
                    from ct1.core.web_fetcher import extract_urls, fetch_url as _fetch_url, URL_PATTERN, MAX_URLS_PER_MESSAGE

                    goal_text_for_urls = actual_goal if isinstance(actual_goal, str) else " ".join(
                        p.get("text", "") for p in actual_goal if isinstance(p, dict) and p.get("type") == "text"
                    )
                    all_found = set(URL_PATTERN.findall(goal_text_for_urls))
                    detected_urls = extract_urls(goal_text_for_urls)

                    if len(all_found) > MAX_URLS_PER_MESSAGE:
                        try:
                            queue.put_nowait({
                                "event": "warning",
                                "message": f"Found {len(all_found)} URLs; only the first {MAX_URLS_PER_MESSAGE} will be fetched.",
                            })
                        except asyncio.QueueFull:
                            pass  # Client not consuming events (likely disconnected)

                    if detected_urls:
                        ctx_size = _cfg.get("llama_server", {}).get("context_size", 16384)
                        budget_chars = int((ctx_size * 3.5 - 2000) / 2 / len(detected_urls))

                        if budget_chars < 500:
                            try:
                                queue.put_nowait({
                                    "event": "warning",
                                    "message": "Context too small to fetch URL content; skipping web fetch.",
                                })
                            except asyncio.QueueFull:
                                pass  # Client not consuming events (likely disconnected)
                            detected_urls = []

                    if detected_urls:
                        fetched_blocks = []
                        fetched_meta = []

                        for u in detected_urls:
                            try:
                                queue.put_nowait({"event": "url_fetching", "url": u})
                            except asyncio.QueueFull:
                                pass  # Client not consuming events (likely disconnected)
                            try:
                                fr = await _fetch_url(u, max_chars=budget_chars)
                                if fr.error:
                                    try:
                                        queue.put_nowait({
                                            "event": "url_failed",
                                            "url": u, "error": fr.error,
                                        })
                                    except asyncio.QueueFull:
                                        pass  # Client not consuming events (likely disconnected)
                                else:
                                    fetched_blocks.append(
                                        f'[FETCHED CONTENT FROM: {fr.url} — "{fr.title}"]\n'
                                        f'{fr.content}\n'
                                        f'[END FETCHED CONTENT]'
                                    )
                                    fetched_meta.append({
                                        "url": fr.url,
                                        "title": fr.title,
                                        "content": fr.content[:500],
                                        "content_length": fr.content_length,
                                        "truncated": fr.truncated,
                                    })
                                    try:
                                        queue.put_nowait({
                                            "event": "url_fetched",
                                            "url": fr.url,
                                            "title": fr.title,
                                            "content_length": fr.content_length,
                                            "truncated": fr.truncated,
                                            "preview": fr.content[:500],
                                        })
                                    except asyncio.QueueFull:
                                        pass  # Client not consuming events (likely disconnected)
                            except Exception as e:
                                try:
                                    queue.put_nowait({
                                        "event": "url_failed",
                                        "url": u, "error": str(e),
                                    })
                                except asyncio.QueueFull:
                                    pass  # Client not consuming events (likely disconnected)

                        if fetched_blocks:
                            ctx = "\n\n".join(fetched_blocks)
                            if isinstance(actual_goal, str):
                                actual_goal = f"{ctx}\n\n{actual_goal}"
                            elif isinstance(actual_goal, list):
                                for part in actual_goal:
                                    if part.get("type") == "text":
                                        part["text"] = f"{ctx}\n\n{part['text']}"
                                        break

                    result = await _orch.think(
                        actual_goal, on_event=on_event, conversation=conversation,
                        mode_override=mode_override,
                        skip_refinement=skip_refinement,
                        atlas_settings=atlas_settings,
                    )
                    # Computer mode: save files → run → inspect → fix loop
                    if result.get("route") == "ROUTE_COMPUTER" and _workspace:
                        # ws_id already resolved above for workspace context injection
                        if not ws_id:
                            try:
                                queue.put_nowait({"event": "warning", "message": "No workspace — files not saved. Switch to Computer mode first."})
                            except asyncio.QueueFull:
                                pass  # Client not consuming events (likely disconnected)
                        if ws_id:
                            current_response = result["response"]
                            max_fix_iterations = 2

                            for iteration in range(max_fix_iterations + 1):
                                # Save files from current response
                                try:
                                    from ct1.core.orchestrator import Orchestrator
                                    files = Orchestrator._parse_multi_file(current_response)
                                    for f in files:
                                        _workspace.write_file(ws_id, f["path"], f["content"])
                                        try:
                                            queue.put_nowait({
                                                "event": "file_saved",
                                                "path": f["path"],
                                                "workspace_id": ws_id,
                                            })
                                        except asyncio.QueueFull:
                                            pass  # Client not consuming events (likely disconnected)
                                except Exception as fs_err:
                                    print(f"[api] file save error: {fs_err}")
                                    break

                                # Execute RUN commands and collect output
                                all_cmd_output = []
                                has_errors = False
                                try:
                                    from ct1.core.orchestrator import Orchestrator
                                    commands = Orchestrator._parse_run_commands(current_response)
                                    # Auto-infer run command when model omits [RUN:]
                                    if not commands and files:
                                        _RUN_MAP = {
                                            ".py": "python {f}",
                                            ".js": "node {f}",
                                            ".ts": "npx tsx {f}",
                                            ".rb": "ruby {f}",
                                            ".go": "go run {f}",
                                            ".sh": "bash {f}",
                                            ".bat": "{f}",
                                        }
                                        for f in files:
                                            ext = "." + f["path"].rsplit(".", 1)[-1] if "." in f["path"] else ""
                                            if ext in _RUN_MAP:
                                                commands.append(_RUN_MAP[ext].format(f=f["path"]))
                                                break  # run the first runnable file
                                    if commands:
                                        ws_dir = str(_workspace._resolve_safe(ws_id))
                                        for cmd_text in commands:
                                            if not is_command_safe(cmd_text):
                                                out_text = f"$ {cmd_text}\nBlocked: command not allowed\n"
                                                try:
                                                    queue.put_nowait({"event": "terminal_output", "text": out_text})
                                                except asyncio.QueueFull:
                                                    pass  # Client not consuming events (likely disconnected)
                                                all_cmd_output.append(out_text)
                                                continue
                                            try:
                                                queue.put_nowait({"event": "terminal_output", "text": f"$ {cmd_text}\n"})
                                            except asyncio.QueueFull:
                                                pass  # Client not consuming events (likely disconnected)
                                            try:
                                                import sys as _sys
                                                shell = "cmd.exe" if _sys.platform == "win32" else "/bin/bash"
                                                shell_flag = "/c" if _sys.platform == "win32" else "-c"
                                                proc = await asyncio.create_subprocess_exec(
                                                    shell, shell_flag, cmd_text,
                                                    stdin=asyncio.subprocess.PIPE,
                                                    stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.STDOUT,
                                                    cwd=ws_dir,
                                                )
                                                # Close stdin immediately so input() gets EOF
                                                if proc.stdin:
                                                    proc.stdin.close()
                                                    await proc.stdin.wait_closed()
                                                stdout, _ = await asyncio.wait_for(
                                                    proc.communicate(), timeout=15,
                                                )
                                                output = stdout.decode("utf-8", errors="replace") if stdout else ""
                                                exit_info = f"\n[exit {proc.returncode}]\n" if proc.returncode else "\n"
                                                try:
                                                    queue.put_nowait({"event": "terminal_output", "text": output + exit_info})
                                                except asyncio.QueueFull:
                                                    pass  # Client not consuming events (likely disconnected)
                                                all_cmd_output.append(f"$ {cmd_text}\n{output}{exit_info}")
                                                if proc.returncode and proc.returncode != 0:
                                                    has_errors = True
                                            except asyncio.TimeoutError:
                                                # Kill the hung process and wait for cleanup
                                                try:
                                                    proc.kill()
                                                    await proc.wait()
                                                except Exception:
                                                    pass
                                                timeout_msg = "[timed out — script may use input() which is not supported in non-interactive mode]\n"
                                                try:
                                                    queue.put_nowait({"event": "terminal_output", "text": timeout_msg})
                                                except asyncio.QueueFull:
                                                    pass  # Client not consuming events (likely disconnected)
                                                all_cmd_output.append(f"$ {cmd_text}\n{timeout_msg}")
                                                has_errors = True
                                            except Exception as cmd_err:
                                                err_text = f"Error: {cmd_err}\n"
                                                try:
                                                    queue.put_nowait({"event": "terminal_output", "text": err_text})
                                                except asyncio.QueueFull:
                                                    pass  # Client not consuming events (likely disconnected)
                                                all_cmd_output.append(f"$ {cmd_text}\n{err_text}")
                                                has_errors = True
                                except Exception as run_err:
                                    print(f"[api] run commands error: {run_err}")
                                    break

                                # If errors found and iterations remain, ask AI to fix
                                if has_errors and iteration < max_fix_iterations:
                                    terminal_log = "\n".join(all_cmd_output)[-3000:]
                                    try:
                                        queue.put_nowait({
                                            "event": "terminal_output",
                                            "text": f"\n[CT-2: errors detected, auto-fixing (attempt {iteration + 1}/{max_fix_iterations})...]\n",
                                        })
                                    except asyncio.QueueFull:
                                        pass  # Client not consuming events (likely disconnected)
                                    try:
                                        queue.put_nowait({"event": "fixing"})
                                    except asyncio.QueueFull:
                                        pass  # Client not consuming events (likely disconnected)

                                    # Read back the files the AI wrote for context
                                    file_context = ""
                                    try:
                                        saved_files = Orchestrator._parse_multi_file(current_response)
                                        for f in saved_files[:5]:
                                            content = _workspace.read_file(ws_id, f["path"])
                                            file_context += f"\n[FILE: {f['path']}]\n{content}\n"
                                    except Exception:
                                        file_context = current_response

                                    fix_goal = (
                                        f"The code has errors. Fix them and output the corrected files.\n\n"
                                        f"IMPORTANT: Scripts run NON-INTERACTIVELY. "
                                        f"Do NOT use input(), scanf(), or any stdin reading. "
                                        f"Use hardcoded test values instead.\n\n"
                                        f"TERMINAL OUTPUT:\n{terminal_log}\n\n"
                                        f"CURRENT FILES:\n{file_context}\n\n"
                                        f"Fix the errors shown in the terminal output. "
                                        f"Output ALL files again with [FILE: path] markers, "
                                        f"even files that don't need changes. "
                                        f"Include [RUN: ...] commands to test the fix."
                                    )

                                    try:
                                        fix_result = await _orch.think(
                                            fix_goal, on_event=on_event,
                                            conversation=conversation,
                                            mode_override="computer",
                                        )
                                        current_response = fix_result["response"]
                                        result["response"] = current_response
                                        result["thinking"] = fix_result.get("thinking", "")
                                        # Loop continues — will save new files and re-run
                                    except Exception as fix_err:
                                        try:
                                            queue.put_nowait({
                                                "event": "terminal_output",
                                                "text": f"\n[CT-2: fix attempt failed: {fix_err}]\n",
                                            })
                                        except asyncio.QueueFull:
                                            pass  # Client not consuming events (likely disconnected)
                                        break
                                else:
                                    # No errors or out of iterations — replay commands in interactive terminal
                                    if commands:
                                        try:
                                            queue.put_nowait({"event": "run_commands", "commands": commands})
                                        except asyncio.QueueFull:
                                            pass
                                    break

                    await queue.put({
                        "event": "done",
                        "response": result["response"],
                        "thinking": result.get("thinking", ""),
                        "draft": result.get("draft", ""),
                        "draft_thinking": result.get("draft_thinking", ""),
                        "route": result.get("route", ""),
                        "specialist_data": result.get("specialist_data"),
                        "reflection": result.get("reflection", {}),
                        "detected_lang": result.get("detected_lang", "text"),
                        "files": result.get("files", []),
                    })

                    # Auto-persist conversation
                    if _db and getattr(_db, '_conn', None):
                        try:
                            conv_id = msg.get("conversation_id")
                            if not conv_id:
                                title_text = goal if isinstance(goal, str) else (goal[0].get("text", "") if isinstance(goal, list) else str(goal))
                                title = title_text[:40].strip()
                                if len(title_text) > 40:
                                    title += "..."
                                conv_id = await _db.create_conversation(title, _raw_cfg.get("active_preset", ""))
                                await websocket.send_json({"event": "conversation_id", "id": conv_id})

                            position = msg.get("position", 0)
                            user_content = goal if isinstance(goal, str) else json.dumps(goal)
                            await _db.add_message(conv_id, "user", user_content, position)

                            await _db.add_message(
                                conv_id, "assistant", result["response"], position + 1,
                                thinking=result.get("thinking", ""),
                                draft=result.get("draft", ""),
                                route=result.get("route", ""),
                                specialist_data=json.dumps(result.get("specialist_data") or {}),
                                reflection=json.dumps(result.get("reflection") or {}),
                            )
                        except Exception as db_err:
                            print(f"[api] conversation save error: {db_err}")  # non-fatal

                    if _orch:
                        asyncio.create_task(_orch.clear_kv_cache())

                async def watch_for_cancel():
                    """Read incoming WebSocket messages while inference runs.
                    The outer while-loop is blocked at gather(), so without this
                    watcher the cancel message would never be received mid-inference."""
                    try:
                        while True:
                            incoming = await websocket.receive_json()
                            if incoming.get("type") == "cancel":
                                if current_think_task and not current_think_task.done():
                                    current_think_task.cancel()
                                return
                    except Exception:
                        pass

                current_think_task = asyncio.create_task(run_think())
                stream_task = asyncio.create_task(stream_events())
                cancel_task = asyncio.create_task(watch_for_cancel())
                try:
                    await asyncio.gather(current_think_task, stream_task)
                except asyncio.CancelledError:
                    await queue.put({"event": "done", "response": "", "route": ""})
                    await stream_task
                finally:
                    cancel_task.cancel()
                    try:
                        await cancel_task  # ensure task terminates before outer loop reads WS again
                    except (asyncio.CancelledError, Exception):
                        pass
                    current_think_task = None

    except WebSocketDisconnect:
        pass
    except Exception as e:
        import traceback
        err_msg = str(e) or repr(e) or traceback.format_exc()[-200:]
        print(f"[api] websocket error: {traceback.format_exc()}")
        try:
            await websocket.send_json({"event": "error", "message": err_msg})
        except Exception:
            pass
    finally:
        _active_think_tasks.discard(current_task)


# ── Workspace endpoints (Computer Mode) ──────────────────────────────

@app.get("/api/workspaces")
async def list_workspaces():
    return _workspace.list_workspaces()


class CreateWorkspaceBody(BaseModel):
    name: str = ""


@app.post("/api/workspaces")
async def create_workspace(body: CreateWorkspaceBody):
    return _workspace.create_workspace(body.name)


@app.get("/api/workspaces/{ws_id}/files")
async def get_workspace_files(ws_id: str):
    try:
        return _workspace.get_file_tree(ws_id)
    except FileNotFoundError:
        return {"error": "Workspace not found"}


@app.get("/api/workspaces/{ws_id}/files/{file_path:path}")
async def read_workspace_file(ws_id: str, file_path: str):
    try:
        content = _workspace.read_file(ws_id, file_path)
        return {"path": file_path, "content": content}
    except (FileNotFoundError, PermissionError) as e:
        return {"error": str(e)}


class WriteFileBody(BaseModel):
    content: str


@app.put("/api/workspaces/{ws_id}/files/{file_path:path}")
async def write_workspace_file(ws_id: str, file_path: str, body: WriteFileBody):
    try:
        written = _workspace.write_file(ws_id, file_path, body.content)
        return {"path": written}
    except (FileNotFoundError, PermissionError) as e:
        return {"error": str(e)}


@app.delete("/api/workspaces/{ws_id}/files/{file_path:path}")
async def delete_workspace_file(ws_id: str, file_path: str):
    try:
        return {"deleted": _workspace.delete_file(ws_id, file_path)}
    except (FileNotFoundError, PermissionError) as e:
        return {"error": str(e)}


@app.delete("/api/workspaces/{ws_id}")
async def delete_workspace(ws_id: str):
    return {"deleted": _workspace.delete_workspace(ws_id)}


# ── Terminal WebSocket (Computer Mode) ───────────────────────────────

@app.websocket("/ws/terminal")
async def ws_terminal(websocket: WebSocket):
    await websocket.accept()
    proc = None
    ws_closed = False
    output_task = None
    try:
        # Wait for init message with workspace_id
        init_msg = await websocket.receive_json()
        ws_id = init_msg.get("workspace_id", "")
        try:
            ws_dir = str(_workspace._resolve_safe(ws_id))
        except FileNotFoundError:
            await websocket.send_json({"type": "error", "text": "Workspace not found"})
            return

        import sys
        shell = "cmd.exe" if sys.platform == "win32" else "/bin/bash"
        proc = await asyncio.create_subprocess_exec(
            shell,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=ws_dir,
        )

        async def read_output():
            try:
                while proc and proc.stdout and not ws_closed:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    if ws_closed:
                        break
                    text = line.decode("utf-8", errors="replace")
                    await websocket.send_json({"type": "output", "text": text})
                if not ws_closed:
                    await websocket.send_json({"type": "exit", "code": proc.returncode})
            except Exception:
                pass  # Connection already closed

        output_task = asyncio.create_task(read_output())

        while True:
            msg = await websocket.receive_json()
            if msg.get("type") == "input":
                cmd_text = msg.get("text", "")
                if not is_command_safe(cmd_text):
                    await websocket.send_json({
                        "type": "error",
                        "text": "Blocked: command not allowed for safety\n",
                    })
                    continue
                if proc and proc.stdin:
                    proc.stdin.write(cmd_text.encode("utf-8"))
                    await proc.stdin.drain()

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        ws_closed = True
        if output_task:
            output_task.cancel()
            try:
                await output_task
            except (asyncio.CancelledError, Exception):
                pass
        if proc:
            try:
                proc.terminate()
                await proc.wait()
            except Exception:
                pass


# Serve SvelteKit build with SPA fallback
_WEB_BUILD = Path(__file__).parent.parent / "web" / "build"


def _mount_frontend_if_built() -> None:
    """Mount the SvelteKit build as a SPA — safe to call multiple times."""
    if not _WEB_BUILD.exists():
        return
    if any(getattr(r, "name", None) == "static" for r in app.routes):
        return  # already mounted
    from starlette.responses import FileResponse

    class SPAStaticFiles(StaticFiles):
        async def get_response(self, path: str, scope):
            try:
                return await super().get_response(path, scope)
            except Exception:
                # SPA fallback: serve index.html for any unmatched route
                return FileResponse(Path(self.directory) / "index.html")

    app.mount("/", SPAStaticFiles(directory=str(_WEB_BUILD), html=True), name="static")


# Mount immediately if the build already exists (external uvicorn / dev reload)
_mount_frontend_if_built()


if __name__ == "__main__":
    import uvicorn
    _ensure_frontend_built()   # npm install + npm run build
    _mount_frontend_if_built() # mount now that the build exists
    uvicorn.run(app, host="0.0.0.0", port=8000)
