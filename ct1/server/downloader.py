"""
llama-server auto-downloader.

Downloads Vulkan and CUDA builds from the latest llama.cpp GitHub release
into bin/vulkan/ and bin/cuda/ at the project root.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path


def _get_platform_info() -> dict:
    """Return platform-specific asset name fragments and executable name.

    Asset naming in ggml-org/llama.cpp releases:
      Windows Vulkan : llama-b{N}-bin-win-vulkan-x64.zip
      Windows CUDA12 : llama-b{N}-bin-win-cuda-12.4-x64.zip  (main binary)
                       cudart-llama-bin-win-cuda-12.4-x64.zip (DLLs, also needed)
      Linux Vulkan   : llama-b{N}-bin-ubuntu-vulkan-x64.tar.gz
      macOS arm64    : llama-b{N}-bin-macos-arm64.tar.gz
    """
    if sys.platform == "win32":
        return {
            "vulkan":       "bin-win-vulkan-x64",
            # Main CUDA binary (contains llama-server.exe).
            # "cudart" must be excluded because cudart-llama-bin-win-cuda-12.4-x64.zip
            # also contains the pattern but has only DLLs, no exe.
            "cuda":         "bin-win-cuda-12.4-x64",
            "cuda_exclude": "cudart",
            # Separate cudart DLL package — extracted into the same bin/cuda/ dir
            "cuda_runtime": "cudart-llama-bin-win-cuda-12.4-x64",
            "exe":          "llama-server.exe",
        }
    elif sys.platform == "darwin":
        import platform
        arch = "arm64" if platform.machine() == "arm64" else "x64"
        return {
            "vulkan": f"bin-macos-{arch}",
            "cuda":   None,            # Metal is built into the macOS binary
            "exe":    "llama-server",
        }
    else:  # Linux
        return {
            "vulkan": "bin-ubuntu-vulkan-x64",
            "cuda":   "bin-ubuntu-x64-cuda-cu12.4",
            "exe":    "llama-server",
        }


def _find_asset(assets: list, pattern: str, exclude: str = "") -> dict | None:
    """Return the first release asset whose name contains pattern.

    Accepts both .zip and .tar.gz archives.
    If exclude is given, skip any asset whose name contains that string.
    """
    for asset in assets:
        name = asset.get("name", "")
        if exclude and exclude in name:
            continue
        if pattern in name and (name.endswith(".zip") or name.endswith(".tar.gz")):
            return asset
    return None


def _download_file(url: str, dest: Path, label: str) -> None:
    """Download url to dest, printing a progress line."""
    def _progress(block_num: int, block_size: int, total_size: int) -> None:
        if total_size > 0:
            pct = min(100, block_num * block_size * 100 // total_size)
            print(f"\r[download] {label} {pct}%...", end="", flush=True)

    urllib.request.urlretrieve(url, dest, reporthook=_progress)
    print(f"\r[download] {label} done           ")


_MMPROJ_TOKEN_DROP = {
    "gguf", "mmproj", "q4", "q5", "q6", "q8", "iq4", "iq5",
    "k", "m", "s", "l", "it", "bf16", "f16", "f32", "fp16", "fp32",
}
_QUANT_SUFFIX_RE = re.compile(
    r"(?i)(?:[-_.](?:i?q\d+(?:_[a-z0-9]+)*|bf16|f16|f32|fp16|fp32))+$"
)


def _strip_quant_suffix(model_filename: str) -> str:
    """Return a model stem without trailing quantization markers."""
    stem = Path(model_filename).stem
    stripped = _QUANT_SUFFIX_RE.sub("", stem)
    return stripped or stem


def _tokenize_model_name(value: str) -> set[str]:
    return {
        token for token in re.split(r"[^a-z0-9]+", value.lower())
        if token and token not in _MMPROJ_TOKEN_DROP
    }


def _normalize_repo_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _fetch_json(url: str, timeout: float = 10.0):
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "ct2-downloader",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _find_hf_repo_for_mmproj(model_path: str | Path) -> str | None:
    """Find a likely upstream GGUF repo for the selected model."""
    model_path = Path(model_path)
    base_name = _strip_quant_suffix(model_path.name)
    expected = _normalize_repo_name(f"{base_name}-GGUF")
    query = urllib.parse.urlencode({
        "author": "ggml-org",
        "search": base_name,
        "limit": 10,
        "full": "false",
    })
    results = _fetch_json(f"https://huggingface.co/api/models?{query}")
    if not isinstance(results, list):
        return None

    ranked: list[tuple[int, str]] = []
    for item in results:
        repo_id = item.get("id", "")
        repo_name = repo_id.split("/", 1)[-1]
        normalized = _normalize_repo_name(repo_name)
        score = 0
        if normalized == expected:
            score += 100
        if normalized.endswith(expected):
            score += 25
        score += len(
            _tokenize_model_name(normalized) &
            _tokenize_model_name(expected)
        )
        if score > 0:
            ranked.append((score, repo_id))

    if not ranked:
        return None

    ranked.sort(reverse=True)
    return ranked[0][1]


def _select_mmproj_filename(model_path: str | Path, siblings: list[dict]) -> str | None:
    """Pick the best matching mmproj filename from a Hugging Face siblings list."""
    model_path = Path(model_path)
    model_tokens = _tokenize_model_name(model_path.stem)
    size_tokens = {
        token for token in model_tokens
        if re.fullmatch(r"(?:[ea]\d+b|\d+b|\d+_\d+)", token)
    }

    ranked: list[tuple[int, int, int, str]] = []
    for sibling in siblings:
        name = sibling.get("rfilename") or sibling.get("path") or sibling.get("name")
        if not name:
            continue
        lower_name = name.lower()
        if "mmproj" not in lower_name or not lower_name.endswith(".gguf"):
            continue

        tokens = _tokenize_model_name(Path(name).stem)
        if size_tokens and not (size_tokens & tokens):
            continue

        overlap = len(model_tokens & tokens)
        prefers_f16 = 1 if "f16" in lower_name else 0
        ranked.append((overlap, prefers_f16, -len(name), name))

    if not ranked:
        return None

    ranked.sort(reverse=True)
    return ranked[0][3] if ranked[0][0] > 0 else None


def resolve_mmproj_download(model_path: str | Path) -> tuple[str, str] | None:
    """Resolve a downloadable mmproj URL for a model, when upstream data is known."""
    repo_id = _find_hf_repo_for_mmproj(model_path)
    if not repo_id:
        return None

    repo_url = "https://huggingface.co/api/models/" + urllib.parse.quote(repo_id, safe="/")
    repo_data = _fetch_json(repo_url)
    siblings = repo_data.get("siblings", []) if isinstance(repo_data, dict) else []
    filename = _select_mmproj_filename(model_path, siblings)
    if not filename:
        return None

    download_url = (
        "https://huggingface.co/"
        f"{repo_id}/resolve/main/{urllib.parse.quote(filename)}?download=true"
    )
    return download_url, Path(filename).name


def ensure_mmproj_downloaded(model_path: str | Path, progress_cb=None) -> str | None:
    """Download a missing mmproj sidecar into the model directory when possible."""
    model_path = Path(model_path)
    resolved = resolve_mmproj_download(model_path)
    if not resolved:
        return None

    url, filename = resolved
    dest = model_path.parent / filename
    if dest.exists():
        return str(dest)

    def _log(msg: str) -> None:
        print(msg)
        if progress_cb:
            progress_cb(msg)

    _log(f"[download] mmproj: downloading {filename} for {model_path.name}...")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        _download_file(url, dest, f"mmproj ({filename})")
        _log(f"[download] mmproj: ready at {dest}")
    except Exception:
        if dest.exists():
            dest.unlink(missing_ok=True)
        raise

    return str(dest)


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


def _extract_tar(tar_path: Path, dest_dir: Path) -> None:
    """Extract .tar.gz into dest_dir, stripping the top-level directory."""
    import tarfile

    dest_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "r:gz") as tf:
        for member in tf.getmembers():
            parts = Path(member.name).parts
            if len(parts) <= 1:
                continue  # skip top-level directory entry itself
            target = dest_dir / Path(*parts[1:])
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with tf.extractfile(member) as src, open(target, "wb") as dst:
                    dst.write(src.read())
    tar_path.unlink()


def download_llama_server(
    project_root: Path,
    backends: list[str] | None = None,
    force: bool = False,
    progress_cb=None,
) -> None:
    """Download llama-server backends from the latest llama.cpp GitHub release.

    Args:
        project_root: Project root directory.
        backends: List of backends to download, e.g. ['vulkan'] or ['cuda'].
                  Defaults to all available backends for the current platform.
        force: If True, re-download even if the executable already exists.
        progress_cb: Optional callable(message: str) for progress reporting.

    Extracts into:
      <project_root>/bin/vulkan/
      <project_root>/bin/cuda/    (skipped on macOS)
    """
    import urllib.request
    import json
    import stat

    def _log(msg: str):
        print(msg)
        if progress_cb:
            progress_cb(msg)

    _log("[download] Fetching latest llama.cpp release info from GitHub...")
    req = urllib.request.Request(
        "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "ct2-downloader"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        release = json.loads(resp.read())

    assets = release.get("assets", [])
    tag = release.get("tag_name", "unknown")
    _log(f"[download] Latest release: {tag} ({len(assets)} assets)")

    platform = _get_platform_info()
    bin_dir = project_root / "bin"
    all_backends = ["vulkan"]
    if platform["cuda"] is not None:
        all_backends.append("cuda")

    selected = [b for b in (backends or all_backends) if b in all_backends]

    for backend in selected:
        pattern = platform[backend]
        dest_dir = bin_dir / backend
        exe = dest_dir / platform["exe"]

        if exe.exists() and not force:
            _log(f"[download] {backend}: already installed at {exe}, skipping")
            continue

        if exe.exists() and force:
            _log(f"[download] {backend}: force-updating, removing old install...")
            import shutil
            shutil.rmtree(dest_dir, ignore_errors=True)

        # Some patterns match multiple assets (e.g. cuda matches cudart too) — exclude those
        exclude = platform.get(f"{backend}_exclude", "")
        asset = _find_asset(assets, pattern, exclude=exclude)
        if asset is None:
            _log(f"[download] WARNING: no {backend} asset found (pattern: '{pattern}')")
            continue

        archive_path = bin_dir / asset["name"]
        bin_dir.mkdir(parents=True, exist_ok=True)

        size_mb = asset.get("size", 0) // (1024 * 1024)
        _log(f"[download] Downloading {backend} ({size_mb} MB)...")
        _download_file(asset["browser_download_url"], archive_path, f"llama-server ({backend})")
        _log(f"[download] Extracting {backend}...")
        if asset["name"].endswith(".tar.gz"):
            _extract_tar(archive_path, dest_dir)
        else:
            _extract_zip(archive_path, dest_dir)

        # Windows CUDA also needs the cudart DLLs package in the same directory
        cuda_runtime_pattern = platform.get("cuda_runtime")
        if backend == "cuda" and cuda_runtime_pattern:
            rt_asset = _find_asset(assets, cuda_runtime_pattern)
            if rt_asset:
                rt_archive = bin_dir / rt_asset["name"]
                _log("[download] Downloading CUDA runtime DLLs...")
                _download_file(rt_asset["browser_download_url"], rt_archive, "CUDA runtime DLLs")
                _log("[download] Extracting CUDA runtime DLLs...")
                _extract_zip(rt_archive, dest_dir)
            else:
                _log(f"[download] WARNING: CUDA runtime DLLs not found (pattern: '{cuda_runtime_pattern}')")

        # Make executable on Unix
        if os.name != "nt" and exe.exists():
            exe.chmod(exe.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        _log(f"[download] {backend} installed → bin/{backend}/")
