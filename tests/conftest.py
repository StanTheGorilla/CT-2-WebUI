import os
import tempfile
from pathlib import Path
from uuid import uuid4


def _configure_local_temp() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tmp_root = repo_root / "_local" / "pytest-tmp"
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
