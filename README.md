# CT-2 — Consciousness Testbed

A local AI assistant powered by [llama.cpp](https://github.com/ggerganov/llama.cpp), with a modern web interface built in SvelteKit. Runs entirely on your machine — no API keys, no cloud, no telemetry.

CT-2 wraps a single local GGUF model in a multi-phase pipeline: deterministic routing → self-planning → generation → validation → formatting. The result is significantly better output quality than talking to the model raw.

---

## Features

- **Single-model architecture** — pick any `.gguf` file, capabilities auto-detected
- **Thinking support** — auto-enabled for models that support it (Qwen3, Nemotron Nano, DeepSeek R1)
- **4 generation modes** — Design (HTML pages), Code (scripts), Computer (multi-file projects), Chat
- **Deterministic routing** — keyword-based classifier, zero AI overhead for routing decisions
- **Section-based editing** — edits only the affected HTML section, preserves everything else
- **Design pipeline** — structured spec → generate → validate → self-refine
- **Atlas Mode** *(beta)* — test-time compute scaling with multi-candidate generation
- **Computer Mode** — multi-file project generation with terminal execution and auto-fix loops
- **Conversation memory** — SQLite-backed chat history with search
- **Journal system** — learning from past interactions
- **URL fetching** — paste URLs in chat, content is fetched and injected into context
- **Context from GGUF** — reads the actual max context length from model metadata
- **AMD Vulkan safe** — graceful llama-server shutdown to prevent GPU memory fragmentation

---

## Requirements

- **Python 3.11+**
- **Node.js 20+**
- **llama.cpp server** (`llama-server`) — [download a release](https://github.com/ggerganov/llama.cpp/releases)
- **A GGUF model file** — any model works, but CT-2 is tested with:
  - [Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B-GGUF) — best balance of speed and quality
  - [NVIDIA Nemotron-3-Nano-4B](https://huggingface.co/nvidia/Nemotron-3-Nano-4B-Instruct-GGUF) — excellent with thinking enabled
  - [Qwen3.5-2B](https://huggingface.co/Qwen/Qwen3.5-2B-GGUF) — fastest, lowest VRAM

---

## Quick Start

### 1. Clone & install dependencies

```bash
git clone [https://github.com/YOUR_USERNAME/ct2.git](https://github.com/StanTheGorilla/CT-2.git)
cd ct2

# Python backend
pip install -r ct1/requirements.txt

# Web frontend
cd ct1/web && npm install && cd ../..
```

### 2. Get llama-server

CT-2 downloads `llama-server` automatically on first startup (both Vulkan and CUDA builds). You can switch between backends in the Settings UI.

If you prefer to manage it manually, download a [llama.cpp release](https://github.com/ggerganov/llama.cpp/releases) and place it in your PATH or next to the project directory.

### 3. Add a model

Place any `.gguf` file in the `models/` directory:

```bash
# Example using huggingface-cli:
huggingface-cli download Qwen/Qwen3.5-4B-GGUF --local-dir models/
```

### 4. Run

```bash
# Terminal 1 — backend
python -m ct1.server.api

# Terminal 2 — web UI
cd ct1/web && npm run dev
```

Open **http://localhost:5173** — go to **Settings** and select your model.

---

## Project Structure

```
ct2/
├── ct1/
│   ├── core/
│   │   ├── orchestrator.py   # 6-phase pipeline (route → plan → generate → validate → format)
│   │   ├── engine.py         # LLM interface (streaming, thinking, task overrides)
│   │   ├── atlas.py          # Atlas Mode (multi-candidate test-time compute)
│   │   ├── formatter.py      # Deterministic output cleanup
│   │   ├── validator.py      # HTML/Python/JS structural validation
│   │   ├── gguf_reader.py    # Reads context_length from GGUF headers
│   │   └── web_fetcher.py    # URL content extraction
│   ├── server/
│   │   ├── api.py            # FastAPI + WebSocket server
│   │   ├── launcher.py       # llama-server process management
│   │   └── model_config.yaml # Model configuration
│   ├── memory/
│   │   ├── conversation_db.py # SQLite conversation storage
│   │   ├── journal.py        # Learning journal
│   │   └── component_cache.py # Cached good outputs
│   ├── web/                  # SvelteKit frontend
│   │   ├── src/
│   │   │   ├── routes/       # Pages (chat, settings)
│   │   │   └── lib/          # Components, stores, utilities
│   │   └── package.json
│   ├── prompts/              # System prompt templates
│   ├── templates/            # Fallback HTML templates
│   └── requirements.txt
├── models/                   # Place .gguf files here (gitignored)
└── tests/
```

---

## Configuration

`ct1/server/model_config.yaml` — edit manually or use the Settings UI:

```yaml
executable: auto          # auto-discovers llama-server
models_dir: models        # directory containing .gguf files
active_model: null        # set via Settings UI or manually

port: 8080                # llama-server port
n_gpu_layers: 99          # GPU offload layers (99 = all)
context_size: 32768       # context window (capped by GGUF max)

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
│  design/code/   │
│  computer/chat  │
└────────┬────────┘
         ▼
┌─────────────────┐
│  PLAN           │  Engine self-planning (lightweight JSON)
│  spec / tasks   │  Design mode: structured page spec
└────────┬────────┘
         ▼
┌─────────────────┐
│  GENERATE       │  Full response with thinking, streaming
│  (streaming)    │  Section-based editing for HTML edits
└────────┬────────┘
         ▼
┌─────────────────┐
│  VALIDATE       │  Structural checks (HTML tags, Python AST)
│  + FORMAT       │  Deterministic cleanup, repetition trimming
└────────┬────────┘
         ▼
┌─────────────────┐
│  REFINE (opt)   │  Self-refinement pass (design mode)
│                 │  Fixes spacing, colors, hover states
└─────────────────┘
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/models` | List available `.gguf` files with sizes and capabilities |
| `GET` | `/api/model` | Current active model info |
| `POST` | `/api/model/select` | Select a model and restart server |
| `POST` | `/api/restart` | Restart with optional context_size |
| `GET` | `/api/config` | Full runtime configuration |
| `GET` | `/api/status` | Server health check |
| `WS` | `/ws/think` | Streaming generation WebSocket |
| `GET` | `/api/conversations` | List chat history |
| `POST` | `/api/conversations` | Create new conversation |

---

## Troubleshooting

**`llama-server` not found**
CT-2 searches for `llama-server` in PATH and in folders named `llama-*-bin-*` next to the project. Either add it to PATH or place the extracted llama.cpp folder next to `ct2/`.

**No models listed in Settings**
Make sure your `.gguf` file is in the `models/` directory at the repo root. The filename must end in `.gguf`.

**GPU not used / slow generation**
Check `n_gpu_layers` in `model_config.yaml` — set to `99` to offload all layers. Make sure you downloaded the correct llama.cpp build for your GPU (Vulkan for AMD/Intel, CUDA for NVIDIA).

**Port already in use**
Change `port` in `model_config.yaml` (default `8080` for llama-server, `8000` for the API). The web UI port (`5173`) can be changed in `ct1/web/vite.config.js`.

**AMD GPU — process hangs after stopping**
CT-2 includes a graceful Vulkan shutdown sequence. If `llama-server` still hangs, kill it manually: `taskkill /IM llama-server.exe /F` (Windows) or `pkill llama-server` (Linux/macOS).

---

## License

MIT

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit your changes
4. Push and open a Pull Request

Run tests before submitting: `pytest tests/`
