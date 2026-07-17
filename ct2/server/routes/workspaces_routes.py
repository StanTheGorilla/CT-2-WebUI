"""Workspace file-management and command-approval endpoints.

Shared state (_workspace, _db, _pending_approvals) lives in
ct2.server.api; read at call time through the module object.
"""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


def _core():
    from ct2.server import api
    return api


@router.get("/api/workspaces")
async def list_workspaces():
    return _core()._workspace.list_workspaces()


class CreateWorkspaceBody(BaseModel):
    name: str = ""


@router.post("/api/workspaces")
async def create_workspace(body: CreateWorkspaceBody):
    return _core()._workspace.create_workspace(body.name)


@router.get("/api/workspaces/{ws_id}/files")
async def get_workspace_files(ws_id: str):
    try:
        return _core()._workspace.get_file_tree(ws_id)
    except FileNotFoundError:
        return {"error": "Workspace not found"}


@router.get("/api/workspaces/{ws_id}/files/{file_path:path}")
async def read_workspace_file(ws_id: str, file_path: str):
    try:
        content = _core()._workspace.read_file(ws_id, file_path)
        return {"path": file_path, "content": content}
    except (FileNotFoundError, PermissionError) as e:
        return {"error": str(e)}


class WriteFileBody(BaseModel):
    content: str


@router.put("/api/workspaces/{ws_id}/files/{file_path:path}")
async def write_workspace_file(ws_id: str, file_path: str, body: WriteFileBody):
    try:
        written = _core()._workspace.write_file(ws_id, file_path, body.content)
        return {"path": written}
    except (FileNotFoundError, PermissionError) as e:
        return {"error": str(e)}


@router.delete("/api/workspaces/{ws_id}/files/{file_path:path}")
async def delete_workspace_file(ws_id: str, file_path: str):
    try:
        return {"deleted": _core()._workspace.delete_file(ws_id, file_path)}
    except (FileNotFoundError, PermissionError) as e:
        return {"error": str(e)}


@router.delete("/api/workspaces/{ws_id}")
async def delete_workspace(ws_id: str):
    return {"deleted": _core()._workspace.delete_workspace(ws_id)}


@router.get("/api/workspaces/{ws_id}/conversation")
async def get_workspace_conversation(ws_id: str):
    db = _core()._db
    if not db or not getattr(db, '_conn', None):
        return {}
    conv = await db.get_latest_conversation_for_workspace(ws_id)
    return conv if conv else {}


class CommandApprovalBody(BaseModel):
    approved: bool


@router.post("/api/command-approve/{approval_id}")
async def command_approve(approval_id: str, body: CommandApprovalBody):
    fut = _core()._pending_approvals.pop(approval_id, None)
    if fut and not fut.done():
        fut.set_result(body.approved)
    return {"ok": True}
