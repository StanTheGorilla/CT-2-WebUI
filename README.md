# CT-2

A fully local AI assistant powered by [llama.cpp](https://github.com/ggerganov/llama.cpp), with a modern web interface built in SvelteKit. Runs entirely on your machine — no API keys, no cloud, no telemetry.

CT-2 wraps a single local GGUF model in a structured multi-phase pipeline: deterministic routing → self-planning → streaming generation → validation → optional refinement. The result is significantly more consistent output quality than prompting the model directly.

---

## Features

### Core Pipeline
- **Deterministic routing** — keyword-based classifier resolves to a mode (Chat, Design, Code, Computer) with zero AI overhead; all routing rules live in `ct1/modes/*.yaml`
- **Self-planning** — lightweight JSON spec phase before generation (output type, components, structure)
- **Streaming generation** — full token-level streaming with thinking visible in the UI
- **Validation + formatting** — HTML structural checks, Python AST validation, JS brace matching; deterministic cleanup and repetition trimming
- **Selective refinement** — optional self-refinement pass (Design mode: spacing, colors, hover states)
- **Atlas Mode** *(beta)* — test-time compute scaling: generate K candidates, score each, select the best

### Modes
- **Chat** — direct conversational responses, LLM-detected questions skip planning overhead
- **Design** — structured spec → generate → validate → self-refine; produces clean, complete HTML/CSS pages
- **Code** — generates Python, JavaScript, TypeScript, Go, Rust, Bash, SQL, and more; observe-only validation (no fix cycle that corrupts working code)
- **Computer** — multi-file project generation with a persistent workspace, file tree explorer, and terminal execution with auto-fix loops
- **Auto** — routes automatically to the best mode based on message content

### Intelligence
- **Thinking support** — extended reasoning (`<think>` blocks) auto-enabled for supported models (Qwen3, DeepSeek R1, Nemotron Nano, Gemma 4); visible as a collapsible trace in the UI
- **Brain system** — compatibility adapter for legacy deliberation interface
- **Journal system** — learns from past interactions; injects relevant lessons into future prompts
- **LLM-refined conversation titles** — heuristic extraction followed by a fast AI-generated title, delivered via WebSocket after generation completes
- **Component cache** — thumbs-up on a Design or Code response automatically saves it to a searchable cache for future injection

### Web Search
- **DuckDuckGo integration** — toggle the search button in the chat composer to enable; no API key required
- **LLM query extraction** — the model reads your message (and recent conversation history) to extract a focused, de-pronominalized search query
- **Explicit mode** — prefix your message with `!search ` to supply the exact query yourself
- **Source tiering** — results sorted by domain quality (Reuters, BBC, Wikipedia, etc. prioritized; social/JS-heavy sites skipped for full-page fetch)
- **Injected context** — search results are formatted as a timestamped context block and injected before generation

### Workspaces & Computer Mode
- **Persistent workspaces** — named project workspaces stored on disk; survive across sessions
- **File tree** — browse, view, and open any file in a workspace directly from the UI
- **Context files** — popover in the chat composer lets you toggle specific workspace files to inject their full content into the prompt
- **Terminal execution** — run generated commands inside the workspace with a sandboxed check (`is_command_safe`) and stream output back to the UI
- **Workspace sidebar** — workspaces appear at the top of the sidebar; clicking opens them in Computer mode automatically

### Memory & History
- **SQLite conversation history** — all messages, routes, and feedback stored locally
- **Full-text search** — search across all past conversations from the sidebar
- **Session restore** — conversations grouped by time (Today / Yesterday / This Week / Older) in the sidebar; click to restore any session
- **Thumbs up / down feedback** — per-message; positive feedback on design/code responses auto-caches the output

### UI
- **Live HTML preview** — resizable split panel that streams rendered HTML as it generates; only opens for HTML output
- **Code syntax highlighting** — per-language highlighting with one-click copy button on all code blocks
- **Retry with versions** — regenerate any response; navigate between all prior versions with ← 1/2 → controls
- **Mode badges** — each conversation in the sidebar shows the mode it used
- **Stop generation** — cancel mid-stream; httpx connection closed immediately to stop wasting GPU cycles

### Infrastructure
- **Auto-download llama-server** — downloads the correct Vulkan or CUDA build on first start; no manual setup
- **In-place llama-server update** — Settings UI includes an update button that downloads and replaces the binary while the server is stopped
- **Background health monitor** — pings llama-server every 30 seconds; auto-restarts after 3 consecutive failures
- **Config rollback** — if a new model fails to load, the API automatically reverts `model_config.yaml` and restarts with the previous working model
- **KV cache management** — clears the llama-server KV cache between conversations and on context switches to prevent cross-contamination
- **AMD Vulkan safe shutdown** — 30-second graceful drain before SIGTERM to prevent GPU memory fragmentation

---

## Requirements

- **Python 3.11+**
- **Node.js 20+**
- **A GGUF model file** — any instruction-tuned model works; CT-2 is tested with:
  - [Qwen3-4B](https://huggingface.co/Qwen/Qwen3-4B-GGUF) — excellent balance of speed and quality, full thinking support
  - [Gemma 4 E4B](https://huggingface.co/google/gemma-4-e4b-it-GGUF) — Google's efficient 4B model
  - [NVIDIA Nemotron-Mini-4B](https://huggingface.co/nvidia/Nemotron-Mini-4B-Instruct-GGUF) — strong reasoning

> **Note:** Models without `<think>` support work but produce less consistent multi-step output. Models smaller than ~1.7B parameters are unreliable. Non-thinking models are not recommended.

> **Vision:** If your model has a paired multimodal projector (`mmproj-*.gguf` in the same directory), CT-2 detects it automatically and enables image attachment in the chat input.

---

## Quick Start

### 1. Clone and install dependencies

```bash
git clone https://github.com/StanTheGorilla/CT-2-WebUI.git
cd CT-2-WebUI

# Python backend
pip install -r ct1/requirements.txt

# Web frontend (optional — built automatically on first start)
cd ct1/web && npm install && cd ../..
```

### 2. Add a model

Place any instruction-tuned `.gguf` file in the `models/` directory:

```bash
# Example using huggingface-cli:
huggingface-cli download Qwen/Qwen3-4B-GGUF --local-dir models/
```

### 3. Start

```bash
python -m ct1.server.api
```

Open **http://localhost:8000** — go to **Settings** to select your model.

> On first start: the SvelteKit frontend is built automatically, and `llama-server` is downloaded for your GPU backend (Vulkan or CUDA). This takes a minute; subsequent starts are instant.

---

## Project Structure

```
CT-2-WebUI/
├── ct1/
│   ├── core/
│   │   ├── orchestrator.py    # Main pipeline (route → plan → generate → validate → refine)
│   │   ├── engine.py          # LLM interface (streaming, thinking, search query extraction)
│   │   ├── brain.py           # Legacy Brain compatibility adapter
│   │   ├── mind.py            # Legacy Mind compatibility adapter
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
│   │   ├── health.py          # Dead-process detection utilities
│   │   ├── downloader.py      # llama-server binary download + extraction
│   │   ├── workspace.py       # WorkspaceManager (file tree, read, execute)
│   │   ├── cache_policy.py    # KV cache clear decision logic
│   │   └── model_config.yaml  # Model and inference configuration
│   ├── memory/
│   │   ├── conversation_db.py # SQLite conversation + message storage
│   │   ├── journal.py         # Learning journal (lessons from past interactions)
│   │   ├── journal_reader.py  # Journal retrieval and stats
│   │   ├── session_store.py   # Session persistence
│   │   └── component_cache.py # Cached good design/code outputs
│   ├── modes/
│   │   ├── registry.py        # ModeRegistry: YAML loading, routing, hot-reload
│   │   ├── chat.yaml          # Chat mode (ROUTE_DIRECT)
│   │   ├── code.yaml          # Code mode (ROUTE_CODE)
│   │   ├── design.yaml        # Design mode (ROUTE_DESIGN)
│   │   └── computer.yaml      # Computer mode (ROUTE_COMPUTER)
│   ├── prompts/
│   │   ├── manager.py         # PromptManager (load, get, save, reset, hot-reload)
│   │   ├── brain_system.txt   # Brain inner-voice system prompt
│   │   ├── generator_*.txt    # Per-mode and per-task generator system prompts
│   │   ├── refine*.txt        # Refinement prompts (full, CSS-only, targeted)
│   │   └── ...                # All other system prompts editable via Settings
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
│               ├── components/           # UI components
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
backend: vulkan           # gpu backend: vulkan (AMD/Intel) or cuda (NVIDIA)
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
  computer:
    temperature: 0.25
    top_p: 0.8
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
┌─────────────────────────────────────────┐
│  ROUTE  (instant, no AI)                │
│  Keyword/regex classifier against       │
│  ct1/modes/*.yaml patterns.             │
│  Manual mode override skips this.       │
│                                         │
│  → ROUTE_DIRECT   (Chat)               │
│  → ROUTE_DESIGN   (Design)             │
│  → ROUTE_CODE     (Code)               │
│  → ROUTE_COMPUTER (Computer)           │
└──────────────────┬──────────────────────┘
                   │
         ┌─────────┴──────────┐
         │ Context detection  │  Is there previous code in the conversation?
         │                    │  Is this an edit, a question, or something new?
         └─────────┬──────────┘
                   │
     ┌─────────────┼─────────────┬──────────────┐
     ▼             ▼             ▼              ▼
  CHAT           DESIGN        CODE          COMPUTER
(see below)   (see below)  (see below)    (see below)
```

---

### Chat Mode  (`ROUTE_DIRECT`)

```
Message
  │
  │ [if web search toggle ON]
  ├──▶ LLM extracts focused search query from message + history
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
  ├─ Prose text (formatted)
  ├─ Code blocks → syntax highlighting + copy button
  ├─ Web search sources shown inline (if search ran)
  └─ Thinking trace (collapsible)
```

**Retry / versions:** regenerate produces a new version; navigate with ← 1/2 →

---

### Design Mode  (`ROUTE_DESIGN`) — New page

```
Message
  ▼
Phase 0 · Spec Generation
  │  engine.generate_spec() — structured JSON plan, thinking disabled for speed
  │  Output: { page_title, color_theme, layout_order, components[], interactions[] }
  │  UI shows: "Generating spec..."  (spec_generating phase)
  │
  ▼
Phase 0.5 · Spec Normalization & Validation  (mechanical, no AI)
  │  Strip invalid interaction names
  │  Normalize unknown component types → "custom"
  │  Validate required fields
  │  UI shows: spec card with component list  (spec_validated phase)
  │
  ▼
Phase 1 · HTML Generation  (streaming)
  │  engine.generate() with spec-guided prompt + Tailwind CDN instruction
  │  Temperature: 0.4  |  Full thinking enabled
  │  Complete single-file HTML page streamed token-by-token
  │  UI shows: live HTML preview panel rendering as tokens arrive
  │
  ▼
Phase 2 · Cleanup  (mechanical)
  │  strip_think_tags() → extract_code() → emit draft
  │
  ▼
Phase 3 · CSS-Only Refinement  (AI)
  │  Split HTML into sections (head / style / body / script)
  │  Extract only the <style> block (~2–5 KB)
  │  engine.refine_css_only() — model polishes spacing, colors, hover states
  │  Improved CSS reassembled back into page
  │  UI updates: preview refreshes with polished output  (polishing → polished)
  │
  ▼
Reflection  (lightweight AI, no streaming)
  │  _write_reflection() — self-score + lesson saved to journal
  ▼
Output
  ├─ Live resizable HTML preview panel (always open for Design)
  ├─ Download as index.html
  ├─ Spec card (page structure, components)
  └─ Thinking trace (collapsible)
```

**Design edit (follow-up message):**
```
Edit message detected (keyword match against _EDIT_INTENT set)
  ▼
Retrieve persisted spec from conversation history
  ▼
Identify target component(s) from edit text (id/type keyword match)
  ▼
For each target component:
  ├─ get_fallback(component_type) — deterministic HTML stub
  └─ patch_component_in_page() — surgical replacement in existing HTML
  ▼
Updated page → preview refreshes
```

---

### Code Mode  (`ROUTE_CODE`)

```
Message
  │
  ├─ [if question detected via LLM classifier] ──▶ Chat path (prose answer)
  │
  ├─ [if edit intent detected via keywords]
  │     ▼
  │   Edit path:
  │     For HTML: section-based edit (only regenerate body/style/script/head
  │               sections that the edit touches — preserves rest exactly)
  │     For other: full regeneration with previous code as context
  │     ──▶ streaming tokens ──▶ done
  │
  └─ [new code request]
       ▼
     Plan  (tier-aware)
       │  Large-tier models: always plan
       │  Medium-tier: only for complex requests (length > 80 chars or keywords)
       │  Small-tier: no plan (inline in system prompt)
       │  Output: { output_type, components[], complexity }
       │  UI shows: plan card
       ▼
     Cache injection
       │  Search component_cache for approved similar outputs
       │  Inject as [REFERENCE] prefix if found
       ▼
     Generate  (streaming)
       │  System prompt: generator_code.txt
       │  Temperature: 0.25  |  Top-p: 0.85  |  Presence penalty: 1.3
       │  Full thinking enabled
       │  Model declares output in fenced code block (```python, ```typescript…)
       ▼
     Format  (mechanical)
       │  Capture fence language tag → detected_lang
       │  Capture explanation prose written before the code fence
       │  clean_response() → strip think tags, extract code from fences
       │  Propagate output_type to plan for correct file extension badge
       ▼
     Validate  (observe-only — no fix cycle for Code mode)
       │  validate_output() — Python AST / JS brace / structural checks
       │  Issues logged but never trigger a forced rewrite
       │  Always emits validated
       ▼
     Self-review  (large-tier models only)
       │  Model checks its own output vs. original request
       │  If issues: one fix pass → replace response
       ▼
     Output
       ├─ Code block with syntax highlighting + copy button
       ├─ Language badge (Python / TypeScript / Go / Rust / …)
       ├─ Explanation text shown above code (if model wrote prose before the fence)
       ├─ Download button (correct extension per language)
       ├─ Plan card (output_type, complexity)
       └─ Thinking trace (collapsible)
```

**Atlas Mode** (optional — enabled per-request):
```
Estimate difficulty → Generate K candidates in parallel → Score each
→ Select best → Repair if needed → Continue to Format/Validate
Candidate 0 streams live; others run silently
```

---

### Computer Mode  (`ROUTE_COMPUTER`)

```
Message
  │
  ▼
Context injection  (before generation)
  ├─ Workspace file tree injected as [EXISTING WORKSPACE FILES] prefix
  │   (up to 60 files listed — model only outputs changed/new files)
  └─ User-selected context files injected in full
      (up to 20 files, 8 KB each, via context files popover in composer)
  ▼
Generate  (streaming)
  │  System prompt: generator_computer.txt
  │  Temperature: 0.25  |  Top-p: 0.8  |  Presence penalty: 1.3
  │  Model outputs multi-file format:
  │    [FILE: src/main.py]
  │    ...content...
  │    [FILE: templates/index.html]
  │    ...content...
  │    [RUN: python main.py]   ← optional run command marker
  ▼
Parse output
  │  _parse_multi_file() — splits by [FILE:] or <!-- FILE: --> markers
  │  _parse_run_commands() — extracts [RUN: command] markers
  │  fix_html_structure() applied to any .html files
  ▼
Validate  (with fix cycle for Computer mode)
  │  validate_file() per parsed file (HTML / Python / JS checks)
  │  If issues: generate fix pass → retry
  ▼
Save files to workspace
  │  Each file written to disk → emit("file_saved", path=...)
  │  File tree panel in UI refreshes automatically
  ▼
Commands (if model emitted [RUN: …] markers)
  │  emit("run_commands") → pending commands queue
  │  UI auto-switches to Terminal tab and shows Run buttons
  │  User clicks Run → command executes in workspace → output streams back
  ▼
Output
  ├─ File tree panel (left) — browse all workspace files
  ├─ File viewer (right) — click any file to read it
  ├─ Terminal panel — run commands, stream output
  ├─ Context files popover — pin specific files into next message's context
  └─ Saved file list on conversation turn (files metadata)
```

---

## Modes System

Each mode is a YAML file in `ct1/modes/`. The `ModeRegistry` auto-discovers and hot-reloads them. You can create custom modes via the API or by dropping a new YAML file.

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

Routing evaluates modes in priority order. `negative_patterns` prevent false positives (e.g., "write a Python script for a landing page" routes to Design, not Code, because `landing page` is a negative pattern for Code mode).

---

## Web Search

Web search is off by default. Enable it per-message with the search button in the chat composer.

**How it works:**
1. You send a message with web search enabled
2. The LLM reads your message and recent conversation history to extract a precise, standalone search query (resolves pronouns like "his", "it", "they")
3. CT-2 queries DuckDuckGo and retrieves up to 5 results
4. Results are sorted by source quality (news wires and encyclopaedic sources first; social media and JS-heavy sites skipped)
5. Snippets are formatted into a timestamped context block injected before your message
6. The model answers using up-to-date web information

**Explicit query mode:** Prefix your message with `!search ` to bypass LLM query extraction and use your exact text as the search query.

---

## Computer Mode & Workspaces

Computer mode generates multi-file projects into a named workspace on disk.

1. Click **+ New Project** in the sidebar (or the Projects section header)
2. Give it a name — CT-2 switches to Computer mode automatically
3. Describe what you want to build; CT-2 generates all necessary files
4. Browse generated files in the file tree panel; click any file to view it
5. Select specific files to inject as context using the context files popover in the chat input
6. Run commands via the terminal panel; output streams back in real time

Workspaces persist across sessions. Switching to a chat conversation clears the active workspace; selecting a workspace from the sidebar restores it.

---

## Prompts

All system prompts are editable at runtime from **Settings → Prompts** — no restart required for content changes. Each prompt is a `.txt` file in `ct1/prompts/`. You can reset any prompt to its shipped default with the Reset button.

Key prompts:

| Prompt | Purpose |
|--------|---------|
| `generator_text` | Chat mode system prompt |
| `generator_design` | Design mode generator |
| `generator_code` | Code mode generator |
| `generator_computer` | Computer mode generator |
| `refine` | Full-page design refinement |
| `refine_css` | CSS-only refinement pass |
| `brain_system` | Brain deliberation system prompt |
| `solo_plan` | Planning phase prompt |
| `spec_generator` | Design spec generation prompt |

---

## API Reference

### Server & Model

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/status` | llama-server health check |
| `GET` | `/api/config` | Full runtime configuration |
| `GET` | `/api/models` | List `.gguf` files with sizes, thinking support, vision, and context length |
| `GET` | `/api/model` | Active model name, capabilities, and context size |
| `POST` | `/api/model/select` | Select a model and restart llama-server; auto-rollback on failure |
| `POST` | `/api/backend/select` | Switch GPU backend (vulkan/cuda) and restart |
| `POST` | `/api/restart` | Restart current model with optional context_size override |
| `POST` | `/api/llama/update/{backend}` | Download latest llama-server binary for a backend |
| `GET` | `/api/llama/update/{backend}/status` | Poll download progress |

### Generation

| Method | Path | Description |
|--------|------|-------------|
| `WS` | `/ws/think` | Streaming generation WebSocket (send `think`, receive event stream) |
| `GET` | `/api/web-search` | Run a DuckDuckGo search and return structured results |

### Conversations & Memory

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/conversations` | List chat history (limit param) |
| `POST` | `/api/conversations` | Create new conversation |
| `GET` | `/api/conversations/{id}` | Get a conversation with all messages |
| `PATCH` | `/api/conversations/{id}` | Rename a conversation |
| `DELETE` | `/api/conversations/{id}` | Delete a conversation |
| `GET` | `/api/search` | Full-text search across all conversations |
| `POST` | `/api/messages/{id}/feedback` | Submit thumbs up/down; thumbs-up auto-caches design/code output |
| `GET` | `/api/journal` | List journal entries and stats |
| `GET` | `/api/sessions` | List saved sessions |

### Modes & Prompts

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/modes` | List all loaded mode definitions |
| `GET` | `/api/modes/{name}` | Get a single mode |
| `PUT` | `/api/modes/{name}` | Update mode config (patterns, overrides); reloads registry |
| `POST` | `/api/modes` | Create a new custom mode |
| `DELETE` | `/api/modes/{name}` | Delete a custom mode (built-in modes protected) |
| `GET` | `/api/prompts` | List all prompts with their content |
| `GET` | `/api/prompts/{name}` | Get a single prompt |
| `PUT` | `/api/prompts/{name}` | Update prompt content (persists to disk) |
| `POST` | `/api/prompts/{name}/reset` | Reset prompt to shipped default |

### Workspaces

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/workspaces` | List all workspaces |
| `POST` | `/api/workspaces` | Create a new workspace |
| `GET` | `/api/workspaces/{id}/files` | Get workspace file tree |
| `GET` | `/api/workspaces/{id}/files/{path}` | Read a file from the workspace |
| `POST` | `/api/workspaces/{id}/exec` | Execute a command in the workspace |

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
  "mode_override": "chat|design|code|computer|auto",
  "web_search": false,
  "context_files": ["path/to/file.py"],
  "workspace_id": "uuid",
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
| `done` | Generation complete (includes `detected_lang`, `files` metadata) |
| `error` | Error message |

Send `{"type": "cancel"}` at any time to stop the active generation immediately.

---

## Troubleshooting

**`llama-server` not found**
CT-2 auto-downloads it on first start. If that fails, download a [llama.cpp release](https://github.com/ggerganov/llama.cpp/releases) and place it in `bin/vulkan/` or `bin/cuda/` next to the project.

**No models listed in Settings**
Make sure your `.gguf` file is in the `models/` directory at the repo root. The filename must end in `.gguf`.

**Model loads but responses are empty or broken**
Some models require specific prompt templates. CT-2 uses ChatML by default. If you see empty responses, ensure your model is instruction-tuned and supports ChatML or the standard instruct format. Also check `thinking_budget` — set to `-1` for unlimited.

**GPU not used / slow generation**
Confirm `n_gpu_layers: 99` in `model_config.yaml`. Make sure you have the right backend selected in Settings: Vulkan for AMD/Intel, CUDA for NVIDIA. You can also trigger a binary update from Settings if you suspect an outdated `llama-server`.

**Port already in use**
Change `port` in `model_config.yaml` (default `8080` for llama-server, `8000` for the FastAPI server).

**AMD GPU — process hangs after stopping**
CT-2 includes a 30-second graceful Vulkan shutdown sequence. If `llama-server` still hangs after that: `taskkill /IM llama-server.exe /F` (Windows) or `pkill llama-server` (Linux/macOS).

**Model swap fails and server is left unresponsive**
CT-2 automatically reverts `model_config.yaml` to the previous working model and attempts a recovery restart. If recovery also fails, open Settings and manually select a different model.

**Web search not returning results**
DuckDuckGo may rate-limit heavy use. Wait a few minutes and retry. Alternatively, use the `!search` prefix to supply an exact query and skip AI query extraction.

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
