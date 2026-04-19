# CT-2 — Agent Instructions

This file provides guidance for AI coding agents (GitHub Copilot, Claude, Cursor, etc.) working in this repository.

## Project overview

CT-2 is a fully local AI assistant. A FastAPI Python backend wraps `llama-server` (from llama.cpp) and exposes a WebSocket + REST API. The frontend is SvelteKit 5 with Svelte runes. There is no cloud dependency — everything runs on-device.

```
ct1/
  core/          # Pipeline logic: orchestrator, engine, validator, formatter, atlas
  memory/        # SQLite conversation DB, journal, component cache, session store
  modes/         # YAML route definitions (code, design, computer, direct)
  prompts/       # .txt prompt templates managed by prompts/manager.py
  server/        # FastAPI app (api.py), llama-server launcher, downloader, health monitor
  web/           # SvelteKit 5 frontend (src/lib/stores, src/routes, src/lib/components)
models/          # Drop .gguf model files here (gitignored except .gitkeep)
tests/           # pytest test suite
```

## Key conventions

### Python backend
- Entry point: `ct1/server/api.py` — FastAPI app with lifespan, REST endpoints, and `/ws/think` WebSocket
- Model config: `ct1/server/model_config.yaml` — active preset, model path, context size, backend
- Pipeline: `Orchestrator.think()` → routing → planning → generation → validation → optional refinement
- Inference: `ct1/core/engine.py` calls `llama-server` HTTP API directly
- All module-level globals in `api.py` are prefixed with `_` (e.g. `_orch`, `_cfg`, `_server_procs`)
- `_is_generating: int` tracks active generation count — do not start server updates while > 0
- `_swapping: bool` — True during model swap; WebSocket connections are rejected while swapping

### SvelteKit frontend
- **Svelte 5 runes** in `.svelte` files: use `$state`, `$derived`, `$effect`
- **Writable stores** in `.ts` files: use `writable()` from `svelte/store`; auto-subscribe with `$storeName` in templates
- Main stores: `chat.ts` (conversation + phase), `conversations.ts` (history), `preferences.ts` (settings), `serverUpdate.ts` (llama-server update state)
- The `chat.phase` field drives UI state: `'idle' | 'routing' | 'planning' | 'generating' | 'polishing' | 'refining' | 'validating' | 'fixing' | 'done'`
- Chat input is disabled when `phase !== 'idle' && phase !== 'done'` OR when a server update is in progress (`isUpdating` from `serverUpdate` store)
- Routes: `/` (main chat), `/settings`, `/journal`

### WebSocket protocol (`/ws/think`)
Send `{ type: 'think', goal, conversation, ... }` to start generation.
Send `{ type: 'cancel' }` to abort.
Events emitted: `routing`, `routed`, `planned`, `generating`, `token`, `done`, `error`, and others.

### llama-server management
- Binary lives in `bin/vulkan/` or `bin/cuda/` (auto-downloaded on first run)
- `ct1/server/launcher.py` — start/stop/restart logic
- `ct1/server/downloader.py` — downloads latest llama.cpp release from GitHub
- Update endpoint: `POST /api/llama/update/{backend}` — blocked while `_is_generating > 0`
- Health monitor: pings `/health` every 30s, auto-restarts after 3 failures

## What NOT to commit

- `models/` — GGUF model files (large binaries, gitignored)
- `ct1/data/` — runtime data (journals, SQLite DB)
- `bin/` — llama-server binaries (auto-downloaded)
- `ct1/web/build/` and `ct1/web/node_modules/` — build artifacts
- `CONTEXT/` — local planning notes, design docs, personal scratch files
- `docs/plans/` — implementation plan documents
- `prompt.txt`, `_local/`, `.obsidian/` — personal files
- Any `.txt` files the user created manually in the repo root

## Testing

```bash
pytest tests/
```

Tests use `pytest-asyncio`. Mocking targets `ct1.core.engine.Engine` rather than HTTP directly.

## Running locally

```bash
python -m ct1.server.api   # starts llama-server + FastAPI on :8000
```

The first run downloads `llama-server` automatically. Drop a `.gguf` model into `models/` and assign it in Settings.
