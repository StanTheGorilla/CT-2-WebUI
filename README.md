# CT-2

A fully local AI assistant with a modern SvelteKit web interface. Works with **llama.cpp** (llama-server), **Ollama**, or **LM Studio** — no API keys, no cloud, no telemetry.

CT-2 wraps any local model in a structured multi-phase pipeline: deterministic routing → self-planning → streaming generation → validation → optional refinement. The result is significantly more consistent output quality than prompting the model directly.

---

## Features

### Core Pipeline
- **Deterministic routing** — keyword/regex classifier resolves to a mode with zero AI overhead; all rules live in `ct1/modes/*.yaml`
- **Self-planning** — lightweight JSON spec phase before generation (output type, components, structure)
- **Streaming generation** — full token-level streaming with thinking traces visible in the UI
- **Validation** — HTML structural checks, Python AST validation, JS brace matching; deterministic cleanup and repetition trimming
- **Selective refinement** — optional self-refinement pass (Design mode: spacing, colors, hover states)
- **Atlas Mode** *(beta)* — test-time compute scaling: generate K candidates, score each, select the best

### Modes
- **Chat** — direct conversational responses; question detection skips planning overhead
- **Design** — spec → generate → validate → CSS-only refine; produces complete, clean single-file HTML/CSS pages
- **Code** — generates Python, JavaScript, TypeScript, Go, Rust, Bash, SQL, and more
- **Auto** — routes automatically to the best mode based on message content

### Intelligence
- **Thinking support** — extended reasoning (`<think>` blocks) auto-enabled for supported models (Qwen3, DeepSeek R1, Nemotron Nano, Gemma 4); visible as a collapsible trace in the UI
- **Journal system** — learns from past interactions; injects relevant lessons into future prompts
- **LLM-refined conversation titles** — heuristic extraction followed by a fast AI-generated title, delivered via WebSocket after generation completes
- **Component cache** — thumbs-up on a Design or Code response saves it to a searchable cache for future injection

### Web Search
- **DuckDuckGo integration** — toggle the search button in the chat composer; no API key required
- **LLM query extraction** — the model extracts a focused, de-pronominalized search query from your message and conversation history
- **Explicit mode** — prefix your message with `!search ` to supply the exact query yourself
- **Source tiering** — results sorted by domain quality (news wires, Wikipedia prioritized; social/JS-heavy sites skipped)
- **Injected context** — search results formatted as a timestamped context block injected before generation

### UI
- **Live HTML preview** — resizable split panel that streams rendered HTML as it generates; opens automatically for Design outputs
- **Context usage bar** — real-time token count and fill indicator in the chat input
- **Download buttons** — save Design output as `index.html`; save Code output with the correct file extension per language
- **Code syntax highlighting** — per-language highlighting with one-click copy on all code blocks
- **Retry with versions** — regenerate any response; navigate all prior versions with ← 1/2 → controls
- **Mode badges** — each conversation in the sidebar shows the mode it used
- **Stop generation** — cancel mid-stream; connection closed immediately to stop GPU work
- **Image attachments** — attach images to any message when a vision-capable model is loaded

### Infrastructure
- **Multi-backend support** — auto-detects and connects to llama-server (llama.cpp), Ollama, or LM Studio; no manual configuration required
- **Auto-download llama-server** — downloads the correct Vulkan or CUDA build on first start
- **In-place llama-server update** — Settings UI includes an update button that replaces the binary while the server is stopped
- **Background health monitor** — pings the inference backend every 30 seconds; auto-restarts after 3 consecutive failures
- **Config rollback** — if a new model fails to load, automatically reverts to the previous working model and restarts
- **KV cache management** — clears the KV cache between conversations and on context switches to prevent cross-contamination
- **AMD Vulkan safe shutdown** — 30-second graceful drain before SIGTERM to prevent GPU memory fragmentation

### Memory & History
- **SQLite conversation history** — all messages, routes, and feedback stored locally
- **Full-text search** — search across all past conversations from the sidebar
- **Session restore** — conversations grouped by time (Today / Yesterday / This Week / Older); click any to restore
- **Thumbs up / down feedback** — per-message; positive feedback on design/code responses auto-caches the output

---

## Requirements

- **Python 3.11+**
- **Node.js 20+**
- **An inference backend** — one of:
  - **llama.cpp** (`llama-server`) — auto-downloaded on first start; requires a `.gguf` model file
  - **Ollama** — if `ollama serve` is running on port `11434`, CT-2 detects it automatically
  - **LM Studio** — if LM Studio's local server is running on port `1234`, CT-2 detects it automatically

**Recommended GGUF models** (for llama-server backend):
- [Qwen3-4B](https://huggingface.co/Qwen/Qwen3-4B-GGUF) — best balance of speed and quality; full thinking support
- [Gemma 4 E4B](https://huggingface.co/google/gemma-4-e4b-it-GGUF) — Google's efficient 4B model
- [NVIDIA Nemotron-Mini-4B](https://huggingface.co/nvidia/Nemotron-Mini-4B-Instruct-GGUF) — strong reasoning

> **Note:** Models without `<think>` support work but produce less consistent multi-step output. Models smaller than ~1.7B are unreliable for structured output.

> **Vision:** If your model has a paired multimodal projector (`mmproj-*.gguf` in the same directory), CT-2 detects it automatically and enables image attachments.

---

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/StanTheGorilla/CT-2-WebUI.git
cd CT-2-WebUI

# Python backend
pip install -r ct1/requirements.txt

# Web frontend (built automatically on first start — optional to pre-build)
cd ct1/web && npm install && cd ../..
```

### 2. Add a model (llama-server backend only)

Place any instruction-tuned `.gguf` file in the `models/` directory:

```bash
huggingface-cli download Qwen/Qwen3-4B-GGUF --local-dir models/
```

Skip this step if you're using Ollama or LM Studio — CT-2 reads their model lists directly.

### 3. Start

```bash
python -m ct1.server.api
```

Open **http://localhost:8000** — go to **Settings** to select your model and backend.

> On first start with llama-server: the SvelteKit frontend is built and `llama-server` is downloaded for your GPU (Vulkan or CUDA). This takes a minute; subsequent starts are instant.

---

## Project Structure

```
CT-2-WebUI/
├── ct1/
│   ├── core/
│   │   ├── orchestrator.py    # Main pipeline (route → plan → generate → validate → refine)
│   │   ├── engine.py          # LLM interface (streaming, thinking, search query extraction)
│   │   ├── atlas.py           # Atlas Mode (multi-candidate test-time compute)
│   │   ├── formatter.py       # Output cleanup, type detection, HTML/CSS polishing
│   │   ├── validator.py       # Structural validation (HTML, Python AST, JS)
│   │   ├── assembler.py       # Design component assembly and patching
│   │   ├── gguf_reader.py     # Reads context_length from GGUF binary headers
│   │   ├── web_fetcher.py     # URL content extraction for in-chat URL pasting
│   │   └── web_searcher.py    # DuckDuckGo search with source tiering
│   ├── server/
│   │   ├── api.py             # FastAPI + WebSocket server (all endpoints)
│   │   ├── launcher.py        # llama-server process management
│   │   ├── backend_detector.py # Auto-detects Ollama, LM Studio, llama-server
│   │   ├── health.py          # Dead-process detection utilities
│   │   ├── downloader.py      # llama-server binary download + extraction
│   │   ├── cache_policy.py    # KV cache clear decision logic
│   │   └── model_config.yaml  # Model and inference configuration
│   ├── memory/
│   │   ├── conversation_db.py # SQLite conversation + message storage
│   │   ├── journal.py         # Learning journal (lessons from past interactions)
│   │   ├── journal_reader.py  # Journal retrieval and stats
│   │   ├── session_store.py   # Session persistence
│   │   └── component_cache.py # Cached high-quality design/code outputs
│   ├── modes/
│   │   ├── registry.py        # ModeRegistry: YAML loading, routing, hot-reload
│   │   ├── direct.yaml        # Chat mode (ROUTE_DIRECT)
│   │   ├── code.yaml          # Code mode (ROUTE_CODE)
│   │   └── design.yaml        # Design mode (ROUTE_DESIGN)
│   ├── prompts/
│   │   ├── manager.py         # PromptManager (load, get, save, reset, hot-reload)
│   │   └── *.txt              # All system prompts — editable at runtime via Settings
│   ├── templates/
│   │   ├── fallbacks.py       # Deterministic fallback outputs when generation fails
│   │   └── snippets.py        # Reusable component snippets
│   └── web/                   # SvelteKit frontend
│       └── src/
│           ├── routes/
│           │   ├── +page.svelte          # Main chat interface
│           │   ├── +layout.svelte        # App shell + sidebar
│           │   ├── settings/+page.svelte # Settings UI
│           │   └── journal/+page.svelte  # Journal viewer
│           └── lib/
│               ├── stores/               # Svelte stores (chat, conversations, preferences)
│               ├── components/           # Shared UI components
│               └── markdown.ts           # Markdown + LaTeX renderer
├── models/                    # Place .gguf files here (gitignored)
├── bin/                       # Downloaded llama-server binaries (gitignored)
└── tests/
```

---

## Configuration

`ct1/server/model_config.yaml` — edit manually or via the Settings UI:

```yaml
executable: auto          # auto-discovers llama-server in bin/ or PATH
backend: vulkan           # llama-server GPU backend: vulkan (AMD/Intel) or cuda (NVIDIA)
models_dir: models        # directory containing .gguf files
active_model: null        # set via Settings UI

port: 8080                # llama-server internal port
n_gpu_layers: 99          # GPU layer offload (99 = all layers)
context_size: 32768       # context window in tokens (capped by model's GGUF max)
parallel_slots: 1         # concurrent request slots

temperature: 0.6
top_p: 0.9
top_k: 40
presence_penalty: 1.0
frequency_penalty: 0.0
thinking_budget: -1       # -1 = unlimited thinking tokens

task_overrides:           # per-mode parameter overrides (editable in Settings)
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
  path: ct1/data/journals
  lessons_on_startup: 10
sessions:
  path: ct1/data/sessions
```

---

## How Each Mode Works

All messages pass through a shared entry point first:

```
User Message
    │
    ▼
┌──────────────────────────────────────────┐
│  ROUTE  (instant, no AI)                 │
│  Keyword/regex classifier against        │
│  ct1/modes/*.yaml patterns.              │
│  Manual mode override skips this.        │
│                                          │
│  → ROUTE_DIRECT   (Chat)                │
│  → ROUTE_DESIGN   (Design)              │
│  → ROUTE_CODE     (Code)               │
└──────────────────┬───────────────────────┘
                   │
         ┌─────────┴──────────┐
         │ Context detection  │  Previous code? Edit intent? New request?
         └─────────┬──────────┘
                   │
        ┌──────────┼──────────┐
        ▼          ▼          ▼
      CHAT       DESIGN      CODE
  (see below) (see below) (see below)
```

---

### Chat Mode (`ROUTE_DIRECT`)

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

---

### Design Mode (`ROUTE_DESIGN`)

```
Message
  ▼
Phase 0 · Spec Generation
  │  Structured JSON plan — thinking disabled for speed
  │  Output: { page_title, color_theme, layout_order, components[], interactions[] }
  │
  ▼
Phase 0.5 · Spec Normalization  (mechanical, no AI)
  │  Strip invalid interaction names, normalize unknown component types
  │
  ▼
Phase 1 · HTML Generation  (streaming)
  │  Spec-guided prompt + Tailwind CDN instruction
  │  Temperature: 0.4  |  Full thinking enabled
  │  Complete single-file HTML page streamed token-by-token
  │  Live HTML preview panel renders as tokens arrive
  │
  ▼
Phase 2 · Cleanup  (mechanical)
  │  strip_think_tags() → extract_code() → emit draft
  │
  ▼
Phase 3 · CSS-Only Refinement  (AI)
  │  Extract only the <style> block (~2–5 KB)
  │  Model polishes spacing, colors, hover states
  │  Improved CSS reassembled back into page
  │
  ▼
Output
  ├─ Live resizable HTML preview panel
  ├─ Download as index.html
  ├─ Spec card (page structure, components)
  └─ Thinking trace (collapsible)
```

**Design edit (follow-up message):**
```
Edit intent detected (keyword match)
  ▼
Retrieve persisted spec → identify target component(s)
  ▼
patch_component_in_page() — surgical replacement in existing HTML
  ▼
Updated page → preview refreshes
```

---

### Code Mode (`ROUTE_CODE`)

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
       ├─ Language badge + download button (correct extension)
       ├─ Explanation text (if model wrote prose before the fence)
       ├─ Plan card (output_type, complexity)
       └─ Thinking trace (collapsible)
```

**Atlas Mode** (optional):
```
Estimate difficulty → Generate K candidates → Score each
→ Select best → Continue to Format/Validate
Candidate 0 streams live; others run silently
```

---

## Modes System

Each mode is a YAML file in `ct1/modes/`. The `ModeRegistry` auto-discovers and hot-reloads them. Custom modes can be created via the API or by adding a new YAML file.

```yaml
name: code
route_id: ROUTE_CODE
description: Code generation, debugging, refactoring
priority: 3
patterns:
  - write\s+(?:\w+\s+){0,4}(?:function|class|script|...)
  - implement\b
  - debug\b
negative_patterns:
  - landing page
lang_patterns:
  - \bpython\b
  - \bjavascript\b
task_overrides:
  temperature: 0.25
  top_p: 0.85
  presence_penalty: 1.3
```

Routing evaluates modes in priority order. `negative_patterns` prevent false positives — e.g., "write a Python script for a landing page" routes to Design, not Code.

---

## Web Search

Web search is off by default. Enable it per-message with the search button in the chat composer.

1. You send a message with web search enabled
2. The LLM extracts a precise, standalone search query from your message and recent history (resolves pronouns)
3. CT-2 queries DuckDuckGo and retrieves up to 5 results
4. Results are sorted by source quality (news wires and encyclopaedic sources first; social media and JS-heavy sites skipped)
5. Snippets are formatted into a timestamped context block injected before your message
6. The model answers using up-to-date web information

**Explicit query mode:** Prefix your message with `!search ` to bypass LLM query extraction and use your exact text.

---

## Prompts

All system prompts are editable at runtime from **Settings → Prompts** — no restart required. Each prompt is a `.txt` file in `ct1/prompts/`. Reset any prompt to its shipped default with the Reset button.

| Prompt | Purpose |
|--------|---------|
| `generator_text` | Chat mode system prompt |
| `generator_design` | Design mode generator |
| `generator_code` | Code mode generator |
| `refine_css` | CSS-only refinement pass |
| `solo_plan` | Planning phase prompt |
| `spec_generator` | Design spec generation prompt |

---

## API Reference

### Server & Model

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/status` | Inference backend health check |
| `GET` | `/api/config` | Full runtime configuration |
| `GET` | `/api/models` | List available models (size, thinking support, vision, context length) |
| `GET` | `/api/model` | Active model name, capabilities, and context size |
| `POST` | `/api/model/select` | Select a model and restart; auto-rollback on failure |
| `POST` | `/api/backend/select` | Switch GPU backend (vulkan/cuda) and restart |
| `POST` | `/api/restart` | Restart with optional context_size override |
| `POST` | `/api/llama/update/{backend}` | Download latest llama-server binary |
| `GET` | `/api/llama/update/{backend}/status` | Poll download progress |

### Generation

| Method | Path | Description |
|--------|------|-------------|
| `WS` | `/ws/think` | Streaming generation WebSocket |
| `GET` | `/api/web-search` | Run a DuckDuckGo search and return structured results |

### Conversations & Memory

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/conversations` | List chat history |
| `POST` | `/api/conversations` | Create new conversation |
| `GET` | `/api/conversations/{id}` | Get a conversation with all messages |
| `PATCH` | `/api/conversations/{id}` | Rename a conversation |
| `DELETE` | `/api/conversations/{id}` | Delete a conversation |
| `GET` | `/api/search` | Full-text search across all conversations |
| `POST` | `/api/messages/{id}/feedback` | Submit thumbs up/down; thumbs-up auto-caches design/code output |
| `GET` | `/api/journal` | List journal entries and stats |

### Modes & Prompts

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/modes` | List all loaded mode definitions |
| `GET` | `/api/modes/{name}` | Get a single mode |
| `PUT` | `/api/modes/{name}` | Update mode config; reloads registry |
| `POST` | `/api/modes` | Create a new custom mode |
| `DELETE` | `/api/modes/{name}` | Delete a custom mode (built-ins protected) |
| `GET` | `/api/prompts` | List all prompts |
| `PUT` | `/api/prompts/{name}` | Update prompt content (persists to disk) |
| `POST` | `/api/prompts/{name}/reset` | Reset prompt to default |

### Component Cache

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/cache` | List cached components |
| `DELETE` | `/api/cache/{id}` | Delete a cached component |

---

## WebSocket Event Protocol

Connect to `/ws/think` and send:

```json
{
  "type": "think",
  "goal": "your message",
  "conversation": [...history],
  "conversation_id": "uuid",
  "mode_override": "chat|design|code|auto",
  "web_search": false,
  "skip_refinement": false,
  "atlas": null
}
```

The server emits a sequence of events:

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

---

## Troubleshooting

**`llama-server` not found**
CT-2 auto-downloads it on first start. If that fails, download a [llama.cpp release](https://github.com/ggerganov/llama.cpp/releases) and place it in `bin/vulkan/` or `bin/cuda/`.

**No models listed in Settings**
Ensure your `.gguf` file is in the `models/` directory at the repo root. If using Ollama or LM Studio, confirm the backend server is running before starting CT-2.

**Model loads but responses are empty or broken**
CT-2 uses ChatML by default. Ensure your model is instruction-tuned and supports ChatML or the standard instruct format. Check that `thinking_budget` is set to `-1` for unlimited.

**GPU not used / slow generation**
Confirm `n_gpu_layers: 99` in `model_config.yaml`. Select the correct backend in Settings: Vulkan for AMD/Intel, CUDA for NVIDIA. Trigger a binary update from Settings if you suspect an outdated `llama-server`.

**Port already in use**
Change `port` in `model_config.yaml` (default `8080` for llama-server, `8000` for the FastAPI server).

**AMD GPU — process hangs after stopping**
CT-2 includes a 30-second graceful Vulkan shutdown. If `llama-server` still hangs: `taskkill /IM llama-server.exe /F` (Windows) or `pkill llama-server` (Linux/macOS).

**Model swap fails and server is unresponsive**
CT-2 automatically reverts `model_config.yaml` to the previous working model and attempts recovery. If recovery also fails, open Settings and manually select a working model.

**Web search not returning results**
DuckDuckGo may rate-limit heavy use. Wait a few minutes and retry. Use the `!search` prefix to supply an exact query and skip AI extraction.

---

## License

MIT

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit your changes
4. Push and open a Pull Request

Run tests before submitting:
```bash
pytest tests/
```
