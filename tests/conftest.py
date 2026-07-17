import os
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest


def _configure_local_temp() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tmp_root = repo_root / "_local" / "tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)

    temp_path = str(tmp_root)
    for key in ("TMPDIR", "TEMP", "TMP"):
        os.environ[key] = temp_path

    tempfile.tempdir = temp_path


_configure_local_temp()

def _sandbox_safe_mkdtemp(suffix=None, prefix=None, dir=None):
    base_dir = Path(dir or tempfile.gettempdir())
    base_dir.mkdir(parents=True, exist_ok=True)

    temp_prefix = prefix if prefix is not None else tempfile.template
    temp_suffix = suffix if suffix is not None else ""

    while True:
        candidate = base_dir / f"{temp_prefix}{uuid4().hex}{temp_suffix}"
        try:
            candidate.mkdir()
            return str(candidate)
        except FileExistsError:
            continue


tempfile.mkdtemp = _sandbox_safe_mkdtemp


@pytest.fixture(autouse=True)
def _force_auth_off():
    """Tests must not depend on the auth mode in the user's live
    model_config.yaml — force mode=none and restore afterwards."""
    from ct1.server import api as api_mod
    from ct1.server.auth import AuthConfig

    prev = api_mod._auth_state.cfg
    api_mod._auth_state.replace(AuthConfig(mode="none"))
    yield
    api_mod._auth_state.replace(prev)
