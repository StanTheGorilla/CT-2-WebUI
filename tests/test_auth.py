"""Auth module tests.

Covers the pieces that don't require a running FastAPI server:
- AuthConfig parsing (mode validation, accounts gating, defaults)
- Password hash/verify round trip
- Session token issue/parse, signature tampering, secret rotation, TTL
- CORS / WS Origin allow-list policy
- is_public_path policy
"""
from __future__ import annotations

import time

import pytest

from ct1.server.auth import (
    AuthConfig,
    SESSION_TTL_SECONDS,
    SHARED_USER_ID,
    computed_allowed_origins,
    ensure_session_secret,
    hash_password,
    is_public_path,
    issue_session,
    parse_session,
    verify_password,
    ws_origin_allowed,
)


# ── AuthConfig ────────────────────────────────────────────────────────

def test_authconfig_defaults_to_none_mode():
    cfg = AuthConfig.from_dict(None)
    assert cfg.mode == "none"
    assert cfg.password_hash == ""
    assert cfg.session_secret == ""
    assert cfg.allowed_origins == []
    assert cfg.bind_when_auth == "0.0.0.0"


def test_authconfig_accepts_password_mode():
    cfg = AuthConfig.from_dict({"mode": "password"})
    assert cfg.mode == "password"
    assert cfg.needs_password_setup() is True  # no hash yet


def test_authconfig_rejects_unknown_mode():
    with pytest.raises(ValueError, match="auth.mode"):
        AuthConfig.from_dict({"mode": "everyone"})


def test_authconfig_blocks_accounts_mode_until_implemented():
    with pytest.raises(ValueError, match="reserved for a future release"):
        AuthConfig.from_dict({"mode": "accounts"})


def test_authconfig_normalizes_case_and_whitespace():
    cfg = AuthConfig.from_dict({"mode": "  Password "})
    assert cfg.mode == "password"


def test_ensure_session_secret_only_fills_empty():
    cfg = AuthConfig.from_dict({"mode": "password"})
    assert cfg.session_secret == ""
    changed = ensure_session_secret(cfg)
    assert changed is True
    secret_first = cfg.session_secret
    assert len(secret_first) > 30
    # Calling again should be a no-op.
    changed = ensure_session_secret(cfg)
    assert changed is False
    assert cfg.session_secret == secret_first


def test_authconfig_round_trip_through_to_dict():
    cfg = AuthConfig.from_dict({
        "mode": "password",
        "password_hash": "$2b$12$abc",
        "session_secret": "s",
        "allowed_origins": ["http://192.168.1.50:8000"],
        "bind_when_auth": "0.0.0.0",
    })
    again = AuthConfig.from_dict(cfg.to_dict())
    assert again == cfg


# ── Password hashing ──────────────────────────────────────────────────

def test_password_hash_verify_round_trip():
    h = hash_password("hunter2")
    assert h.startswith("$2")
    assert verify_password("hunter2", h) is True
    assert verify_password("hunter3", h) is False


def test_password_hash_rejects_empty():
    with pytest.raises(ValueError):
        hash_password("")


def test_verify_password_handles_garbage_input():
    assert verify_password("anything", "") is False
    assert verify_password("", "$2b$12$abc") is False
    assert verify_password("anything", "not-a-hash") is False


# ── Sessions ──────────────────────────────────────────────────────────

def test_session_round_trip():
    secret = "test-secret-1234567890"
    token = issue_session(secret, user_id="alice", role="admin")
    s = parse_session(token, secret)
    assert s is not None
    assert s.user_id == "alice"
    assert s.role == "admin"
    assert s.issued_at <= int(time.time())


def test_session_default_user_is_shared():
    token = issue_session("k")
    s = parse_session(token, "k")
    assert s.user_id == SHARED_USER_ID
    assert s.role == "admin"


def test_session_rejects_wrong_secret():
    token = issue_session("secret-A")
    assert parse_session(token, "secret-B") is None


def test_session_rejects_tampered_payload():
    token = issue_session("k")
    body, sig = token.split(".", 1)
    # Flip a character in the payload — signature should no longer match.
    tampered = body[:-1] + ("X" if body[-1] != "X" else "Y") + "." + sig
    assert parse_session(tampered, "k") is None


def test_session_rejects_missing_or_bad_format():
    assert parse_session("", "k") is None
    assert parse_session("no-dot", "k") is None
    assert parse_session("a.b", "k") is None  # not valid base64
    assert parse_session("anything", "") is None  # no secret


def test_session_expiry(monkeypatch):
    secret = "k"
    token = issue_session(secret)
    # Push the clock forward past the TTL window.
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + SESSION_TTL_SECONDS + 60)
    assert parse_session(token, secret) is None


# ── CORS / WS Origin ──────────────────────────────────────────────────

def test_allowed_origins_in_none_mode_is_localhost_only():
    cfg = AuthConfig.from_dict({"mode": "none"})
    origins = computed_allowed_origins(cfg, port=8000)
    assert "http://localhost:8000" in origins
    assert "http://127.0.0.1:8000" in origins
    assert len(origins) == 2


def test_allowed_origins_in_password_mode_includes_extras():
    cfg = AuthConfig.from_dict({
        "mode": "password",
        "allowed_origins": ["http://192.168.1.50:8000", "http://nas.local:8000/"],
    })
    origins = computed_allowed_origins(cfg, port=8000)
    assert "http://192.168.1.50:8000" in origins
    # Trailing slash must be normalized away.
    assert "http://nas.local:8000" in origins
    assert "http://nas.local:8000/" not in origins


def test_ws_origin_allowed_localhost():
    cfg = AuthConfig.from_dict({"mode": "none"})
    assert ws_origin_allowed("http://localhost:8000", cfg) is True
    assert ws_origin_allowed("http://127.0.0.1:8000", cfg) is True


def test_ws_origin_rejects_cross_site():
    cfg = AuthConfig.from_dict({"mode": "none"})
    assert ws_origin_allowed("https://evil.example", cfg) is False
    assert ws_origin_allowed("http://localhost:9999", cfg) is False  # wrong port


def test_ws_origin_missing_header_blocked_in_password_mode():
    cfg = AuthConfig.from_dict({"mode": "password"})
    # Non-browser clients (no Origin header) only allowed in `none` mode.
    assert ws_origin_allowed(None, cfg) is False


def test_ws_origin_missing_header_allowed_in_none_mode():
    cfg = AuthConfig.from_dict({"mode": "none"})
    assert ws_origin_allowed(None, cfg) is True


# ── Public path policy ────────────────────────────────────────────────

def test_is_public_path_auth_endpoints_are_public():
    assert is_public_path("/api/auth/status") is True
    assert is_public_path("/api/auth/login") is True
    assert is_public_path("/api/auth/logout") is True


def test_is_public_path_other_api_endpoints_are_gated():
    assert is_public_path("/api/conversations") is False
    assert is_public_path("/api/model") is False
    assert is_public_path("/api/auth/password") is False  # admin-only after login


def test_is_public_path_static_shell_is_public():
    # The login screen and SvelteKit shell must always render.
    assert is_public_path("/") is True
    assert is_public_path("/login") is True
    assert is_public_path("/_app/immutable/chunks/foo.js") is True
