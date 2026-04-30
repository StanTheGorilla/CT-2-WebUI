# Changelog

All notable changes to CT-2 are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0] - 2026-04-30

### Added

#### Pipeline
- Six-phase generation pipeline: route → plan → generate → validate → refine
- Deterministic keyword/regex router — zero AI overhead; rules live in `ct1/modes/*.yaml`
- JSON spec planning phase before HTML/code generation (output type, components, structure)
- Full token-level streaming generation with live thinking traces in the UI
- Structural validation: HTML tag balance, Python AST parse, JavaScript brace matching
- CSS-only selective refinement pass for Design mode (spacing, colours, hover states)

#### Modes
- **Chat mode** (`ROUTE_DIRECT`) — conversational responses; question detection skips planning overhead; Markdown + LaTeX rendering
- **Design mode** (`ROUTE_DESIGN`) — spec → generate → validate → CSS refine; produces complete single-file HTML/CSS pages with live resizable preview panel
- **Code mode** (`ROUTE_CODE`) — generates Python, JavaScript, TypeScript, Go, Rust, Bash, SQL and more; tier-aware planning, section-based HTML edits, syntax highlighting + download button
- **Auto routing** — resolves the best mode from message content; manual mode override available in the UI

#### Atlas Mode *(beta)*
- Test-time compute scaling: generate K candidates in parallel, score each, return the best
- Candidate 0 streams live; remaining candidates run silently in the background
- Difficulty estimation determines whether Atlas activates automatically

#### Inference Backends
- **llama.cpp / llama-server** — primary backend; auto-downloaded (Vulkan or CUDA build) on first start; in-place update button in Settings UI
- **Ollama** — auto-detected when `ollama serve` is running on port 11434
- **LM Studio** — auto-detected when the local server is running on port 1234
- Automatic backend detection and failover; no manual configuration required
- Background health monitor pings the active backend every 30 s; auto-restarts after 3 consecutive failures
- Config rollback: if a new model fails to load, reverts to the previous working model automatically
- KV cache cleared between conversations and on context switches to prevent cross-contamination
- AMD Vulkan safe shutdown: 30-second graceful drain before SIGTERM to prevent GPU memory fragmentation

#### Thinking Support
- Extended reasoning (`<think>` blocks) auto-detected and enabled for: Qwen3, DeepSeek R1, Gemma 4, NVIDIA Nemotron Nano
- Thinking tokens streamed live and displayed as a collapsible trace in the UI
- Per-mode `thinking_budget` control (`-1` = unlimited)

#### Web Search
- DuckDuckGo integration — no API key required; toggle per-message in the chat composer
- LLM query extraction: model derives a focused, de-pronominalized search query from message + history
- Explicit mode: prefix message with `!search ` to supply the exact query
- Source tiering: news wires and encyclopaedic sources prioritised; social media and JS-heavy sites skipped
- Up to 5 results injected as a timestamped context block before generation

#### Journal System
- Learns from past interactions; injects relevant lessons into future prompts
- Journal viewer page with entry list and stats
- Configurable lesson count on startup (`journal.lessons_on_startup`)

#### Component Cache
- Thumbs-up on any Design or Code response saves it to a searchable cache
- Cache contents injected as `[REFERENCE]` prefix in future similar requests
- Cache management API (`GET /api/cache`, `DELETE /api/cache/{id}`)

#### Memory & History
- SQLite-backed conversation history — messages, routes, and feedback stored locally
- Full-text search across all past conversations from the sidebar
- Session restore: conversations grouped by Today / Yesterday / This Week / Older
- Per-message thumbs up / down feedback; positive feedback on design/code auto-caches output
- LLM-refined conversation titles delivered via WebSocket after generation completes

#### UI
- SvelteKit 5 frontend served by FastAPI (`http://localhost:8000`)
- Live HTML preview panel — streams rendered HTML as tokens arrive; opens automatically for Design outputs
- Context usage bar: real-time token count and fill indicator in the chat input
- Retry with versions: regenerate any response; navigate all prior versions with ← 1/2 → controls
- Stop generation: cancel mid-stream; connection closed immediately to halt GPU work
- Image attachments: attach images to any message when a vision-capable model is loaded
- Mode badges on each conversation in the sidebar
- Code syntax highlighting with one-click copy on all code blocks
- Download buttons: Design output as `index.html`; Code output with correct extension per language
- Settings UI: model selection, backend switching, parameter tuning, prompt editing, llama-server update

#### API
- FastAPI + WebSocket server on port 8000
- `GET /api/status` — backend health check, now includes `version` field
- Full REST API for conversations, messages, modes, prompts, cache, journal, and backend control
- WebSocket `/ws/think` with structured event protocol (`route`, `plan`, `thinking`, `token`, `validation`, `done`, `error`, `cancel`)
