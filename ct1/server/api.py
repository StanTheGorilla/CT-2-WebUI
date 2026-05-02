import asyncio
import json
import re as _re
import yaml
import httpx
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse as _BaseStreamingResponse


class StreamingResponse(_BaseStreamingResponse):
    """Suppresses CancelledError from listen_for_disconnect during server shutdown."""
    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        except asyncio.CancelledError:
            if _shutting_down:
                return
            raise
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from ct1.core.orchestrator import Orchestrator, _get_mode_registry
from ct1.prompts.manager import _get_prompt_manager as _get_pm
from ct1.server.health import check_server_health
from ct1.server.launcher import (
    load_raw_config, resolve_config,
    kill_existing_llama_servers, start_server, stop_server,
    _detect_vision_support, _find_mmproj_path,
)
from ct1.memory.journal_reader import JournalReader
from ct1.memory.session_store import SessionStore
from ct1.memory.conversation_db import ConversationDB
from ct1.memory.component_cache import ComponentCache
from ct1.server.workspace import WorkspaceManager, is_command_safe
from ct1.server.cache_policy import should_clear_kv_cache
from ct1.server.backend_detector import detect as _detect_backend, probe_ollama, probe_lm_studio, stop_managed_proc as _stop_ollama

APP_VERSION = "0.1.0"

_TITLE_STRIP = _re.compile(
    r'^(?:(?:can\s+you|please|could\s+you|i(?:\'d)?\s+(?:like|want|need)(?:\s+you)?\s+to|'
    r'generate|create|make|build|write|design|implement|develop|add|fix|update|'
    r'show(?:\s+me)?|give\s+me|help\s+(?:me\s+)?(?:with\s+)?|explain|describe)\s+)+',
    _re.IGNORECASE,
)
_TITLE_ARTICLE = _re.compile(r'^\s*(?:a|an|the)\s+', _re.IGNORECASE)

def _heuristic_title(msg: str) -> str:
    """Strip common filler prefixes and return a concise title (max 6 words)."""
    text = (msg.strip() if isinstance(msg, str) else str(msg))[:300]
    text = _TITLE_STRIP.sub('', text).strip()
    text = _TITLE_ARTICLE.sub('', text).strip()
    first_line = _re.split(r'[.!?\n]', text)[0].strip()
    words = first_line.split()[:6]
    result = ' '.join(words).capitalize()
    fallback = msg.strip()[:40] if isinstance(msg, str) else ''
    return result or fallback or 'New chat'

async def _refine_title(conv_id: str, first_msg: str, websocket: WebSocket) -> None:
    """Call inference backend for a short AI-generated title, then update DB + notify frontend."""
    try:
        if _external_backend:
            base_url = _external_backend["base_url"]
            model_name = _external_backend.get("active_model", "")
        else:
            port = _raw_cfg.get("llama_server", {}).get("port", 8080)
            base_url = f"http://localhost:{port}"
            model_name = ""
        prompt = (
            f"Respond with only a 4-6 word title for this message. "
            f"No punctuation, no quotes, no explanation.\n\nMessage: {first_msg[:200]}"
        )
        payload: dict = {
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 20,
            "temperature": 0.3,
            "stream": False,
        }
        if model_name:
            payload["model"] = model_name
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                f"{base_url}/v1/chat/completions",
                json=payload,
            )
        if resp.status_code == 200:
            raw = resp.json()["choices"][0]["message"]["content"].strip().strip('"\'')
            words = raw.split()
            if 2 <= len(words) <= 8:
                title = ' '.join(words).capitalize()
                if _db and getattr(_db, '_conn', None):
                    await _db.rename_conversation(conv_id, title)
                try:
                    await websocket.send_json({"event": "title_update", "id": conv_id, "title": title})
                except Exception:
                    pass  # WS may be closed — DB is already updated
    except Exception as e:
        print(f"[api] title refinement skipped: {e}")

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
_pending_approvals: dict = {}    # approval_id -> asyncio.Future[bool]
_active_think_tasks: set = set() # Active /ws/think asyncio tasks
_health_task: asyncio.Task | None = None  # Background health monitor task
_is_generating: int = 0          # Active generation count (blocks server update)
_external_backend: dict | None = None  # Populated at startup if Ollama/LM Studio detected
_sse_clients: set[asyncio.Queue] = set()  # One queue per connected SSE client
_watcher_task: asyncio.Task | None = None  # Background external-backend state poller
_WS_QUEUE_MAX = 500  # Max buffered events per WebSocket session (~1-2 full responses)

_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for current information. Use when the user asks "
                "about recent events, live data, or anything your training data "
                "may not cover."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Focused search query",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": (
                "Fetch and read the contents of a URL. Use to get full content "
                "from a specific web page."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Full URL to fetch",
                    }
                },
                "required": ["url"],
            },
        },
    },
]

_COMPUTER_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command in the workspace directory. Returns stdout and stderr combined. Use to install packages, run scripts, test code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file in the workspace. Creates parent directories automatically.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path, e.g. 'src/app.py'"},
                    "content": {"type": "string", "description": "Full file content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path"},
                },
                "required": ["path"],
            },
        },
    },
]


def _make_tool_executor(queue: asyncio.Queue):
    """Return an async tool executor that emits websocket progress events."""

    async def _executor(tool_calls: list[dict]) -> list[str]:
        from ct1.core.web_searcher import search_web, format_results_as_context
        from ct1.core.web_fetcher import fetch_url as _fetch_url

        results: list[str] = []

        for tc in tool_calls:
            name = tc["name"]
            args = tc.get("args", {})

            if name == "web_search":
                query = (args.get("query") or "").strip()
                if not query:
                    results.append("Search query was empty.")
                    continue

                try:
                    queue.put_nowait({"event": "web_searching", "query": query})
                except asyncio.QueueFull:
                    pass

                sr = await search_web(query, max_results=8)

                try:
                    queue.put_nowait({
                        "event": "web_search_results",
                        "query": sr.query,
                        "results": [
                            {"title": r.title, "url": r.url, "snippet": r.snippet}
                            for r in sr.results
                        ],
                        "error": sr.error,
                    })
                except asyncio.QueueFull:
                    pass

                if sr.results:
                    results.append(format_results_as_context(sr))
                else:
                    results.append(f"No results found for '{query}'.")

            elif name == "fetch_url":
                url = (args.get("url") or "").strip()
                if not url:
                    results.append("URL was empty.")
                    continue

                try:
                    queue.put_nowait({"event": "url_fetching", "url": url})
                except asyncio.QueueFull:
                    pass

                fr = await _fetch_url(url, max_chars=4000)

                if fr.error or not fr.content:
                    try:
                        queue.put_nowait({
                            "event": "url_failed",
                            "url": url,
                            "error": fr.error or "empty",
                        })
                    except asyncio.QueueFull:
                        pass
                    results.append(f"Could not fetch {url}: {fr.error or 'empty'}")
                else:
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
                        pass
                    results.append(f"[{fr.title or url}]\n{fr.content}")
            else:
                results.append(f"Unknown tool: {name}")

        return results

    return _executor


def _make_computer_tool_executor(queue: asyncio.Queue, workspace, ws_id: str, require_approval: bool = False):
    """Tool executor for Computer Mode: bash, write_file, read_file."""
    import uuid as _uuid
    _used = {"count": 0}

    async def _executor(tool_calls: list[dict]) -> list[str]:
        import sys as _sys
        results: list[str] = []
        for tc in tool_calls:
            name = tc.get("name", "")
            args = tc.get("args", {})
            _used["count"] += 1

            if name == "bash":
                cmd = args.get("command", "").strip()
                if not cmd:
                    results.append("Error: empty command")
                    continue
                if not is_command_safe(cmd):
                    out = f"$ {cmd}\nBlocked: command not allowed\n"
                    try:
                        queue.put_nowait({"event": "terminal_output", "text": out})
                    except asyncio.QueueFull:
                        pass
                    results.append(out)
                    continue
                if require_approval:
                    approval_id = str(_uuid.uuid4())
                    loop = asyncio.get_event_loop()
                    fut: asyncio.Future = loop.create_future()
                    _pending_approvals[approval_id] = fut
                    try:
                        queue.put_nowait({"event": "command_approval_request",
                                          "approval_id": approval_id, "command": cmd})
                    except asyncio.QueueFull:
                        pass
                    try:
                        approved = await asyncio.shield(fut)
                    except asyncio.CancelledError:
                        _pending_approvals.pop(approval_id, None)
                        results.append(f"[command cancelled: {cmd}]")
                        continue
                    if not approved:
                        try:
                            queue.put_nowait({"event": "terminal_output",
                                              "text": f"[rejected: {cmd}]\n"})
                        except asyncio.QueueFull:
                            pass
                        results.append(f"Command rejected by user: {cmd}")
                        continue
                try:
                    queue.put_nowait({"event": "terminal_output", "text": f"$ {cmd}\n"})
                except asyncio.QueueFull:
                    pass
                try:
                    ws_dir = str(workspace._resolve_safe(ws_id))
                    shell = "cmd.exe" if _sys.platform == "win32" else "/bin/bash"
                    flag = "/c" if _sys.platform == "win32" else "-c"
                    proc = await asyncio.create_subprocess_exec(
                        shell, flag, cmd,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                        cwd=ws_dir,
                    )
                    if proc.stdin:
                        proc.stdin.close()
                        await proc.stdin.wait_closed()
                    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
                    output = stdout.decode("utf-8", errors="replace") if stdout else ""
                    exit_info = f"[exit {proc.returncode}]\n" if proc.returncode else ""
                    full_out = output + exit_info
                    try:
                        queue.put_nowait({"event": "terminal_output", "text": full_out})
                    except asyncio.QueueFull:
                        pass
                    results.append(full_out or "(no output)")
                except asyncio.TimeoutError:
                    try:
                        proc.kill()
                        await proc.wait()
                    except Exception:
                        pass
                    msg = "[timed out — script may block on input]\n"
                    try:
                        queue.put_nowait({"event": "terminal_output", "text": msg})
                    except asyncio.QueueFull:
                        pass
                    results.append(msg)
                except Exception as e:
                    results.append(f"Error: {e}")

            elif name == "write_file":
                path = args.get("path", "").strip()
                content = args.get("content", "")
                if not path:
                    results.append("Error: empty path")
                    continue
                try:
                    workspace.write_file(ws_id, path, content)
                    try:
                        queue.put_nowait({"event": "file_saved", "path": path, "workspace_id": ws_id})
                    except asyncio.QueueFull:
                        pass
                    results.append(f"Written {path} ({len(content)} bytes)")
                except Exception as e:
                    results.append(f"Error writing {path}: {e}")

            elif name == "read_file":
                path = args.get("path", "").strip()
                if not path:
                    results.append("Error: empty path")
                    continue
                try:
                    content = workspace.read_file(ws_id, path)
                    results.append(content)
                except FileNotFoundError:
                    results.append(f"File not found: {path}")
                except Exception as e:
                    results.append(f"Error reading {path}: {e}")

            else:
                results.append(f"Unknown tool: {name}")

        return results

    _executor._used = _used
    return _executor


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
    global _orch, _server_procs, _db, _cache, _workspace, _shutting_down, _external_backend

    # Connect to the explicitly chosen backend (Ollama / LM Studio / local)
    preference = _raw_cfg.get("inference_backend", "local")
    _external_backend = await _detect_backend(preference)

    if _external_backend:
        btype = _external_backend["type"]
        nmodels = len(_external_backend.get("models", []))
        print(f"[api] External backend detected: {btype} ({nmodels} model(s) available)")
        # Pick the active model: use saved preference or first available
        saved_key = f"{btype}_model"
        saved = _raw_cfg.get(saved_key, "")
        models = _external_backend.get("models", [])
        if saved and any(m["name"] == saved for m in models):
            active = saved
        elif models:
            active = models[0]["name"]
        else:
            active = ""
        _external_backend["active_model"] = active
        if active:
            print(f"[api] Using model: {active}")
    elif preference == "local":
        try:
            _server_procs = await start_server(str(_CONFIG_PATH))
        except Exception as e:
            print(f"[api] WARNING: Model server failed to start: {e}")
            print("[api]    Open Settings in the web UI to assign a model file to your preset.")
    else:
        # External backend configured but not reachable — do not start local server.
        print(f"[api] WARNING: {preference} server not reachable — will retry on demand.")

    _cache = ComponentCache()
    await _cache.init()
    try:
        if _external_backend:
            _orch = Orchestrator(
                str(_CONFIG_PATH), component_cache=_cache,
                external_base_url=_external_backend["base_url"],
                external_model_name=_external_backend.get("active_model", ""),
            )
        else:
            _orch = Orchestrator(str(_CONFIG_PATH), component_cache=_cache)
    except Exception as e:
        print(f"[api] WARNING: Orchestrator init failed: {e}")
    _db = ConversationDB()
    await _db.init()
    _workspace = WorkspaceManager()
    global _health_task, _watcher_task
    if not _external_backend and preference == "local":
        _health_task = asyncio.create_task(_health_monitor(port=_cfg.get("llama_server", {}).get("port", 8080)))
    if preference in ("lm_studio", "ollama"):
        _watcher_task = asyncio.create_task(_external_backend_watcher())
    yield
    _shutting_down = True
    # Close all SSE streams immediately — otherwise uvicorn waits for their 25s timeout
    for q in list(_sse_clients):
        try:
            q.put_nowait(None)  # None = shutdown sentinel
        except asyncio.QueueFull:
            pass
    _sse_clients.clear()
    for task in (_health_task, _watcher_task):
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    # Drain active generations (max 30s)
    if _is_generating > 0:
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
    if _server_procs and not _external_backend:
        stop_server(_server_procs)
    _stop_ollama()  # No-op unless CT-2 started Ollama itself


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
    return {"model": model, "version": APP_VERSION}


@app.get("/api/events")
async def sse_events():
    """Server-Sent Events stream — pushes model_state updates in real time."""
    q: asyncio.Queue = asyncio.Queue(maxsize=20)
    _sse_clients.add(q)

    async def generator():
        try:
            # Send current state immediately on connect
            if _external_backend:
                _init_active = _external_backend.get("active_model", "")
                _init_models = _external_backend.get("models", [])
            else:
                _init_active = _raw_cfg.get("active_model", "") if _raw_cfg else ""
                _init_models = []
            initial = json.dumps({
                "type": "model_state",
                "active_model": _init_active,
                "models": _init_models,
            })
            yield f"data: {initial}\n\n"
            while not _shutting_down:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=25.0)
                    if data is None:  # shutdown sentinel
                        return
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    if _shutting_down:
                        return
                    yield ": keepalive\n\n"
        finally:
            _sse_clients.discard(q)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/backend/status")
async def get_backend_status():
    """Return which inference backend is currently active."""
    if _external_backend:
        return {
            "type": _external_backend["type"],
            "base_url": _external_backend["base_url"],
            "active_model": _external_backend.get("active_model", ""),
            "model_count": len(_external_backend.get("models", [])),
        }
    return {"type": "local"}


class BackendPreference(BaseModel):
    preference: str  # "auto" | "local" | "ollama" | "lm_studio"


def _pick_active_model(backend: dict) -> str:
    """Pick the best active model for a newly detected external backend."""
    saved_key = f"{backend['type']}_model"
    saved = _raw_cfg.get(saved_key, "")
    models = backend.get("models", [])
    if saved and any(m["name"] == saved for m in models):
        return saved
    return models[0]["name"] if models else ""


_reconnect_cooldown: float = 0.0

async def _try_reconnect_external() -> bool:
    """If preference is external but backend isn't connected, try to reconnect."""
    global _external_backend, _reconnect_cooldown
    if _external_backend:
        return True
    pref = _raw_cfg.get("inference_backend", "local")
    if pref not in ("ollama", "lm_studio"):
        return False
    import time
    now = time.monotonic()
    if now - _reconnect_cooldown < 30:
        return False
    _reconnect_cooldown = now
    probed = await _detect_backend(pref)
    if not probed:
        return False
    active = _pick_active_model(probed)
    probed["active_model"] = active
    _external_backend = probed
    if _orch and _orch.engine:
        _orch.engine.base_url = probed["base_url"]
        _orch.engine.model_name = active
        _orch.engine.is_external = True
    print(f"[api] Auto-reconnected to {probed['type']} ({active})")
    return True


@app.post("/api/backend/preference")
async def set_backend_preference(body: BackendPreference):
    """Save the inference backend preference and switch live immediately."""
    global _raw_cfg, _external_backend, _orch, _server_procs, _health_task

    allowed = {"local", "ollama", "lm_studio"}
    if body.preference not in allowed:
        from fastapi import HTTPException
        raise HTTPException(400, f"preference must be one of: {', '.join(sorted(allowed))}")

    # Save to YAML
    _raw_cfg["inference_backend"] = body.preference
    _CONFIG_PATH.write_text(
        yaml.dump(_raw_cfg, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    # Probe for the requested backend
    new_external = await _detect_backend(body.preference)

    if new_external and not _external_backend:
        # local → external: stop llama-server + health monitor, switch orchestrator
        # (if switching to Ollama, the process handle is already tracked in backend_detector)
        if _health_task:
            _health_task.cancel()
            try:
                await _health_task
            except asyncio.CancelledError:
                pass
            _health_task = None
        if _server_procs:
            stop_server(_server_procs)
            _server_procs = []
        active = _pick_active_model(new_external)
        new_external["active_model"] = active
        _external_backend = new_external
        if _orch:
            await _orch.close()
        try:
            _orch = Orchestrator(str(_CONFIG_PATH), component_cache=_cache,
                                 external_base_url=new_external["base_url"],
                                 external_model_name=active)
        except Exception as e:
            print(f"[api] Orchestrator init failed after switch to external: {e}")
        print(f"[api] Switched live to {new_external['type']} ({active})")
        return {"ok": True, "switched": True, "backend": new_external["type"]}

    elif not new_external and _external_backend:
        # external → local: stop Ollama if we started it, start llama-server
        _stop_ollama()
        _external_backend = None
        if _orch:
            await _orch.close()
            _orch = None
        try:
            _server_procs = await start_server(str(_CONFIG_PATH))
        except Exception as e:
            print(f"[api] Failed to start llama-server: {e}")
        try:
            _orch = Orchestrator(str(_CONFIG_PATH), component_cache=_cache)
            await _orch.reset_engine_client()
        except Exception as e:
            print(f"[api] Orchestrator init failed after switch to local: {e}")
        _health_task = asyncio.create_task(
            _health_monitor(port=_cfg.get("llama_server", {}).get("port", 8080))
        )
        print("[api] Switched live to local llama-server")
        return {"ok": True, "switched": True, "backend": "local"}

    elif new_external and _external_backend:
        # external → different external: stop Ollama if we're leaving it
        if _external_backend.get("type") == "ollama" and new_external.get("type") != "ollama":
            _stop_ollama()
        active = _pick_active_model(new_external)
        new_external["active_model"] = active
        _external_backend = new_external
        if _orch and _orch.engine:
            _orch.engine.base_url = new_external["base_url"]
            _orch.engine.model_name = active
            _orch.engine.is_external = True
        print(f"[api] Switched live to {new_external['type']} ({active})")
        return {"ok": True, "switched": True, "backend": new_external["type"]}

    # Already on local — nothing to switch
    if body.preference == "local":
        return {"ok": True, "switched": False}

    # Requested external backend not reachable
    if body.preference == "ollama":
        msg = "Ollama is not installed or could not be started. Install Ollama first."
    else:
        msg = "LM Studio server is not running. Open LM Studio and start the local server."
    return {"ok": True, "switched": False, "warning": msg}


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
    if _is_generating > 0:
        return {"error": "Model is busy — wait for the current generation to finish before updating"}
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


def _ext_context_size() -> int | None:
    """Return the active external model's context window, or None if unknown."""
    if not _external_backend:
        return None
    active = _external_backend.get("active_model", "")
    models = _external_backend.get("models", [])
    m = next((x for x in models if x["name"] == active), None)
    if m and m.get("context_length"):
        return int(m["context_length"])
    return None


@app.get("/api/config")
async def get_config():
    await _try_reconnect_external()
    server = _cfg.get("llama_server", {})
    model_params = _cfg.get("models", {}).get("director", {})
    preset_info = _cfg.get("_preset_info", {})
    return {
        "preset": _cfg.get("_preset", ""),
        "preset_name": preset_info.get("name", ""),
        "tier": preset_info.get("tier"),
        "model": Path(server.get("model", "")).name,
        "context_size": _ext_context_size() if _external_backend else server.get("context_size"),
        "gguf_context_length": _ext_context_size() if _external_backend else _cfg.get("_gguf_context_length"),
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
        "inference_backend": _raw_cfg.get("inference_backend", "local"),
        "inference_backend_preference": _raw_cfg.get("inference_backend", "local"),
        "external_connected": bool(_external_backend),
    }


class CompactRequest(BaseModel):
    conversation: list[dict]

@app.post("/api/compact")
async def compact_conversation(body: CompactRequest):
    if _orch is None:
        return {"error": "No model loaded", "conversation": body.conversation}
    try:
        compacted = await _orch.compact_conversation(body.conversation)
        return {
            "conversation": compacted,
            "original_turns": len(body.conversation),
            "compacted_turns": len(compacted),
        }
    except Exception as e:
        print(f"[api] compact endpoint error: {e}")
        return {"error": str(e), "conversation": body.conversation}


async def _refresh_lm_studio_state() -> None:
    """Re-check /v1/models to see if the active model is still loaded.

    Uses only a GET request — no inference probe — so it cannot trigger
    LM Studio to auto-load anything.
    """
    global _external_backend
    if not _external_backend or _external_backend.get("type") != "lm_studio":
        return
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(f"{_external_backend['base_url']}/v1/models")
        if r.status_code != 200:
            return
        raw = r.json().get("data", [])
        has_state = any("state" in m for m in raw)
        if has_state:
            loaded_ids = {m["id"] for m in raw if m.get("state") == "loaded"}
        elif len(raw) <= 1:
            loaded_ids = {m["id"] for m in raw}
        else:
            # Multiple models, no state — leave untouched; watcher will do full probe
            return
        # Sync models list to what is actually loaded right now
        loaded_models = [
            {"name": m["id"], "size_gb": 0.0, "thinking": False, "vision": False,
             "context_length": m.get("context_length") or m.get("max_context_length") or None}
            for m in raw if m.get("id") in loaded_ids
        ]
        _external_backend["models"] = loaded_models
        current = _external_backend.get("active_model", "")
        changed = False
        if current and current not in loaded_ids:
            # Previously-active model was unloaded
            new_active = loaded_models[0]["name"] if loaded_models else ""
            _external_backend["active_model"] = new_active
            if _orch and _orch.engine:
                _orch.engine.model_name = new_active
            changed = True
        elif not current and loaded_models:
            # A model became loaded after CT-2 started with nothing selected
            new_active = loaded_models[0]["name"]
            _external_backend["active_model"] = new_active
            if _orch and _orch.engine:
                _orch.engine.model_name = new_active
            changed = True
        if changed:
            await _broadcast_model_state()
    except Exception:
        pass


async def _broadcast_model_state() -> None:
    """Push current model state to all connected SSE clients."""
    global _sse_clients
    if not _sse_clients:
        return
    if _external_backend:
        _bcast_active = _external_backend.get("active_model", "")
        _bcast_models = _external_backend.get("models", [])
    else:
        _bcast_active = _raw_cfg.get("active_model", "") if _raw_cfg else ""
        _bcast_models = []
    payload = json.dumps({
        "type": "model_state",
        "active_model": _bcast_active,
        "models": _bcast_models,
    })
    dead: set = set()
    for q in _sse_clients:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.add(q)
    _sse_clients -= dead


async def _external_backend_watcher() -> None:
    """Poll external backend every 5 s; reconnect if down; push state changes via SSE."""
    last_active: str = ""
    last_model_names: list[str] = []
    while not _shutting_down:
        await asyncio.sleep(5)
        if _shutting_down:
            break
        # Reconnect if backend went away or was never up
        if not _external_backend:
            await _try_reconnect_external()
            if _external_backend:
                await _broadcast_model_state()
            continue
        # Full probe — picks up loaded/unloaded changes including "multiple models, no state"
        btype = _external_backend.get("type")
        if btype == "lm_studio":
            fresh = await probe_lm_studio()
        elif btype == "ollama":
            fresh = await probe_ollama()
        else:
            continue
        if fresh is None:
            continue  # Backend temporarily unreachable
        # Update models list from fresh probe
        _external_backend["models"] = fresh["models"]
        model_names = [m["name"] for m in fresh["models"]]
        current = _external_backend.get("active_model", "")
        if current and current not in model_names:
            new_active = model_names[0] if model_names else ""
            _external_backend["active_model"] = new_active
            if _orch and _orch.engine:
                _orch.engine.model_name = new_active
        elif not current and model_names:
            _external_backend["active_model"] = model_names[0]
            if _orch and _orch.engine:
                _orch.engine.model_name = model_names[0]
        active = _external_backend.get("active_model", "")
        if active != last_active or model_names != last_model_names:
            last_active = active
            last_model_names = model_names
            await _broadcast_model_state()


@app.get("/api/model")
async def get_model_info():
    """Return current active model info."""
    await _try_reconnect_external()
    if _external_backend:
        await _refresh_lm_studio_state()
        active = _external_backend.get("active_model", "")
        ctx = _ext_context_size()
        return {
            "active_model": active,
            "model_found": bool(active),
            "enable_thinking": False,
            "vision_supported": False,
            "context_size": ctx or 0,
            "gguf_context_length": ctx,
        }

    # Preference is an external backend but it isn't connected — return empty.
    pref = _raw_cfg.get("inference_backend", "local")
    if pref in ("lm_studio", "ollama"):
        return {
            "active_model": "",
            "model_found": False,
            "enable_thinking": False,
            "vision_supported": False,
            "context_size": 0,
            "gguf_context_length": None,
        }

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
    vision_supported = _cfg.get("models", {}).get("director", {}).get("vision_supported", False) if model_found else False

    return {
        "active_model": model_name,
        "model_found": model_found,
        "enable_thinking": thinking,
        "vision_supported": vision_supported,
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
    vision_supported = _cfg.get("models", {}).get("director", {}).get("vision_supported", False) if model_found else False

    return {
        "active_model": model_name,
        "model_found": model_found,
        "enable_thinking": thinking,
        "vision_supported": vision_supported,
        "context_size": yaml_ctx or gguf_ctx or 0,
        "gguf_context_length": gguf_ctx,
    }


@app.get("/api/models")
async def list_models():
    """List available models — from disk (.gguf) or external backend API."""
    await _try_reconnect_external()
    if _external_backend:
        # Re-probe for fresh model list (user may have loaded a different model)
        if _external_backend["type"] == "lm_studio":
            fresh = await probe_lm_studio()
        elif _external_backend["type"] == "ollama":
            fresh = await probe_ollama()
        else:
            fresh = None
        if fresh is not None:
            _external_backend["models"] = fresh["models"]
            model_names = {m["name"] for m in fresh["models"]}
            current = _external_backend.get("active_model", "")
            if current not in model_names:
                new_active = fresh["models"][0]["name"] if fresh["models"] else ""
                _external_backend["active_model"] = new_active
                if _orch and _orch.engine:
                    _orch.engine.model_name = new_active
        return {"models": _external_backend.get("models", []), "models_dir": None}

    # Preference is an external backend but it isn't connected — don't show local files.
    pref = _raw_cfg.get("inference_backend", "local")
    if pref in ("lm_studio", "ollama"):
        return {"models": [], "models_dir": None}

    from ct1.server.launcher import _detect_thinking_support
    from ct1.core.gguf_reader import read_context_length

    models_dir_rel = _raw_cfg.get("models_dir", "models")
    models_dir = _CONFIG_PATH.resolve().parent.parent.parent / models_dir_rel
    if not models_dir.exists():
        return {"models": [], "models_dir": str(models_dir)}
    files = []
    for p in sorted(models_dir.glob("*.gguf")):
        if p.name.lower().startswith("mmproj"):
            continue
        try:
            size_gb = round(p.stat().st_size / (1024 ** 3), 2)
        except OSError:
            size_gb = 0.0
        gguf_ctx = read_context_length(p)
        files.append({
            "name": p.name,
            "size_gb": size_gb,
            "thinking": _detect_thinking_support(p.name),
            "vision": bool(_detect_vision_support(p.name, p) and _find_mmproj_path(p)),
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
    """Select a model. For external backends: switches instantly (no restart).
    For local llama-server: restarts with the new model file.
    """
    global _raw_cfg, _cfg, _orch, _server_procs, _swapping, _active_think_tasks, _external_backend

    # External backend — instant switch, no server restart needed
    if _external_backend:
        # For LM Studio, always re-probe to get the currently-loaded model list
        # before accepting a selection — prevents selecting an unloaded model which
        # would cause LM Studio to try loading it alongside the already-loaded one.
        if _external_backend["type"] == "lm_studio":
            fresh = await probe_lm_studio()
            if fresh is not None:
                _external_backend["models"] = fresh["models"]
            loaded_names = {m["name"] for m in _external_backend.get("models", [])}
            if body.model not in loaded_names:
                return {
                    "error": (
                        f"'{body.model}' is not loaded in LM Studio. "
                        "Load it in LM Studio first, then click Refresh."
                    )
                }
        else:
            models = _external_backend.get("models", [])
            if not any(m["name"] == body.model for m in models):
                return {"error": f"Model not available: {body.model}"}
        _external_backend["active_model"] = body.model
        # Persist preference so next startup uses the same model
        key = f"{_external_backend['type']}_model"
        _raw_cfg[key] = body.model
        _CONFIG_PATH.write_text(
            yaml.dump(_raw_cfg, default_flow_style=False, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        if _orch and _orch.engine:
            _orch.engine.model_name = body.model
        await _broadcast_model_state()
        return {"status": "ok", "model": body.model}

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
        if _is_generating > 0:
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

        await _broadcast_model_state()
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
        if _is_generating > 0:
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
        if _is_generating > 0:
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


@app.get("/api/web-search")
async def web_search_endpoint(q: str = "", max_results: int = 5):
    """Run a DuckDuckGo web search and return structured results."""
    from ct1.core.web_searcher import search_web
    if not q.strip():
        return {"query": q, "results": [], "error": "Empty query"}
    resp = await search_web(q.strip(), max_results=max(1, min(max_results, 20)))
    return {
        "query": resp.query,
        "results": [{"title": r.title, "url": r.url, "snippet": r.snippet} for r in resp.results],
        "error": resp.error,
    }


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


class ForkConversationBody(BaseModel):
    upto_position: int | None = None
    title: str | None = None
    conversation: list[dict] | None = None


@app.post("/api/conversations/{conv_id}/fork")
async def fork_conversation_endpoint(conv_id: str, body: ForkConversationBody):
    if body.conversation is not None:
        forked = await _db.fork_conversation_from_messages(
            conv_id, body.conversation, body.title
        )
    elif body.upto_position is not None:
        forked = await _db.fork_conversation(conv_id, body.upto_position, body.title)
    else:
        raise HTTPException(status_code=400, detail="Missing fork source")
    if forked is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return forked


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
    slot_conversation_id: str | None = None
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
                    nonlocal slot_conversation_id
                    mode_override = msg.get("mode_override")
                    skip_refinement = msg.get("skip_refinement", False)
                    atlas_settings = msg.get("atlas")
                    actual_goal = goal
                    ws_id = msg.get("workspace_id")
                    incoming_conv_id = msg.get("conversation_id")
                    force_clear_kv = bool(msg.get("force_clear_kv"))

                    if _orch and force_clear_kv:
                        await _orch.clear_kv_cache()
                        slot_conversation_id = None
                    elif _orch and should_clear_kv_cache(
                        slot_conversation_id, incoming_conv_id, conversation,
                    ):
                        await _orch.clear_kv_cache()
                        slot_conversation_id = None

                    # ── Computer mode: inject existing workspace files into context ──
                    if mode_override == "computer" and ws_id and _workspace:
                        try:
                            tree = _workspace.get_file_tree(ws_id)
                            existing = [f["path"] for f in tree if not f["is_dir"]]
                            if existing:
                                file_list = "\n".join(f"  - {p}" for p in existing[:60])
                                ctx_prefix = (
                                    f"[WORKSPACE FILES]\n{file_list}\n\n"
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
                    # Scan the *original* goal (before search-context injection) so that
                    # URLs that appear only inside the injected search snippets are not
                    # double-fetched and bloat the context.
                    from ct1.core.web_fetcher import extract_urls, fetch_url as _fetch_url, URL_PATTERN, MAX_URLS_PER_MESSAGE

                    _original_goal_text = goal if isinstance(goal, str) else " ".join(
                        p.get("text", "") for p in goal if isinstance(p, dict) and p.get("type") == "text"
                    )
                    all_found = set(URL_PATTERN.findall(_original_goal_text))
                    detected_urls = extract_urls(_original_goal_text)

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

                    _search_capability = bool(
                        msg.get("search_capability", msg.get("web_search", False))
                    )
                    _is_computer = mode_override == "computer" and bool(ws_id) and _workspace is not None
                    if _is_computer:
                        _tools = _COMPUTER_TOOL_SCHEMAS + (_TOOL_SCHEMAS if _search_capability else [])
                        _require_approval = bool(msg.get("require_command_approval", False))
                        _tool_executor = _make_computer_tool_executor(queue, _workspace, ws_id, _require_approval)
                    elif _search_capability:
                        _tools = _TOOL_SCHEMAS
                        _tool_executor = _make_tool_executor(queue)
                    else:
                        _tools = None
                        _tool_executor = None

                    result = await _orch.think(
                        actual_goal, on_event=on_event, conversation=conversation,
                        mode_override=mode_override,
                        skip_refinement=skip_refinement,
                        atlas_settings=atlas_settings,
                        tools=_tools,
                        tool_executor=_tool_executor,
                    )
                    # Computer mode: save files → run → inspect → fix loop
                    # Skipped when the AI used tool calls (bash/write_file) — the
                    # Engine's tool loop already handled everything iteratively.
                    _used_tool_calls = (
                        _tool_executor is not None
                        and hasattr(_tool_executor, "_used")
                        and _tool_executor._used.get("count", 0) > 0
                    )
                    if result.get("route") == "ROUTE_COMPUTER" and _workspace and not _used_tool_calls:
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
                                            tools=_tools,
                                            tool_executor=_tool_executor,
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
                        "finish_reason": result.get("finish_reason"),
                        "truncated": result.get("truncated", False),
                        "auto_continuations": result.get("auto_continuations", 0),
                        "explanation": result.get("explanation"),
                    })

                    # Auto-persist conversation
                    _is_new_conv = False
                    if _db and getattr(_db, '_conn', None):
                        try:
                            conv_id = msg.get("conversation_id")
                            if not conv_id:
                                title_text = goal if isinstance(goal, str) else (goal[0].get("text", "") if isinstance(goal, list) else str(goal))
                                title = _heuristic_title(title_text)
                                conv_id = await _db.create_conversation(title, _raw_cfg.get("active_preset", ""), ws_id or None)
                                await websocket.send_json({"event": "conversation_id", "id": conv_id})
                                _is_new_conv = True

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
                                detected_lang=result.get("detected_lang", ""),
                            )

                            # Refine title with LLM for new conversations
                            if _is_new_conv:
                                first_msg_text = goal if isinstance(goal, str) else (goal[0].get("text", "") if isinstance(goal, list) else str(goal))
                                asyncio.create_task(_refine_title(conv_id, first_msg_text, websocket))
                            slot_conversation_id = conv_id
                        except Exception as db_err:
                            print(f"[api] conversation save error: {db_err}")  # non-fatal
                    elif incoming_conv_id:
                        slot_conversation_id = incoming_conv_id

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

                async def _tracked_run_think():
                    global _is_generating
                    _is_generating += 1
                    try:
                        await run_think()
                    finally:
                        _is_generating -= 1

                current_think_task = asyncio.create_task(_tracked_run_think())
                stream_task = asyncio.create_task(stream_events())
                cancel_task = asyncio.create_task(watch_for_cancel())
                try:
                    await asyncio.gather(current_think_task, stream_task)
                except asyncio.CancelledError:
                    await queue.put({
                        "event": "done",
                        "response": "",
                        "route": "",
                        "truncated": False,
                        "auto_continuations": 0,
                    })
                    await stream_task
                finally:
                    cancel_task.cancel()
                    try:
                        await cancel_task  # ensure task terminates before outer loop reads WS again
                    except (asyncio.CancelledError, Exception):
                        pass
                    current_think_task = None

    except (WebSocketDisconnect, RuntimeError):
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


@app.get("/api/workspaces/{ws_id}/conversation")
async def get_workspace_conversation(ws_id: str):
    if not _db or not getattr(_db, '_conn', None):
        return {}
    conv = await _db.get_latest_conversation_for_workspace(ws_id)
    return conv if conv else {}


class CommandApprovalBody(BaseModel):
    approved: bool

@app.post("/api/command-approve/{approval_id}")
async def command_approve(approval_id: str, body: CommandApprovalBody):
    fut = _pending_approvals.pop(approval_id, None)
    if fut and not fut.done():
        fut.set_result(body.approved)
    return {"ok": True}


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
    uvicorn.run(app, host="0.0.0.0", port=8000, timeout_graceful_shutdown=5)
