# CT-2

A local AI assistant powered by [llama.cpp](https://github.com/ggerganov/llama.cpp), with a modern web interface built in SvelteKit. Runs entirely on your machine — no API keys, no cloud, no telemetry.

CT-2 wraps a single local GGUF model in a multi-phase pipeline: deterministic routing → self-planning → generation → validation → optional refinement. The result is significantly better output quality than talking to the model directly.

---

## Features

- **Single-model architecture** — pick any `.gguf` file, capabilities auto-detected
- **Thinking support** — auto-enabled for models that support it (Qwen3, DeepSeek R1, Nemotron Nano)
- **5 generation modes** — Chat, Design, Code, Computer, Auto (with manual override)
- **Deterministic routing** — keyword-based classifier with per-mode YAML configuration, zero AI overhead for routing decisions
- **Modes system** — routes defined in `ct1/modes/*.yaml`, each with its own patterns, task overrides, and parameters
- **Brain system** — multi-voice inner deliberation for complex tasks, synthesized into a single confident response
- **Design pipeline** — structured spec → generate → validate → self-refine, produces clean HTML/CSS
- **Atlas Mode** *(beta)* — test-time compute scaling with multi-candidate generation and scoring
- **Computer Mode** — multi-file project generation with file tree, terminal execution, and auto-fix loops
- **PromptManager** — per-mode system prompt templates with variable injection
- **Conversation memory** — SQLite-backed chat history with search and session restore
- **Journal system** — learns from past interactions, injects relevant lessons into future prompts
- **URL fetching** — paste a URL in chat, content is fetched and injected into context
- **Retry with versions** — regenerate any response and navigate between all versions (← 1/2 →)
- **Context-aware from GGUF** — reads the actual max context length from model metadata headers
- **AMD Vulkan safe** — graceful llama-server shutdown to prevent GPU memory fragmentation on AMD cards

---

## Requirements

- **Python 3.11+**
- **Node.js 20+**
- **llama.cpp server** (`llama-server`) — downloaded automatically on first start
- **A GGUF model file** — any works, but CT-2 is tested with:
  - [Qwen3-4B](https://huggingface.co/Qwen/Qwen3-4B-GGUF) — best balance of speed and quality
  - [NVIDIA Nemotron-Mini-4B](https://huggingface.co/nvidia/Nemotron-Mini-4B-Instruct-GGUF) — strong reasoning

> **Note:** Models without `<think>` support work but produce less consistent output. Models smaller than ~1B parameters are unreliable.

---

## Quick Start

### 1. Clone & install dependencies

```bash
git clone https://github.com/StanTheGorilla/CT-2-WebUI.git
cd CT-2-WebUI

# Python backend
pip install -r ct1/requirements.txt

# Web frontend
cd ct1/web && npm install && cd ../..
```

### 2. Add a model

Place any `.gguf` file in the `models/` directory:

```bash
# Example using huggingface-cli:
huggingface-cli download Qwen/Qwen3-4B-GGUF --local-dir models/
```

### 3. Run

```bash
python -m ct1.server.api
```

Open **http://localhost:8000** — go to **Settings** and select your model.

> On first start: the frontend is built automatically, and llama-server is downloaded (Vulkan + CUDA builds). This takes a minute — subsequent starts are instant.

---

## Project Structure

```
ct2/
├── ct1/
│   ├── core/
│   │   ├── orchestrator.py    # Main pipeline (route → plan → generate → validate → refine)
│   │   ├── engine.py          # LLM interface (streaming, thinking, task overrides)
│   │   ├── brain.py           # Multi-voice deliberation system
│   │   ├── atlas.py           # Atlas Mode (multi-candidate test-time compute)
│   │   ├── formatter.py       # Deterministic output cleanup
│   │   ├── validator.py       # HTML/Python/JS structural validation
│   │   ├── assembler.py       # Precision-Design component assembly
│   │   ├── gguf_reader.py     # Reads context_length from GGUF headers
│   │   └── web_fetcher.py     # URL content extraction
│   ├── server/
│   │   ├── api.py             # FastAPI + WebSocket server
│   │   ├── launcher.py        # llama-server process management + health monitor
│   │   ├── health.py          # Dead-process detection and auto-recovery
│   │   └── model_config.yaml  # Model + inference configuration
│   ├── memory/
│   │   ├── conversation_db.py # SQLite conversation storage
│   │   ├── journal.py         # Learning journal (lessons from past interactions)
│   │   └── component_cache.py # Cached good design outputs
│   ├── modes/                 # Per-route YAML definitions
│   │   ├── chat.yaml          # Chat mode (ROUTE_DIRECT)
│   │   ├── code.yaml          # Code mode (ROUTE_CODE)
│   │   ├── design.yaml        # Design mode (ROUTE_DESIGN)
│   │   └── computer.yaml      # Computer mode (ROUTE_COMPUTER)
│   ├── prompts/               # System prompt templates
│   │   ├── brain_system.txt   # Brain inner-voice system prompt
│   │   └── ...                # Per-mode specialist prompts
│   ├── web/                   # SvelteKit frontend
│   │   ├── src/
│   │   │   ├── routes/        # +page.svelte (chat), settings/+page.svelte
│   │   │   └── lib/           # Components, stores, markdown renderer
│   │   └── package.json
│   └── requirements.txt
├── models/                    # Place .gguf files here (gitignored)
└── tests/
```

---

## Configuration

`ct1/server/model_config.yaml` — edit manually or via the Settings UI:

```yaml
executable: auto          # auto-discovers llama-server
models_dir: models        # directory containing .gguf files
active_model: null        # set via Settings UI

port: 8080                # llama-server port
n_gpu_layers: 99          # GPU offload (99 = all layers)
context_size: 32768       # context window (capped by model's GGUF max)

temperature: 0.6
top_p: 0.9
top_k: 40
presence_penalty: 1.0
thinking_budget: -1       # -1 = unlimited thinking tokens
```

---

## How the Pipeline Works

```
User Message
    │
    ▼
┌─────────────────┐
│  ROUTE (0ms)    │  Deterministic keyword classifier — no AI call
│  design/code/   │  Rules defined in ct1/modes/*.yaml
│  computer/chat  │
└────────┬────────┘
         ▼
┌─────────────────┐
│  BRAIN          │  Multi-voice inner deliberation (complex tasks)
│  deliberation   │  Simple tasks answered directly
└────────┬────────┘
         ▼
┌─────────────────┐
│  PLAN           │  Lightweight JSON spec (output type, components)
│                 │  Design mode: full page structure spec
└────────┬────────┘
         ▼
┌─────────────────┐
│  GENERATE       │  Full streaming response with thinking
│  (streaming)    │  Section-based editing for HTML modifications
└────────┬────────┘
         ▼
┌─────────────────┐
│  VALIDATE       │  Structural checks (HTML tags, Python AST, JS syntax)
│  + FORMAT       │  Deterministic cleanup, repetition trimming
└────────┬────────┘
         ▼
┌─────────────────┐
│  REFINE (opt)   │  Self-refinement pass (design mode only)
│                 │  Improves spacing, colors, hover states
└─────────────────┘
```

**Atlas Mode** (optional) runs multiple candidates in parallel, scores them, and selects the best:
```
Generate K candidates → Score each → Select best → Repair if needed
```

---

## Modes System

Each mode is defined in `ct1/modes/<name>.yaml`:

```yaml
name: code
route_id: ROUTE_CODE
description: Code generation, debugging, refactoring
priority: 3
patterns:
  - write\s+(?:\w+\s+){0,4}(?:function|class|script|...)
  - implement\b
  - debug\b
task_overrides:
  temperature: 0
  top_p: 1
  presence_penalty: 1.3
```

You can add new modes by creating YAML files in `ct1/modes/`. The router auto-discovers them.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/models` | List available `.gguf` files with sizes and capabilities |
| `GET` | `/api/model` | Current active model info |
| `POST` | `/api/model/select` | Select a model and restart llama-server |
| `POST` | `/api/restart` | Restart with optional context_size |
| `GET` | `/api/config` | Full runtime configuration |
| `GET` | `/api/status` | Server health (model loaded, GPU layers, context size) |
| `WS` | `/ws/think` | Streaming generation WebSocket |
| `GET` | `/api/conversations` | List chat history |
| `POST` | `/api/conversations` | Create new conversation |
| `GET` | `/api/conversations/:id/messages` | Load a conversation |
| `POST` | `/api/messages/:id/feedback` | Submit thumbs up/down feedback |
| `GET` | `/api/workspaces` | List computer-mode workspaces |
| `POST` | `/api/workspaces` | Create a new workspace |

---

## Troubleshooting

**`llama-server` not found**
CT-2 auto-downloads it on first start. If that fails, download a [llama.cpp release](https://github.com/ggerganov/llama.cpp/releases) and place it in your PATH or in a folder named `llama-*-bin-*` next to the project.

**No models listed in Settings**
Make sure your `.gguf` file is in the `models/` directory at the repo root. The filename must end in `.gguf`.

**GPU not used / slow generation**
Check `n_gpu_layers` in `model_config.yaml` — set to `99` to offload all layers. Make sure you have the correct llama.cpp build for your GPU (Vulkan for AMD/Intel, CUDA for NVIDIA).

**Port already in use**
Change `port` in `model_config.yaml` (default `8080` for llama-server, `8000` for the API).

**AMD GPU — process hangs after stopping**
CT-2 includes a graceful Vulkan shutdown sequence. If `llama-server` still hangs: `taskkill /IM llama-server.exe /F` (Windows) or `pkill llama-server` (Linux/macOS).

**Model loads but generation is empty**
Some models require specific prompt templates. CT-2 uses the ChatML format by default. If you see empty responses, check that your model supports ChatML or instruction-tuned input.

---

## License

MIT

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit your changes
4. Push and open a Pull Request

Run tests before submitting: `pytest tests/`
