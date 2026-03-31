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
            "cuda":   None,
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
