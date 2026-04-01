# Plan: Fix Design Refinement Stage

**Date:** 2026-04-01  
**Status:** Ready to implement  
**Priority:** High — current refinement actively degrades output quality

---

## Problem

The current Phase 3 refinement in `_design_pipeline()` sends the full HTML page
(30–50 KB, 1000+ lines) to the model and asks it to "rewrite it to be
significantly better." A 4B model cannot hold that much content in attention
and surgically improve it — it generates a fresh page from scratch, losing
the original content/structure and often producing shorter, worse output.

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
| `ct1/core/engine.py` | Add `_REFINE_CSS_SYSTEM` prompt; add `refine_css_only()` method |
| `ct1/core/orchestrator.py` | Replace Phase 3 full-rewrite with CSS-only refinement |

---

## Task List

### Task 1 — Add CSS-only refinement to engine.py

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

### Task 2 — Replace Phase 3 in orchestrator.py

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

- Phase 0 (spec generation) — unchanged
- Phase 1 (full HTML generation) — unchanged  
- Phase 2 (mechanical cleanup) — unchanged
- Deterministic CSS polish (`polish_html_css()` in the polishing step) — unchanged
- `skip_refinement` flag — still works the same way
- Edit pipeline (`_design_edit_pipeline`) — not affected
