# CT-2 WebUI

A local AI assistant with a SvelteKit web interface. Runs against **llama.cpp** (`llama-server`), **Ollama**, or **LM Studio** — no API keys, no cloud, no telemetry.

CT-2 wraps any local model in a structured pipeline (route → plan → generate → validate → optional refinement) instead of prompting it directly. The result is more consistent output for design, code, and structured tasks than naked chat — especially on small models.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![SvelteKit](https://img.shields.io/badge/SvelteKit-5-orange)](https://kit.svelte.dev)
[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://www.python.org)
[![Backends](https://img.shields.io/badge/Backends-llama.cpp%20%7C%20Ollama%20%7C%20LM%20Studio-green)](#requirements)

---

## Table of contents

- [Why CT-2 WebUI](#why-ct-2-webui)
- [Quick start](#quick-start)
- [Requirements](#requirements)
- [Highlights](#highlights)
- [Configuration](#configuration)
- [Sharing on the home network](#sharing-on-the-home-network)
- [Security model](#security-model)
- [How each mode works](#how-each-mode-works) *(collapsed)*
- [RAG](#rag-retrieval-augmented-generation) *(collapsed)*
- [Atlas Mode](#atlas-mode) *(collapsed)*
- [API reference](#api-reference) *(collapsed)*
- [WebSocket protocol](#websocket-protocol) *(collapsed)*
- [Troubleshooting](#troubleshooting)
- [Project layout](#project-layout)
- [Contributing](#contributing)
- [License](#license)

---

## Why CT-2 WebUI

Most local-LLM front-ends are thin chat wrappers. CT-2 WebUI adds the pieces a single naked prompt usually misses:

- **A real pipeline.** Routing → planning → generation → validation → optional refinement. Quality stays consistent across runs instead of being a coin flip.
- **A working journal.** The app remembers lessons from past interactions and injects relevant ones into future prompts.
- **Test-time compute.** Atlas Mode generates K candidates, scores them against self-generated tests, and returns the best — for tasks where one shot isn't enough.
- **Local document grounding.** Drop files into a folder, RAG indexes them on startup, and every message can pull in the most relevant chunks.
- **Multi-backend out of the box.** Auto-detects llama-server, Ollama, or LM Studio. The llama-server binary downloads itself on first start.
- **No telemetry, no accounts, no API keys.** Everything runs on your machine.

---

## Quick start

```bash
git clone https://github.com/StanTheGorilla/CT-2-WebUI.git
cd CT-2-WebUI

# Python backend
pip install -r ct2/requirements.txt

# Web frontend (auto-builds on first start; pre-build is optional)
cd web && npm install && cd ..

# Add a model (skip if using Ollama or LM Studio)
huggingface-cli download Qwen/Qwen3-4B-GGUF --local-dir models/

# Start
python -m ct2.server.api
```

Open **http://localhost:8000** and pick a model in **Settings**.

> First start: the SvelteKit frontend is built and `llama-server` is downloaded for your GPU (Vulkan or CUDA). Subsequent starts are instant.

---

## Requirements

- **Python 3.11+**
- **Node.js 20+**
- **An inference backend** — one of:
  - **llama.cpp** (`llama-server`) — auto-downloaded; needs a `.gguf` model file in `models/`
  - **Ollama** — detected automatically if `ollama serve` is on `:11434`
  - **LM Studio** — detected automatically if its local server is on `:1234`

**Recommended GGUF models** (llama-server backend):

| Model | Why |
|------|-----|
| [Qwen3-4B](https://huggingface.co/Qwen/Qwen3-4B-GGUF) | Best balance of speed + quality; full thinking support |
| [Gemma 4 E4B](https://huggingface.co/google/gemma-4-e4b-it-GGUF) | Google's efficient 4B |
| [Nemotron-Mini-4B](https://huggingface.co/nvidia/Nemotron-Mini-4B-Instruct-GGUF) | Strong reasoning |

> Models without `<think>` support work but produce less consistent multi-step output. Models smaller than ~1.7B are unreliable for structured outputs.
>
> If your model has a paired multimodal projector (`mmproj-*.gguf` next to the main file), CT-2 detects it and enables image attachments automatically.

---

## Highlights

| Area | What you get |
|------|-------------|
| **Modes** | Chat · Design · Code · Auto (router-driven). Manual override per-message. |
| **Streaming** | Token-level streaming of both answer and `<think>` trace |
| **Live HTML preview** | Resizable split panel; opens automatically for Design output |
| **Web search** | DuckDuckGo, no API key. LLM extracts a focused query from your message + history |
| **RAG** | Local document grounding (PDF/text/code/CSV/JSON/HTML). Auto-index on startup |
| **Atlas Mode** | Multi-candidate test-time compute with self-generated test scoring |
| **Journal** | Lessons from past interactions are injected into future prompts |
| **Component cache** | Thumbs-up on a Design or Code response saves it for future reference injection |
| **History** | SQLite, full-text search, restore any conversation |
| **Backends** | llama.cpp · Ollama · LM Studio — auto-detected |
| **Resilience** | Health monitor, auto-restart, config rollback on failed model swap |
| **Privacy** | No API keys, no telemetry, no cloud |
| **Two UIs** | A modern interface and a classic interface — switch in Settings |
| **Single or shared** | Default single-user (binds `127.0.0.1`). Optional shared-password mode for hosting one model for the whole family — see [below](#sharing-on-the-home-network) |

Full feature lists for each area are in the collapsed sections below.

---

## Configuration

`ct2/server/model_config.yaml` — edit by hand or via Settings:

```yaml
executable: auto          # auto-discovers llama-server in bin/ or PATH
backend: vulkan           # vulkan (AMD/Intel) or cuda (NVIDIA)
models_dir: models
active_model: null        # set via Settings UI

port: 8080
n_gpu_layers: 99          # 99 = offload all
context_size: 32768       # capped by model's GGUF max
parallel_slots: 1

temperature: 0.6
top_p: 0.9
top_k: 40
presence_penalty: 1.0
frequency_penalty: 0.0
thinking_budget: -1       # -1 = unlimited

task_overrides:
  design:
    temperature: 0.4
  code:
    temperature: 0.25
    top_p: 0.85
    presence_penalty: 1.3
  direct:
    temperature: 0.5
    presence_penalty: 0.6

journal:
  path: ct2/data/journals
  lessons_on_startup: 10

rag:
  enabled: false
  data_dir: rag_data
  chunks_per_query: 5
  chunk_size: 400
  chunk_overlap: 100
  max_file_mb: 25

auth:
  mode: none                 # none | password   (accounts: roadmap)
  password_hash: ""           # bcrypt; set via Settings → Security
  session_secret: ""          # auto-generated on first start
  allowed_origins: []         # extra LAN origins for CORS / WS, e.g. http://192.168.1.42:8000
  bind_when_auth: 0.0.0.0     # what to bind to when mode != none
```

> Override the bind address at run time with `CT2_HOST=127.0.0.1`. Useful when fronting CT-2 with a reverse proxy.

All system prompts live in `ct2/prompts/` as `.txt` files and are editable at runtime from **Settings → Prompts**. Reset any prompt to its shipped default with the Reset button.

---

## Sharing on the home network

CT-2 WebUI runs in **single-user mode by default** — it binds to `127.0.0.1` only, no login screen, just open the browser and use it. This is the right behaviour for the 99% case (you and your laptop).

If you want to host one model and let your family use it from their own devices, switch on **shared-password mode**:

1. Open **Settings → Security**.
2. Enter a password and click **Enable password**.
3. Restart CT-2.
4. The bind opens to `0.0.0.0` so other devices on the LAN can reach `http://<your-pc-ip>:8000`.
5. Each device sees a login screen on first visit. Sessions last 30 days per browser.

Changing the password signs every other device out automatically. Switching back to single-user wipes the password and reverts the bind to localhost on next start.

> **Adding LAN origins.** If browsers on the LAN connect by IP (`http://192.168.1.42:8000`), add that origin under `auth.allowed_origins` in `model_config.yaml` so the WebSocket origin check accepts it. CORS and WS upgrades both honour the same allow-list.

> **Exposing beyond the home.** Don't expose CT-2 directly to the internet — terminate TLS at a reverse proxy (Caddy, Tailscale Funnel, Cloudflare Tunnel) and point it at `127.0.0.1:8000`. Then set `CT2_HOST=127.0.0.1` so CT-2 binds only to the proxy.

A future release will add **per-user accounts** with isolated chat history. Today, all authed devices share one account in password mode — the foundation is already in place so accounts will land as a drop-in.

---

## Security model

CT-2 WebUI is built to run on your own hardware. The default posture reflects that — a solo user shouldn't have to think about auth at all — but every defence still kicks in if the surface area widens.

| Concern | What CT-2 does |
|---------|---------------|
| **Network exposure** | Default bind is `127.0.0.1`. Only widens to `0.0.0.0` when you turn on `auth.mode = password`. Override either way with `CT2_HOST`. |
| **Browser drive-by attacks** | CORS allow-list is computed from `auth.mode` + your configured origins (no `*`). The `/ws/think` and `/ws/terminal` WebSockets reject any `Origin` not on the list — this closes the DNS-rebinding vector against localhost. |
| **Authentication** | Optional shared-password mode: bcrypt-hashed password in `model_config.yaml`, HMAC-signed session cookies (`httpOnly`, `samesite=lax`), 30-day TTL. Rotating the password rotates the signing secret, invalidating every other device. |
| **Privacy** | No telemetry, no analytics, no outbound calls except the inference backend you point CT-2 at, optional DuckDuckGo search, and the URL fetcher when you paste a link. Conversations live in a local SQLite file. |

**Known limits — read these before opening it up.**

- **No HTTPS by default.** Password mode sends the password in cleartext. On a trusted home network this is acceptable (the realistic threat is a roommate's laptop, not a sniffer); for anything more, terminate TLS at a reverse proxy.
- **No rate limiting.** A logged-in user (or every browser tab they have open) can spam the inference backend.
- **No SSRF guard on the URL fetcher** — when chat-pasting a link, the fetcher will resolve and fetch any URL the model is asked to load. Don't enable web search on a server with sensitive internal services on the same LAN.
- **Per-user isolation isn't here yet.** Password mode is one shared account. If your family member needs their own private chat history, wait for the accounts release.

Found something? Open a private security advisory on the GitHub repo (Security tab → Report a vulnerability) rather than a public issue.

---

## How each mode works

<details>
<summary><b>Routing (shared entry point)</b></summary>

```
User Message
    │
    ▼
┌─────────────────────────────────────────┐
│  ROUTE  (instant, no AI)                │
│  Keyword/regex classifier against       │
│  ct2/modes/*.yaml patterns.             │
│  Manual mode override skips this.       │
│                                         │
│  → ROUTE_DIRECT   (Chat)                │
│  → ROUTE_DESIGN   (Design)              │
│  → ROUTE_CODE     (Code)                │
└──────────────────┬──────────────────────┘
                   │
         ┌─────────┴──────────┐
         │ Context detection  │  Previous code? Edit intent? New request?
         └─────────┬──────────┘
                   │
        ┌──────────┼──────────┐
        ▼          ▼          ▼
      CHAT       DESIGN      CODE
```

Each mode is a YAML file in `ct2/modes/`. The `ModeRegistry` auto-discovers and hot-reloads them. New modes can be added by dropping a YAML file in or via the API.

```yaml
name: code
route_id: ROUTE_CODE
description: Code generation, debugging, refactoring
priority: 3
patterns:
  - write\s+(?:\w+\s+){0,4}(?:function|class|script|...)
  - implement\b
negative_patterns:
  - landing page
task_overrides:
  temperature: 0.25
  top_p: 0.85
  presence_penalty: 1.3
```

`negative_patterns` prevent false positives — "write a Python script for a landing page" routes to Design, not Code.

</details>

<details>
<summary><b>Chat mode (ROUTE_DIRECT)</b></summary>

```
Message
  │
  │ [if web search enabled]
  ├──▶ LLM extracts focused query from message + history
  │    ──▶ DuckDuckGo search
  │    ──▶ Results injected as timestamped context block
  │
  │ [if URL detected in message]
  ├──▶ URL fetched → content injected into prompt
  │
  ▼
Generate  (streaming)
  │  System prompt: generator_text.txt
  │  Temperature: 0.5  |  Presence penalty: 0.6
  │  Thinking tokens streamed live (collapsible in UI)
  │  No planning call, no validation
  ▼
Response rendered as Markdown
  ├─ Prose text
  ├─ Code blocks → syntax highlighting + copy button
  ├─ Web search sources shown inline (if search ran)
  └─ Thinking trace (collapsible)
```

</details>

<details>
<summary><b>Design mode (ROUTE_DESIGN)</b></summary>

```
Message
  ▼
Phase 0 · Spec generation
  │  Structured JSON plan — thinking disabled for speed
  │  { page_title, color_theme, layout_order, components[], interactions[] }
  ▼
Phase 0.5 · Spec normalization  (mechanical)
  │  Strip invalid interaction names, normalize unknown component types
  ▼
Phase 1 · HTML generation  (streaming)
  │  Spec-guided prompt + Tailwind CDN instruction
  │  Temperature: 0.4  |  Full thinking enabled
  │  Live HTML preview panel renders as tokens arrive
  ▼
Phase 2 · Cleanup  (mechanical)
  │  strip_think_tags() → extract_code() → emit draft
  ▼
Phase 3 · CSS-only refinement  (AI)
  │  Extract only the <style> block (~2–5 KB)
  │  Model polishes spacing, colors, hover states
  │  Improved CSS reassembled back into the page
  ▼
Output
  ├─ Live resizable HTML preview panel
  ├─ Download as index.html
  ├─ Spec card (page structure, components)
  └─ Thinking trace (collapsible)
```

**Design edits** (follow-up message):
```
Edit intent detected
  ▼
Retrieve persisted spec → identify target component(s)
  ▼
patch_component_in_page() — surgical replacement in existing HTML
  ▼
Updated page → preview refreshes
```

</details>

<details>
<summary><b>Code mode (ROUTE_CODE)</b></summary>

```
Message
  │
  ├─ [question detected] ──▶ Chat path (prose answer)
  │
  ├─ [edit intent detected]
  │     ▼
  │   Edit path:
  │     HTML: section-based edit (only regenerate touched sections)
  │     Other: full regeneration with previous code as context
  │
  └─ [new code request]
       ▼
     Plan  (tier-aware)
       │  Large models: always plan
       │  Medium: only for complex requests
       │  Small: inline in system prompt
       ▼
     Cache injection
       │  Search component_cache for approved similar outputs
       │  Inject as [REFERENCE] prefix if found
       ▼
     Generate  (streaming)
       │  Temperature: 0.25  |  Top-p: 0.85  |  Presence penalty: 1.3
       │  Full thinking enabled
       ▼
     Format  (mechanical)
       │  Capture fence language tag → detected_lang
       │  Extract explanation prose written before the code fence
       ▼
     Validate  (observe-only)
       │  Python AST / JS brace / structural checks
       │  Issues logged — never trigger a forced rewrite
       ▼
     Output
       ├─ Code block with syntax highlighting + copy button
       ├─ Language badge + download (correct extension)
       ├─ Explanation prose (if model wrote any before the fence)
       ├─ Plan card
       └─ Thinking trace (collapsible)
```

</details>

---

## RAG (Retrieval-Augmented Generation)

RAG grounds the model's responses in your own documents — project specs, API docs, research notes, brand guidelines, meeting transcripts. CT-2 indexes text files from a local folder and injects the most relevant chunks before every message.

<details>
<summary><b>How it works</b></summary>

```
┌─────────────────────────────────────────┐
│  rag_data/                              │
│  ├── api-docs.md                        │
│  ├── brand-guide.pdf                    │
│  └── project-spec.txt                   │
└──────────────┬──────────────────────────┘
               │
               ▼
  Indexing  (startup + manual re-index)
  ├─ Parse: PDF (PyMuPDF), CSV/TSV, JSON, plain text (.md/.py/.txt/...)
  ├─ Chunk: split on paragraph boundaries, merge to ~400 tokens with 100-token overlap
  ├─ Embed: POST /v1/embeddings → float32 vectors
  └─ Store: SQLite (metadata) + numpy .npy (embeddings, memory-mapped)
               │
               ▼
  Per-message  (when RAG toggle is on)
  ├─ Embed user query → same embedding endpoint
  ├─ Cosine similarity search → top-k chunks (default 5)
  └─ Format as [RAG CONTEXT] block → prepend to message before generation
```

</details>

<details>
<summary><b>Setup, supported types, configuration</b></summary>

**Setup**

1. Enable RAG in `model_config.yaml`:
   ```yaml
   rag:
     enabled: true
   ```
2. Add files to the `rag_data/` folder (created automatically) — drag-and-drop, or use **Settings → RAG**.
3. Restart CT-2. Files are indexed on startup — you'll see `[rag] Indexed: ...` in the console.
4. Toggle RAG on in the chat composer — folder icon next to Search.

**Supported types**

| Category | Extensions |
|----------|-----------|
| Documents | `.pdf`, `.txt`, `.md`, `.rst` |
| Code | `.py`, `.js`, `.ts`, `.jsx`, `.tsx`, `.java`, `.go`, `.rs`, `.c`, `.cpp`, `.h`, `.cs`, `.rb`, `.php` |
| Web | `.html`, `.htm`, `.css`, `.scss`, `.less`, `.svg` |
| Data | `.json`, `.yaml`, `.yml`, `.toml`, `.ini`, `.cfg`, `.xml`, `.csv`, `.tsv` |
| Scripts | `.sh`, `.bat`, `.ps1`, `.sql` |

**Configuration**

```yaml
rag:
  enabled: false            # set true to activate
  data_dir: rag_data
  embedding_model: ""       # empty = use chat model for embeddings
  embedding_port: 8081      # port for dedicated embedding model (if set)
  chunks_per_query: 5
  chunk_size: 400
  chunk_overlap: 100
  max_file_mb: 25
```

**Context budget**

Each query injects roughly `chunks_per_query × chunk_size` tokens. With defaults (5 × 400 = 2,000 tokens), a 4K model has ~2,000 left for conversation. Recommendations:

| Model context | chunks_per_query | Comfort |
|--------------|-----------------|---------|
| 4K | 2–3 | Tight |
| 8K | 3–5 | Usable |
| 16K+ | 5–10 | Comfortable |

CT-2's context compaction still works — if history + RAG exceed the limit, older turns are summarized.

**Dedicated embedding model (optional)**

By default the loaded chat model is used for embeddings. For faster, lower-VRAM indexing:

1. Open **Settings → RAG → Embedding Model**
2. Search Hugging Face for `nomic-embed-text-v1.5` or `bge-small-en` (~130–140 MB)
3. Download and select it — CT-2 spins up a second llama-server on the embedding port

</details>

---

## Atlas Mode

Atlas Mode applies **test-time compute scaling** to improve output quality on demanding tasks. Instead of generating a single response, CT-2 generates **K candidates** and returns the best one.

<details>
<summary><b>How K is determined</b></summary>

Atlas estimates task difficulty from four signals before generating anything:

| Signal | Weight | Source |
|--------|--------|--------|
| Cache similarity | 30% | How closely the request matches cached component embeddings |
| Journal pattern match | 25% | Overlap with lessons learned from past interactions |
| Keyword complexity | 20% | Density of complexity keywords + message length |
| Conversation depth | 25% | Number of prior turns in the session |

The combined difficulty score (0.0–1.0) maps to candidate count and a **thinking tier** (nothink → light → standard → hard → extreme):

| Difficulty | K candidates |
|------------|-------------|
| < 0.4 | 1 (single pass) |
| 0.4–0.6 | 2 |
| 0.6–0.8 | 3 |
| ≥ 0.8 | 5 |

</details>

<details>
<summary><b>How candidates are scored</b></summary>

- Candidate 0 (baseline) streams live to the UI as normal.
- Candidates 1+ run silently in the background with a different perspective prompt injected (e.g. "systems architect", "performance engineer", "security-conscious lead").
- Each candidate is scored by running self-generated test cases against the output and blending with the model's own reflection score (60% test / 40% reflection).
- The highest-scoring candidate is selected and returned.
- If all candidates score below 0.5 and the model's context window is ≥ 32K, Atlas attempts one iterative repair pass using failure analysis + Plan-Refine Chain of Thought.

</details>

**When to use it.** Tasks where output quality matters more than response time: complex algorithms, multi-constraint code, architecture design, anything where one shot is inconsistent. With K=2 generation roughly doubles in time; K=5 is ~5×. Candidate 0 streams immediately so the UI is never blank — others run in the background and the best result is shown when selection completes. For simple or conversational messages Atlas usually picks K=1 (no overhead).

---

## API reference

<details>
<summary><b>Server &amp; model</b></summary>

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/status` | Inference backend health check |
| `GET` | `/api/config` | Full runtime configuration |
| `GET` | `/api/models` | List available models (size, thinking, vision, context) |
| `GET` | `/api/model` | Active model name, capabilities, context size |
| `POST` | `/api/model/select` | Select a model and restart; auto-rollback on failure |
| `POST` | `/api/backend/select` | Switch GPU backend (vulkan/cuda) and restart |
| `POST` | `/api/restart` | Restart with optional context_size override |
| `POST` | `/api/llama/update/{backend}` | Download latest llama-server binary |
| `GET` | `/api/llama/update/{backend}/status` | Poll download progress |

</details>

<details>
<summary><b>Authentication</b></summary>

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/auth/status` | `{mode, authenticated, needs_setup}` — the frontend hits this on boot to decide between the chat shell and the login screen. Always public. |
| `POST` | `/api/auth/login` | `{password}` — sets the session cookie on success. 401 on wrong password. |
| `POST` | `/api/auth/logout` | Clears the session cookie. |
| `POST` | `/api/auth/password` | `{new_password, current_password?, enable?}` — first-time setup or password change. Rotates the session secret on change so other devices are signed out. |
| `POST` | `/api/auth/disable` | `{password}` — switch back to single-user mode. Wipes the password hash and rotates the secret. |

</details>

<details>
<summary><b>Generation, RAG, conversations, modes, prompts, cache</b></summary>

**Generation**

| Method | Path | Description |
|--------|------|-------------|
| `WS` | `/ws/think` | Streaming generation WebSocket |
| `GET` | `/api/web-search` | DuckDuckGo search, structured results |

**RAG**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/rag/status` | Index state, chunk count, context cost |
| `GET` | `/api/rag/files` | List indexed files |
| `POST` | `/api/rag/upload` | Upload via multipart form → auto-index |
| `DELETE` | `/api/rag/files/{name}` | Remove file and chunks |
| `POST` | `/api/rag/reindex` | Full re-index of `rag_data/` |
| `POST` | `/api/rag/search` | Test query → top matching chunks with scores |

**Conversations & memory**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/conversations` | List chat history |
| `POST` | `/api/conversations` | Create new conversation |
| `GET` | `/api/conversations/{id}` | Get conversation with all messages |
| `PATCH` | `/api/conversations/{id}` | Rename a conversation |
| `DELETE` | `/api/conversations/{id}` | Delete a conversation |
| `GET` | `/api/search` | Full-text search across all conversations |
| `POST` | `/api/messages/{id}/feedback` | Thumbs up/down; up auto-caches design/code output |
| `GET` | `/api/journal` | List journal entries and stats |

**Modes & prompts**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/modes` | List loaded mode definitions |
| `GET` | `/api/modes/{name}` | Get a single mode |
| `PUT` | `/api/modes/{name}` | Update mode config; reloads registry |
| `POST` | `/api/modes` | Create a new custom mode |
| `DELETE` | `/api/modes/{name}` | Delete a custom mode (built-ins protected) |
| `GET` | `/api/prompts` | List all prompts |
| `PUT` | `/api/prompts/{name}` | Update prompt content (persists to disk) |
| `POST` | `/api/prompts/{name}/reset` | Reset prompt to default |

**Component cache**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/cache` | List cached components |
| `DELETE` | `/api/cache/{id}` | Delete a cached component |

</details>

---

## WebSocket protocol

<details>
<summary><b>Connect to <code>/ws/think</code> and exchange messages</b></summary>

Send:

```json
{
  "type": "think",
  "goal": "your message",
  "conversation": [...history],
  "conversation_id": "uuid",
  "mode_override": "chat|design|code|auto",
  "web_search": false,
  "rag_enabled": false,
  "skip_refinement": false,
  "atlas": null
}
```

Server emits a sequence of events:

| Event | Description |
|-------|-------------|
| `route` | Resolved mode name |
| `plan` | Planning phase output |
| `thinking` | Token-level thinking stream |
| `token` | Generated response token |
| `validation` | Validation result |
| `web_search_extracting` | Search query being extracted |
| `web_search_results` | Search results available |
| `title_update` | AI-refined conversation title |
| `done` | Generation complete (includes `detected_lang`) |
| `error` | Error message |

Send `{"type": "cancel"}` at any time to stop active generation immediately.

</details>

---

## Troubleshooting

**`llama-server` not found.** CT-2 auto-downloads it on first start. If that fails, grab a [llama.cpp release](https://github.com/ggerganov/llama.cpp/releases) and drop it in `bin/vulkan/` or `bin/cuda/`.

**No models listed in Settings.** Ensure your `.gguf` file is in `models/` at the repo root. If you're on Ollama or LM Studio, confirm the backend server is running before starting CT-2.

**Model loads but responses are empty or broken.** CT-2 uses ChatML by default — make sure your model is instruction-tuned and supports ChatML or the standard instruct format. Check that `thinking_budget` is `-1` for unlimited.

**GPU not used / slow generation.** Confirm `n_gpu_layers: 99` in `model_config.yaml`. Pick the right backend in Settings: Vulkan for AMD/Intel, CUDA for NVIDIA. Trigger a binary update from Settings if `llama-server` may be outdated.

**Port already in use.** Change `port` in `model_config.yaml` (default `8080` for llama-server, `8000` for the FastAPI server).

**AMD GPU — process hangs after stopping.** CT-2 includes a 30-second graceful Vulkan shutdown. If `llama-server` still hangs: `taskkill /IM llama-server.exe /F` on Windows or `pkill llama-server` on Linux/macOS.

**Model swap fails and the server is unresponsive.** CT-2 reverts `model_config.yaml` to the previous working model and attempts recovery automatically. If recovery also fails, open Settings and pick a working model manually.

**Web search not returning results.** DuckDuckGo may rate-limit heavy use — wait a few minutes and retry. Use `!search` to supply an exact query and skip AI extraction.

---

## Project layout

```
CT-2-WebUI/
├── ct2/
│   ├── core/         # Pipeline: orchestrator, engine, atlas, formatter, validator
│   ├── rag/          # Indexing, chunking, embedding, retrieval
│   ├── server/       # FastAPI app, llama-server launcher, backend detector, downloader
│   ├── memory/       # SQLite history, journal, sessions, component cache
│   ├── modes/        # YAML route definitions (direct, code, design)
│   ├── prompts/      # System prompts (.txt, runtime-editable)
│   ├── templates/    # Fallbacks + reusable snippets
│   └── web/          # SvelteKit frontend
├── models/           # .gguf files (gitignored)
├── bin/              # Downloaded llama-server binaries (gitignored)
└── tests/
```

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit your changes
4. Run the test suite:
   ```bash
   pytest tests/
   ```
5. Push and open a Pull Request

Issues and discussions welcome — please include the model, backend, and OS you're running on.

---

## License

[MIT](LICENSE)
