import subprocess
import asyncio
import yaml
import os
import signal
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

def load_config(config_path: str = "ct1/server/model_config.yaml") -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)

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
    specialist_proc = await _launch_one(cfg["llama_server_specialist"])
    return [director_proc, specialist_proc]

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
    print("[launcher] Both servers running. Press Ctrl+C to stop.")
    try:
        while True:
            _time.sleep(1)
    except KeyboardInterrupt:
        stop_server(procs)
