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
_cfg: dict = resolve_config(_raw_cfg, str(_CONFIG_PATH))
_orch: Orchestrator | None = None
_server_procs: list = []
_db: ConversationDB | None = None
_cache: ComponentCache | None = None
_workspace: WorkspaceManager | None = None


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _orch, _server_procs, _db, _cache, _workspace
    # Start llama-server processes, then create orchestrator
    _server_procs = await start_server(str(_CONFIG_PATH))
    _cache = ComponentCache()
    await _cache.init()
    _orch = Orchestrator(str(_CONFIG_PATH), component_cache=_cache)
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
    model_url = f"http://localhost:{_cfg['llama_server']['port']}"
    model = await check_server_health(model_url)
    return {"model": model}


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
    server = _cfg.get("llama_server", {})
    model_params = _cfg.get("models", {}).get("director", {})
    preset_info = _cfg.get("_preset_info", {})
    return {
        "preset": _cfg.get("_preset", ""),
        "preset_name": preset_info.get("name", ""),
        "tier": preset_info.get("tier"),
        "model": Path(server.get("model", "")).name,
        "context_size": server.get("context_size"),
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
    }


@app.get("/api/presets")
async def get_presets():
    """List available presets and the active one."""
    presets = {}
    for name, preset in _raw_cfg.get("presets", {}).items():
        # Support both flat format (model at root) and legacy nested (under "director")
        model_src = preset if "model" in preset else preset.get("director", {})
        presets[name] = {
            "id": name,
            "name": preset.get("name", name),
            "model": model_src.get("model", ""),
            "tier": preset.get("tier") or model_src.get("tier"),
            "context_size": model_src.get("context_size", 0),
        }
    return {
        "active": _raw_cfg.get("active_preset", ""),
        "presets": presets,
    }


class PresetSwitch(BaseModel):
    preset: str


@app.post("/api/preset")
async def switch_preset(body: PresetSwitch):
    """Switch to a different model preset. Restarts the llama-server process."""
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

    # Kill and restart the llama-server process
    kill_existing_llama_servers()
    try:
        _server_procs = await start_server(str(_CONFIG_PATH))
    except Exception as e:
        return {"error": f"Failed to start server: {e}"}

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
                    actual_goal = goal

                    # Inject workspace file context for non-computer modes
                    # so users can ask questions about their computer mode code
                    ws_id = msg.get("workspace_id")
                    if ws_id and mode_override != "computer" and _workspace:
                        try:
                            tree = _workspace.get_file_tree(ws_id)
                            file_parts = []
                            for entry in tree:
                                if entry["is_dir"] or entry["size"] > 50000:
                                    continue
                                try:
                                    content = _workspace.read_file(ws_id, entry["path"])
                                    file_parts.append(f"[Workspace file: {entry['path']}]\n{content}")
                                except Exception:
                                    pass
                            if file_parts:
                                ctx = "\n\n".join(file_parts[:10])  # cap at 10 files
                                if isinstance(actual_goal, str):
                                    actual_goal = f"[WORKSPACE FILES — the user has these files from computer mode]\n{ctx}\n\n{actual_goal}"
                                elif isinstance(actual_goal, list):
                                    # Multimodal: prepend to the text part
                                    for part in actual_goal:
                                        if part.get("type") == "text":
                                            part["text"] = f"[WORKSPACE FILES — the user has these files from computer mode]\n{ctx}\n\n{part['text']}"
                                            break
                        except Exception as e:
                            print(f"[api] workspace context inject error: {e}")

                    result = await _orch.think(
                        actual_goal, on_event=on_event, conversation=conversation,
                        mode_override=mode_override,
                        skip_refinement=skip_refinement,
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
