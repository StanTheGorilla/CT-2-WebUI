# Repo Cleanup & First GitHub Push — Design

**Date:** 2026-03-31

## Goal

Prepare the `ct2` repository for its first public GitHub push. Scope is web UI only (`python -m ct1.server.api` + SvelteKit frontend). CLI, training code, and evolution module are moved to a local-only folder and excluded from version control.

## Repo Name

`ct2`

## What Gets Moved (not deleted)

Move to `_local/` at the repo root — gitignored, never pushed:

| Source | Destination |
|--------|-------------|
| `ct1.py` | `_local/ct1.py` |
| `ct1/cli/` | `_local/cli/` |
| `ct1/evolution/` | `_local/evolution/` |
| `ct1/requirements-training.txt` | `_local/requirements-training.txt` |

## `.gitignore` Changes

- Add `_local/`
- Remove `!ct1/requirements-training.txt` exception (file no longer at that path)

## `model_config.yaml` Reset

Reset to safe defaults so personal settings don't leak to GitHub:

- `active_model: null`
- `context_size: 32768`

## `models/.gitkeep`

Add empty `.gitkeep` so the `models/` directory is preserved for cloners.

## README Rewrite

Web UI focused, covers:

1. **What it is** — single-model local AI with pipeline, SvelteKit UI
2. **Requirements** — Python 3.11+, Node.js 20+, llama-server, a GGUF model
3. **Quick Start** — 4 steps: clone, install, get llama-server, add model, run
   - Start command: `python -m ct1.server.api` (not `uvicorn` directly)
4. **Project structure** — web UI focused, no CLI entries
5. **Configuration** — model_config.yaml fields explained
6. **How the pipeline works** — existing diagram kept
7. **API endpoints** — existing table kept
8. **Troubleshooting** — llama-server not found, GPU issues, port conflicts
9. **License / Contributing**
