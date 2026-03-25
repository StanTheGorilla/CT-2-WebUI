# Solo Adaptive Pipeline Design

**Date:** 2026-03-25
**Status:** Approved
**Goal:** Replace dual-model cooperative system with a single-model adaptive pipeline that scales pipeline depth based on model capability tier.

---

## Positioning

This project is an open-source local AI web UI. The goal is to visibly outperform LM Studio, Ollama, and similar tools that pass raw prompts with no orchestration. The adaptive pipeline is the differentiator -- intelligent orchestration that scales to the model's capability.

## Architecture Overview

### What Changes

- Dual-model system (4B Director + 2B Specialist) replaced by single-model pipeline
- `specialist.py` deleted. `director.py` refactored into generic `Engine` class
- One llama-server process, one port, one model loaded at a time
- Preset system flattened from `{director, specialist}` to single model block per preset
- Pipeline depth adapts based on detected tier (small/medium/large)

### Pipeline Flow

```
User message
  -> Deterministic route (keyword/regex, no AI call, all tiers)
  -> [Medium/Large only] Planning call if complex
  -> Generate (system prompt varies by mode + tier)
  -> [Large only] Self-review pass
  -> Deterministic format/validate
  -> Response
```

### Tier Detection

1. Check `tier:` field in active preset config -> use if present
2. Else parse model filename with regex: `/(\d+\.?\d*)[Bb]/` -> extract param count
3. Map: <=8B -> small, 8B-30B -> medium, >30B -> large
4. If parsing fails and no override -> default to **small** (fail safe, not fail ambitious)

### Tier Behavior Matrix

| Phase    | Small (<=8B)            | Medium (8-30B)          | Large (30B+)                  |
|----------|-------------------------|-------------------------|-------------------------------|
| Route    | Deterministic           | Deterministic           | Deterministic                 |
| Plan     | Inline in system prompt | One call if complex     | Always plan                   |
| Generate | Direct                  | Direct                  | Direct                        |
| Review   | Inline in system prompt | Inline in system prompt | Separate review pass          |
| Validate | Deterministic (formatter) | Deterministic (formatter) | Deterministic + AI review |

---

## Mode System Prompts

Four modes, each with a rebuilt system prompt:

### Direct Mode -- General-purpose conversational AI
- **Scope:** Essays, explanations, summarization, research, analysis, creative writing, Q&A, translation, brainstorming, debate, comparison -- anything conversational
- **Prompt structure:** Role definition -> task decomposition instructions (identify -> plan -> execute) -> output format guidelines (adapt length/structure to request) -> quality constraints (no fabrication, cite reasoning)
- **No artificial constraints** on topic or length
- **Temperature:** 0.5 (small tier), 0.6 (medium/large tier)

### Design Mode -- Single-file web designs
- **Scope:** Complete HTML files with inline CSS/JS. Landing pages, dashboards, portfolios, UI mockups
- **Prompt structure:** Role (visual designer + frontend engineer) -> design principles (hierarchy, whitespace, typography, color theory) -> technical constraints (single file, inline everything, responsive, accessible) -> output format (raw HTML, no markdown fences, no explanations)
- **Temperature:** 0.4

### Code Mode -- Code in conversation
- **Scope:** Write, explain, debug, refactor code. Output is code blocks in chat. Any language.
- **Prompt structure:** Role (senior developer) -> task decomposition -> output format (code blocks with language tags, explanations before/after) -> quality constraints (complete working code, handle edge cases, follow language idioms)
- **Temperature:** 0.25

### Computer Mode -- Agentic workspace
- **Scope:** Multi-file projects on disk. Create directories, write files, run commands, test, iterate.
- **Prompt structure:** Role (project engineer) -> file format markers (`[FILE: path]`, `[RUN: cmd]`) -> project planning instructions (list files first, then implement) -> execution constraints (test after writing, fix errors)
- **Temperature:** 0.25

### Tier-Specific Prompt Additions
- **Small:** Append inline planning + verification block to every mode's prompt
- **Medium:** Append verification block only (planning is a separate call)
- **Large:** Minimal additions (planning and review are separate pipeline steps)

---

## Deterministic Routing

Keyword/regex matching, no AI call, all tiers. Evaluated top to bottom, first match wins:

1. **Mode override** -- User selected a mode pill -> use that route directly
2. **ROUTE_COMPUTER** -- File operations, project creation, terminal commands (`create a project`, `build a website`, `write to file`, `run command`, `mkdir`, `multi-file`, `full project`). Requires active workspace OR explicit project language.
3. **ROUTE_DESIGN** -- Single-file visual design (`design`, `landing page`, `dashboard`, `portfolio`, `webpage`, `UI`, `mockup`). Excludes questions about design (`explain`, `how does`, `what is`).
4. **ROUTE_CODE** -- Code generation/discussion (`write a function`, `implement`, `debug`, `refactor`, `fix this code`, language names + action verbs, code fences in input).
5. **ROUTE_DIRECT** -- Default fallback. Everything else.

**Ambiguity rules:**
- Ambiguous visual vs code -> ROUTE_DESIGN (prefer visual output)
- Questions about code -> ROUTE_DIRECT (conversation, not generation)
- "Explain this code" + code block -> ROUTE_CODE (code context present)

---

## Quality Mechanisms

### 1. Inline Self-Verification (all tiers)
Every system prompt ends with:
```
Before finalizing your response, verify:
- Does the output fully address every part of the request?
- [Mode-specific checks]
- Is anything missing, incomplete, or placeholder?
If any check fails, fix it before responding.
```
Zero extra inference -- executes in thinking tokens.

### 2. Few-Shot Examples (small tier only)
1-2 short structural examples in system prompt for design and code modes. Under 200 tokens each. Structural templates, not content. Skipped if context budget too tight (Qwen 2B 4K).

### 3. Defensive Output Parsing (all tiers)
Unconditionally applied regardless of system prompt compliance:
- Strip markdown fences from design/code output
- Strip preamble ("Here's your code:", "Sure, here is...")
- Strip postamble ("Let me know if you need...")
- Validate HTML structure (balanced tags)
- Design mode: inject `box-sizing: border-box` and viewport meta if missing

### 4. Computer Mode Format Enforcement (all tiers)
If model output contains code but no `[FILE:]` markers in computer mode, wrap in default marker based on detected language.

### 5. Context Budget Management (small tier)
- Keep system prompt + current user message always
- Truncate oldest conversation turns first
- Never truncate mid-turn (keep user+assistant pairs intact)
- Reserve at least `max_tokens` space for response

---

## Model Configuration

### Preset Structure (new)
```yaml
executable: F:/AI_Workstation/ct/llama-b8292-bin-win-vulkan-x64/llama-server.exe
models_dir: models
active_preset: qwen4b-q6

presets:
  qwen4b:
    name: Qwen 3.5 4B
    model: Qwen3.5-4B-Q3_K_S.gguf
    port: 8080
    n_gpu_layers: 99
    context_size: 16384
    enable_thinking: true
    tier: null  # auto -> small
    task_overrides:
      design: { temperature: 0.4 }
      code: { temperature: 0.25 }
      computer: { temperature: 0.25 }
      direct: { temperature: 0.5 }
```

Each of the 5 models gets its own preset block.

### Settings Persistence
- User-modified settings (context size, temperature overrides) save per preset
- Persist across sessions in localStorage
- Context size slider: universal minimum floor to preset max, default at max
- Changing context size requires explicit restart (notice + button, no silent restarts)

---

## Model Compatibility

All 5 models work with all 4 modes. No model-specific code paths.

| Model | File | Size | Tier | Context | Thinking |
|-------|------|------|------|---------|----------|
| Qwen 3.5 4B Q3 | Qwen3.5-4B-Q3_K_S.gguf | 2.7GB | small | 16K | yes |
| Qwen 3.5 4B Q6 Distilled | Qwen3.5-4B.Q6_Kdistiled.gguf | 3.4GB | small | 16K | yes |
| Nemotron 4B Q8 | NVIDIA-Nemotron-3-Nano-4B-Q8_0.gguf | 4.2GB | small | 65K | yes |
| Nemotron 4B Q4 | NVIDIA-Nemotron-3-Nano-4B-Q4_K_M.gguf | 2.8GB | small | 65K | yes |
| Qwen 3.5 2B Q4 | Qwen3.5-2B.Q4_K_M.gguf | 1.3GB | small | 4K | no |

All current models are small tier. Medium/large tiers activate when users add bigger models.

### Frontend Changes
- Single "Model" status indicator (replaces Director/Specialist pair)
- Preset selector showing all models
- Context size slider per preset
- Per-preset settings persistence
- "Restart required" notice + restart button

---

## Files Affected

### Delete
- `ct1/core/specialist.py` -- replaced by single-model pipeline

### Major Refactor
- `ct1/core/director.py` -> rename to `engine.py`, generic model interface
- `ct1/core/orchestrator.py` -- replace 6-phase dual-model pipeline with adaptive tier pipeline
- `ct1/server/model_config.yaml` -- flatten presets, add tier field
- `ct1/server/launcher.py` -- single-process launch, tier detection
- `ct1/server/api.py` -- remove specialist health checks, update preset endpoints

### Moderate Changes
- `ct1/core/formatter.py` -- ensure defensive parsing runs unconditionally
- `ct1/web/src/lib/stores/chat.ts` -- remove specialist events, add per-preset persistence
- `ct1/web/src/routes/settings/+page.svelte` -- context slider, single model status, restart button
- `ct1/web/src/lib/components/ChatInput.svelte` -- remove "solo" mode pill if present
- `ct1/web/src/routes/+layout.svelte` -- update phase indicators

### Minor/No Change
- `ct1/core/formatter.py` -- existing logic mostly preserved
- `ct1/core/validator.py` -- deterministic validation unchanged
- `ct1/core/assembler.py` -- unchanged
- `ct1/web/src/lib/components/PreviewPanel.svelte` -- visual preview unchanged
- `ct1/web/src/lib/components/TerminalPanel.svelte` -- terminal unchanged
- `ct1/web/src/lib/components/FileTree.svelte` -- file tree unchanged
