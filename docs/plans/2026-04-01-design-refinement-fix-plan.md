# Plan: Fix Design Pipeline — Refinement + Spec JSON Errors

**Date:** 2026-04-01  
**Status:** Ready to implement  
**Priority:** High — both bugs affect every design-mode request

---

## Bug 1: Spec JSON Parse Error ("Spec validation failed")

### Symptom
Users see a warning: `Spec validation failed: Expecting ',' delimiter: line 1 column 14 (char 13)`  
This has been happening for weeks. Intermittent but frequent.

### Root Cause
`generate_spec()` in `ct1/core/engine.py:1065` asks the model to output a JSON spec.
The model (Qwen3.5-4B Q8) frequently writes `style_hints` as a **multi-line string**
with literal newline characters inside the JSON string value. Literal newlines inside
a JSON string are invalid. Example:

```json
"style_hints": "min-h-screen flex items-center justify-center
via-zinc-800 to-black. text-center px-6. typography: tracking-w..."
```

`_repair_json()` in `engine.py:13` fixes trailing commas, single quotes, and
unquoted keys — but does **not** escape literal newlines inside strings.
Both `json.loads(raw_json)` and `json.loads(repaired)` fail. The error is
emitted as a warning, a retry fires, but the retry often fails too.

### Fix: Add newline escaping to `_repair_json()`

**File:** `ct1/core/engine.py`  
**Location:** `_repair_json()` function, after step 5 (around line 87)

Add a new step 6 that walks through the repaired text and escapes any literal
`\n`, `\r`, `\t` characters found inside string values:

```python
# 6. Escape literal newlines/tabs inside JSON strings
# (models sometimes write style_hints as multi-line values)
result = []
in_string = False
i = 0
while i < len(text):
    ch = text[i]
    if ch == '"' and (i == 0 or text[i-1] != '\\'):
        in_string = not in_string
        result.append(ch)
    elif in_string and ch == '\n':
        result.append('\\n')
    elif in_string and ch == '\r':
        result.append('\\r')
    elif in_string and ch == '\t':
        result.append('\\t')
    else:
        result.append(ch)
    i += 1
text = ''.join(result)

return text
```

**Important:** Remove the bare `return text` that currently ends the function
and replace it with the block above (which ends with `return text`).

---

## Bug 2: Refinement Stage Replaces the Whole Design

### Symptom
After Phase 1 generates a good HTML page, Phase 3 (refinement) sends the entire
page back to the model asking it to "rewrite it to be significantly better."
The 4B model regenerates from scratch instead of polishing, producing a
completely different — often worse — output.

**Root cause:** `engine.refine_design()` in `ct1/core/engine.py:1164` uses a
full-rewrite prompt. The model can't do reliable in-place editing at this scale.

---

## Decision: CSS-Only Targeted Refinement

The HTML structure from Phase 1 is correct (sections, content, JS work).
Only the CSS needs polish: spacing, typography, hover states, responsiveness.

**New approach:**
1. Extract just the `<style>` block from the draft (~2–5 KB)
2. Ask the model to improve ONLY the CSS (keep all class names/IDs intact)
3. Splice improved CSS back using `reassemble_html_section(draft, 'style', ...)`

**Benefits:**
- HTML structure preserved 100% — no more "completely different file"
- ~70% fewer tokens (CSS only vs full HTML)
- Faster generation
- The model CAN reliably improve 2–5 KB of CSS — well within 4B capability

---

## Files to Change

| File | Change |
|------|--------|
| `ct1/core/engine.py` | Fix `_repair_json()` newline escaping; add `_REFINE_CSS_SYSTEM` + `refine_css_only()` |
| `ct1/core/orchestrator.py` | Replace Phase 3 full-rewrite with CSS-only refinement |

---

## Task List

### Task 1 — Fix `_repair_json()` in engine.py (spec JSON error)

**File:** `ct1/core/engine.py`  
**Location:** end of `_repair_json()` function (currently ends with bare `return text` around line 87)

Replace the final `return text` with the newline-escaping block shown in Bug 1 above.
This is a pure mechanical fix — no prompt changes, no LLM changes.

**Verification:** After the fix, a `style_hints` string like:
```
"min-h-screen flex items-center\nvia-zinc-800 to-black"
```
should repair to:
```
"min-h-screen flex items-center\\nvia-zinc-800 to-black"
```
...which is valid JSON.

---

### Task 2 — Add CSS-only refinement to engine.py (Bug 2)

**File:** `ct1/core/engine.py`

Add after `_REFINE_TARGETED_SYSTEM` (around line 1162):

```python
_REFINE_CSS_SYSTEM = (
    "You are a CSS expert reviewing a website's stylesheet.\n"
    "Improve the CSS below for better visual polish. Focus on:\n"
    "- SPACING: Consistent padding/margin scale. Generous whitespace in sections.\n"
    "- TYPOGRAPHY: Clear hierarchy. Headings sized properly. Body text readable.\n"
    "- HOVER STATES: Every button, link, and card needs a hover transition.\n"
    "- TRANSITIONS: Use 'transition: all 0.2s ease' on interactive elements.\n"
    "- CONSISTENCY: Same border-radius, box-shadow style throughout.\n"
    "- MOBILE: Ensure media queries stack correctly on small screens.\n\n"
    "Rules:\n"
    "- Output ONLY the CSS — no HTML, no explanation, no markdown fences.\n"
    "- Keep ALL existing class names and IDs exactly as-is.\n"
    "- Do not remove any existing rules — only improve or add to them.\n"
    "- Do not add new components or change the HTML structure.\n"
)
```

Add method `refine_css_only()` after `refine_design()`:

```python
async def refine_css_only(self, css: str, task_overrides: dict = None) -> dict:
    """Refine only the CSS block of a design output.

    Much safer than full-page rewrite: the model only processes ~2-5 KB
    of CSS, preserving the original HTML structure entirely.
    Returns {"text": str, "thinking": str}.
    """
    ovr = task_overrides or {}
    messages = [
        {"role": "system", "content": self._REFINE_CSS_SYSTEM},
        {"role": "user", "content": f"Improve this CSS:\n\n{css}"},
    ]
    return await self._call_stream(
        messages,
        on_token=None,
        max_tokens=min(self.max_tokens, 8192),  # CSS won't need 100k tokens
        temperature=ovr.get("temperature", 0.3),
        top_p=ovr.get("top_p", 0.9),
        enable_thinking=False,  # no thinking needed for CSS polish
        thinking_budget=0,
    )
```

---

### Task 3 — Replace Phase 3 in orchestrator.py (Bug 2)

**File:** `ct1/core/orchestrator.py`  
**Location:** `_design_pipeline()`, Phase 3 block starting at line ~881

Replace the entire Phase 3 block:

```python
# ── Phase 3: Self-refinement (AI rewrites for polish) ──────
if not skip_refinement:
    try:
        ...
        refine_result = await self.engine.refine_design(...)
        ...
    except Exception as e:
        ...
```

With the new CSS-only refinement:

```python
# ── Phase 3: CSS-only refinement ────────────────────────────
# Extract just the <style> block and ask the model to polish it.
# Much safer than full-page rewrite: HTML structure is preserved,
# the model only handles ~2-5 KB of CSS instead of the full page.
if not skip_refinement:
    try:
        from ct1.core.formatter import split_html_sections, reassemble_html_section
        sections = split_html_sections(draft)
        css = sections.get("style", "")
        if css and len(css.strip()) > 100:
            emit("refining")
            refine_ovr = {**task_ovr}
            refine_result = await self.engine.refine_css_only(
                css, task_overrides=refine_ovr,
            )
            improved_css = strip_think_tags(refine_result["text"])
            # Strip any accidental fences the model adds
            improved_css = re.sub(r'^```\w*\s*\n?', '', improved_css.strip())
            improved_css = re.sub(r'\n?```\s*$', '', improved_css)
            if improved_css and len(improved_css.strip()) > 50:
                final_response = reassemble_html_section(draft, "style", improved_css)
                emit("polished", code=final_response)
                print("[design] Phase 3: CSS-only refinement applied")
            else:
                print("[design] Phase 3: CSS refinement output empty, keeping original")
        else:
            print("[design] Phase 3: skipping — no meaningful CSS to refine")
    except Exception as e:
        print(f"[design] Phase 3: CSS refinement failed, keeping original: {e}")
```

---

## Notes for Implementation

- The `split_html_sections()` and `reassemble_html_section()` functions already
  exist in `ct1/core/formatter.py` — no new utilities needed.
- `re` is already imported in orchestrator.py.
- `strip_think_tags` is already imported.
- The `enable_thinking=False` in `refine_css_only()` saves tokens — no thinking
  needed for CSS polish, it's a well-defined mechanical task.
- If the design has inline styles but no `<style>` block (rare), Phase 3 is
  silently skipped — that's fine, the output is still valid.

---

## What Does NOT Change

- Phase 0 spec generation prompt — unchanged (the JSON schema stays the same)
- Phase 1 (full HTML generation) — unchanged  
- Phase 2 (mechanical cleanup) — unchanged
- Deterministic CSS polish (`polish_html_css()` in the polishing step) — unchanged
- `skip_refinement` flag — still works the same way
- Edit pipeline (`_design_edit_pipeline`) — not affected
- The retry logic in orchestrator Phase 0 — unchanged (still retries once on failure;
  the `_repair_json` fix should make the first attempt succeed in most cases)

---

## Implementation Order

1. **Task 1 first** (Bug 1 fix) — standalone, no dependencies, immediate improvement
2. **Task 2 + Task 3 together** (Bug 2 fix) — must be done as a pair
