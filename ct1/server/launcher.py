import subprocess
import asyncio
import shutil
import re
import yaml
import os
import signal
import time
from pathlib import Path
from ct1.server.health import wait_for_server


# ─── GPU / load diagnostics ───────────────────────────────────────────────
# Updated by _drain_stderr whenever llama-server prints layer-offload info.
# Read by /api/system/gpu-status so the UI can warn when a restart left the
# model partially on CPU (the classic symptom of VRAM fragmentation).
_layer_status: dict | None = None
_LAYER_OFFLOAD_RE = re.compile(
    r"offloaded\s+(?P<offloaded>\d+)\s*/\s*(?P<total>\d+)\s+layers?\s+to\s+GPU",
    re.IGNORECASE,
)


def get_layer_status() -> dict | None:
    """Return the most recent {offloaded, total, degraded} dict, or None.

    `degraded=True` means the latest model load did not place every layer
    on the GPU — a strong signal that throughput will be much slower than
    a clean load, usually caused by AMD Vulkan VRAM fragmentation after
    repeated restarts.
    """
    return _layer_status


def reset_layer_status() -> None:
    """Clear the cached status — call before starting a new server so a
    failed launch doesn't show stale numbers from the previous run."""
    global _layer_status
    _layer_status = None


def probe_used_vram_mb() -> int | None:
    """Return total dedicated VRAM in use across all GPU adapters, in MB.

    Windows-only (uses PowerShell PDH counters). Returns None if the probe
    fails or is unavailable. Used purely for logging — never gates launch.
    """
    if os.name != "nt":
        return None
    try:
        ps = (
            "(Get-Counter '\\GPU Adapter Memory(*)\\Dedicated Usage' "
            "-ErrorAction SilentlyContinue).CounterSamples.CookedValue | "
            "Measure-Object -Sum | Select -ExpandProperty Sum"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=4,
        )
        out = (r.stdout or "").strip()
        if not out:
            return None
        return int(float(out) / 1024 / 1024)
    except Exception:
        return None


def _find_llama_executable(project_root: Path, configured: str = "auto",
                            backend: str = "vulkan") -> str:
    """Resolve the llama-server binary path.

    Priority:
    1. Explicit path in config, if it exists on disk
    2. `llama-server` found via PATH (shutil.which)
    3. bin/{backend}/ directory (auto-downloaded)
    4. Any llama-*-bin-* directory relative to project root or its parent
    5. Auto-download from GitHub, then retry bin/{backend}/
    """
    ext = ".exe" if os.name == "nt" else ""

    if configured and configured.lower() != "auto":
        p = Path(configured)
        if p.exists():
            return str(p)

    # PATH
    found = shutil.which("llama-server")
    if found:
        return found

    # bin/{backend}/ — auto-downloaded location
    bin_path = project_root / "bin" / backend / f"llama-server{ext}"
    if bin_path.exists():
        return str(bin_path)

    # Scan for bundled binary directories (newest first by name sort)
    for search_root in [project_root, project_root.parent]:
        candidates = sorted(search_root.glob("llama-*-bin-*"), reverse=True)
        for d in candidates:
            candidate = d / f"llama-server{ext}"
            if candidate.exists():
                return str(candidate)

    # Auto-download as last resort
    print("[launcher] llama-server not found — downloading automatically...")
    from ct1.server.downloader import download_llama_server
    download_llama_server(project_root)

    if bin_path.exists():
        return str(bin_path)

    # Fallback: if requested backend failed, try vulkan (always downloaded)
    if backend != "vulkan":
        vulkan_path = project_root / "bin" / "vulkan" / f"llama-server{ext}"
        if vulkan_path.exists():
            print(f"[launcher] {backend} not available, falling back to vulkan")
            return str(vulkan_path)

    raise FileNotFoundError(
        "llama-server executable not found and auto-download failed.\n"
        f"  • Add llama-server{ext} to your PATH, or\n"
        "  • Place a llama-*-bin-* directory next to this project, or\n"
        "  • Set 'executable' in ct1/server/model_config.yaml to its full path."
    )


def _is_llama_server_running() -> bool:
    """Check if any llama-server process is still alive."""
    try:
        if os.name == "nt":
            r = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/NH"],
                capture_output=True, text=True, encoding="utf-8", errors="replace"
            )
            return "llama-server.exe" in r.stdout
        else:
            r = subprocess.run(
                ["pgrep", "-f", "llama-server"],
                capture_output=True
            )
            return r.returncode == 0
    except Exception:
        return False


def _get_llama_pid():
    """Return the PID of the running llama-server process, or None."""
    try:
        if os.name == "nt":
            r = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            for line in r.stdout.strip().splitlines():
                # CSV format: "llama-server.exe","1234","Console","1","..."
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) >= 2:
                    try:
                        return int(parts[1])
                    except ValueError:
                        pass
        else:
            r = subprocess.run(
                ["pgrep", "-f", "llama-server"], capture_output=True, text=True, encoding="utf-8", errors="replace"
            )
            if r.returncode == 0:
                return int(r.stdout.strip().split()[0])
    except Exception:
        pass
    return None


def _graceful_shutdown_llama(port: int = 8080, timeout: float = 10.0) -> bool:
    """Shut down llama-server gracefully so it can release Vulkan resources.

    Strategy (in order):
    1. POST /shutdown — works on llama-server b9xxx+
    2. CTRL_BREAK_EVENT (Windows) / SIGTERM (Linux) — triggers the process's own
       signal handler which calls vkDestroyDevice before exiting.  Much better than
       taskkill /F which skips cleanup and leaves VRAM fragmented.

    Returns True if the process exited cleanly within timeout.
    """
    import urllib.request

    shutdown_signaled = False

    # ── Step 1: HTTP shutdown endpoint ───────────────────────────────────────
    try:
        req = urllib.request.Request(
            f"http://localhost:{port}/shutdown",
            method="POST",
            data=b"",
        )
        urllib.request.urlopen(req, timeout=3)
        shutdown_signaled = True
    except (ConnectionError, OSError):
        # Connection reset/refused after sending = server accepted and is exiting.
        shutdown_signaled = True
    except Exception:
        pass  # Likely 404 on older build — fall through to signal approach

    # ── Step 2: Process signal (graceful, not force-kill) ────────────────────
    if not shutdown_signaled:
        pid = _get_llama_pid()
        if pid is None:
            return False
        try:
            if os.name == "nt":
                # CTRL_BREAK_EVENT goes to the process group (llama-server was started
                # with CREATE_NEW_PROCESS_GROUP so its PGID == PID).  This fires the
                # C-runtime signal handler, which calls proper Vulkan teardown.
                os.kill(pid, signal.CTRL_BREAK_EVENT)
            else:
                os.kill(pid, signal.SIGTERM)
            shutdown_signaled = True
            print(f"[launcher] Sent graceful signal to llama-server (pid {pid})")
        except (ProcessLookupError, PermissionError, OSError):
            return False

    # ── Poll for process exit ─────────────────────────────────────────────────
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if not _is_llama_server_running():
            elapsed = time.monotonic() - start
            print(f"[launcher] llama-server exited gracefully in {elapsed:.1f}s (Vulkan resources released)")
            return True
        time.sleep(0.5)

    print(f"[launcher] Graceful shutdown timed out after {timeout}s — escalating to force-kill")
    return False


def kill_existing_llama_servers(port: int = 8080, *, hard: bool = False):
    """Kill any leftover llama-server processes before starting new ones.

    Tries graceful API shutdown first (preserves Vulkan driver state),
    falls back to force-kill only if graceful fails.

    `hard=True` doubles the cooldown windows and bumps the graceful
    timeout. Use it from /api/server/hard-reset when a normal restart
    keeps producing partially-CPU loads — gives the AMD Vulkan driver
    extra time to coalesce freed VRAM into a contiguous pool.
    """
    if not _is_llama_server_running():
        # Even with no process running, log free VRAM if available — useful
        # for confirming whether prior shutdowns released memory.
        used = probe_used_vram_mb()
        if used is not None:
            print(f"[launcher] No llama-server running; VRAM in use: {used} MB")
        return

    used_before = probe_used_vram_mb()
    if used_before is not None:
        print(f"[launcher] VRAM in use before shutdown: {used_before} MB")

    # Step 1: Try graceful shutdown via API — this lets llama-server
    # call vkDestroyDevice and properly release GPU memory
    graceful_timeout = 15.0 if hard else 10.0
    if _graceful_shutdown_llama(port, timeout=graceful_timeout):
        # GPU cooldown — driver reclaims VRAM. AMD Vulkan in particular
        # needs a few seconds; bump it on Windows where fragmentation is worst.
        if os.name == "nt":
            time.sleep(8 if hard else 4)
        else:
            time.sleep(4 if hard else 2)
        used_after = probe_used_vram_mb()
        if used_after is not None and used_before is not None:
            freed = used_before - used_after
            print(f"[launcher] VRAM in use after cooldown: {used_after} MB (freed {freed} MB)")
        return

    # Step 2: Graceful failed — force kill as fallback
    print("[launcher] Graceful shutdown failed, force-killing...")
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
    except Exception:
        pass

    # Poll until process is actually gone (up to 10–15s)
    poll_seconds = 15 if hard else 10
    for _ in range(poll_seconds):
        if not _is_llama_server_running():
            break
        time.sleep(1.0)
    else:
        print(f"[launcher] WARNING: llama-server still alive after {poll_seconds}s — proceeding anyway")

    # GPU cooldown — extra-long after force-kill since the process
    # didn't get to call vkDestroyDevice cleanly.
    if os.name == "nt":
        time.sleep(12 if hard else 6)  # AMD Vulkan driver needs a long moment to reclaim VRAM
    else:
        time.sleep(5 if hard else 3)
    used_after = probe_used_vram_mb()
    if used_after is not None:
        if used_before is not None:
            freed = used_before - used_after
            print(f"[launcher] VRAM in use after force-kill cooldown: {used_after} MB (freed {freed} MB)")
        else:
            print(f"[launcher] VRAM in use after force-kill cooldown: {used_after} MB")


def load_raw_config(config_path: str = "ct1/server/model_config.yaml") -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _detect_mtp_support(model_filename: str) -> bool:
    """Return True if the model filename contains 'mtp', indicating MTP draft heads are baked in."""
    return "mtp" in model_filename.lower()


def _detect_thinking_support(model_filename: str) -> bool:
    """Auto-detect whether a model supports thinking from its filename.

    Known thinking-capable model families:
    - Qwen 3+ (Qwen3, Qwen3.5, etc.)
    - Gemma 4
    - NVIDIA Nemotron Nano (has /think tags in chat template)
    - DeepSeek R1/V3
    - Any model with 'think' in the name
    """
    name = model_filename.lower()
    if "qwen3" in name or "qwen-3" in name:
        return True
    if "gemma-4" in name or "gemma4" in name:
        return True
    if "nemotron" in name and "nano" in name:
        return True
    if "deepseek" in name and ("r1" in name or "v3" in name):
        return True
    if "think" in name:
        return True
    return False


def _detect_vision_support(model_filename: str, model_path: str | Path | None = None) -> bool:
    """Best-effort detection for multimodal/vision-capable GGUF models."""
    name = model_filename.lower()
    name_hits = (
        "vision",
        "llava",
        "pixtral",
        "internvl",
        "minicpm-v",
        "minicpmv",
        "paligemma",
        "moondream",
        "fuyu",
        "bunny",
        "cogvlm",
        "deepseek-vl",
        "phi-3-vision",
        "phi3-vision",
        "phi3v",
        "mllama",
        "qwen2-vl",
        "qwen2.5-vl",
        "qwen-2-vl",
        "qwen-2.5-vl",
        "llama-3.2-vision",
    )
    if any(hit in name for hit in name_hits):
        return True

    if model_path:
        try:
            from ct1.core.gguf_reader import read_architecture

            arch = (read_architecture(model_path) or "").lower()
            if arch in {
                "gemma3",
                "gemma4",
                "llava",
                "mllama",
                "paligemma",
                "pixtral",
                "minicpmv",
                "internvl",
                "moondream",
                "fuyu",
            }:
                return True
            if "vl" in arch or "vision" in arch:
                return True
        except Exception:
            pass

    return False


def _find_mmproj_path(model_path: str | Path, configured: str | None = "auto") -> str | None:
    """Resolve an mmproj sidecar for a multimodal model when available."""
    model_path = Path(model_path)

    if configured and str(configured).lower() != "auto":
        candidate = Path(configured)
        return str(candidate) if candidate.exists() else None

    candidates = sorted(model_path.parent.glob("*mmproj*.gguf"))
    if not candidates:
        return None

    def _tokens(value: str) -> set[str]:
        return {
            tok for tok in re.split(r"[^a-z0-9]+", value.lower())
            if tok and tok not in {"gguf", "mmproj", "q4", "q5", "q6", "q8", "k", "m", "s", "it", "f16", "f32", "bf16"}
        }

    model_tokens = _tokens(model_path.stem)
    size_tokens = {tok for tok in model_tokens if re.fullmatch(r"(?:[ea]\d+b|\d+b)", tok)}
    ranked = sorted(
        ((len(model_tokens & _tokens(cand.stem)), cand) for cand in candidates),
        key=lambda item: (item[0], -len(item[1].name)),
        reverse=True,
    )
    best_score, best = ranked[0]
    if size_tokens:
        best_tokens = _tokens(best.stem)
        if not (size_tokens & best_tokens):
            return None
    return str(best) if best_score > 0 else None


def _ensure_mmproj_path(model_path: str | Path, configured: str | None = "auto") -> str | None:
    """Return a local mmproj path, auto-downloading a known sidecar when needed."""
    mmproj_path = _find_mmproj_path(model_path, configured)
    if mmproj_path:
        return mmproj_path

    if configured and str(configured).lower() != "auto":
        return None

    try:
        from ct1.server.downloader import ensure_mmproj_downloaded

        resolved = ensure_mmproj_downloaded(model_path)
        if resolved:
            print(f"[launcher] mmproj ready: {resolved}")
        return resolved
    except Exception as exc:
        print(f"[launcher] mmproj auto-download unavailable: {exc}")
        return None


def resolve_config(raw_cfg: dict, config_path: str = None,
                    context_size_override: int = None) -> dict:
    """Resolve model config into flat format expected by Orchestrator/API.

    Supports two config formats:
    1. New flat format: active_model + top-level params (no presets)
    2. Legacy preset format: presets[active_preset] with per-preset params

    context_size_override: if provided, use this as context_size (from UI slider).
    Otherwise, use config context_size as a cap on the GGUF model's actual max.
    """
    # Resolve project root
    if config_path:
        project_root = Path(config_path).resolve().parent.parent.parent
    else:
        project_root = Path.cwd()

    models_dir_rel = raw_cfg.get("models_dir", "models")
    models_dir = project_root / models_dir_rel

    backend = raw_cfg.get("backend", "vulkan")
    executable = _find_llama_executable(project_root, raw_cfg.get("executable", "auto"), backend=backend)

    # ── Detect config format ──────────────────────────────────────
    is_new_format = "active_model" in raw_cfg and "presets" not in raw_cfg

    if is_new_format:
        # ── New flat format ───────────────────────────────────────
        model_name = raw_cfg.get("active_model")
        if not model_name:
            raise ValueError(
                "No model selected.\n"
                "  Open Settings in the web UI and pick a .gguf file."
            )

        model_path = models_dir / model_name
        enable_thinking = _detect_thinking_support(model_name)
        explicit_vision = raw_cfg.get("vision_supported") if "vision_supported" in raw_cfg else None
        vision_capable = explicit_vision if explicit_vision is not None else _detect_vision_support(model_name, model_path)
        mmproj_path = _ensure_mmproj_path(model_path, raw_cfg.get("mmproj", "auto")) if vision_capable else None
        vision_supported = bool(vision_capable and (mmproj_path or explicit_vision is True))

        from ct1.core.gguf_reader import read_context_length
        gguf_context = read_context_length(model_path)
        yaml_context = raw_cfg.get("context_size")

        if gguf_context is None:
            gguf_context = yaml_context or 16384

        if context_size_override is not None:
            effective_context = min(context_size_override, gguf_context)
        elif yaml_context is not None:
            effective_context = min(yaml_context, gguf_context)
        else:
            effective_context = gguf_context

        mtp_default = 2 if _detect_mtp_support(model_name) else 0
        result = {
            "llama_server": {
                "executable": executable,
                "model": str(model_path),
                "port": raw_cfg.get("port", 8080),
                "n_gpu_layers": raw_cfg.get("n_gpu_layers", 99),
                "parallel_slots": raw_cfg.get("parallel_slots", 1),
                "context_size": effective_context,
                "cont_batching": raw_cfg.get("cont_batching", False),
                "flash_attn": raw_cfg.get("flash_attn", False),
                "embeddings": raw_cfg.get("rag", {}).get("enabled", False),
                "mtp_n_draft": raw_cfg.get("mtp_n_draft", mtp_default),
            },
            "_gguf_context_length": gguf_context,
            "models": {
                "director": {
                    "enable_thinking": enable_thinking,
                    "temperature": raw_cfg.get("temperature", 0.6),
                    "top_p": raw_cfg.get("top_p", 0.9),
                    "top_k": raw_cfg.get("top_k", 40),
                    "presence_penalty": raw_cfg.get("presence_penalty", 0),
                    "frequency_penalty": raw_cfg.get("frequency_penalty", 0),
                    "max_tokens": raw_cfg.get("max_tokens", 100000),
                    "thinking_budget": raw_cfg.get("thinking_budget", -1),
                    "repeat_penalty": raw_cfg.get("repeat_penalty", 1.10),
                    "vision_supported": vision_supported,
                },
            },
            "journal": raw_cfg.get("journal", {}),
            "sessions": raw_cfg.get("sessions", {}),
            "_preset": "default",
            "_preset_info": {
                "name": model_name.replace(".gguf", ""),
                "description": "",
                "model_file": model_name,
                "tier": None,
            },
            "_task_overrides": raw_cfg.get("task_overrides", {}),
        }
        if mmproj_path:
            result["llama_server"]["mmproj"] = mmproj_path
        return result

    # ── Legacy preset format ──────────────────────────────────────
    preset_name = raw_cfg.get("active_preset", "ct2")
    presets = raw_cfg.get("presets", {})

    if preset_name not in presets:
        raise ValueError(f"Unknown preset: {preset_name}")

    preset = presets[preset_name]

    # Detect sub-format: old (director/specialist nesting) vs flat preset
    is_flat = "director" not in preset

    if is_flat:
        director = preset
    else:
        director = preset["director"]

    model_name = director.get("model")
    if not model_name:
        raise ValueError(
            f"No model file configured for preset '{preset_name}'.\n"
            "  Open Settings in the web UI and assign a .gguf file to this preset."
        )
    model_path = models_dir / model_name
    explicit_vision = director.get("vision_supported") if "vision_supported" in director else None
    vision_capable = explicit_vision if explicit_vision is not None else _detect_vision_support(model_name, model_path)
    mmproj_cfg = director.get("mmproj", raw_cfg.get("mmproj", "auto"))
    mmproj_path = _ensure_mmproj_path(model_path, mmproj_cfg) if vision_capable else None
    vision_supported = bool(vision_capable and (mmproj_path or explicit_vision is True))

    from ct1.core.gguf_reader import read_context_length
    gguf_context = read_context_length(model_path)
    yaml_context = director.get("context_size")

    if gguf_context is None:
        gguf_context = yaml_context or 16384

    if context_size_override is not None:
        effective_context = min(context_size_override, gguf_context)
    elif yaml_context is not None:
        effective_context = min(yaml_context, gguf_context)
    else:
        effective_context = gguf_context

    mtp_default = 2 if _detect_mtp_support(model_name) else 0
    result = {
        "llama_server": {
            "executable": executable,
            "model": str(model_path),
            "port": director.get("port", 8080),
            "n_gpu_layers": director.get("n_gpu_layers", 99),
            "parallel_slots": director.get("parallel_slots", 1),
            "context_size": effective_context,
            "cont_batching": director.get("cont_batching", False),
            "flash_attn": director.get("flash_attn", False),
            "mtp_n_draft": director.get("mtp_n_draft", raw_cfg.get("mtp_n_draft", mtp_default)),
        },
        "_gguf_context_length": gguf_context,
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
                "repeat_penalty": director.get("repeat_penalty", 1.10),
                "vision_supported": vision_supported,
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
    if mmproj_path:
        result["llama_server"]["mmproj"] = mmproj_path

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
def load_config(config_path: str = "ct1/server/model_config.yaml",
                context_size_override: int = None) -> dict:
    raw = load_raw_config(config_path)
    return resolve_config(raw, config_path,
                          context_size_override=context_size_override)


def build_server_command(s: dict) -> list:
    mtp = s.get("mtp_n_draft", 0)
    # MTP requires single parallel slot
    parallel = 1 if mtp > 0 else s["parallel_slots"]
    cmd = [
        s["executable"],
        "-m", s["model"],
        "--port", str(s["port"]),
        "--n-gpu-layers", str(s["n_gpu_layers"]),
        "--parallel", str(parallel),
        "-c", str(s["context_size"]),
    ]
    if s.get("mmproj"):
        cmd += ["--mmproj", str(s["mmproj"])]
    if s.get("cont_batching"):
        cmd.append("--cont-batching")
    if s.get("flash_attn"):
        cmd += ["--flash-attn", "on"]
    if s.get("embeddings") and mtp == 0:
        cmd += ["--embeddings", "--pooling", "last"]
    if mtp > 0:
        model_name = Path(s["model"]).name
        if _detect_mtp_support(model_name):
            cmd += ["--spec-type", "draft-mtp", "--spec-draft-n-max", str(mtp)]
            if s.get("embeddings"):
                print("[launcher] INFO: MTP active — --embeddings skipped (incompatible graph configurations)")
        else:
            print(f"[launcher] WARNING: mtp_n_draft={mtp} requested but '{model_name}' has no MTP layers — skipping MTP flags")
    return cmd

def _drain_stderr(proc: subprocess.Popen, label: str = "llama"):
    """Read llama-server stderr in a background thread, print key lines, and
    parse the layer-offload count into _layer_status for the UI."""
    import threading

    def _reader():
        global _layer_status
        for raw_line in proc.stderr:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue
            # Always print GPU/VRAM and KV cache lines — critical for diagnosing perf
            if any(kw in line.lower() for kw in [
                "gpu", "vram", "vulkan", "kv ", "layer", "offload",
                "context", "error", "warning", "fail", "memory",
            ]):
                print(f"[{label}] {line}")

            # Parse 'offloaded N/M layers to GPU' so the UI can flag a
            # degraded load (typical of post-fragmentation restarts).
            m = _LAYER_OFFLOAD_RE.search(line)
            if m:
                offloaded = int(m.group("offloaded"))
                total = int(m.group("total"))
                _layer_status = {
                    "offloaded": offloaded,
                    "total": total,
                    "degraded": offloaded < total,
                }
                if offloaded < total:
                    print(
                        f"[{label}] WARNING: only {offloaded}/{total} layers on GPU "
                        f"— remainder running on CPU, throughput will be much slower. "
                        f"Try a Hard reset to clear VRAM fragmentation."
                    )

    t = threading.Thread(target=_reader, daemon=True)
    t.start()


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
    _drain_stderr(proc, label=f"llama:{port}")
    base_url = f"http://localhost:{port}"
    alive = await wait_for_server(base_url, timeout=90, proc=proc)
    if not alive:
        exit_code = proc.poll()
        proc.terminate()
        if exit_code is not None:
            raise RuntimeError(
                f"llama-server on port {port} exited immediately (code {exit_code}) — "
                "model may be incompatible or corrupted"
            )
        raise RuntimeError(f"llama-server on port {port} failed to start within 90 seconds")
    print(f"[launcher] Server ready at {base_url}")
    return proc

async def start_server(config_path: str = "ct1/server/model_config.yaml",
                       context_size_override: int = None,
                       *, hard: bool = False) -> list:
    """Launch llama-server (and optional specialist) for the active model.

    `hard=True` extends shutdown cooldowns — see kill_existing_llama_servers.
    """
    reset_layer_status()  # don't show stale numbers if launch fails
    kill_existing_llama_servers(hard=hard)
    cfg = load_config(config_path, context_size_override=context_size_override)

    director_proc = await _launch_one(cfg["llama_server"])
    procs = [director_proc]

    if "llama_server_specialist" in cfg:
        specialist_proc = await _launch_one(cfg["llama_server_specialist"])
        procs.append(specialist_proc)
    else:
        print("[launcher] Solo mode — no specialist server.")

    return procs

def stop_server(procs, port: int = 8080, *, hard: bool = False):
    """Stop the running llama-server process(es) and wait for VRAM cleanup.

    Always sleeps after a graceful shutdown so the AMD Vulkan driver gets
    time to coalesce freed VRAM into a contiguous pool. Without this wait
    the next `start_server` call would launch into a fragmented pool and
    silently fall back to partial CPU offload.
    """
    if isinstance(procs, subprocess.Popen):
        procs = [procs]

    used_before = probe_used_vram_mb()
    if used_before is not None:
        print(f"[launcher] VRAM in use before stop: {used_before} MB")

    # Try graceful API shutdown first — critical for AMD Vulkan cleanup
    graceful = False
    if any(p and p.poll() is None for p in procs):
        graceful = _graceful_shutdown_llama(port, timeout=15.0 if hard else 10.0)

    # Clean up any that didn't exit via API
    for proc in procs:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    # GPU cooldown — must happen here, otherwise start_server's call to
    # kill_existing_llama_servers will skip it (no process to kill).
    if os.name == "nt":
        wait_s = (8 if hard else 4) if graceful else (12 if hard else 6)
    else:
        wait_s = (4 if hard else 2) if graceful else (5 if hard else 3)
    time.sleep(wait_s)

    used_after = probe_used_vram_mb()
    if used_after is not None:
        if used_before is not None:
            print(f"[launcher] Servers stopped. VRAM: {used_before} → {used_after} MB (freed {used_before - used_after} MB after {wait_s}s cooldown)")
        else:
            print(f"[launcher] Servers stopped. VRAM in use: {used_after} MB after {wait_s}s cooldown")
    else:
        print(f"[launcher] Servers stopped. {wait_s}s GPU cooldown complete.")


if __name__ == "__main__":
    import time as _time
    procs = asyncio.run(start_server())
    print("[launcher] Servers running. Press Ctrl+C to stop.")
    try:
        while True:
            _time.sleep(1)
    except KeyboardInterrupt:
        stop_server(procs)
