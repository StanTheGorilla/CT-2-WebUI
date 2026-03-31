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
from ct1.memory.component_cache import ComponentCache
from ct1.server.workspace import WorkspaceManager, is_command_safe

_CONFIG_PATH = Path(__file__).parent.parent.parent / "ct1" / "server" / "model_config.yaml"

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


def _ensure_frontend_built() -> None:
    """Run `npm run build` in ct1/web/ if the build output doesn't exist yet."""
    import subprocess
    web_dir = Path(__file__).parent.parent / "web"
    build_dir = web_dir / "build"
    index = build_dir / "index.html"
    if index.exists():
        return
    print("[api] Frontend build not found — running npm run build...")
    try:
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(web_dir),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"[api] WARNING: npm build failed:\n{result.stderr[-1000:]}")
        else:
            print("[api] Frontend built successfully.")
    except FileNotFoundError:
        print("[api] WARNING: npm not found — install Node.js to build the frontend.")


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _orch, _server_procs, _db, _cache, _workspace
    _ensure_frontend_built()
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
    yield
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


@app.post("/api/model/select")
async def select_model(body: ModelSelect):
    """Select a model file and restart the server."""
    global _raw_cfg, _cfg, _orch, _server_procs

    # Validate model exists
    models_dir_rel = _raw_cfg.get("models_dir", "models")
    models_dir = _CONFIG_PATH.resolve().parent.parent.parent / models_dir_rel
    model_path = models_dir / body.model
    if not model_path.exists():
        return {"error": f"Model file not found: {body.model}"}

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
        return {"error": str(e)}

    # Teardown old orchestrator
    if _orch:
        await _orch.close()

    # Restart llama-server
    if _server_procs:
        stop_server(_server_procs)
        _server_procs = []
    try:
        _server_procs = await start_server(str(_CONFIG_PATH),
                                           context_size_override=body.context_size)
    except Exception as e:
        return {"error": f"Failed to start server: {e}"}

    # New orchestrator
    _orch = Orchestrator(str(_CONFIG_PATH),
                         context_size_override=body.context_size)

    return {
        "status": "ok",
        "model": body.model,
        "info": _cfg.get("_preset_info", {}),
    }


class BackendSelect(BaseModel):
    backend: str  # "vulkan" | "cuda"


@app.post("/api/backend/select")
async def select_backend(body: BackendSelect):
    """Switch active backend (vulkan/cuda) and restart llama-server."""
    global _raw_cfg, _cfg, _orch, _server_procs

    if body.backend not in ("vulkan", "cuda"):
        return {"error": f"Invalid backend '{body.backend}'. Must be 'vulkan' or 'cuda'."}

    _raw_cfg["backend"] = body.backend
    _CONFIG_PATH.write_text(
        yaml.dump(_raw_cfg, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    try:
        _cfg = resolve_config(_raw_cfg, str(_CONFIG_PATH))
    except Exception as e:
        return {"error": str(e)}

    stop_server(_server_procs)
    _server_procs = []
    try:
        _server_procs = await start_server(str(_CONFIG_PATH))
        _orch = Orchestrator(str(_CONFIG_PATH), component_cache=_cache)
        return {"ok": True, "backend": body.backend}
    except Exception as e:
        return {"error": str(e)}


class RestartBody(BaseModel):
    context_size: int | None = None


@app.post("/api/restart")
async def restart_model(body: RestartBody):
    """Restart the current model with an optional context_size override."""
    global _raw_cfg, _cfg, _orch, _server_procs

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

    if _server_procs:
        stop_server(_server_procs)
        _server_procs = []
    try:
        _server_procs = await start_server(str(_CONFIG_PATH),
                                           context_size_override=body.context_size)
    except Exception as e:
        return {"error": f"Failed to start server: {e}"}

    _orch = Orchestrator(str(_CONFIG_PATH),
                         context_size_override=body.context_size)

    return {"status": "ok", "info": _cfg.get("_preset_info", {})}


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
    await websocket.accept()
    current_think_task: asyncio.Task | None = None
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
                queue: asyncio.Queue = asyncio.Queue()

                def on_event(event: str, **data):
                    queue.put_nowait({"event": event, **data})

                async def stream_events():
                    while True:
                        item = await queue.get()
                        try:
                            await websocket.send_json(item)
                        except Exception:
                            break
                        if item.get("event") == "done":
                            break

                async def run_think():
                    mode_override = msg.get("mode_override")
                    skip_refinement = msg.get("skip_refinement", False)
                    atlas_settings = msg.get("atlas")
                    actual_goal = goal

                    # ── URL content fetching ──
                    from ct1.core.web_fetcher import extract_urls, fetch_url as _fetch_url, URL_PATTERN, MAX_URLS_PER_MESSAGE

                    goal_text_for_urls = actual_goal if isinstance(actual_goal, str) else " ".join(
                        p.get("text", "") for p in actual_goal if isinstance(p, dict) and p.get("type") == "text"
                    )
                    all_found = set(URL_PATTERN.findall(goal_text_for_urls))
                    detected_urls = extract_urls(goal_text_for_urls)

                    if len(all_found) > MAX_URLS_PER_MESSAGE:
                        queue.put_nowait({
                            "event": "warning",
                            "message": f"Found {len(all_found)} URLs; only the first {MAX_URLS_PER_MESSAGE} will be fetched.",
                        })

                    if detected_urls:
                        ctx_size = _cfg.get("llama_server", {}).get("context_size", 16384)
                        budget_chars = int((ctx_size * 3.5 - 2000) / 2 / len(detected_urls))

                        if budget_chars < 500:
                            queue.put_nowait({
                                "event": "warning",
                                "message": "Context too small to fetch URL content; skipping web fetch.",
                            })
                            detected_urls = []

                    if detected_urls:
                        fetched_blocks = []
                        fetched_meta = []

                        for u in detected_urls:
                            queue.put_nowait({"event": "url_fetching", "url": u})
                            try:
                                fr = await _fetch_url(u, max_chars=budget_chars)
                                if fr.error:
                                    queue.put_nowait({
                                        "event": "url_failed",
                                        "url": u, "error": fr.error,
                                    })
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
                                    queue.put_nowait({
                                        "event": "url_fetched",
                                        "url": fr.url,
                                        "title": fr.title,
                                        "content_length": fr.content_length,
                                        "truncated": fr.truncated,
                                        "preview": fr.content[:500],
                                    })
                            except Exception as e:
                                queue.put_nowait({
                                    "event": "url_failed",
                                    "url": u, "error": str(e),
                                })

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
                        ws_id = msg.get("workspace_id")
                        if not ws_id:
                            queue.put_nowait({"event": "warning", "message": "No workspace — files not saved. Switch to Computer mode first."})
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
                                        queue.put_nowait({
                                            "event": "file_saved",
                                            "path": f["path"],
                                            "workspace_id": ws_id,
                                        })
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
                                                queue.put_nowait({"event": "terminal_output", "text": out_text})
                                                all_cmd_output.append(out_text)
                                                continue
                                            queue.put_nowait({"event": "terminal_output", "text": f"$ {cmd_text}\n"})
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
                                                queue.put_nowait({"event": "terminal_output", "text": output + exit_info})
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
                                                queue.put_nowait({"event": "terminal_output", "text": timeout_msg})
                                                all_cmd_output.append(f"$ {cmd_text}\n{timeout_msg}")
                                                has_errors = True
                                            except Exception as cmd_err:
                                                err_text = f"Error: {cmd_err}\n"
                                                queue.put_nowait({"event": "terminal_output", "text": err_text})
                                                all_cmd_output.append(f"$ {cmd_text}\n{err_text}")
                                                has_errors = True
                                except Exception as run_err:
                                    print(f"[api] run commands error: {run_err}")
                                    break

                                # If errors found and iterations remain, ask AI to fix
                                if has_errors and iteration < max_fix_iterations:
                                    terminal_log = "\n".join(all_cmd_output)[-3000:]
                                    queue.put_nowait({
                                        "event": "terminal_output",
                                        "text": f"\n[CT-2: errors detected, auto-fixing (attempt {iteration + 1}/{max_fix_iterations})...]\n",
                                    })
                                    queue.put_nowait({"event": "fixing"})

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
                                        queue.put_nowait({
                                            "event": "terminal_output",
                                            "text": f"\n[CT-2: fix attempt failed: {fix_err}]\n",
                                        })
                                        break
                                else:
                                    # No errors or out of iterations
                                    break

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

                current_think_task = asyncio.create_task(run_think())
                stream_task = asyncio.create_task(stream_events())
                try:
                    await asyncio.gather(current_think_task, stream_task)
                except asyncio.CancelledError:
                    queue.put_nowait({"event": "done", "response": "", "route": ""})
                    await stream_task
                finally:
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
