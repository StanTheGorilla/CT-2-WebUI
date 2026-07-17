"""Workspace manager for Computer Mode.

Manages project directories where AI-generated files are saved.
All file operations are sandboxed within the workspace directory.
"""
import os
import uuid
import json
import asyncio
from pathlib import Path
from datetime import datetime, timezone


_DEFAULT_BASE = Path(__file__).parent.parent / "data" / "workspaces"


class WorkspaceManager:
    def __init__(self, base_dir: str | None = None):
        self.base = Path(base_dir) if base_dir else _DEFAULT_BASE
        self.base.mkdir(parents=True, exist_ok=True)

    def _resolve_safe(self, workspace_id: str, rel_path: str = "") -> Path:
        """Resolve a path within a workspace, blocking directory traversal."""
        ws_dir = (self.base / workspace_id).resolve()
        if not ws_dir.exists():
            raise FileNotFoundError(f"Workspace not found: {workspace_id}")
        if not rel_path:
            return ws_dir
        target = (ws_dir / rel_path).resolve()
        if not str(target).startswith(str(ws_dir)):
            raise PermissionError("Path escapes workspace directory")
        return target

    def create_workspace(self, name: str = "") -> dict:
        ws_id = str(uuid.uuid4())[:8]
        safe_name = "".join(c for c in name if c.isalnum() or c in " -_").strip()
        if safe_name:
            ws_id = f"{ws_id}-{safe_name[:30].replace(' ', '-').lower()}"
        ws_dir = self.base / ws_id
        ws_dir.mkdir(parents=True, exist_ok=True)
        # Write workspace metadata
        meta = {
            "id": ws_id,
            "name": name or ws_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        (ws_dir / ".workspace.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
        return meta

    def list_workspaces(self) -> list[dict]:
        results = []
        if not self.base.exists():
            return results
        for d in sorted(self.base.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            meta_file = d / ".workspace.json"
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    # Count files (exclude hidden)
                    file_count = sum(
                        1 for f in d.rglob("*")
                        if f.is_file() and not f.name.startswith(".")
                    )
                    meta["file_count"] = file_count
                    results.append(meta)
                except Exception:
                    pass
            else:
                results.append({
                    "id": d.name, "name": d.name,
                    "created_at": "", "file_count": 0,
                })
        return results

    def get_file_tree(self, workspace_id: str) -> list[dict]:
        """Return flat list of files with relative paths."""
        ws_dir = self._resolve_safe(workspace_id)
        files = []
        for f in sorted(ws_dir.rglob("*")):
            if f.name.startswith("."):
                continue
            rel = f.relative_to(ws_dir)
            files.append({
                "path": str(rel).replace("\\", "/"),
                "is_dir": f.is_dir(),
                "size": f.stat().st_size if f.is_file() else 0,
            })
        return files

    def read_file(self, workspace_id: str, rel_path: str) -> str:
        target = self._resolve_safe(workspace_id, rel_path)
        if not target.is_file():
            raise FileNotFoundError(f"File not found: {rel_path}")
        return target.read_text(encoding="utf-8")

    def write_file(self, workspace_id: str, rel_path: str, content: str) -> str:
        target = self._resolve_safe(workspace_id, rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return str(target.relative_to(self.base / workspace_id)).replace("\\", "/")

    def delete_file(self, workspace_id: str, rel_path: str) -> bool:
        target = self._resolve_safe(workspace_id, rel_path)
        if target.is_file():
            target.unlink()
            return True
        return False

    def delete_workspace(self, workspace_id: str) -> bool:
        ws_dir = (self.base / workspace_id).resolve()
        if not str(ws_dir).startswith(str(self.base.resolve())):
            return False
        if ws_dir.exists():
            import shutil
            shutil.rmtree(ws_dir)
            return True
        return False


# ── Dangerous command blocklist for terminal safety ──────────────────

_BLOCKED_COMMANDS = {
    "rm -rf /", "rm -rf /*", "del /s /q c:\\",
    "format c:", "format c:/",
    "rd /s /q c:\\", "rmdir /s /q c:\\",
    ":(){:|:&};:", "fork bomb",
    "mkfs.", "dd if=/dev/zero",
}

_BLOCKED_PREFIXES = (
    "rm -rf /", "del /s /q c:", "format c",
    "rd /s /q c:", "rmdir /s /q c:",
)


def is_command_safe(cmd: str) -> bool:
    """Basic safety check for terminal commands. Returns False for obviously destructive commands."""
    lower = cmd.strip().lower()
    if lower in _BLOCKED_COMMANDS:
        return False
    if any(lower.startswith(p) for p in _BLOCKED_PREFIXES):
        return False
    return True
