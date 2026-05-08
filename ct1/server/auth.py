"""Authentication for CT-2 WebUI.

Three modes, set via `auth.mode` in model_config.yaml:

  none      Single-user (default). Bind is restricted to 127.0.0.1.
            No auth required, no login screen.

  password  Shared-password mode. Bind opens to 0.0.0.0 so the family
            can reach it on the LAN. One password gates everything.
            All authed clients act as the single admin user.

  accounts  RESERVED for a future release. Per-user accounts with isolated
            history. Validates as a config value but errors at startup.

The session token is an HMAC-signed cookie (`ct2_session`) carrying
{user_id, role, issued_at}. The signing key is `auth.session_secret`,
auto-generated on first start if empty. Rotating the secret invalidates
every existing session — used on password change.

Forward-compat note: `accounts` mode plugs in by adding a users table
and switching `validate_password()` to consult it. The session payload
already carries user_id (defaults to "shared" in password mode), and
admin-only endpoints already use `require_admin`.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Optional

import bcrypt
from fastapi import HTTPException, Request, WebSocket, status

# 30 days. Long enough that returning to the family LLM doesn't
# require a re-login; short enough that a stolen cookie expires.
SESSION_TTL_SECONDS = 30 * 24 * 3600
COOKIE_NAME = "ct2_session"
SHARED_USER_ID = "shared"


# ── Config ─────────────────────────────────────────────────────────────

@dataclass
class AuthConfig:
    """Loaded from the `auth:` section of model_config.yaml."""

    mode: str = "none"                  # none | password | accounts
    password_hash: str = ""              # bcrypt hash; empty = needs setup
    session_secret: str = ""             # HMAC key; auto-filled on first start
    allowed_origins: list[str] = field(default_factory=list)
    bind_when_auth: str = "0.0.0.0"     # honored when mode != none

    @classmethod
    def from_dict(cls, raw: Optional[dict]) -> "AuthConfig":
        raw = raw or {}
        mode = (raw.get("mode") or "none").strip().lower()
        if mode not in ("none", "password", "accounts"):
            raise ValueError(
                f"auth.mode must be one of: none, password, accounts (got {mode!r})"
            )
        if mode == "accounts":
            raise ValueError(
                "auth.mode=accounts is reserved for a future release. "
                "Use 'password' for now — it shares one password across the LAN."
            )
        return cls(
            mode=mode,
            password_hash=str(raw.get("password_hash") or ""),
            session_secret=str(raw.get("session_secret") or ""),
            allowed_origins=list(raw.get("allowed_origins") or []),
            bind_when_auth=str(raw.get("bind_when_auth") or "0.0.0.0"),
        )

    def needs_password_setup(self) -> bool:
        return self.mode == "password" and not self.password_hash

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "password_hash": self.password_hash,
            "session_secret": self.session_secret,
            "allowed_origins": list(self.allowed_origins),
            "bind_when_auth": self.bind_when_auth,
        }


def ensure_session_secret(cfg: AuthConfig) -> bool:
    """Auto-generate a session secret on first start. Returns True if changed."""
    if not cfg.session_secret:
        cfg.session_secret = secrets.token_urlsafe(48)
        return True
    return False


# ── Password hashing ──────────────────────────────────────────────────

def hash_password(plaintext: str) -> str:
    if not plaintext:
        raise ValueError("password must not be empty")
    salted = bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt(rounds=12))
    return salted.decode("utf-8")


def verify_password(plaintext: str, hashed: str) -> bool:
    if not plaintext or not hashed:
        return False
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ── Session tokens (HMAC-signed cookie) ───────────────────────────────
#
# Format: base64(payload_json) + "." + base64(hmac_sha256(payload_json, secret))
# Both segments use urlsafe-b64 without padding so the cookie stays compact.

def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def issue_session(secret: str, user_id: str = SHARED_USER_ID, role: str = "admin") -> str:
    payload = {"u": user_id, "r": role, "t": int(time.time())}
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return f"{_b64encode(body)}.{_b64encode(sig)}"


@dataclass
class SessionData:
    user_id: str
    role: str
    issued_at: int


def parse_session(token: str, secret: str) -> Optional[SessionData]:
    """Validate the HMAC and TTL. Returns None on any failure."""
    if not token or not secret or "." not in token:
        return None
    try:
        body_b64, sig_b64 = token.split(".", 1)
        body = _b64decode(body_b64)
        sig = _b64decode(sig_b64)
    except (ValueError, TypeError):
        return None

    expected_sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    if not hmac.compare_digest(expected_sig, sig):
        return None

    try:
        payload = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    issued = int(payload.get("t", 0))
    if issued <= 0 or time.time() - issued > SESSION_TTL_SECONDS:
        return None

    return SessionData(
        user_id=str(payload.get("u", SHARED_USER_ID)),
        role=str(payload.get("r", "user")),
        issued_at=issued,
    )


# ── FastAPI deps ──────────────────────────────────────────────────────

class AuthState:
    """A handle on the live AuthConfig.

    The middleware reads from this object so that a config update
    (password change, mode change) takes effect immediately without
    restarting uvicorn.
    """

    def __init__(self, cfg: AuthConfig):
        self.cfg = cfg

    def replace(self, cfg: AuthConfig) -> None:
        self.cfg = cfg


def get_session_from_request(request: Request, state: AuthState) -> Optional[SessionData]:
    if state.cfg.mode == "none":
        # No auth — every caller is the implicit admin.
        return SessionData(user_id=SHARED_USER_ID, role="admin", issued_at=int(time.time()))
    token = request.cookies.get(COOKIE_NAME, "")
    return parse_session(token, state.cfg.session_secret)


def get_session_from_websocket(ws: WebSocket, state: AuthState) -> Optional[SessionData]:
    if state.cfg.mode == "none":
        return SessionData(user_id=SHARED_USER_ID, role="admin", issued_at=int(time.time()))
    token = ws.cookies.get(COOKIE_NAME, "")
    return parse_session(token, state.cfg.session_secret)


def require_auth(request: Request, state: AuthState) -> SessionData:
    s = get_session_from_request(request, state)
    if s is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Cookie"},
        )
    return s


def require_admin(request: Request, state: AuthState) -> SessionData:
    s = require_auth(request, state)
    if s.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only.")
    return s


# ── Middleware path policy ────────────────────────────────────────────
#
# Paths that work without auth (login screen, status check, static shell).
# Everything under /api/* and the WebSocket are gated otherwise.

PUBLIC_API_PREFIXES = (
    "/api/auth/status",
    "/api/auth/login",
    "/api/auth/logout",
)


def is_public_path(path: str) -> bool:
    """True if `path` should bypass the auth gate."""
    if path.startswith("/api/"):
        return any(path.startswith(p) for p in PUBLIC_API_PREFIXES)
    # Static shell + login page must always render so the user can log in.
    return True


# ── CORS / WS Origin policy ───────────────────────────────────────────

def computed_allowed_origins(cfg: AuthConfig, port: int = 8000) -> list[str]:
    """Origins allowed for CORS and WebSocket upgrades.

    none  → localhost-only (the user opened the app on their own machine).
    auth  → localhost-only PLUS whatever the host added (e.g.
            http://192.168.1.42:8000) so family browsers can connect.
    """
    base = [f"http://localhost:{port}", f"http://127.0.0.1:{port}"]
    if cfg.mode == "none":
        return base
    extra = [o.rstrip("/") for o in cfg.allowed_origins if o]
    return base + extra


def ws_origin_allowed(origin: Optional[str], cfg: AuthConfig, port: int = 8000) -> bool:
    """Reject WebSocket upgrades whose Origin header isn't allow-listed.

    Closes the DNS-rebinding / CSRF attack vector against /ws/think.
    A missing Origin (non-browser client like wscat) is allowed only
    in `none` mode where the bind is localhost-only anyway.
    """
    if origin is None:
        return cfg.mode == "none"
    return origin.rstrip("/") in computed_allowed_origins(cfg, port)
