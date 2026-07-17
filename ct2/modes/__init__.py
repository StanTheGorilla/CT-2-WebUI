from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ModeDefinition:
    name: str                    # e.g. "design", "code", "direct", "computer"
    route_id: str                # e.g. "ROUTE_DESIGN"
    description: str = ""        # human-readable description
    priority: int = 99           # lower = checked first (1=highest)
    patterns: list[str] = field(default_factory=list)           # regex patterns that trigger this mode
    negative_patterns: list[str] = field(default_factory=list)  # regex patterns that suppress this mode
    lang_patterns: list[str] = field(default_factory=list)      # language-name-only patterns (step-3 lang-before-design check)
    detected_lang: str = "text"  # default output lang hint ("html","python","multi","text")
    task_overrides: dict = field(default_factory=dict)  # temperature/top_p/presence_penalty overrides


def load_mode_from_dict(d: dict) -> ModeDefinition:
    """Construct a ModeDefinition from a plain dict (e.g. as loaded from YAML)."""
    return ModeDefinition(
        name=d["name"],
        route_id=d["route_id"],
        description=d.get("description", ""),
        priority=d.get("priority", 99),
        patterns=d.get("patterns", []),
        negative_patterns=d.get("negative_patterns", []),
        lang_patterns=d.get("lang_patterns", []),
        detected_lang=d.get("detected_lang", "text"),
        task_overrides=d.get("task_overrides", {}),
    )
