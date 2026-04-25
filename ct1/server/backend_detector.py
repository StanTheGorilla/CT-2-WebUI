"""Probe and start external inference backends (Ollama, LM Studio)."""
from __future__ import annotations
import asyncio
import shutil
import subprocess
import httpx

# Process handle for an Ollama we started ourselves (None = pre-existing / not started by us)
_managed_proc: subprocess.Popen | None = None

OLLAMA_URL    = "http://localhost:11434"
LM_STUDIO_URL = "http://localhost:1234"


async def probe_ollama() -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags")
        if r.status_code != 200:
            return None
        models = [
            {
                "name": m["name"],
                "size_gb": round(m.get("size", 0) / 1024 ** 3, 2),
                "thinking": False,
                "vision": False,
                "context_length": None,
            }
            for m in r.json().get("models", [])
        ]
        return {"type": "ollama", "base_url": OLLAMA_URL, "models": models}
    except Exception:
        return None


async def _lm_studio_identify_loaded(raw: list[dict]) -> list[dict]:
    """Identify which models are actually loaded when /v1/models gives no state field.

    Strategy 1 — LM Studio native API (/api/v0/models): richer state info,
    no inference cost.
    Strategy 2 — chat completions probe: LM Studio uses whatever is loaded;
    if nothing is loaded it returns a non-200 error so we get an empty list.
    """
    # -- Strategy 1: native v0 API -----------------------------------------------
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(f"{LM_STUDIO_URL}/api/v0/models")
        if r.status_code == 200:
            data = r.json()
            native = data.get("data", data) if isinstance(data, dict) else data
            if isinstance(native, list):
                loaded_ids: set[str] = set()
                for m in native:
                    mid = m.get("id") or m.get("identifier") or m.get("modelKey") or ""
                    state = str(m.get("state", "")).lower()
                    if state in ("loaded", "running", "serving") or m.get("loaded"):
                        loaded_ids.add(mid)
                if loaded_ids:
                    matched = [m for m in raw if m.get("id") in loaded_ids]
                    if matched:
                        return matched
    except Exception:
        pass

    # -- Strategy 2: chat completions probe --------------------------------------
    # LM Studio always uses the currently-loaded model when no model is specified.
    # A 200 response means something is loaded; non-200 (e.g. 503) means nothing is.
    try:
        async with httpx.AsyncClient(timeout=4.0) as c:
            r = await c.post(
                f"{LM_STUDIO_URL}/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "."}],
                      "max_tokens": 1, "stream": False},
            )
        if r.status_code == 200:
            active_id = r.json().get("model", "")
            if active_id:
                active_lower = active_id.lower()
                # Exact match
                for m in raw:
                    if m.get("id") == active_id:
                        return [m]
                # Case-insensitive / partial match (LM Studio may shorten IDs)
                for m in raw:
                    mid = m.get("id", "")
                    if mid.lower() == active_lower or active_id in mid or mid in active_id:
                        return [m]
        else:
            # Non-200 explicitly means nothing is loaded (e.g. 503 "no model loaded")
            return []
    except Exception:
        pass

    # Both probes inconclusive — show everything rather than a blank list.
    return raw


async def probe_lm_studio() -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(f"{LM_STUDIO_URL}/v1/models")
        if r.status_code != 200:
            return None
        raw = r.json().get("data", [])

        # Strategy 1: state field present — filter to loaded models only.
        has_state = any("state" in m for m in raw)
        if has_state:
            candidates = [m for m in raw if m.get("state") == "loaded"]
        elif len(raw) == 1:
            # Single entry, no state — must be the loaded model (LM Studio ≤0.2).
            candidates = raw
        elif len(raw) == 0:
            candidates = []
        else:
            # Multiple entries, no state — newer LM Studio listing all downloads.
            # Probe with a real request to discover which one is actually loaded.
            candidates = await _lm_studio_identify_loaded(raw)

        models = [
            {
                "name": m["id"],
                "size_gb": 0.0,
                "thinking": False,
                "vision": False,
                # LM Studio returns context_length or max_context_length on the model object
                "context_length": m.get("context_length") or m.get("max_context_length") or None,
            }
            for m in candidates
        ]
        return {"type": "lm_studio", "base_url": LM_STUDIO_URL, "models": models}
    except Exception:
        return None


async def start_ollama(timeout: float = 15.0) -> dict | None:
    """Launch `ollama serve`, store the process handle, wait up to `timeout` seconds."""
    global _managed_proc
    if not shutil.which("ollama"):
        return None
    try:
        _managed_proc = subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        _managed_proc = None
        return None

    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        result = await probe_ollama()
        if result:
            return result
        await asyncio.sleep(1.0)

    # Timed out — kill the process we started
    stop_managed_proc()
    return None


def stop_managed_proc() -> None:
    """Terminate the Ollama process CT-2 started, if any. No-op if pre-existing."""
    global _managed_proc
    if _managed_proc is None:
        return
    try:
        _managed_proc.terminate()
        _managed_proc.wait(timeout=5)
    except Exception:
        try:
            _managed_proc.kill()
        except Exception:
            pass
    finally:
        _managed_proc = None


async def detect(preference: str) -> dict | None:
    """Resolve the active backend for the given explicit preference.

    preference: "ollama" | "lm_studio" | "local"
    Returns: {"type": ..., "base_url": ..., "models": [...]} or None (use local llama-server).
    Ollama: started automatically if not running.
    LM Studio: probed only — user must start it manually.
    """
    if preference == "ollama":
        result = await probe_ollama()
        if result:
            return result
        print("[backend] Ollama not running — attempting to start it...")
        result = await start_ollama()
        if result:
            print("[backend] Ollama started successfully")
        else:
            print("[backend] WARNING: Could not start Ollama. Is it installed?")
        return result

    if preference == "lm_studio":
        result = await probe_lm_studio()
        if not result:
            print("[backend] WARNING: LM Studio server not reachable on port 1234. "
                  "Open LM Studio and start the local server.")
        return result

    return None  # "local" or anything else → use llama-server
