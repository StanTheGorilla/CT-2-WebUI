import pytest
from pathlib import Path
from uuid import uuid4


@pytest.mark.parametrize(
    ("model_name", "expected"),
    [
        ("Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf", True),
        ("llama-3.2-11b-vision-instruct-q4.gguf", True),
        ("MiniCPM-V-4_5-Q4_K_M.gguf", True),
        ("Qwen3.5-4B.Q4_K_S.gguf", False),
        ("Bonsai-8B.gguf", False),
    ],
)
def test_detect_vision_support_from_filename(model_name, expected):
    from ct1.server.launcher import _detect_vision_support

    assert _detect_vision_support(model_name) is expected


@pytest.mark.parametrize(
    ("model_name", "expected"),
    [
        ("gemma-4-E2B-it-Q5_K_M.gguf", True),
        ("Qwen3.5-4B.Q4_K_S.gguf", True),
        ("Bonsai-8B.gguf", False),
    ],
)
def test_detect_thinking_support_from_filename(model_name, expected):
    from ct1.server.launcher import _detect_thinking_support

    assert _detect_thinking_support(model_name) is expected


def test_detect_vision_support_from_architecture(monkeypatch):
    from ct1.server.launcher import _detect_vision_support

    monkeypatch.setattr("ct1.core.gguf_reader.read_architecture", lambda _path: "gemma4")

    assert _detect_vision_support("Gemma-4-E2B-It-Q5_K_M.gguf", "models/Gemma-4-E2B-It-Q5_K_M.gguf") is True


def test_find_mmproj_path_returns_only_candidate():
    from ct1.server.launcher import _find_mmproj_path

    base = Path("_local") / "test-mmproj-path" / uuid4().hex
    base.mkdir(parents=True, exist_ok=True)

    model_path = base / "gemma-4-E2B-it-Q5_K_M.gguf"
    model_path.write_text("", encoding="utf-8")
    mmproj_path = base / "mmproj-gemma-4-e2b-it-f16.gguf"
    mmproj_path.write_text("", encoding="utf-8")

    assert _find_mmproj_path(model_path) == str(mmproj_path)


def test_find_mmproj_path_rejects_wrong_model_size():
    from ct1.server.launcher import _find_mmproj_path

    base = Path("_local") / "test-mmproj-path" / uuid4().hex
    base.mkdir(parents=True, exist_ok=True)

    model_path = base / "gemma-4-E4B-it-Q4_K_S.gguf"
    model_path.write_text("", encoding="utf-8")
    mmproj_path = base / "mmproj-gemma-4-e2b-it-f16.gguf"
    mmproj_path.write_text("", encoding="utf-8")

    assert _find_mmproj_path(model_path) is None


def test_build_server_command_includes_mmproj_when_present():
    from ct1.server.launcher import build_server_command

    cmd = build_server_command({
        "executable": "llama-server",
        "model": "model.gguf",
        "port": 8080,
        "n_gpu_layers": 99,
        "parallel_slots": 1,
        "context_size": 32768,
        "mmproj": "mmproj.gguf",
    })

    assert "--mmproj" in cmd
    assert "mmproj.gguf" in cmd
