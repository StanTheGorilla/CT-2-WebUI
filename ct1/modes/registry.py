from __future__ import annotations

from pathlib import Path

from . import ModeDefinition


class ModeRegistry:
    """Registry of ModeDefinition objects loaded from YAML files.

    Full matching/loading logic is added in Task 16. This is the skeleton.
    """

    def __init__(self, modes_dir: str | Path | None = None) -> None:
        self._modes_dir: Path = Path(modes_dir) if modes_dir is not None else Path(__file__).parent
        self._modes: list[ModeDefinition] = []
        self._load()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load all *.yaml files from modes_dir into _modes."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, msg: str) -> ModeDefinition:
        """Return the best-matching ModeDefinition for *msg*."""
        raise NotImplementedError

    def get_all(self) -> list[ModeDefinition]:
        """Return every registered ModeDefinition."""
        raise NotImplementedError

    def reload(self) -> None:
        """Re-read all YAML files from disk and refresh the registry."""
        self._modes.clear()
        self._load()
