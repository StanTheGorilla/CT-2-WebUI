import subprocess
import asyncio
import yaml
import os
import signal
from pathlib import Path
from ct1.server.health import wait_for_server


def kill_existing_llama_servers():
    """Kill any leftover llama-server processes before starting new ones."""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/IM", "llama-server.exe"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        else:
            subprocess.run(
                ["pkill", "-f", "llama-server"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        # Give OS a moment to release ports
        import time
        time.sleep(1)
    except Exception:
        pass


def load_raw_config(config_path: str = "ct1/server/model_config.yaml") -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_config(raw_cfg: dict, config_path: str = None) -> dict:
    """Resolve active preset into flat config format expected by Orchestrator/API."""
    preset_name = raw_cfg.get("active_preset", "ct2")
    presets = raw_cfg.get("presets", {})

    if preset_name not in presets:
        raise ValueError(f"Unknown preset: {preset_name}")

    preset = presets[preset_name]
    executable = raw_cfg.get("executable", "")
    models_dir_rel = raw_cfg.get("models_dir", "models")

    # Resolve models_dir relative to project root
    if config_path:
        project_root = Path(config_path).resolve().parent.parent.parent
    else:
        project_root = Path.cwd()
    models_dir = project_root / models_dir_rel

    # Detect format: old (director/specialist nesting) vs new (flat preset)
    is_flat = "director" not in preset

    if is_flat:
        # New flat format — model config lives at preset root
        director = preset
    else:
        # Legacy nested format — model config under "director" key
        director = preset["director"]

    result = {
        "llama_server": {
            "executable": executable,
            "model": str(models_dir / director["model"]),
            "port": director["port"],
            "n_gpu_layers": director.get("n_gpu_layers", 99),
            "parallel_slots": director.get("parallel_slots", 1),
            "context_size": director.get("context_size", 16384),
            "cont_batching": director.get("cont_batching", False),
        },
        "models": {
            "director": {
                "enable_thinking": director.get("enable_thinking", True),
                "temperature": director.get("temperature", 0.6),
                "top_p": director.get("top_p", 0.9),
                "top_k": director.get("top_k", 40),
                "presence_penalty": director.get("presence_penalty", 0),
                "frequency_penalty": director.get("frequency_penalty", 0),
                "max_tokens": director.get("max_tokens", 100000),
                "thinking_budget": director.get("thinking_budget", -1),
                "vision_supported": director.get("vision_supported", False),
            },
        },
        "journal": raw_cfg.get("journal", {}),
        "sessions": raw_cfg.get("sessions", {}),
        "_preset": preset_name,
        "_preset_info": {
            "name": preset.get("name", preset_name),
            "description": preset.get("description", ""),
            "model_file": director.get("model", ""),
            "tier": director.get("tier"),
        },
        "_task_overrides": director.get("task_overrides", {}),
    }

    # Specialist handling (legacy nested format only)
    if not is_flat and "specialist" in preset:
        specialist = preset["specialist"]
        result["llama_server_specialist"] = {
            "executable": executable,
            "model": str(models_dir / specialist["model"]),
            "port": specialist["port"],
            "n_gpu_layers": specialist.get("n_gpu_layers", 99),
            "parallel_slots": specialist.get("parallel_slots", 1),
            "context_size": specialist.get("context_size", 4096),
            "cont_batching": specialist.get("cont_batching", False),
        }
        result["models"]["specialist"] = {
            "enable_thinking": specialist.get("enable_thinking", False),
            "temperature": specialist.get("temperature", 0.1),
            "top_p": specialist.get("top_p", 0.9),
            "top_k": specialist.get("top_k", 10),
            "max_tokens": specialist.get("max_tokens", 1024),
        }

    return result


# Backward-compatible: resolves preset automatically
def load_config(config_path: str = "ct1/server/model_config.yaml") -> dict:
    raw = load_raw_config(config_path)
    return resolve_config(raw, config_path)


def build_server_command(s: dict) -> list:
    cmd = [
        s["executable"],
        "-m", s["model"],
        "--port", str(s["port"]),
        "--n-gpu-layers", str(s["n_gpu_layers"]),
        "--parallel", str(s["parallel_slots"]),
        "-c", str(s["context_size"]),
    ]
    if s.get("cont_batching"):
        cmd.append("--cont-batching")
    return cmd

async def _launch_one(s: dict) -> subprocess.Popen:
    cmd = build_server_command(s)
    port = s["port"]
    print(f"[launcher] Starting llama-server on port {port}...")
    print(f"[launcher] Command: {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    base_url = f"http://localhost:{port}"
    alive = await wait_for_server(base_url, timeout=90)
    if not alive:
        proc.terminate()
        raise RuntimeError(f"llama-server on port {port} failed to start within 90 seconds")
    print(f"[launcher] Server ready at {base_url}")
    return proc

async def start_server(config_path: str = "ct1/server/model_config.yaml") -> list:
    kill_existing_llama_servers()
    cfg = load_config(config_path)

    director_proc = await _launch_one(cfg["llama_server"])
    procs = [director_proc]

    if "llama_server_specialist" in cfg:
        specialist_proc = await _launch_one(cfg["llama_server_specialist"])
        procs.append(specialist_proc)
    else:
        print("[launcher] Solo mode — no specialist server.")

    return procs

def stop_server(procs):
    if isinstance(procs, subprocess.Popen):
        procs = [procs]
    for proc in procs:
        if proc and proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=10)
    print("[launcher] Servers stopped.")


if __name__ == "__main__":
    import time as _time
    procs = asyncio.run(start_server())
    print("[launcher] Servers running. Press Ctrl+C to stop.")
    try:
        while True:
            _time.sleep(1)
    except KeyboardInterrupt:
        stop_server(procs)
