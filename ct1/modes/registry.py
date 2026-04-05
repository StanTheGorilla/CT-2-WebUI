from __future__ import annotations

import re
import yaml
from pathlib import Path

from . import ModeDefinition, load_mode_from_dict


# Canonical mode names — these must match the 'name' field in the corresponding YAML files.
# The routing algorithm in resolve() references these by name directly.
_COMPUTER_MODE = "computer"
_DESIGN_MODE = "design"
_CODE_MODE = "code"
_DIRECT_MODE = "direct"


class ModeRegistry:
    """Registry of ModeDefinition objects loaded from YAML files.

    Implements the same routing algorithm as the original
    ``_deterministic_route()`` in ``ct1/core/orchestrator.py``, but sources
    all patterns from YAML files instead of hard-coded regex literals.
    """

    # These stay in Python — not worth putting in YAML
    _QUESTION_STARTS = (
        "what is", "what are", "what does", "what was", "what do",
        "explain", "describe", "tell me", "can you explain",
        "could you explain", "how does", "how do", "how is",
        "how can i", "how would", "how to",
        "why is", "why does", "why do", "why are",
        "who is", "who are", "where is", "where are",
        "when is", "when does", "what's", "where's",
        "is there", "is this", "is it", "are there", "are these",
        "does this", "does it", "do they", "do these",
        "which", "summarize", "summary", "show me",
    )
    _DIRECT_SIGNALS = {
        "analyze", "analyse", "analyzing", "analysis",
        "evaluate", "evaluating", "evaluation",
        "advising", "advise", "advice",
        "recommend", "assess", "assessing",
        "compare", "contrast", "discuss",
        "maximize", "minimize", "optimize",
        "probability", "trade-off", "tradeoff",
        "pros and cons", "constraint",
        "scenario", "decompos",
        "think through", "reason about",
        "what would", "how would you", "what should",
        "advantages", "disadvantages",
        "calculate", "solve", "prove", "derive",
    }
    _BUILD_PHRASES = {
        "build", "create", "make me", "make a", "make an",
        "generate a", "generate an", "generate me",
        "write me", "write a", "write an",
        "code a", "code me", "implement a", "implement an",
        "develop a", "develop an", "scaffold",
        "build me", "create me", "give me a", "give me an",
        "set up a", "set up an",
    }
    _CODE_FENCE = re.compile(r'```\w*\n')

    def __init__(self, modes_dir: str | Path | None = None) -> None:
        self._modes_dir: Path = (
            Path(modes_dir) if modes_dir is not None else Path(__file__).parent
        )
        self._modes: list[ModeDefinition] = []
        # Compiled pattern cache: name → (compiled_patterns, compiled_negatives, compiled_lang)
        self._compiled: dict[str, tuple] = {}
        self._load()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load all *.yaml files from modes_dir, compile regex patterns."""
        loaded: list[ModeDefinition] = []
        for yaml_file in self._modes_dir.glob("*.yaml"):
            try:
                with yaml_file.open(encoding="utf-8") as f:
                    data = yaml.safe_load(f)
            except Exception as e:
                print(f"[modes] WARNING: failed to load {yaml_file.name}: {e}")
                continue
            if not isinstance(data, dict) or "name" not in data or "route_id" not in data:
                continue
            mode = load_mode_from_dict(data)
            loaded.append(mode)
        # Sort by priority ascending (lowest number = highest priority)
        loaded.sort(key=lambda m: m.priority)
        self._modes = loaded
        # Compile patterns for each mode
        self._compiled.clear()
        for mode in self._modes:
            pat = (
                re.compile("|".join(mode.patterns), re.IGNORECASE)
                if mode.patterns
                else None
            )
            neg = (
                re.compile("|".join(mode.negative_patterns), re.IGNORECASE)
                if mode.negative_patterns
                else None
            )
            lang = (
                re.compile("|".join(mode.lang_patterns), re.IGNORECASE)
                if mode.lang_patterns
                else None
            )
            self._compiled[mode.name] = (pat, neg, lang)

    def _is_question(self, msg: str) -> bool:
        lower = msg.lower().strip()
        if lower.startswith(self._QUESTION_STARTS):
            return True
        return lower.endswith("?")

    def _matches(self, name: str, msg: str) -> bool:
        """True if *name* mode's patterns match and negative_patterns don't."""
        pat, neg, _ = self._compiled.get(name, (None, None, None))
        if pat is None:
            return False
        if not pat.search(msg):
            return False
        if neg and neg.search(msg):
            return False
        return True

    def _lang_matches(self, msg: str) -> bool:
        """True if the code mode's lang_patterns match *msg*."""
        _, _, lang = self._compiled.get(_CODE_MODE, (None, None, None))
        return bool(lang and lang.search(msg))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, msg: str) -> ModeDefinition:
        """Return the best-matching ModeDefinition for *msg*.

        Replicates the original ``_deterministic_route()`` algorithm exactly,
        but sources all patterns from the loaded YAML modes.
        """
        lower = msg.lower().strip()

        # 1. Questions → DIRECT (exception: code fence → CODE)
        if self._is_question(msg):
            if self._CODE_FENCE.search(msg):
                return self._get(_CODE_MODE)
            return self._get(_DIRECT_MODE)

        # 2. Computer (file operations, project creation)
        if self._matches(_COMPUTER_MODE, msg):
            return self._get(_COMPUTER_MODE)

        # 3. Language name anywhere, but not in design context → CODE
        design_pat, _, _ = self._compiled.get(_DESIGN_MODE, (None, None, None))
        if self._lang_matches(msg) and not (design_pat and design_pat.search(msg)):
            return self._get(_CODE_MODE)

        # 4. Design patterns (unless suppressed by negative)
        if self._matches(_DESIGN_MODE, msg):
            return self._get(_DESIGN_MODE)

        # 5. Code patterns or code fence
        code_pat, _, _ = self._compiled.get(_CODE_MODE, (None, None, None))
        if (code_pat and code_pat.search(msg)) or self._CODE_FENCE.search(msg):
            return self._get(_CODE_MODE)

        # 6. Analysis / reasoning signals → DIRECT
        if any(kw in lower for kw in self._DIRECT_SIGNALS):
            return self._get(_DIRECT_MODE)

        # 7. Build phrases → DESIGN
        if any(phrase in lower for phrase in self._BUILD_PHRASES):
            return self._get(_DESIGN_MODE)

        # 8. Long text → DIRECT
        if len(msg) > 300:
            return self._get(_DIRECT_MODE)

        # 9. Default fallback
        return self._get(_DIRECT_MODE)

    def _get(self, name: str) -> ModeDefinition:
        """Get a loaded mode by name. Falls back to 'direct' if not found."""
        for m in self._modes:
            if m.name == name:
                return m
        # Graceful fallback: unknown mode name → direct
        for m in self._modes:
            if m.name == _DIRECT_MODE:
                print(f"[modes] WARNING: mode '{name}' not found, falling back to '{_DIRECT_MODE}'")
                return m
        raise KeyError(f"Mode '{name}' not found and no '{_DIRECT_MODE}' fallback available")

    def get_all(self) -> list[ModeDefinition]:
        """Return every registered ModeDefinition."""
        return list(self._modes)

    def reload(self) -> None:
        """Re-read all YAML files from disk and refresh the registry."""
        self._load()
