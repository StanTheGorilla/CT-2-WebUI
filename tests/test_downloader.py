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
