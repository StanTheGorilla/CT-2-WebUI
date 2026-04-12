import sys
import pytest
from pathlib import Path
from uuid import uuid4


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


def test_find_asset_accepts_tar_gz():
    from ct1.server.downloader import _find_asset
    assets = [
        {"name": "llama-b9000-bin-ubuntu-vulkan-x64.tar.gz", "browser_download_url": "https://example.com/linux.tar.gz"},
    ]
    result = _find_asset(assets, "bin-ubuntu-vulkan-x64")
    assert result is not None
    assert result["name"] == "llama-b9000-bin-ubuntu-vulkan-x64.tar.gz"


def test_find_asset_ignores_unknown_extensions():
    from ct1.server.downloader import _find_asset
    assets = [
        {"name": "llama-b9000-bin-win-vulkan-x64.exe", "browser_download_url": "x"},
        {"name": "llama-b9000-SHA256SUMS", "browser_download_url": "x"},
    ]
    assert _find_asset(assets, "bin-win-vulkan-x64") is None


def test_get_platform_info_windows_cuda_pattern():
    from ct1.server.downloader import _get_platform_info
    if sys.platform != "win32":
        pytest.skip("Windows only")
    info = _get_platform_info()
    # Main CUDA binary (contains llama-server.exe)
    assert "bin-win-cuda-12.4-x64" == info["cuda"]
    # Separate cudart DLL package required alongside the binary
    assert "cudart-llama-bin-win-cuda-12.4-x64" == info["cuda_runtime"]
    # Exclusion prevents matching cudart-llama-bin-win-cuda-12.4-x64.zip instead of the binary
    assert info["cuda_exclude"] == "cudart"


def test_find_asset_exclude_skips_matching_names():
    from ct1.server.downloader import _find_asset
    # Both assets match the pattern — exclude should skip the cudart one
    assets = [
        {"name": "cudart-llama-bin-win-cuda-12.4-x64.zip", "browser_download_url": "https://example.com/cudart.zip"},
        {"name": "llama-b9000-bin-win-cuda-12.4-x64.zip",  "browser_download_url": "https://example.com/cuda.zip"},
    ]
    result = _find_asset(assets, "bin-win-cuda-12.4-x64", exclude="cudart")
    assert result is not None
    assert result["name"] == "llama-b9000-bin-win-cuda-12.4-x64.zip"


def test_find_asset_exclude_none_returns_first_match():
    from ct1.server.downloader import _find_asset
    assets = [
        {"name": "cudart-llama-bin-win-cuda-12.4-x64.zip", "browser_download_url": "x"},
        {"name": "llama-b9000-bin-win-cuda-12.4-x64.zip",  "browser_download_url": "y"},
    ]
    # Without exclude, returns first match (the cudart one)
    result = _find_asset(assets, "bin-win-cuda-12.4-x64")
    assert result["name"] == "cudart-llama-bin-win-cuda-12.4-x64.zip"


def test_strip_quant_suffix_removes_trailing_quant_markers():
    from ct1.server.downloader import _strip_quant_suffix

    assert _strip_quant_suffix("gemma-4-E2B-it-Q5_K_M.gguf") == "gemma-4-E2B-it"
    assert _strip_quant_suffix("Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf") == "Qwen2.5-VL-7B-Instruct"
    assert _strip_quant_suffix("llama-3.2-11b-vision-instruct-q4.gguf") == "llama-3.2-11b-vision-instruct"


def test_find_hf_repo_for_mmproj_prefers_exact_repo(monkeypatch):
    from ct1.server.downloader import _find_hf_repo_for_mmproj

    def fake_fetch(url: str, timeout: float = 10.0):
        assert "api/models?" in url
        return [
            {"id": "ggml-org/gemma-4-E2B-it-GGUF-old"},
            {"id": "ggml-org/gemma-4-E2B-it-GGUF"},
        ]

    monkeypatch.setattr("ct1.server.downloader._fetch_json", fake_fetch)

    repo_id = _find_hf_repo_for_mmproj("models/gemma-4-E2B-it-Q5_K_M.gguf")

    assert repo_id == "ggml-org/gemma-4-E2B-it-GGUF"


def test_resolve_mmproj_download_returns_resolve_url(monkeypatch):
    from ct1.server.downloader import resolve_mmproj_download

    calls = []

    def fake_fetch(url: str, timeout: float = 10.0):
        calls.append(url)
        if "api/models?" in url:
            return [{"id": "ggml-org/gemma-4-E2B-it-GGUF"}]
        return {
            "siblings": [
                {"rfilename": "README.md"},
                {"rfilename": "mmproj-gemma-4-e2b-it-f16.gguf"},
            ]
        }

    monkeypatch.setattr("ct1.server.downloader._fetch_json", fake_fetch)

    resolved = resolve_mmproj_download("models/gemma-4-E2B-it-Q5_K_M.gguf")

    assert resolved == (
        "https://huggingface.co/ggml-org/gemma-4-E2B-it-GGUF/resolve/main/mmproj-gemma-4-e2b-it-f16.gguf?download=true",
        "mmproj-gemma-4-e2b-it-f16.gguf",
    )
    assert len(calls) == 2


def test_ensure_mmproj_downloaded_writes_missing_file(monkeypatch):
    from ct1.server.downloader import ensure_mmproj_downloaded

    base = Path("_local") / "test-mmproj-download" / uuid4().hex
    base.mkdir(parents=True, exist_ok=True)
    model_path = base / "gemma-4-E2B-it-Q5_K_M.gguf"
    model_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "ct1.server.downloader.resolve_mmproj_download",
        lambda _model_path: (
            "https://example.com/mmproj.gguf",
            "mmproj-gemma-4-e2b-it-f16.gguf",
        ),
    )

    def fake_download(url: str, dest: Path, label: str) -> None:
        assert url == "https://example.com/mmproj.gguf"
        assert "mmproj" in label
        dest.write_text("stub", encoding="utf-8")

    monkeypatch.setattr("ct1.server.downloader._download_file", fake_download)

    mmproj_path = ensure_mmproj_downloaded(model_path)

    assert mmproj_path == str(base / "mmproj-gemma-4-e2b-it-f16.gguf")
    assert (base / "mmproj-gemma-4-e2b-it-f16.gguf").exists()
