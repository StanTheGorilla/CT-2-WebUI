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
    from ct2.server.launcher import _detect_vision_support

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
    from ct2.server.launcher import _detect_thinking_support

    assert _detect_thinking_support(model_name) is expected


def test_detect_vision_support_from_architecture(monkeypatch):
    from ct2.server.launcher import _detect_vision_support

    monkeypatch.setattr("ct2.core.gguf_reader.read_architecture", lambda _path: "gemma4")

    assert _detect_vision_support("Gemma-4-E2B-It-Q5_K_M.gguf", "models/Gemma-4-E2B-It-Q5_K_M.gguf") is True


def test_find_mmproj_path_returns_only_candidate():
    from ct2.server.launcher import _find_mmproj_path

    base = Path("_local") / "test-mmproj-path" / uuid4().hex
    base.mkdir(parents=True, exist_ok=True)

    model_path = base / "gemma-4-E2B-it-Q5_K_M.gguf"
    model_path.write_text("", encoding="utf-8")
    mmproj_path = base / "mmproj-gemma-4-e2b-it-f16.gguf"
    mmproj_path.write_text("", encoding="utf-8")

    assert _find_mmproj_path(model_path) == str(mmproj_path)


def test_find_mmproj_path_rejects_wrong_model_size():
    from ct2.server.launcher import _find_mmproj_path

    base = Path("_local") / "test-mmproj-path" / uuid4().hex
    base.mkdir(parents=True, exist_ok=True)

    model_path = base / "gemma-4-E4B-it-Q4_K_S.gguf"
    model_path.write_text("", encoding="utf-8")
    mmproj_path = base / "mmproj-gemma-4-e2b-it-f16.gguf"
    mmproj_path.write_text("", encoding="utf-8")

    assert _find_mmproj_path(model_path) is None


def test_ensure_mmproj_path_uses_auto_download_when_missing(monkeypatch):
    from ct2.server.launcher import _ensure_mmproj_path

    monkeypatch.setattr("ct2.server.launcher._find_mmproj_path", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "ct2.server.downloader.ensure_mmproj_downloaded",
        lambda _model_path: "models/mmproj-gemma-4-e2b-it-f16.gguf",
    )

    resolved = _ensure_mmproj_path("models/gemma-4-E2B-it-Q5_K_M.gguf")

    assert resolved == "models/mmproj-gemma-4-e2b-it-f16.gguf"


def test_build_server_command_includes_mmproj_when_present():
    from ct2.server.launcher import build_server_command

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


def test_resolve_config_marks_vision_ready_after_auto_download(monkeypatch):
    from ct2.server.launcher import resolve_config

    base = Path("_local") / "test-resolve-mmproj" / uuid4().hex
    models_dir = base / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    model_path = models_dir / "gemma-4-E2B-it-Q5_K_M.gguf"
    model_path.write_text("", encoding="utf-8")

    monkeypatch.setattr("ct2.server.launcher._find_llama_executable", lambda *_args, **_kwargs: "llama-server")
    monkeypatch.setattr("ct2.server.launcher._detect_vision_support", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("ct2.server.launcher._ensure_mmproj_path", lambda *_args, **_kwargs: str(models_dir / "mmproj-gemma-4-e2b-it-f16.gguf"))
    monkeypatch.setattr("ct2.core.gguf_reader.read_context_length", lambda _path: 32768)

    cfg = resolve_config({
        "models_dir": str(models_dir),
        "active_model": model_path.name,
    }, config_path=str(base / "ct2" / "server" / "model_config.yaml"))

    assert cfg["models"]["director"]["vision_supported"] is True
    assert cfg["llama_server"]["mmproj"].endswith("mmproj-gemma-4-e2b-it-f16.gguf")
