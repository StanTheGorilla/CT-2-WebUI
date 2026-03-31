# llama-server Auto-Download Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** When `python -m ct1.server.api` starts and llama-server is not found, automatically download both Vulkan and CUDA builds from the latest llama.cpp GitHub release, and let the user switch between backends in the Settings UI.

**Architecture:** A new `ct1/server/downloader.py` module handles GitHub API fetch, asset filtering, download with progress, and zip extraction into `bin/vulkan/` and `bin/cuda/`. The existing `_find_llama_executable` in `launcher.py` is extended to check `bin/{backend}/` and call the downloader as a last resort. A new `POST /api/backend/select` endpoint + Settings dropdown lets the user switch backends.

**Tech Stack:** Python stdlib (`urllib.request`, `zipfile`, `json`), FastAPI, Svelte 5 runes, GitHub Releases API

---

### Task 1: Gitignore + default backend field

**Files:**
- Modify: `.gitignore`
- Modify: `ct1/server/model_config.yaml`

**Step 1: Add `bin/` to `.gitignore`**

Open `.gitignore` and add under the `# ── Model files` section:
```
# ── llama-server auto-downloaded binaries ──────────────────────────────────
bin/
```

**Step 2: Add `backend` field to `model_config.yaml`**

Open `ct1/server/model_config.yaml`. Add after `executable: auto`:
```yaml
backend: vulkan           # vulkan | cuda  (macOS always uses Metal build)
```

**Step 3: Verify**
```bash
git check-ignore -v bin/
# Expected: .gitignore:N  bin/
grep "backend" ct1/server/model_config.yaml
# Expected: backend: vulkan
```

**Step 4: Commit**
```bash
git add .gitignore ct1/server/model_config.yaml
git commit -m "chore: gitignore bin/, add backend field to model_config"
```

---

### Task 2: `downloader.py` — platform detection + asset filtering (TDD)

**Files:**
- Create: `ct1/server/downloader.py`
- Create: `tests/test_downloader.py`

**Step 1: Write the failing tests**

Create `tests/test_downloader.py`:
```python
import sys
import pytest


def test_get_platform_info_returns_required_keys():
    from ct1.server.downloader import _get_platform_info
    info = _get_platform_info()
    assert "vulkan" in info
    assert "cuda" in info   # may be None on macOS
    assert "exe" in info


def test_get_platform_info_exe_extension():
    from ct1.server.downloader import _get_platform_info
    info = _get_platform_info()
    if sys.platform == "win32":
        assert info["exe"] == "llama-server.exe"
    else:
        assert info["exe"] == "llama-server"


def test_get_platform_info_macos_no_cuda():
    """macOS has no CUDA build."""
    from ct1.server.downloader import _get_platform_info
    if sys.platform != "darwin":
        pytest.skip("macOS only")
    info = _get_platform_info()
    assert info["cuda"] is None


def test_find_asset_matches_by_substring():
    from ct1.server.downloader import _find_asset
    assets = [
        {"name": "llama-b9000-bin-win-vulkan-x64.zip", "browser_download_url": "https://example.com/vulkan.zip"},
        {"name": "llama-b9000-bin-win-cuda-cu12.4-x64.zip", "browser_download_url": "https://example.com/cuda.zip"},
        {"name": "llama-b9000-SHA256SUMS", "browser_download_url": "https://example.com/sha"},
    ]
    result = _find_asset(assets, "bin-win-vulkan-x64")
    assert result is not None
    assert result["name"] == "llama-b9000-bin-win-vulkan-x64.zip"


def test_find_asset_returns_none_when_not_found():
    from ct1.server.downloader import _find_asset
    assets = [{"name": "llama-b9000-SHA256SUMS", "browser_download_url": "x"}]
    assert _find_asset(assets, "bin-win-vulkan-x64") is None


def test_find_asset_ignores_non_zip():
    from ct1.server.downloader import _find_asset
    assets = [
        {"name": "llama-b9000-bin-win-vulkan-x64.tar.gz", "browser_download_url": "x"},
    ]
    # Must end in .zip
    assert _find_asset(assets, "bin-win-vulkan-x64") is None
```

**Step 2: Run tests to verify they fail**
```bash
cd F:/AI_Workstation/web-ui
pytest tests/test_downloader.py -v
# Expected: ImportError or ModuleNotFoundError (downloader doesn't exist yet)
```

**Step 3: Create `ct1/server/downloader.py` with just these two functions**

```python
"""
llama-server auto-downloader.

Downloads Vulkan and CUDA builds from the latest llama.cpp GitHub release
into bin/vulkan/ and bin/cuda/ at the project root.
"""
import os
import sys
from pathlib import Path


def _get_platform_info() -> dict:
    """Return platform-specific asset name fragments and executable name."""
    if sys.platform == "win32":
        return {
            "vulkan": "bin-win-vulkan-x64",
            "cuda":   "bin-win-cuda-cu12.4-x64",
            "exe":    "llama-server.exe",
        }
    elif sys.platform == "darwin":
        return {
            "vulkan": "bin-macos-arm64",
            "cuda":   None,            # Metal is built into the macOS binary
            "exe":    "llama-server",
        }
    else:  # Linux
        return {
            "vulkan": "bin-ubuntu-x64",
            "cuda":   "bin-ubuntu-x64-cuda-cu12.4",
            "exe":    "llama-server",
        }


def _find_asset(assets: list, pattern: str) -> dict | None:
    """Return the first release asset whose name contains pattern and ends with .zip."""
    for asset in assets:
        name = asset.get("name", "")
        if pattern in name and name.endswith(".zip"):
            return asset
    return None
```

**Step 4: Run tests to verify they pass**
```bash
pytest tests/test_downloader.py -v
# Expected: 6 passed (or 5 if not on macOS — the macOS test skips)
```

**Step 5: Commit**
```bash
git add ct1/server/downloader.py tests/test_downloader.py
git commit -m "feat: downloader — platform detection and asset filtering (TDD)"
```

---

### Task 3: `downloader.py` — download + extraction

**Files:**
- Modify: `ct1/server/downloader.py`

**Step 1: Add `_download_file`, `_extract_zip`, and `download_llama_server` to `ct1/server/downloader.py`**

Append these functions to the file (after `_find_asset`):

```python
def _download_file(url: str, dest: Path, label: str) -> None:
    """Download url to dest, printing a progress line."""
    import urllib.request

    def _progress(block_num: int, block_size: int, total_size: int) -> None:
        if total_size > 0:
            pct = min(100, block_num * block_size * 100 // total_size)
            print(f"\r[download] {label} {pct}%...", end="", flush=True)

    urllib.request.urlretrieve(url, dest, reporthook=_progress)
    print(f"\r[download] {label} done           ")


def _extract_zip(zip_path: Path, dest_dir: Path) -> None:
    """Extract zip into dest_dir, stripping the top-level directory."""
    import zipfile

    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            parts = Path(member.filename).parts
            if len(parts) > 1:
                target = dest_dir / Path(*parts[1:])
            else:
                target = dest_dir / parts[0]
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    dst.write(src.read())
    zip_path.unlink()


def download_llama_server(project_root: Path) -> None:
    """Download both llama-server backends from the latest llama.cpp GitHub release.

    Extracts into:
      <project_root>/bin/vulkan/
      <project_root>/bin/cuda/    (skipped on macOS)

    Skips any backend whose executable already exists.
    """
    import urllib.request
    import json
    import stat

    print("[download] Fetching latest llama.cpp release info from GitHub...")
    req = urllib.request.Request(
        "https://api.github.com/repos/ggerganov/llama.cpp/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "ct2-downloader"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        release = json.loads(resp.read())

    assets = release.get("assets", [])
    tag = release.get("tag_name", "unknown")
    print(f"[download] Latest release: {tag} ({len(assets)} assets)")

    platform = _get_platform_info()
    bin_dir = project_root / "bin"
    backends = ["vulkan"]
    if platform["cuda"] is not None:
        backends.append("cuda")

    for backend in backends:
        pattern = platform[backend]
        dest_dir = bin_dir / backend
        exe = dest_dir / platform["exe"]

        if exe.exists():
            print(f"[download] {backend}: already installed at {exe}, skipping")
            continue

        asset = _find_asset(assets, pattern)
        if asset is None:
            print(f"[download] WARNING: no {backend} asset found (pattern: '{pattern}')")
            continue

        zip_path = bin_dir / asset["name"]
        bin_dir.mkdir(parents=True, exist_ok=True)

        _download_file(asset["browser_download_url"], zip_path, f"llama-server ({backend})")
        print(f"[download] Extracting {backend}...")
        _extract_zip(zip_path, dest_dir)

        # Make executable on Unix
        if os.name != "nt" and exe.exists():
            exe.chmod(exe.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        print(f"[download] {backend} installed → bin/{backend}/")
```

**Step 2: Run existing tests to confirm nothing broke**
```bash
pytest tests/test_downloader.py -v
# Expected: all still pass
```

**Step 3: Commit**
```bash
git add ct1/server/downloader.py
git commit -m "feat: downloader — download + extraction with terminal progress"
```

---

### Task 4: `launcher.py` — extend `_find_llama_executable` + hook downloader

**Files:**
- Modify: `ct1/server/launcher.py:11-44` (`_find_llama_executable`)
- Modify: `ct1/server/launcher.py:196` (`resolve_config` — pass `backend`)

**Step 1: Replace `_find_llama_executable` (lines 11–44) with the new version**

```python
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
    print(f"[launcher] llama-server not found — downloading automatically...")
    from ct1.server.downloader import download_llama_server
    download_llama_server(project_root)

    if bin_path.exists():
        return str(bin_path)

    raise FileNotFoundError(
        "llama-server executable not found and auto-download failed.\n"
        f"  • Add llama-server{ext} to your PATH, or\n"
        "  • Place a llama-*-bin-* directory next to this project, or\n"
        "  • Set 'executable' in ct1/server/model_config.yaml to its full path."
    )
```

**Step 2: In `resolve_config`, pass `backend` to `_find_llama_executable`**

Find this line (around line 196):
```python
executable = _find_llama_executable(project_root, raw_cfg.get("executable", "auto"))
```

Replace with:
```python
backend = raw_cfg.get("backend", "vulkan")
executable = _find_llama_executable(project_root, raw_cfg.get("executable", "auto"), backend=backend)
```

**Step 3: Verify imports at top of `launcher.py` — no new imports needed** (downloader is imported lazily inside the function)

**Step 4: Run existing tests**
```bash
pytest tests/ -v
# Expected: all pass
```

**Step 5: Commit**
```bash
git add ct1/server/launcher.py
git commit -m "feat: launcher — check bin/{backend}/, auto-download on missing llama-server"
```

---

### Task 5: `api.py` — `POST /api/backend/select` endpoint

**Files:**
- Modify: `ct1/server/api.py`

**Step 1: Add `BackendSelect` model and endpoint after the existing `ModelSelect` block (around line 244)**

Find the end of the `select_model` function. After it, add:

```python
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
```

**Step 2: Also expose `backend` in `GET /api/config`**

Find the `get_config` function. Add `"backend"` to its return dict:
```python
"backend": _raw_cfg.get("backend", "vulkan"),
```

**Step 3: Run tests**
```bash
pytest tests/ -v
# Expected: all pass
```

**Step 4: Commit**
```bash
git add ct1/server/api.py
git commit -m "feat: api — POST /api/backend/select endpoint, expose backend in /api/config"
```

---

### Task 6: Settings UI — backend dropdown

**Files:**
- Modify: `ct1/web/src/routes/settings/+page.svelte`

**Step 1: Add backend state variables** after the existing `let switching` state block (around line 24):

```typescript
/* ── Backend state ── */
let activeBackend = $state<'vulkan' | 'cuda'>('vulkan');
let switchingBackend = $state(false);
let backendError = $state('');
const isMac = $derived(
    typeof navigator !== 'undefined' && navigator.platform.toLowerCase().includes('mac')
);
```

**Step 2: Load backend in `loadData()`**

In the `loadData` function, after `config = await configRes.json();`, add:
```typescript
activeBackend = (config.backend as 'vulkan' | 'cuda') ?? 'vulkan';
```

**Step 3: Add `switchBackend` function** after `selectModel`:

```typescript
async function switchBackend(backend: 'vulkan' | 'cuda') {
    if (backend === activeBackend) return;
    switchingBackend = true;
    backendError = '';
    try {
        const res = await fetch('/api/backend/select', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ backend }),
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        activeBackend = backend;
        await loadData();
    } catch (e: any) {
        backendError = e.message || 'Failed to switch backend';
    } finally {
        switchingBackend = false;
    }
}
```

**Step 4: Add backend dropdown to the template**

In the HTML section, find the model selector block. Add the backend section **below** the model selector (before the context slider). Look for the section containing the `context_size` slider and add before it:

```svelte
{#if !isMac}
    <div class="setting-row">
        <label class="setting-label">Backend</label>
        <div class="backend-picker">
            <button
                class="backend-btn"
                class:active={activeBackend === 'vulkan'}
                onclick={() => switchBackend('vulkan')}
                disabled={switchingBackend}
            >Vulkan</button>
            <button
                class="backend-btn"
                class:active={activeBackend === 'cuda'}
                onclick={() => switchBackend('cuda')}
                disabled={switchingBackend}
            >CUDA</button>
        </div>
        {#if backendError}
            <p class="error-text">{backendError}</p>
        {/if}
        {#if switchingBackend}
            <p class="switching-text">Switching backend…</p>
        {/if}
    </div>
{/if}
```

**Step 5: Add styles** in the `<style>` section:

```css
.backend-picker {
    display: flex;
    gap: 0.5rem;
}
.backend-btn {
    padding: 0.35rem 0.9rem;
    border: 1px solid var(--border, #444);
    border-radius: 6px;
    background: transparent;
    color: inherit;
    cursor: pointer;
    font-size: 0.85rem;
    opacity: 0.6;
    transition: opacity 0.15s, border-color 0.15s;
}
.backend-btn.active {
    opacity: 1;
    border-color: var(--accent, #7c6af7);
}
.backend-btn:disabled { cursor: wait; opacity: 0.3; }
.switching-text { font-size: 0.8rem; opacity: 0.6; margin: 0.25rem 0 0; }
```

**Step 6: Commit**
```bash
git add ct1/web/src/routes/settings/+page.svelte
git commit -m "feat: settings — backend dropdown (Vulkan/CUDA), hidden on macOS"
```

---

### Task 7: README — update Quick Start

**Files:**
- Modify: `README.md`

**Step 1: Replace the "Get llama-server" step**

Find the `### 2. Get llama-server` section and replace it with:

```markdown
### 2. Get llama-server

CT-2 downloads `llama-server` automatically on first startup (both Vulkan and CUDA builds). You can switch between backends in the Settings UI.

If you prefer to manage it manually, download a [llama.cpp release](https://github.com/ggerganov/llama.cpp/releases) and place it in your PATH or next to the project directory.
```

**Step 2: Verify**
```bash
grep -A5 "Get llama-server" README.md
# Expected: shows the new auto-download text
```

**Step 3: Commit**
```bash
git add README.md
git commit -m "docs: README — auto-download llama-server on first startup"
```

---

### Task 8: Push to GitHub

**Step 1: Verify clean state**
```bash
git status
# Expected: clean working tree
git log --oneline -8
# Expected: all 7 commits visible
```

**Step 2: Push**
```bash
git push origin main
```
