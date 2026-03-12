import subprocess
import asyncio
import yaml
import os
from pathlib import Path
from ct1.server.health import wait_for_server

def load_config(config_path: str = "ct1/server/model_config.yaml") -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)

def build_server_command(cfg: dict) -> list:
    s = cfg["llama_server"]
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

async def start_server(config_path: str = "ct1/server/model_config.yaml") -> subprocess.Popen:
    cfg = load_config(config_path)
    cmd = build_server_command(cfg)
    port = cfg["llama_server"]["port"]

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
        raise RuntimeError("llama-server failed to start within 90 seconds")

    print(f"[launcher] Server ready at {base_url}")
    return proc

def stop_server(proc: subprocess.Popen):
    if proc and proc.poll() is None:
        proc.terminate()
        proc.wait(timeout=10)
        print("[launcher] Server stopped.")
