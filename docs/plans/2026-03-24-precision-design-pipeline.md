# Precision-Design Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the current ROUTE_DESIGN pipeline with the Precision-Design architecture — spec-driven, per-component generation, mechanical validation, targeted patching, fallback templates.

**Architecture:** Director (4B) generates a JSON spec from user prompts. Specialist (2B) generates HTML components from the spec, one at a time. Scripts validate mechanically — no model evaluates its own output. Failed components get patched, re-generated, or replaced with fallbacks.

**Tech Stack:** Python 3.10+, httpx (async HTTP), json/jsonschema (validation), BeautifulSoup4 (HTML parsing), Svelte/TS (frontend)

---

## File Map

| New File | Purpose |
|----------|---------|
| `ct1/core/spec_schema.json` | JSON Schema for Director spec output |
| `ct1/core/validator.py` | Mechanical validation (spec, component, page) |
| `ct1/core/assembler.py` | Page assembly + component stitching |
| `ct1/templates/wrapper.html` | Static page wrapper |
| `ct1/templates/fallbacks.py` | Fallback component library (Python dict) |
| `ct1/templates/snippets.py` | Interaction snippet library (Python dict) |

| Modified File | What Changes |
|---------------|-------------|
| `ct1/core/director.py` | Add `generate_spec()` method |
| `ct1/core/specialist.py` | Add `generate_component()` and `patch_component()` methods |
| `ct1/core/orchestrator.py` | New `_design_pipeline()` replacing current design flow |
| `ct1/core/formatter.py` | No changes — existing HTML validators stay for non-design routes |
| `ct1/server/api.py` | No backend changes needed — events already use generic `emit()` |
| `ct1/web/src/lib/stores/chat.ts` | New phase values + component progress tracking |
| `ct1/web/src/routes/+page.svelte` | Updated pipeline step UI for new phases |

---

## Task 1: Install BeautifulSoup4 dependency

**Files:**
- Modify: `requirements.txt` (or equivalent — check what exists)

**Step 1: Check dependency management**

Run: `ls F:/AI_Workstation/web-ui/requirements.txt F:/AI_Workstation/web-ui/pyproject.toml F:/AI_Workstation/web-ui/setup.py 2>/dev/null`

**Step 2: Install beautifulsoup4**

Run: `pip install beautifulsoup4`

The validator needs a real HTML parser, not regex. BeautifulSoup is the standard choice for this.

---

## Task 2: Create JSON Spec Schema

**Files:**
- Create: `ct1/core/spec_schema.json`

**Step 1: Write the schema file**

Copy the JSON Schema from precision-design-plan.md Section 1.4 verbatim into `ct1/core/spec_schema.json`. This is the contract between Director and the rest of the pipeline.

**Step 2: Verify the schema is valid JSON**

Run: `python -c "import json; json.load(open('ct1/core/spec_schema.json'))" && echo OK`

---

## Task 3: Create Static Templates

**Files:**
- Create: `ct1/templates/` directory
- Create: `ct1/templates/__init__.py`
- Create: `ct1/templates/wrapper.html`
- Create: `ct1/templates/fallbacks.py`
- Create: `ct1/templates/snippets.py`

### 3a: Page Wrapper Template

`ct1/templates/wrapper.html` — the static HTML skeleton from plan Section 1.1:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script src="https://cdn.tailwindcss.com"></script>
  <title>{{PAGE_TITLE}}</title>
</head>
<body class="min-h-screen bg-white text-gray-900 antialiased">
  {{COMPONENTS}}
  {{SCRIPTS}}
</body>
</html>
```

### 3b: Fallback Component Library

`ct1/templates/fallbacks.py` — Python dict mapping component type → HTML string. Per plan Section 1.2, create fallbacks for: `navbar`, `hero`, `features`, `testimonials`, `cta`, `footer`, `contact`, `pricing`.

Each fallback must:
- Be fully responsive (`sm:`, `md:`, `lg:` breakpoints)
- Use neutral Tailwind colors (gray, slate, white)
- Contain `<!-- PLACEHOLDER: Replace with actual content -->` markers
- Accept an `id` parameter (use `{id}` placeholder in the string, formatted at runtime)

Implementation: A `get_fallback(component_type: str, component_id: str) -> str` function that returns the formatted HTML.

### 3c: Interaction Snippet Library

`ct1/templates/snippets.py` — Python dict mapping snippet ID → `<script>` block. Per plan Section 1.3, create snippets for: `hamburger-toggle`, `smooth-scroll`, `accordion`, `form-validation`, `dark-mode-toggle`, `carousel`, `modal`, `scroll-reveal`.

Each snippet must:
- Be self-contained (no external dependencies)
- Use `document.querySelectorAll` with `data-*` attributes
- Degrade gracefully (no errors if target elements don't exist)

Implementation: A `get_snippets(snippet_ids: list[str]) -> str` function that returns concatenated `<script>` blocks (deduplicated).

---

## Task 4: Create Mechanical Validator

**Files:**
- Create: `ct1/core/validator.py`

This is the most critical new module. Zero AI involvement.

### 4a: Spec Validation (Phase 0.5)

```python
def validate_spec(spec: dict) -> tuple[bool, list[str]]:
    """Validate Director's JSON spec against the schema.

    Checks:
    1. Valid JSON conforming to schema (jsonschema.validate)
    2. Every id in components appears in layout_order (and vice versa)
    3. No duplicate id values
    4. Each component has at least one required_element

    Returns: (passed, list_of_error_strings)
    """
```

Use `jsonschema` library (stdlib-compatible, already commonly installed). If not available, fall back to manual checks.

### 4b: Component Validation (Phase 2.1)

```python
def validate_component(html: str, component_spec: dict) -> tuple[bool, list[str]]:
    """Validate a single generated HTML component against its spec.

    Checks:
    1. Parseable HTML (BeautifulSoup)
    2. Root element has correct id attribute
    3. Each required_element exists (find by tag + identifier as id/class/data attr)
    4. No <style> blocks (strip automatically if found, non-critical)
    5. No <script> tags or inline event handlers (strip automatically)
    6. If interactions specified, verify data-* attributes exist

    Returns: (passed, list_of_error_strings)
    """
```

### 4c: Page Validation (Phase 2.2)

```python
def validate_page(assembled_html: str, spec: dict) -> tuple[bool, list[str]]:
    """Validate the fully assembled page.

    Checks:
    1. No duplicate IDs across components
    2. Component order in DOM matches layout_order
    3. All components present

    Returns: (passed, list_of_error_strings)
    """
```

### 4d: Auto-fix helpers

```python
def strip_style_tags(html: str) -> str:
    """Remove <style> blocks from component HTML."""

def strip_script_tags(html: str) -> str:
    """Remove <script> tags and inline event handlers from component HTML."""
```

---

## Task 5: Create Page Assembler

**Files:**
- Create: `ct1/core/assembler.py`

```python
from pathlib import Path
from ct1.templates.snippets import get_snippets

_WRAPPER = (Path(__file__).parent.parent / "templates" / "wrapper.html").read_text()

def assemble_page(
    page_title: str,
    component_html: dict[str, str],  # id → html
    layout_order: list[str],
    spec: dict,
) -> str:
    """Assemble final HTML page from components.

    1. Concatenate component HTML in layout_order
    2. Collect all interaction snippet IDs from spec
    3. Load + deduplicate snippets
    4. Replace {{PAGE_TITLE}}, {{COMPONENTS}}, {{SCRIPTS}} in wrapper
    """

def patch_component(
    assembled_html: str,
    component_id: str,
    new_html: str,
) -> str:
    """Replace a single component in the assembled page by matching root element id.

    Uses BeautifulSoup to find element with id=component_id and replace it.
    """
```

---

## Task 6: Add `generate_spec()` to Director

**Files:**
- Modify: `ct1/core/director.py`

Add a new method to the Director class. This is the Phase 0 call — Director (4B) produces the JSON spec.

```python
# New system prompt constant (from plan Section 4.1)
_SPEC_GENERATOR_SYSTEM = """..."""  # Full prompt from plan

async def generate_spec(
    self, goal, conversation: list[dict] = None,
    task_overrides: dict = None,
) -> dict:
    """Phase 0: Generate JSON spec from user prompt.

    Returns parsed JSON dict conforming to spec_schema.json.
    Raises ValueError if output is not valid JSON.
    """
```

Key implementation details:
- Use `self._call()` (non-streaming, we need the complete JSON)
- Temperature: low (0.3-0.4) for deterministic spec generation
- Thinking: enabled (the 4B needs to reason about the page structure)
- Strip think tags, extract JSON, parse with `json.loads()`
- Do NOT validate against schema here — that's the validator's job

---

## Task 7: Add `generate_component()` and `patch_component()` to Specialist

**Files:**
- Modify: `ct1/core/specialist.py`

### 7a: Component generation (Phase 1)

```python
# New system prompt constant (from plan Section 4.2)
_COMPONENT_GENERATOR_SYSTEM = """..."""  # Full prompt from plan

async def generate_component(
    self, component_spec: dict, color_theme: dict,
    on_token=None,
) -> str:
    """Phase 1: Generate HTML for a single component from its spec.

    Returns raw HTML string (single <section>/<nav>/<footer> block).
    """
```

Key details:
- Build prompt with: component spec JSON + color theme
- Inject the system prompt from plan Section 4.2 with color theme values substituted
- Use higher max_tokens than usual for the Specialist (2048+)
- Strip think tags from output
- Return raw HTML string

### 7b: Component patching (Phase 3)

```python
async def patch_component(
    self, component_spec: dict, color_theme: dict,
    failing_html: str, errors: list[str],
    on_token=None,
) -> str:
    """Phase 3: Fix a failing component.

    Provides the failing HTML and specific errors.
    Returns corrected HTML string.
    """
```

---

## Task 8: Rewrite Design Pipeline in Orchestrator

**Files:**
- Modify: `ct1/core/orchestrator.py`

This is the core change. Add a new `_design_pipeline()` method and wire it into `_pipeline()`.

### 8a: Add imports

```python
from ct1.core.validator import validate_spec, validate_component, validate_page
from ct1.core.assembler import assemble_page, patch_component as patch_component_in_page
from ct1.templates.fallbacks import get_fallback
```

### 8b: Create `_design_pipeline()`

```python
async def _design_pipeline(
    self, goal, goal_text: str, conversation: list[dict],
    emit, on_token, task_ovr: dict,
    mode: str, previous_code: str,
) -> dict:
    """Precision-Design pipeline for ROUTE_DESIGN.

    Phases:
    0.  Director generates JSON spec
    0.5 Script validates spec
    1.  Specialist generates each component
    2.  Script validates each component
    3.  Targeted patching for failures
    4.  Assembly + output
    """
```

Flow:

```
# ── Phase 0: Spec Generation ──
emit("spec_generating")
spec = await self.director.generate_spec(goal, conversation, task_ovr)

# ── Phase 0.5: Spec Validation ──
passed, errors = validate_spec(spec)
if not passed:
    # Retry once with corrective instruction
    emit("spec_failed", errors=errors)
    spec = await self.director.generate_spec(
        corrective_goal, conversation, task_ovr
    )
    passed, errors = validate_spec(spec)
    if not passed:
        # Abort
        return error_result

emit("spec_validated", spec=spec)

# ── Phase 1 + 2: Per-component generation + validation ──
component_html = {}
for i, comp_id in enumerate(spec["layout_order"]):
    comp_spec = find_component(spec, comp_id)
    emit("component_generating", component_id=comp_id, index=i, total=len(spec["layout_order"]))

    html = await self.specialist.generate_component(comp_spec, spec["color_theme"], on_token)

    passed, errors = validate_component(html, comp_spec)
    if passed:
        component_html[comp_id] = html
        emit("component_validated", component_id=comp_id, index=i)
        continue

    # ── Phase 3: Patching ──
    emit("component_patching", component_id=comp_id, errors=errors)

    # Attempt 1: Targeted patch
    patched = await self.specialist.patch_component(comp_spec, spec["color_theme"], html, errors)
    passed, errors = validate_component(patched, comp_spec)
    if passed:
        component_html[comp_id] = patched
        emit("component_validated", component_id=comp_id, index=i)
        continue

    # Attempt 2: Full regeneration
    regenerated = await self.specialist.generate_component(comp_spec, spec["color_theme"])
    passed, errors = validate_component(regenerated, comp_spec)
    if passed:
        component_html[comp_id] = regenerated
        emit("component_validated", component_id=comp_id, index=i)
        continue

    # Fallback
    component_html[comp_id] = get_fallback(comp_spec["type"], comp_id)
    emit("component_fallback", component_id=comp_id)

# ── Phase 4: Assembly ──
emit("assembling")
final_html = assemble_page(
    spec["page_title"], component_html,
    spec["layout_order"], spec,
)

# Page-level validation
passed, errors = validate_page(final_html, spec)
# Auto-fix duplicate IDs or wrong order if needed

emit("done", response=final_html, ...)
```

### 8c: Wire into `_pipeline()`

In the existing `_pipeline()` method, after routing determines `ROUTE_DESIGN`:
- If `mode == "new"`: call `_design_pipeline()`
- If `mode == "edit"`: call `_design_edit_pipeline()` (spec-based editing)
- If `mode == "question"`: keep existing question flow

Replace the current design-specific code paths (consulting, refining, polish skip) with this single branch.

### 8d: Persist spec in pipeline result

Add `"spec"` to the result dict returned by `_design_pipeline()`. This is needed for edit mode — the frontend sends it back so edits can modify the spec and regenerate individual components.

### 8e: Create `_design_edit_pipeline()`

```python
async def _design_edit_pipeline(
    self, goal_text: str, conversation: list[dict],
    emit, on_token, task_ovr: dict,
    previous_code: str,
) -> dict:
    """Edit mode for Precision-Design.

    1. Retrieve persisted spec from conversation
    2. Parse which component(s) the edit targets
    3. Modify spec entry
    4. Re-run generation + validation for only that component
    5. Patch into assembled page
    """
```

This is lower priority — get new generation working first, then layer this on.

---

## Task 9: Update Frontend — Chat Store

**Files:**
- Modify: `ct1/web/src/lib/stores/chat.ts`

### 9a: Update phase type

Change the phase union type:

```typescript
phase: 'idle' | 'routing' | 'planning' | 'consulting' | 'generating'
     | 'polishing' | 'refining' | 'validating' | 'fixing' | 'done'
     // New design-pipeline phases:
     | 'spec_generating' | 'spec_validated'
     | 'component_generating' | 'component_validating'
     | 'assembling';
```

### 9b: Add component progress state

```typescript
// Add to ChatState interface:
designSpec: any | null;           // The JSON spec (persisted for edits)
componentProgress: {              // Per-component generation progress
    id: string;
    index: number;
    total: number;
    status: 'generating' | 'validated' | 'patching' | 'fallback';
}[];
```

### 9c: Add event handlers

```typescript
case 'spec_generating':
    s.phase = 'spec_generating';
    break;
case 'spec_validated':
    s.phase = 'spec_validated';
    s.designSpec = data.spec || null;
    break;
case 'spec_failed':
    s.warning = `Spec validation failed: ${(data.errors || []).join(', ')}`;
    break;
case 'component_generating':
    s.phase = 'component_generating';
    // Update or add component progress entry
    s.componentProgress = updateProgress(s.componentProgress, data.component_id, data.index, data.total, 'generating');
    break;
case 'component_validated':
    s.componentProgress = updateProgress(s.componentProgress, data.component_id, data.index, data.total, 'validated');
    break;
case 'component_patching':
    s.componentProgress = updateProgress(s.componentProgress, data.component_id, data.index, data.total, 'patching');
    break;
case 'component_fallback':
    s.componentProgress = updateProgress(s.componentProgress, data.component_id, data.index, data.total, 'fallback');
    break;
case 'assembling':
    s.phase = 'assembling';
    break;
```

### 9d: Persist spec in conversation turn

In the `'done'` handler, save `designSpec` into the assistant turn so it survives conversation reload (needed for edit mode).

---

## Task 10: Update Frontend — Pipeline Step UI

**Files:**
- Modify: `ct1/web/src/routes/+page.svelte`

### 10a: Replace old phase displays

Remove or gate behind `route !== 'ROUTE_DESIGN'`:
- The `refining` card (line 617-632)
- The `polishing` card (line 634-645)
- The `consulting` display

### 10b: Add new pipeline step displays

After the routing step, add for ROUTE_DESIGN:

```svelte
{#if $chat.phase === 'spec_generating'}
    <div class="step">
        <span class="step-dot pulse"></span>
        <span class="step-text">Planning page structure...</span>
    </div>
{/if}

{#if $chat.phase === 'spec_validated' || $chat.phase === 'component_generating'}
    <!-- Component progress bar -->
    <div class="component-progress">
        {#each $chat.componentProgress as comp}
            <div class="comp-item" class:done={comp.status === 'validated'}
                 class:patching={comp.status === 'patching'}
                 class:fallback={comp.status === 'fallback'}>
                <span class="comp-dot" class:pulse={comp.status === 'generating'}></span>
                <span class="comp-name">{comp.id}</span>
                <span class="comp-status">{comp.status}</span>
            </div>
        {/each}
    </div>
{/if}

{#if $chat.phase === 'assembling'}
    <div class="step">
        <span class="step-dot pulse"></span>
        <span class="step-text">Assembling page...</span>
    </div>
{/if}
```

### 10c: Style the component progress

Add CSS for the component progress display — minimal, consistent with existing step styling.

---

## Task 11: Integration Test — End-to-End

**Step 1: Start the server**

Run: `cd F:/AI_Workstation/web-ui && python -m ct1.server.api`

**Step 2: Send a design request via WebSocket**

Test with: "Landing page for a coffee shop called Bean & Brew"

Expected event flow:
```
routing → routed(ROUTE_DESIGN)
→ spec_generating → spec_validated
→ component_generating(navbar) → component_validated(navbar)
→ component_generating(hero) → component_validated(hero)
→ ...
→ assembling → done
```

**Step 3: Verify output**

- Response should be complete HTML with Tailwind CDN
- Each component should have the correct `id` attribute
- Components should appear in the spec's layout_order
- Interactive components should have data-* attributes
- Interaction scripts should be injected at the end

---

## Execution Order & Dependencies

```
Task 1 (bs4 install)         ← independent
Task 2 (JSON schema)         ← independent
Task 3 (templates)           ← independent
Task 4 (validator)           ← depends on Task 2 (schema), Task 1 (bs4)
Task 5 (assembler)           ← depends on Task 3 (templates)
Task 6 (Director.generate_spec) ← depends on Task 2 (schema)
Task 7 (Specialist methods)  ← independent
Task 8 (orchestrator)        ← depends on Tasks 4, 5, 6, 7
Task 9 (frontend store)      ← independent of backend
Task 10 (frontend UI)        ← depends on Task 9
Task 11 (integration test)   ← depends on all
```

**Parallelizable groups:**
- Group A: Tasks 1, 2, 3 (all independent)
- Group B: Tasks 4, 5, 6, 7 (after Group A, can be parallel)
- Group C: Tasks 9, 10 (frontend, parallel with Group B)
- Sequential: Task 8 (after Group B), Task 11 (after everything)

---

## What NOT to Change

- **Routing logic** — `_pre_route()`, `_keyword_route()`, Specialist `route()` stay as-is
- **Non-design routes** — ROUTE_CODE, ROUTE_DIRECT, ROUTE_COMPUTER pipelines are untouched
- **Model loading/serving** — `launcher.py`, `model_config.yaml`, llama-server management stay as-is
- **Conversation DB** — schema stays the same, spec is stored as JSON string in specialist_data
- **Journal/reflection** — reflection still runs after design generation (uses the assembled output)
- **Director._call() / Specialist._call()** — inference plumbing is preserved
- **Edit mode for non-design routes** — section editing, patch editing stay as-is
