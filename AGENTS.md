# AI Agent Instructions — CT-2-WebUI

Instructions for any AI agent (Claude Code, Copilot, Cursor, etc.) working on this repository.

---

## Repository

- **Remote:** https://github.com/StanTheGorilla/CT-2-WebUI
- **Main branch:** `main`
- **Working directory:** project root (contains `ct1/`, `tests/`, `docs/`, `models/`, `bin/`)

---

## Before making any changes

1. Read the relevant source files before editing — never guess at existing code
2. Run existing tests to confirm the baseline passes:
   ```
   python -m pytest tests/ -v
   ```
3. Check git status to understand the current state:
   ```
   git status
   git log --oneline -5
   ```

---

## Making changes

### File rules

| Path | Rule |
|------|------|
| `ct1/` | Main source — edit freely |
| `tests/` | Always update tests when changing logic |
| `models/` | Never commit — gitignored |
| `bin/` | Never commit — gitignored (auto-downloaded at runtime) |
| `_local/` | Never commit — gitignored (personal/local files only) |
| `ct1/server/model_config.yaml` | Keep `active_model: null` in commits — never commit a personal model path |

### Never commit

- `.gguf` model files
- `bin/` executables or DLLs
- `ct1/web/build/` (auto-generated frontend)
- `ct1/web/node_modules/`
- `ct1/data/sessions/` contents
- Any file from `_local/`
- `.env` files or secrets

---

## Running tests

```bash
python -m pytest tests/ -v
```

All tests must pass before committing. If you add new behaviour, add a test for it.

---

## Committing

Stage specific files — never `git add -A` or `git add .`:

```bash
git add ct1/server/api.py ct1/server/downloader.py
git commit -m "fix: short description of what changed and why"
```

### Commit message format

```
<type>: <short description>

<optional body explaining why, not what>
```

Types: `feat` (new feature) · `fix` (bug fix) · `refactor` · `test` · `docs` · `chore`

Keep the subject line under 72 characters.

---

## Pushing

Always push to the remote after committing:

```bash
git push origin main
```

If the push is rejected (diverged history), rebase first:

```bash
git pull --rebase origin main
git push origin main
```

Never force-push to `main`.

---

## Starting the server (for testing)

```bash
python -m ct1.server.api
```

This will:
1. Download llama-server (Vulkan + CUDA) if not already in `bin/`
2. Run `npm install` if `ct1/web/node_modules/` is missing
3. Run `npm run build` to build the SvelteKit frontend
4. Start the API server at http://localhost:8000

---

## Key architecture

- `ct1/server/api.py` — FastAPI server, WebSocket, SPA static serving
- `ct1/server/launcher.py` — llama-server process management
- `ct1/server/downloader.py` — GitHub Releases auto-download (Vulkan + CUDA)
- `ct1/core/orchestrator.py` — 6-phase generation pipeline
- `ct1/core/engine.py` — LLM streaming interface
- `ct1/server/model_config.yaml` — runtime config (model, backend, context size)
- `ct1/web/src/` — SvelteKit frontend source
