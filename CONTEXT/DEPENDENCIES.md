# DEPENDENCIES — CT-2 WebUI

## Python (ct1/)

| Package | Version | Purpose |
| --- | --- | --- |
| `ddgs` | ≥9.0.0 | DuckDuckGo web search (renamed from `duckduckgo-search`) |
| `httpx` | — | Async HTTP client for URL fetching |
| `trafilatura` | — | Primary HTML→text extractor |
| `beautifulsoup4` | — | Fallback HTML parser + title extraction |
| `fastapi` | — | API + WebSocket server |
| `ctranslate2` | — | LLM inference backend |
| `anyio` / `asyncio` | stdlib | Async task management |

## Frontend (ct1/web/)

| Package | Purpose |
| --- | --- |
| SvelteKit 5 | App framework (runes: `$state`, `$derived`, `$effect`) |
| TypeScript | Type safety |
| Vite | Build tool |

## Key env / runtime

- llama-server (llama.cpp) spawned as subprocess by `ct1/server/launcher.py`
- `ct1/server/model_config.yaml` — model list, capability flags
- AMD GPU via Vulkan backend (no CUDA); VRAM fragmentation risk on hard shutdown

## Notes
- `ddgs` import: `from ddgs import DDGS` (NOT `duckduckgo_search`)
- `test_evolution.py` requires `ct1.evolution` module (not present); skip with `--ignore`
