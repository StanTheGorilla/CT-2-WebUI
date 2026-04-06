from __future__ import annotations
import os
import tempfile
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent  # ct1/prompts/


class PromptManager:
    """Loads all *.txt prompt files from the prompts directory.

    Supports hot-reload (reload()) and atomic saves (save()).
    Missing prompt names return "" with a console warning.
    """

    def __init__(self, prompts_dir: str | Path | None = None) -> None:
        self._dir: Path = Path(prompts_dir) if prompts_dir is not None else _PROMPTS_DIR
        self._prompts: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        """Read all *.txt files from prompts_dir into memory."""
        loaded: dict[str, str] = {}
        for txt_file in self._dir.glob("*.txt"):
            try:
                content = txt_file.read_text(encoding="utf-8")
                loaded[txt_file.stem] = content  # stem = filename without .txt
            except Exception as e:
                print(f"[prompts] WARNING: failed to load {txt_file.name}: {e}")
        self._prompts = loaded

    def get(self, name: str) -> str:
        """Return prompt content by name (filename without .txt extension).
        Returns empty string with a warning if the name is not found.
        """
        if name not in self._prompts:
            print(f"[prompts] WARNING: prompt '{name}' not found — returning empty string")
            return ""
        return self._prompts[name]

    def list_all(self) -> dict[str, str]:
        """Return a copy of all loaded prompts as {name: content}."""
        return dict(self._prompts)

    def save(self, name: str, content: str) -> None:
        """Atomically write prompt content to disk and update in-memory cache.

        Uses tempfile + os.replace for atomic write (no partial-write corruption).
        Creates the file if it doesn't exist.
        """
        if not name or "/" in name or "\\" in name or name.endswith(".txt"):
            raise ValueError(f"Invalid prompt name: {name!r}")
        target = self._dir / f"{name}.txt"
        # Path traversal guard
        if target.resolve().parent != self._dir.resolve():
            raise ValueError(f"Invalid prompt name: {name!r}")
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(self._dir), suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, str(target))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        self._prompts[name] = content

    def get_default(self, name: str) -> str | None:
        """Return the shipped default content for a prompt, or None if no default exists."""
        default_file = self._dir / "defaults" / f"{name}.txt"
        if not default_file.exists():
            return None
        try:
            return default_file.read_text(encoding="utf-8")
        except Exception as e:
            print(f"[prompts] WARNING: failed to read default for '{name}': {e}")
            return None

    def reset(self, name: str) -> str:
        """Reset a prompt to its shipped default. Returns the restored content.

        Raises ValueError if no default exists for the given name.
        """
        default = self.get_default(name)
        if default is None:
            raise ValueError(f"No default exists for prompt '{name}'")
        self.save(name, default)
        return default

    def reload(self) -> None:
        """Re-read all *.txt files from disk."""
        self._load()


# ── Module-level singleton ──────────────────────────────────────────
_prompt_manager: PromptManager | None = None


def _get_prompt_manager() -> PromptManager:
    """Lazy-load the prompt manager singleton."""
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager
