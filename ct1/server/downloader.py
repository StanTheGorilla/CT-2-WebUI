"""
llama-server auto-downloader.

Downloads Vulkan and CUDA builds from the latest llama.cpp GitHub release
into bin/vulkan/ and bin/cuda/ at the project root.
"""
import os
import sys
from pathlib import Path


def _get_platform_info() -> dict:
    """Return platform-specific asset name fragments and executable name.

    Asset naming in ggml-org/llama.cpp releases:
      Windows Vulkan : llama-b{N}-bin-win-vulkan-x64.zip
      Windows CUDA12 : cudart-llama-bin-win-cuda-12.4-x64.zip
      Linux Vulkan   : llama-b{N}-bin-ubuntu-vulkan-x64.tar.gz
      Linux CUDA12   : llama-b{N}-bin-ubuntu-x64-cuda-cu12.4.tar.gz
      macOS arm64    : llama-b{N}-bin-macos-arm64.tar.gz
    """
    if sys.platform == "win32":
        return {
            "vulkan":       "bin-win-vulkan-x64",
            # Main CUDA binary (contains llama-server.exe)
            "cuda":         "bin-win-cuda-cu12.4-x64",
            # Separate cudart DLL package — must be extracted to the same dir
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


def _find_asset(assets: list, pattern: str) -> dict | None:
    """Return the first release asset whose name contains pattern.

    Accepts both .zip and .tar.gz archives.
    """
    for asset in assets:
        name = asset.get("name", "")
        if pattern in name and (name.endswith(".zip") or name.endswith(".tar.gz")):
            return asset
    return None


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
        "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest",
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

        archive_path = bin_dir / asset["name"]
        bin_dir.mkdir(parents=True, exist_ok=True)

        _download_file(asset["browser_download_url"], archive_path, f"llama-server ({backend})")
        print(f"[download] Extracting {backend}...")
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
                _download_file(rt_asset["browser_download_url"], rt_archive, "CUDA runtime DLLs")
                print("[download] Extracting CUDA runtime DLLs...")
                _extract_zip(rt_archive, dest_dir)
            else:
                print(f"[download] WARNING: CUDA runtime DLLs not found (pattern: '{cuda_runtime_pattern}')")

        # Make executable on Unix
        if os.name != "nt" and exe.exists():
            exe.chmod(exe.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        print(f"[download] {backend} installed → bin/{backend}/")
