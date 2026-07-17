"""Auth endpoints — login, logout, password management.

Shared state lives in ct2.server.api; this module reads it at call time
through the module object so config swaps take effect immediately.
"""
import asyncio
import secrets

import yaml
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from ct2.server.auth import (
    COOKIE_NAME,
    SESSION_TTL_SECONDS,
    AuthConfig,
    ensure_session_secret,
    hash_password,
    issue_session,
    parse_session,
    verify_password,
)

router = APIRouter()


def _core():
    from ct2.server import api
    return api


class _LoginBody(BaseModel):
    password: str


class _PasswordChangeBody(BaseModel):
    current_password: str | None = None  # required if a hash already exists
    new_password: str
    enable: bool = True  # also flip auth.mode → password if currently 'none'


@router.get("/api/auth/status")
async def auth_status(request: Request):
    """Always public. The frontend hits this on boot to decide whether
    to render the login screen or the app shell."""
    cfg = _core()._auth_state.cfg
    if cfg.mode == "none":
        return {"mode": "none", "authenticated": True, "needs_setup": False}
    needs_setup = cfg.needs_password_setup()
    token = request.cookies.get(COOKIE_NAME, "")
    authed = parse_session(token, cfg.session_secret) is not None
    return {
        "mode": cfg.mode,
        "authenticated": authed and not needs_setup,
        "needs_setup": needs_setup,
    }


@router.post("/api/auth/login")
async def auth_login(body: _LoginBody, response: Response):
    cfg = _core()._auth_state.cfg
    if cfg.mode == "none":
        # Login isn't meaningful without auth — but don't 404 either; the
        # frontend may briefly hit this during a mode transition.
        return {"ok": True, "mode": "none"}
    if cfg.needs_password_setup():
        raise HTTPException(status_code=409, detail="Password setup required.")
    if not verify_password(body.password, cfg.password_hash):
        # Constant-ish delay to soften timing attacks. Bcrypt verify is
        # already slow enough; this is belt-and-braces.
        await asyncio.sleep(0.4)
        raise HTTPException(status_code=401, detail="Wrong password.")
    token = issue_session(cfg.session_secret)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=False,  # toggle on once TLS termination is documented
        path="/",
    )
    return {"ok": True}


@router.post("/api/auth/logout")
async def auth_logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


def _persist_auth_cfg() -> None:
    """Write the live AuthConfig back to model_config.yaml."""
    core = _core()
    core._raw_cfg["auth"] = core._auth_state.cfg.to_dict()
    with open(core._CONFIG_PATH, "w", encoding="utf-8") as fh:
        yaml.safe_dump(core._raw_cfg, fh, sort_keys=False)


@router.post("/api/auth/password")
async def auth_set_password(body: _PasswordChangeBody, request: Request, response: Response):
    """Set or change the shared password.

    First-time setup (no current hash): no current_password required, and
    auth.mode flips to 'password' atomically. Subsequent changes require
    the current password and rotate the session secret so existing
    sessions everywhere are invalidated.
    """
    cfg = _core()._auth_state.cfg
    new_pw = (body.new_password or "").strip()
    if len(new_pw) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")

    is_first_setup = (cfg.mode == "none") or cfg.needs_password_setup()
    if not is_first_setup:
        # Caller must already be authed (middleware already enforced that
        # for password mode) AND prove they know the current password.
        if not body.current_password or not verify_password(body.current_password, cfg.password_hash):
            await asyncio.sleep(0.4)
            raise HTTPException(status_code=401, detail="Current password is wrong.")

    new_cfg = AuthConfig(
        mode="password" if (is_first_setup and body.enable) else cfg.mode,
        password_hash=hash_password(new_pw),
        # Rotate the secret on every password change → every session everywhere logs out.
        session_secret=secrets.token_urlsafe(48) if not is_first_setup else cfg.session_secret,
        allowed_origins=list(cfg.allowed_origins),
        bind_when_auth=cfg.bind_when_auth,
    )
    if is_first_setup:
        # Ensure a secret exists for the first-time enable case too.
        ensure_session_secret(new_cfg)
    _core()._auth_state.replace(new_cfg)
    _persist_auth_cfg()

    # Issue a fresh session for the caller so they aren't kicked out.
    token = issue_session(new_cfg.session_secret)
    response.set_cookie(
        key=COOKIE_NAME, value=token, max_age=SESSION_TTL_SECONDS,
        httponly=True, samesite="lax", secure=False, path="/",
    )
    return {"ok": True, "mode": new_cfg.mode}


@router.post("/api/auth/disable")
async def auth_disable(body: _LoginBody, request: Request, response: Response):
    """Switch back to single-user `none` mode. Requires the current password.

    Wipes the password hash and rotates the session secret so any other
    devices that were logged in lose access immediately.
    """
    cfg = _core()._auth_state.cfg
    if cfg.mode == "none":
        return {"ok": True, "mode": "none"}
    if not verify_password(body.password, cfg.password_hash):
        await asyncio.sleep(0.4)
        raise HTTPException(status_code=401, detail="Wrong password.")
    new_cfg = AuthConfig(
        mode="none",
        password_hash="",
        session_secret=secrets.token_urlsafe(48),
        allowed_origins=list(cfg.allowed_origins),
        bind_when_auth=cfg.bind_when_auth,
    )
    _core()._auth_state.replace(new_cfg)
    _persist_auth_cfg()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True, "mode": "none"}
