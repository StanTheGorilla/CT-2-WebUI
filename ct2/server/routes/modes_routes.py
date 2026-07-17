"""Mode and prompt management endpoints — self-contained (no api globals)."""
import os
import tempfile
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ct2.core.orchestrator import _get_mode_registry
from ct2.prompts.manager import _get_prompt_manager as _get_pm

router = APIRouter()

_MODES_DIR = Path(__file__).parent.parent.parent / "modes"
_BUILTIN_MODES: frozenset[str] = frozenset({"direct", "code", "design", "computer"})


class ModeUpdate(BaseModel):
    """Partial update for a mode definition.

    Note: `priority` and `route_id` are intentionally excluded — they can only
    be set at creation time. To change priority, delete and recreate the mode.
    """

    description: str | None = None
    patterns: list[str] | None = None
    negative_patterns: list[str] | None = None
    lang_patterns: list[str] | None = None
    detected_lang: str | None = None
    task_overrides: dict | None = None


class ModeCreate(BaseModel):
    name: str
    route_id: str
    description: str = ""
    priority: int = 99
    patterns: list[str] = Field(default_factory=list)
    negative_patterns: list[str] = Field(default_factory=list)
    lang_patterns: list[str] = Field(default_factory=list)
    detected_lang: str = "text"
    task_overrides: dict = Field(default_factory=dict)


class PromptUpdate(BaseModel):
    """Update a prompt's content. Content replaces the full prompt text."""
    content: str


def _mode_dict(m) -> dict:
    return {
        "name": m.name,
        "route_id": m.route_id,
        "description": m.description,
        "priority": m.priority,
        "patterns": m.patterns,
        "negative_patterns": m.negative_patterns,
        "lang_patterns": m.lang_patterns,
        "detected_lang": m.detected_lang,
        "task_overrides": m.task_overrides,
    }


def _write_mode_yaml(yaml_path: Path, data: dict) -> None:
    content = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(_MODES_DIR), suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, str(yaml_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


@router.get("/api/modes")
async def list_modes():
    """List all loaded mode definitions."""
    registry = _get_mode_registry()
    return {"modes": [_mode_dict(m) for m in registry.get_all()]}


@router.get("/api/modes/{name}")
async def get_mode(name: str):
    """Get a single mode definition by name."""
    registry = _get_mode_registry()
    for m in registry.get_all():
        if m.name == name:
            return _mode_dict(m)
    raise HTTPException(status_code=404, detail=f"Mode '{name}' not found")


@router.put("/api/modes/{name}")
async def update_mode(name: str, body: ModeUpdate):
    """Update an existing mode's config and persist to YAML. Reloads registry."""
    yaml_path = (_MODES_DIR / f"{name}.yaml").resolve()
    if yaml_path.parent != _MODES_DIR.resolve():
        raise HTTPException(status_code=400, detail="Invalid mode name")
    if not yaml_path.exists():
        raise HTTPException(status_code=404, detail=f"Mode file '{name}.yaml' not found")
    with yaml_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    # Apply only fields that were provided
    if body.description is not None:
        data["description"] = body.description
    if body.patterns is not None:
        data["patterns"] = body.patterns
    if body.negative_patterns is not None:
        data["negative_patterns"] = body.negative_patterns
    if body.lang_patterns is not None:
        data["lang_patterns"] = body.lang_patterns
    if body.detected_lang is not None:
        data["detected_lang"] = body.detected_lang
    if body.task_overrides is not None:
        data["task_overrides"] = body.task_overrides
    _write_mode_yaml(yaml_path, data)
    _get_mode_registry().reload()
    return {"ok": True, "name": name}


@router.post("/api/modes")
async def create_mode(body: ModeCreate):
    """Create a new mode definition YAML file. Reloads registry."""
    yaml_path = (_MODES_DIR / f"{body.name}.yaml").resolve()
    if yaml_path.parent != _MODES_DIR.resolve():
        raise HTTPException(status_code=400, detail="Invalid mode name")
    if yaml_path.exists():
        raise HTTPException(status_code=409, detail=f"Mode '{body.name}' already exists")
    data = {
        "name": body.name,
        "route_id": body.route_id,
        "description": body.description,
        "priority": body.priority,
        "patterns": body.patterns,
        "negative_patterns": body.negative_patterns,
        "lang_patterns": body.lang_patterns,
        "detected_lang": body.detected_lang,
        "task_overrides": body.task_overrides,
    }
    _write_mode_yaml(yaml_path, data)
    _get_mode_registry().reload()
    return {"ok": True, "name": body.name}


@router.delete("/api/modes/{name}")
async def delete_mode(name: str):
    """Delete a mode YAML file and reload the registry."""
    # Protect built-in modes from deletion
    if name in _BUILTIN_MODES:
        raise HTTPException(status_code=403, detail=f"Built-in mode '{name}' cannot be deleted")
    yaml_path = (_MODES_DIR / f"{name}.yaml").resolve()
    if yaml_path.parent != _MODES_DIR.resolve():
        raise HTTPException(status_code=400, detail="Invalid mode name")
    if not yaml_path.exists():
        raise HTTPException(status_code=404, detail=f"Mode '{name}' not found")
    yaml_path.unlink()
    _get_mode_registry().reload()
    return {"ok": True, "name": name}


@router.get("/api/prompts")
async def list_prompts():
    """List all loaded prompts with their content."""
    return {"prompts": _get_pm().list_all()}


@router.get("/api/prompts/{name}")
async def get_prompt(name: str):
    """Get a single prompt by name."""
    pm = _get_pm()
    all_prompts = pm.list_all()
    if name not in all_prompts:
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' not found")
    return {"name": name, "content": all_prompts[name]}


@router.put("/api/prompts/{name}")
async def update_prompt(name: str, body: PromptUpdate):
    """Update a prompt's content. Persists to disk and updates the in-memory cache."""
    pm = _get_pm()
    # Only allow updating existing prompts (no creating new ones via PUT)
    if name not in pm.list_all():
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' not found")
    try:
        pm.save(name, body.content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "name": name, "restart_required": True}


@router.post("/api/prompts/{name}/reset")
async def reset_prompt(name: str):
    """Reset a prompt to its shipped default content."""
    pm = _get_pm()
    try:
        content = pm.reset(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True, "name": name, "content": content, "restart_required": True}
