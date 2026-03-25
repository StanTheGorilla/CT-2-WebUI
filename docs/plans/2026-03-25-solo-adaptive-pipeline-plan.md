# Solo Adaptive Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the dual-model (Director+Specialist) cooperative system with a single-model adaptive pipeline where pipeline depth scales with model capability tier.

**Architecture:** One llama-server process, one model. Deterministic keyword routing (no AI routing call). Three pipeline tiers (small/medium/large) auto-detected from GGUF filename. All 5 models work with all 4 modes.

**Tech Stack:** Python (FastAPI, httpx), Svelte 5, TypeScript, llama.cpp server, YAML config

**Design doc:** `docs/plans/2026-03-25-solo-adaptive-pipeline-design.md`

---

## Task 1: Tier Detection Module

**Files:**
- Create: `ct1/core/tier.py`
- Test: manual — `python -c "from ct1.core.tier import detect_tier; ..."`

**Step 1: Create tier detection module**

```python
# ct1/core/tier.py
"""Model tier detection from GGUF filename or explicit config."""
import re

TIERS = ("small", "medium", "large")

def detect_tier(model_filename: str, explicit_tier: str | None = None) -> str:
    """Detect model tier.

    Priority:
    1. Explicit tier from config (if set)
    2. Parse parameter count from filename
    3. Default to 'small' (fail safe)

    Tier mapping:
      <= 8B  -> small
      8-30B  -> medium
      > 30B  -> large
    """
    if explicit_tier and explicit_tier in TIERS:
        return explicit_tier

    match = re.search(r'(\d+\.?\d*)\s*[Bb]', model_filename)
    if match:
        params_b = float(match.group(1))
        if params_b <= 8:
            return "small"
        elif params_b <= 30:
            return "medium"
        else:
            return "large"

    # Fail safe — never default to large
    return "small"
```

**Step 2: Verify it works**

Run: `cd F:/AI_Workstation/web-ui && python -c "from ct1.core.tier import detect_tier; print(detect_tier('Qwen3.5-4B-Q3_K_S.gguf')); print(detect_tier('NVIDIA-Nemotron-3-Nano-4B-Q8_0.gguf')); print(detect_tier('some-70B-model.gguf')); print(detect_tier('weird-name.gguf')); print(detect_tier('x.gguf', 'large'))"`

Expected:
```
small
small
large
small
large
```

**Step 3: Commit**

```bash
git add ct1/core/tier.py
git commit -m "feat: add tier detection module for adaptive pipeline"
```

---

## Task 2: Restructure model_config.yaml

**Files:**
- Modify: `ct1/server/model_config.yaml` (full rewrite)

**Step 1: Rewrite config with flat preset structure**

Replace the entire file with this new structure. Each model gets its own preset. No `director`/`specialist` nesting — flat model block per preset.

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
    parallel_slots: 1
    context_size: 16384
    enable_thinking: true
    tier: null
    temperature: 0.6
    top_p: 0.9
    top_k: 40
    presence_penalty: 1.0
    max_tokens: 100000
    vision_supported: false
    task_overrides:
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

  qwen4b-q6:
    name: Qwen 3.5 4B Q6 Distilled
    model: Qwen3.5-4B.Q6_Kdistiled.gguf
    port: 8080
    n_gpu_layers: 99
    parallel_slots: 1
    context_size: 16384
    enable_thinking: true
    tier: null
    temperature: 0.6
    top_p: 0.9
    top_k: 40
    presence_penalty: 1.0
    max_tokens: 100000
    vision_supported: false
    task_overrides:
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

  nemotron-q8:
    name: Nemotron 4B Q8
    model: NVIDIA-Nemotron-3-Nano-4B-Q8_0.gguf
    port: 8080
    n_gpu_layers: 99
    parallel_slots: 1
    context_size: 65536
    enable_thinking: true
    thinking_budget: 36864
    tier: null
    temperature: 0.7
    top_p: 0.95
    top_k: 40
    presence_penalty: 1.2
    frequency_penalty: 0.3
    max_tokens: 100000
    vision_supported: false
    task_overrides:
      design:
        temperature: 0.4
        thinking_budget: 36864
      code:
        temperature: 0.25
        top_p: 0.9
        thinking_budget: 36864
      computer:
        temperature: 0.25
        top_p: 0.85
        thinking_budget: 36864
      direct:
        temperature: 0.6
        top_p: 0.95

  nemotron-q4:
    name: Nemotron 4B Q4
    model: NVIDIA-Nemotron-3-Nano-4B-Q4_K_M.gguf
    port: 8080
    n_gpu_layers: 99
    parallel_slots: 1
    context_size: 65536
    enable_thinking: true
    thinking_budget: 36864
    tier: null
    temperature: 0.7
    top_p: 0.95
    top_k: 40
    presence_penalty: 1.2
    frequency_penalty: 0.3
    max_tokens: 100000
    vision_supported: false
    task_overrides:
      design:
        temperature: 0.4
        thinking_budget: 36864
      code:
        temperature: 0.25
        top_p: 0.9
        thinking_budget: 36864
      computer:
        temperature: 0.25
        top_p: 0.85
        thinking_budget: 36864
      direct:
        temperature: 0.6
        top_p: 0.95

  qwen2b:
    name: Qwen 3.5 2B
    model: Qwen3.5-2B.Q4_K_M.gguf
    port: 8080
    n_gpu_layers: 99
    parallel_slots: 1
    context_size: 4096
    enable_thinking: false
    tier: small
    temperature: 0.5
    top_p: 0.9
    top_k: 40
    presence_penalty: 1.0
    max_tokens: 4000
    vision_supported: false
    task_overrides:
      design:
        temperature: 0.4
      code:
        temperature: 0.25
      computer:
        temperature: 0.25
      direct:
        temperature: 0.4

journal:
  path: ct1/data/journals
  lessons_on_startup: 10
sessions:
  path: ct1/data/sessions
```

**Step 2: Verify YAML parses**

Run: `cd F:/AI_Workstation/web-ui && python -c "import yaml; d = yaml.safe_load(open('ct1/server/model_config.yaml')); print(list(d['presets'].keys())); print('OK')"`

Expected: `['qwen4b', 'qwen4b-q6', 'nemotron-q8', 'nemotron-q4', 'qwen2b']` then `OK`

**Step 3: Commit**

```bash
git add ct1/server/model_config.yaml
git commit -m "refactor: flatten preset config to single-model structure"
```

---

## Task 3: Update launcher.py for flat config

**Files:**
- Modify: `ct1/server/launcher.py`

**Step 1: Rewrite `resolve_config()` to handle flat presets**

The new config has no `director`/`specialist` nesting. Each preset is a flat model block. `resolve_config()` must read the flat structure and produce the same output format the rest of the system expects (under `llama_server` and `models.director` keys for backward compat with Orchestrator).

Replace `resolve_config()` (lines 35-109) with:

```python
def resolve_config(raw_cfg: dict, config_path: str = None) -> dict:
    """Resolve active preset into flat config format expected by Orchestrator/API."""
    preset_name = raw_cfg.get("active_preset", "qwen4b-q6")
    presets = raw_cfg.get("presets", {})

    if preset_name not in presets:
        raise ValueError(f"Unknown preset: {preset_name}")

    preset = presets[preset_name]
    executable = raw_cfg.get("executable", "")
    models_dir_rel = raw_cfg.get("models_dir", "models")

    # Resolve models_dir relative to project root
    if config_path:
        project_root = Path(config_path).resolve().parent.parent.parent
    else:
        project_root = Path.cwd()
    models_dir = project_root / models_dir_rel

    # Flat preset: model config is at top level, not under "director"
    # Support both old (nested) and new (flat) formats during migration
    if "director" in preset:
        model_cfg = preset["director"]
    else:
        model_cfg = preset

    result = {
        "llama_server": {
            "executable": executable,
            "model": str(models_dir / model_cfg["model"]),
            "port": model_cfg["port"],
            "n_gpu_layers": model_cfg.get("n_gpu_layers", 99),
            "parallel_slots": model_cfg.get("parallel_slots", 1),
            "context_size": model_cfg.get("context_size", 16384),
            "cont_batching": model_cfg.get("cont_batching", False),
        },
        "models": {
            "director": {
                "enable_thinking": model_cfg.get("enable_thinking", True),
                "temperature": model_cfg.get("temperature", 0.6),
                "top_p": model_cfg.get("top_p", 0.9),
                "top_k": model_cfg.get("top_k", 40),
                "presence_penalty": model_cfg.get("presence_penalty", 0),
                "frequency_penalty": model_cfg.get("frequency_penalty", 0),
                "max_tokens": model_cfg.get("max_tokens", 100000),
                "thinking_budget": model_cfg.get("thinking_budget", -1),
                "vision_supported": model_cfg.get("vision_supported", False),
            },
        },
        "journal": raw_cfg.get("journal", {}),
        "sessions": raw_cfg.get("sessions", {}),
        "_preset": preset_name,
        "_preset_info": {
            "name": preset.get("name", preset_name),
            "description": preset.get("description", ""),
            "model_file": model_cfg["model"],
            "tier": preset.get("tier"),
        },
        "_task_overrides": model_cfg.get("task_overrides", {}),
    }

    # No specialist in new config format
    # Support old format during migration
    if "specialist" in preset:
        specialist = preset["specialist"]
        result["llama_server_specialist"] = {
            "executable": executable,
            "model": str(models_dir / specialist["model"]),
            "port": specialist["port"],
            "n_gpu_layers": specialist.get("n_gpu_layers", 99),
            "parallel_slots": specialist.get("parallel_slots", 1),
            "context_size": specialist.get("context_size", 4096),
            "cont_batching": specialist.get("cont_batching", False),
        }
        result["models"]["specialist"] = {
            "enable_thinking": specialist.get("enable_thinking", False),
            "temperature": specialist.get("temperature", 0.1),
            "top_p": specialist.get("top_p", 0.9),
            "top_k": specialist.get("top_k", 10),
            "max_tokens": specialist.get("max_tokens", 1024),
        }

    return result
```

Also update `start_server()` (lines 150-163): Remove the specialist launch branch since new presets won't have one. Keep backward compat print for solo mode.

```python
async def start_server(config_path: str = "ct1/server/model_config.yaml") -> list:
    kill_existing_llama_servers()
    cfg = load_config(config_path)

    proc = await _launch_one(cfg["llama_server"])
    procs = [proc]

    if "llama_server_specialist" in cfg:
        specialist_proc = await _launch_one(cfg["llama_server_specialist"])
        procs.append(specialist_proc)
    else:
        print("[launcher] Solo mode — single model.")

    return procs
```

**Step 2: Verify config resolution works**

Run: `cd F:/AI_Workstation/web-ui && python -c "from ct1.server.launcher import load_config; cfg = load_config(); print(cfg['_preset']); print(cfg['_preset_info']['model_file']); print('specialist' not in cfg.get('models', {})); print('OK')"`

Expected: `qwen4b-q6`, `Qwen3.5-4B.Q6_Kdistiled.gguf`, `True`, `OK`

**Step 3: Commit**

```bash
git add ct1/server/launcher.py
git commit -m "refactor: update launcher for flat preset config format"
```

---

## Task 4: Refactor director.py -> engine.py

**Files:**
- Rename: `ct1/core/director.py` -> `ct1/core/engine.py`
- Modify: All imports referencing `director` / `Director`

**Step 1: Rename file and class**

```bash
cd F:/AI_Workstation/web-ui
git mv ct1/core/director.py ct1/core/engine.py
```

In `ct1/core/engine.py`:
- Change class name `Director` -> `Engine` (search-replace)
- Update module docstring
- Keep ALL existing system prompt constants and methods unchanged

**Step 2: Update imports across codebase**

Files to update:
- `ct1/core/orchestrator.py` line 13: `from ct1.core.director import Director` -> `from ct1.core.engine import Engine`
- `ct1/core/orchestrator.py` line 716: `from ct1.core.director import Director` -> `from ct1.core.engine import Engine`
- `ct1/core/orchestrator.py`: All `self.director` references stay (they reference the instance variable, not the class) — but rename to `self.engine` for clarity
- `ct1/server/api.py`: Search for any `Director` import and update

**Step 3: In orchestrator.py, rename `self.director` -> `self.engine`**

Replace all occurrences. The variable name `director` is misleading when there's no specialist. Use `self.engine` throughout.

**Step 4: Verify Python parses**

Run: `cd F:/AI_Workstation/web-ui && python -c "import ast; ast.parse(open('ct1/core/engine.py').read()); ast.parse(open('ct1/core/orchestrator.py').read()); print('OK')"`

Expected: `OK`

**Step 5: Commit**

```bash
git add ct1/core/engine.py ct1/core/orchestrator.py ct1/server/api.py
git rm ct1/core/director.py  # if git mv didn't handle it
git commit -m "refactor: rename Director to Engine, remove director/specialist terminology"
```

---

## Task 5: Remove Specialist from Pipeline

**Files:**
- Modify: `ct1/core/orchestrator.py`
- Delete: `ct1/core/specialist.py` (after verifying nothing else imports it)

**Step 1: Remove specialist import and initialization**

In `ct1/core/orchestrator.py`:

Remove line 14: `from ct1.core.specialist import Specialist`

In `__init__` (lines 138-151), delete the specialist initialization block:
```python
# DELETE these lines:
        # Specialist is optional (solo presets don't have one)
        if "llama_server_specialist" in cfg and "specialist" in cfg.get("models", {}):
            specialist_url = f"http://localhost:{cfg['llama_server_specialist']['port']}"
            sc = cfg["models"]["specialist"]
            self.specialist = Specialist(
                base_url=specialist_url,
                temperature=sc["temperature"],
                top_p=sc["top_p"],
                top_k=sc["top_k"],
                max_tokens=sc["max_tokens"],
                enable_thinking=sc.get("enable_thinking", False),
            )
        else:
            self.specialist = None
```

**Step 2: Remove all specialist calls from pipeline**

In `_pipeline()`:

a) **Lines 1103-1106** — routing fallback: Remove specialist.route(), keep only `_keyword_route()`:
```python
# BEFORE:
            route = self._pre_route(user_message)
            if route:
                print(f"[pre-route] → {route} (deterministic)")
            elif self.specialist:
                route = await self.specialist.route(user_message)
            else:
                route = self._keyword_route(user_message)

# AFTER:
            route = self._pre_route(user_message)
            if route:
                print(f"[pre-route] → {route} (deterministic)")
            else:
                route = self._keyword_route(user_message)
```

b) **Lines 1114-1150** — ROUTE_DESIGN with specialist gate: Remove `and self.specialist` condition. The design pipeline should work without specialist (it already uses director for spec generation).
```python
# BEFORE:
        if route == "ROUTE_DESIGN" and self.specialist:

# AFTER:
        if route == "ROUTE_DESIGN":
```

c) **Lines 1152-1202** — Remove entire ROUTE_SOLO block. ROUTE_SOLO was a workaround for when specialist was unavailable. Now everything is solo — the normal pipeline handles it. Remove the `"solo"` entry from `_MODE_ROUTE_MAP` too.

d) **Lines 1207-1208** — planning: Remove specialist.plan(), keep only solo planning:
```python
# BEFORE:
            if self.specialist:
                plan = await self.specialist.plan(user_message, route)
                emit("planned", plan=plan)
            elif len(user_message) > 30:

# AFTER:
            if len(user_message) > 30:
```

e) **Lines 1219-1230** — decomposition: Remove entire specialist.decompose() block. Planning handles this now.

f) **Lines 1235-1256** — adaptive thinking budget: Keep the logic but feed it from plan data instead of specialist_data. If plan has components, use those for item count.

g) Remove `self.specialist` references from `_format_specialist_data()` (line 713-717).

**Step 3: Delete specialist.py**

```bash
git rm ct1/core/specialist.py
```

**Step 4: Verify nothing else imports Specialist**

Run: `cd F:/AI_Workstation/web-ui && grep -r "from ct1.core.specialist" --include="*.py" | grep -v __pycache__`

Expected: No output (nothing imports it anymore)

**Step 5: Verify Python parses**

Run: `cd F:/AI_Workstation/web-ui && python -c "import ast; ast.parse(open('ct1/core/orchestrator.py').read()); print('OK')"`

Expected: `OK`

**Step 6: Commit**

```bash
git add ct1/core/orchestrator.py
git rm ct1/core/specialist.py
git commit -m "refactor: remove specialist from pipeline, all routing now deterministic"
```

---

## Task 6: Build Adaptive Pipeline with Tier Support

**Files:**
- Modify: `ct1/core/orchestrator.py`

This is the core architectural change. The pipeline adapts based on the model's tier.

**Step 1: Add tier to Orchestrator.__init__**

```python
from ct1.core.tier import detect_tier

class Orchestrator:
    def __init__(self, config_path: str = None, component_cache=None):
        # ... existing config loading ...

        # Detect model tier
        preset_info = cfg.get("_preset_info", {})
        model_file = preset_info.get("model_file", "")
        explicit_tier = preset_info.get("tier")
        self.tier = detect_tier(model_file, explicit_tier)
        print(f"[orch] Model tier: {self.tier} (model: {model_file})")
```

**Step 2: Implement tier-aware pipeline in `_pipeline()`**

After routing (Phase 1), the pipeline branches by tier:

```python
        # ── Tier-aware pipeline ──
        is_complex = len(user_message) > 80 or any(
            kw in user_message.lower()
            for kw in ("step by step", "multiple", "project", "full", "complete")
        )

        # Phase 2: PLAN (medium/large only, complex requests only)
        plan = None
        if self.tier in ("medium", "large") and is_code and not is_edit and is_complex:
            plan = await self._solo_plan(user_message, route)
            if plan:
                emit("planned", plan=plan)
        elif self.tier == "large" and is_code and not is_edit:
            # Large tier always plans for code
            plan = await self._solo_plan(user_message, route)
            if plan:
                emit("planned", plan=plan)

        # Phase 3: GENERATE (all tiers)
        # ... existing generation code ...

        # Phase 4: REVIEW (large tier only)
        if self.tier == "large" and is_code and not is_edit:
            review = await self._self_review(draft, user_message, route)
            if review and not review.get("pass", True):
                # Re-generate with fix instructions
                # ... fix loop ...
```

**Step 3: Add `_self_review()` method for large tier**

```python
    async def _self_review(self, code: str, goal: str, route: str) -> dict | None:
        """Large-tier self-review: model checks its own output."""
        review_prompt = (
            f"Review this code against the original request.\n\n"
            f"REQUEST: {goal[:500]}\n\n"
            f"CODE:\n{code[:3000]}\n\n"
            f"Check for:\n"
            f"1. Does it fully address the request?\n"
            f"2. Any syntax errors or bugs?\n"
            f"3. Missing functionality?\n\n"
            f"Output ONLY a JSON object:\n"
            f'{{"pass": true/false, "issues": ["issue1", ...], "fix_instructions": "..."}}'
        )
        try:
            result = await self.engine.generate(
                review_prompt, route,
                task_overrides={"temperature": 0.1, "enable_thinking": False},
            )
            import json
            return json.loads(result["text"].strip())
        except Exception as e:
            print(f"[orch] self-review failed: {e}")
            return None
```

**Step 4: Verify**

Run: `cd F:/AI_Workstation/web-ui && python -c "import ast; ast.parse(open('ct1/core/orchestrator.py').read()); print('OK')"`

**Step 5: Commit**

```bash
git add ct1/core/orchestrator.py
git commit -m "feat: implement tier-aware adaptive pipeline (small/medium/large)"
```

---

## Task 7: Rebuild System Prompts for All Modes

**Files:**
- Modify: `ct1/core/engine.py` (all `_GENERATOR_*_SYSTEM` constants)

**Step 1: Rewrite `_GENERATOR_TEXT_SYSTEM` (Direct Mode)**

```python
_GENERATOR_TEXT_SYSTEM = (
    "You are a knowledgeable, versatile assistant.\n"
    "Handle any conversational task: essays, explanations, summaries, research, analysis, "
    "creative writing, Q&A, translation, brainstorming, debate, comparison.\n\n"

    "RESPONSE GUIDELINES:\n"
    "- Match response length and depth to the request. Short question = short answer. "
    "Complex analysis = thorough treatment.\n"
    "- Use structure (headings, bullets, numbered lists) for longer responses.\n"
    "- Include code examples when discussing technical topics.\n"
    "- Never fabricate facts. State uncertainty when unsure.\n"
    "- No filler. No 'I hope this helps'. Get to the substance.\n\n"

    "TASK APPROACH:\n"
    "1. Identify what is actually being asked\n"
    "2. Determine the appropriate depth and format\n"
    "3. Deliver a complete, well-structured response\n"
)
```

**Step 2: Rewrite `_GENERATOR_DESIGN_SYSTEM` (Design Mode)**

Keep the existing Tailwind/design mandate but add the structured approach. The existing prompt at lines 37-102 is already comprehensive — keep its content but prepend the task approach structure and append verification.

**Step 3: Rewrite `_GENERATOR_CODE_SYSTEM` (Code Mode)**

```python
_GENERATOR_CODE_SYSTEM = (
    "You are an expert developer. Respond with code and technical explanations.\n\n"

    "OUTPUT FORMAT:\n"
    "- Code goes in markdown-fenced code blocks with language tags.\n"
    "- Explain approach before the code block, not inside it.\n"
    "- For debugging: identify the bug, explain why it happens, show the fix.\n"
    "- For refactoring: explain what changes and why, then show the result.\n\n"

    "CODE QUALITY:\n"
    "- Complete, working code. No placeholders. No TODOs. No '...' skips.\n"
    "- Handle edge cases. Follow language idioms.\n"
    "- Include imports, error handling, type hints where appropriate.\n\n"

    "TASK APPROACH:\n"
    "1. Understand what is being asked\n"
    "2. Identify language, key data structures, algorithms needed\n"
    "3. Consider edge cases\n"
    "4. Write complete, working code\n"
)
```

**Step 4: Keep `_GENERATOR_COMPUTER_SYSTEM` mostly as-is**

The computer mode prompt with `[FILE: path]` and `[RUN: cmd]` markers is already well-structured. Just ensure it has the task approach prepended.

**Step 5: Add tier-specific prompt suffixes**

Create a function that appends the right suffix based on tier:

```python
_INLINE_PLANNING_SUFFIX = (
    "\n\nBEFORE RESPONDING — work through these in your thinking:\n"
    "1. What type of task is this?\n"
    "2. Break it into concrete steps\n"
    "3. What are the key requirements and constraints?\n"
    "4. Execute each step\n"
    "5. Verify: does your output fully address every part of the request? "
    "Is anything missing, incomplete, or placeholder? If so, fix it.\n"
)

_INLINE_VERIFY_SUFFIX = (
    "\n\nBEFORE FINALIZING — verify in your thinking:\n"
    "- Does the output fully address every part of the request?\n"
    "- Is anything missing, incomplete, or placeholder?\n"
    "- If any check fails, fix it before responding.\n"
)

def get_system_prompt(route: str, tier: str) -> str:
    """Get the system prompt for a route, with tier-appropriate suffix."""
    prompts = {
        "ROUTE_DIRECT": _GENERATOR_TEXT_SYSTEM,
        "ROUTE_DESIGN": _GENERATOR_DESIGN_SYSTEM,
        "ROUTE_CODE": _GENERATOR_CODE_SYSTEM,
        "ROUTE_COMPUTER": _GENERATOR_COMPUTER_SYSTEM,
    }
    base = prompts.get(route, _GENERATOR_TEXT_SYSTEM)

    if tier == "small":
        return base + _INLINE_PLANNING_SUFFIX
    elif tier == "medium":
        return base + _INLINE_VERIFY_SUFFIX
    else:  # large
        return base  # planning and review are separate pipeline steps
```

**Step 6: Update `generate()` to accept tier and use `get_system_prompt()`**

In `Engine.generate()`, replace the hardcoded system prompt selection with `get_system_prompt(route, tier)`. Add `tier` as a parameter.

**Step 7: Verify**

Run: `cd F:/AI_Workstation/web-ui && python -c "import ast; ast.parse(open('ct1/core/engine.py').read()); print('OK')"`

**Step 8: Commit**

```bash
git add ct1/core/engine.py
git commit -m "feat: rebuild all mode system prompts with tier-aware suffixes"
```

---

## Task 8: Expand Deterministic Routing

**Files:**
- Modify: `ct1/core/orchestrator.py`

**Step 1: Merge `_pre_route()` and `_keyword_route()` into single `_deterministic_route()`**

The current codebase has two partial routing functions. Merge them into one comprehensive router:

```python
    # ── Routing patterns ──
    _COMPUTER_PATTERNS = re.compile(
        r'\b(?:create\s+a?\s*project|build\s+a?\s*(?:website|app|project)|'
        r'write\s+to\s+file|run\s+command|execute|install|mkdir|'
        r'save\s+as|multi[- ]?file|full\s+project|make\s+a?\s*folder|'
        r'set\s+up\s+a?\s*(?:project|repo|directory))\b', re.I
    )

    _DESIGN_PATTERNS = re.compile(
        r'\b(?:design|landing\s+page|dashboard|portfolio|webpage|'
        r'website\s+layout|mockup|wireframe|styled?\s+page|'
        r'html\s+page|web\s+page|ui\s+design)\b', re.I
    )
    _DESIGN_NEGATIVE = re.compile(
        r'\b(?:explain|how\s+does|what\s+is|what\s+are|why\s+does)\b', re.I
    )

    _CODE_PATTERNS = re.compile(
        r'\b(?:write\s+a?\s*(?:function|class|script|program|module)|'
        r'implement|debug|refactor|fix\s+(?:this|the)\s+(?:code|bug|error)|'
        r'(?:python|javascript|typescript|java|rust|go|c\+\+|ruby)\s+'
        r'(?:script|function|class|program|code)|'
        r'api\s+endpoint|add\s+(?:a\s+)?(?:method|function|test))\b', re.I
    )
    _CODE_FENCE = re.compile(r'```\w*\n')

    @classmethod
    def _deterministic_route(cls, msg: str, has_workspace: bool = False) -> str:
        """Deterministic routing via keyword/regex. No AI call.

        Priority: computer > design > code > direct (fallback).
        """
        lower = msg.lower().strip()

        # 1. Questions -> always DIRECT
        if _is_question(msg):
            # Exception: question + code fence = code context
            if cls._CODE_FENCE.search(msg):
                return "ROUTE_CODE"
            return "ROUTE_DIRECT"

        # 2. Computer mode (needs workspace or explicit project language)
        if cls._COMPUTER_PATTERNS.search(msg):
            return "ROUTE_COMPUTER"

        # 3. Design (single-file visual) — but not questions about design
        if cls._DESIGN_PATTERNS.search(msg) and not cls._DESIGN_NEGATIVE.search(msg):
            return "ROUTE_DESIGN"

        # 4. Code (generation/discussion)
        if cls._CODE_PATTERNS.search(msg) or cls._CODE_FENCE.search(msg):
            return "ROUTE_CODE"

        # 5. Analysis/reasoning signals -> DIRECT
        if any(kw in lower for kw in cls._DIRECT_SIGNALS):
            return "ROUTE_DIRECT"

        # 6. Build phrases without specific route -> DESIGN (prefer visual)
        if any(phrase in lower for phrase in cls._BUILD_PHRASES):
            return "ROUTE_DESIGN"

        # 7. Long text without build intent -> DIRECT
        if len(msg) > 300:
            return "ROUTE_DIRECT"

        # 8. Default
        return "ROUTE_DIRECT"
```

**Step 2: Update `_pipeline()` Phase 1 to use new router**

```python
        # ── Phase 1: ROUTE (deterministic, no AI call) ──
        emit("routing")
        forced_route = self._MODE_ROUTE_MAP.get(mode_override or "")
        if forced_route:
            if is_edit:
                route = forced_route if forced_route != "ROUTE_DIRECT" else "ROUTE_CODE"
            elif mode == "question" and forced_route == "ROUTE_DIRECT":
                route = "ROUTE_DIRECT"
            else:
                route = forced_route
            print(f"[mode-override] → {route} (user selected '{mode_override}')")
        elif no_vision and not is_edit:
            route = "ROUTE_DIRECT"
        elif is_edit:
            route = "ROUTE_CODE"
        elif mode == "question":
            route = "ROUTE_DIRECT"
        else:
            route = self._deterministic_route(user_message)
            print(f"[route] → {route} (deterministic)")
        emit("routed", route=route)
```

**Step 3: Remove old `_pre_route()` and `_keyword_route()` methods**

Delete both methods. `_deterministic_route()` replaces them.

**Step 4: Update `_MODE_ROUTE_MAP`**

Remove `"solo": "ROUTE_SOLO"`. Only 4 modes remain: design, code, chat, computer.

```python
    _MODE_ROUTE_MAP = {
        "design": "ROUTE_DESIGN",
        "code": "ROUTE_CODE",
        "chat": "ROUTE_DIRECT",
        "computer": "ROUTE_COMPUTER",
    }
```

**Step 5: Verify**

Run: `cd F:/AI_Workstation/web-ui && python -c "import ast; ast.parse(open('ct1/core/orchestrator.py').read()); print('OK')"`

**Step 6: Commit**

```bash
git add ct1/core/orchestrator.py
git commit -m "feat: unified deterministic router, remove AI routing"
```

---

## Task 9: Defensive Output Parsing

**Files:**
- Modify: `ct1/core/formatter.py`

**Step 1: Ensure `clean_response()` runs unconditionally**

Read the current `clean_response()` function. Ensure it:
- Always strips markdown fences (`\`\`\`html ... \`\`\``) from code output
- Always strips preamble ("Here's your code:", "Sure, here is...")
- Always strips postamble ("Let me know if you need...", "I hope this helps")

**Step 2: Add computer mode format enforcement**

```python
def enforce_file_markers(text: str, route: str) -> str:
    """If computer mode output has code but no [FILE:] markers, wrap it."""
    if route != "ROUTE_COMPUTER":
        return text
    if "[FILE:" in text or "[FILE :" in text:
        return text  # Already has markers

    # Detect language and wrap in default marker
    ext_map = {
        "<!DOCTYPE": ("index.html", True),
        "<html": ("index.html", True),
        "import React": ("App.jsx", True),
        "def ": ("main.py", True),
        "function ": ("index.js", True),
        "const ": ("index.js", True),
    }
    for pattern, (filename, _) in ext_map.items():
        if pattern in text:
            return f"[FILE: {filename}]\n{text}"
    return text
```

**Step 3: Ensure all parsing runs in pipeline Phase 6**

In orchestrator.py, ensure `clean_response()` and `enforce_file_markers()` run on ALL routes, not just code routes.

**Step 4: Commit**

```bash
git add ct1/core/formatter.py ct1/core/orchestrator.py
git commit -m "feat: defensive output parsing, enforce file markers in computer mode"
```

---

## Task 10: Few-Shot Examples for Small Tier

**Files:**
- Modify: `ct1/core/engine.py`

**Step 1: Add minimal few-shot examples**

```python
_DESIGN_FEWSHOT = (
    "\n\nEXAMPLE STRUCTURE (follow this pattern, not content):\n"
    "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
    "  <meta charset=\"UTF-8\">\n  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
    "  <script src=\"https://cdn.tailwindcss.com\"></script>\n"
    "  <style>/* custom animations, gradients, fonts only */</style>\n"
    "</head>\n<body class=\"bg-gray-50 text-gray-900\">\n"
    "  <!-- semantic sections with Tailwind classes -->\n"
    "</body>\n</html>\n"
)

_CODE_FEWSHOT = (
    "\n\nEXAMPLE STRUCTURE (follow this pattern, not content):\n"
    "```python\n"
    "import sys\n\n"
    "def process(data: list[str]) -> dict:\n"
    "    \"\"\"Process input data.\"\"\"\n"
    "    if not data:\n"
    "        return {}\n"
    "    result = {}\n"
    "    for item in data:\n"
    "        # handle edge cases\n"
    "        result[item] = len(item)\n"
    "    return result\n\n"
    "if __name__ == \"__main__\":\n"
    "    print(process(sys.argv[1:]))\n"
    "```\n"
)
```

**Step 2: Inject in `get_system_prompt()` for small tier**

```python
def get_system_prompt(route: str, tier: str, context_budget: int = 16384) -> str:
    base = prompts.get(route, _GENERATOR_TEXT_SYSTEM)

    if tier == "small":
        suffix = _INLINE_PLANNING_SUFFIX
        # Add few-shot for code/design if context allows
        if context_budget >= 8192:
            if route == "ROUTE_DESIGN":
                suffix = _DESIGN_FEWSHOT + suffix
            elif route == "ROUTE_CODE":
                suffix = _CODE_FEWSHOT + suffix
        return base + suffix
    elif tier == "medium":
        return base + _INLINE_VERIFY_SUFFIX
    else:
        return base
```

**Step 3: Commit**

```bash
git add ct1/core/engine.py
git commit -m "feat: add few-shot examples for small tier models"
```

---

## Task 11: Context Budget Management

**Files:**
- Modify: `ct1/core/engine.py`

**Step 1: Add conversation truncation method**

```python
def truncate_conversation(
    conversation: list[dict],
    system_prompt: str,
    max_context: int,
    reserve_output: int = 2048,
    chars_per_token: float = 3.5,
) -> list[dict]:
    """Truncate conversation to fit within context budget.

    Keeps system prompt + current user message always.
    Removes oldest turns first. Never splits user+assistant pairs.
    """
    if not conversation:
        return conversation

    # Rough token estimation
    system_tokens = len(system_prompt) / chars_per_token
    available = max_context - system_tokens - reserve_output

    # Always keep the last message (current user input)
    result = []
    total = 0

    # Walk from newest to oldest
    for msg in reversed(conversation):
        msg_tokens = len(msg.get("content", "")) / chars_per_token
        if total + msg_tokens > available:
            break
        result.insert(0, msg)
        total += msg_tokens

    return result
```

**Step 2: Call in `Engine.generate()` before building messages**

Apply truncation before sending to the model, using the preset's `context_size`.

**Step 3: Commit**

```bash
git add ct1/core/engine.py
git commit -m "feat: context budget management with conversation truncation"
```

---

## Task 12: Update API Layer

**Files:**
- Modify: `ct1/server/api.py`

**Step 1: Update `/api/status` endpoint**

Remove specialist health check. Single model status only.

**Step 2: Update `/api/config` endpoint**

Return single model config, tier info, no specialist fields.

**Step 3: Update `/api/presets` endpoint**

List all 5 presets from flat config. No specialist model display.

**Step 4: Update `/api/preset` (switch) endpoint**

When switching presets, kill current server, launch new one with selected model. Create new Orchestrator.

**Step 5: Verify**

Run: `cd F:/AI_Workstation/web-ui && python -c "import ast; ast.parse(open('ct1/server/api.py').read()); print('OK')"`

**Step 6: Commit**

```bash
git add ct1/server/api.py
git commit -m "refactor: update API endpoints for single-model pipeline"
```

---

## Task 13: Update Frontend — Chat Store

**Files:**
- Modify: `ct1/web/src/lib/stores/chat.ts`

**Step 1: Remove specialist event handlers**

Remove handlers for: `consulting`, `specialist_token`, `consulted` events.

**Step 2: Remove `specialistStream` from state**

Remove `specialistStream: string` from `ChatState` interface and initial state.

**Step 3: Keep `SpecialistData` interface**

Keep the interface for backward compatibility with stored conversation history. Just don't populate it for new conversations.

**Step 4: Verify TypeScript compiles**

Run: `cd F:/AI_Workstation/web-ui/ct1/web && npx svelte-check --no-tsconfig 2>&1 | head -20`

**Step 5: Commit**

```bash
git add ct1/web/src/lib/stores/chat.ts
git commit -m "refactor: remove specialist events from chat store"
```

---

## Task 14: Update Frontend — Settings Page

**Files:**
- Modify: `ct1/web/src/routes/settings/+page.svelte`

**Step 1: Remove specialist status indicator**

Remove `specialistStatus` state variable and its display in the template.

**Step 2: Remove specialist model from preset cards**

Remove the conditional `{#if info.specialist_model}` block.

**Step 3: Add context size slider**

Add a slider to the settings page per-preset:
- Min: `CONTEXT_MIN_FLOOR` (constant, ~2048 — enough for largest system prompt + 512 input + 1024 output)
- Max: preset's configured `context_size`
- Default: max
- Label shows current value in K (e.g., "16K", "65K")

**Step 4: Add per-preset settings persistence**

Save user-modified settings to localStorage as `ct2-preset-{presetName}`:
```typescript
const savePresetSettings = (preset: string, settings: Record<string, any>) => {
    localStorage.setItem(`ct2-preset-${preset}`, JSON.stringify(settings));
};
```

**Step 5: Add restart notice**

When context size changes, show a notice: "Restart required to apply changes." with a restart button that calls the preset switch endpoint.

**Step 6: Commit**

```bash
git add ct1/web/src/routes/settings/+page.svelte
git commit -m "feat: context size slider, per-preset persistence, restart notice"
```

---

## Task 15: Update Frontend — Layout

**Files:**
- Modify: `ct1/web/src/routes/+layout.svelte`

**Step 1: Remove "consulting" from phase labels**

```typescript
const phaseLabels: Record<string, string> = {
    idle: '',
    routing: 'Classifying',
    planning: 'Planning',
    // removed: consulting: 'Analyzing',
    generating: 'Generating',
    polishing: 'Polishing',
    refining: 'Refining',
    validating: 'Validating',
    fixing: 'Fixing',
    done: '',
};
```

**Step 2: Commit**

```bash
git add ct1/web/src/routes/+layout.svelte
git commit -m "refactor: remove consulting phase from layout"
```

---

## Task 16: Update Frontend — Remove Solo Mode Pill

**Files:**
- Modify: `ct1/web/src/lib/components/ChatInput.svelte`
- Modify: `ct1/web/src/lib/stores/chat.ts` (ModeOverride type)

**Step 1: Verify current mode pills**

The current modes array is: `auto, design, code, chat, computer`. If `solo` is present, remove it. The 4 functional modes + auto should remain.

**Step 2: Update `ModeOverride` type if needed**

Remove `'solo'` from the union type if present.

**Step 3: Commit**

```bash
git add ct1/web/src/lib/components/ChatInput.svelte ct1/web/src/lib/stores/chat.ts
git commit -m "refactor: clean up mode pills, remove solo option"
```

---

## Task 17: Integration Verification

**Step 1: Verify all Python files parse**

Run: `cd F:/AI_Workstation/web-ui && python -c "import ast; [ast.parse(open(f).read()) for f in ['ct1/core/engine.py', 'ct1/core/orchestrator.py', 'ct1/core/formatter.py', 'ct1/core/tier.py', 'ct1/server/api.py', 'ct1/server/launcher.py']]; print('All Python OK')"`

**Step 2: Verify YAML config**

Run: `cd F:/AI_Workstation/web-ui && python -c "import yaml; d=yaml.safe_load(open('ct1/server/model_config.yaml')); assert len(d['presets'])==5; print('YAML OK')"`

**Step 3: Verify frontend builds**

Run: `cd F:/AI_Workstation/web-ui/ct1/web && npm run build 2>&1 | tail -5`

**Step 4: Verify specialist.py is deleted**

Run: `ls F:/AI_Workstation/web-ui/ct1/core/specialist.py 2>&1`
Expected: `No such file or directory`

**Step 5: Verify no remaining specialist imports**

Run: `cd F:/AI_Workstation/web-ui && grep -r "specialist" --include="*.py" --include="*.ts" --include="*.svelte" -l | grep -v __pycache__ | grep -v node_modules`

Review output — specialist should only appear in:
- Comments explaining backward compat
- `SpecialistData` type (kept for conversation history compat)
- Launcher's backward-compat branch for old config format

**Step 6: Final commit**

```bash
git add -A
git commit -m "chore: integration verification pass"
```

---

## Execution Notes

**Order matters:** Tasks 1-3 (tier, config, launcher) are foundational. Task 4-5 (rename, remove specialist) are the core refactor. Tasks 6-11 are feature work that builds on the refactored pipeline. Tasks 12-16 are frontend. Task 17 is verification.

**Risk areas:**
- Task 5 (specialist removal) touches the most code and has the highest breakage risk. Read every specialist reference before deleting.
- Task 6 (adaptive pipeline) is the most complex new logic. Test each tier path.
- Task 8 (routing) must cover the same cases as the old AI router. Compare against specialist.py's routing prompt for coverage gaps.

**Rollback:** If anything breaks catastrophically, the old config format is still supported by the backward-compat branch in `resolve_config()`. Set `active_preset: ct2` in the old-format YAML to revert.
