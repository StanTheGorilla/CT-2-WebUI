# Design: Settings UX + Chat Bug + Mode Order

**Date:** 2026-04-06  
**Status:** Approved

---

## Changes

### 1. Settings Page Restructure (settings/+page.svelte)

Rename sections and sliders throughout. No layout or logic changes — labels and descriptions only.

**Section renames:**

| Before | After |
|---|---|
| Backend + Context Size (separate) | Performance (merged section) |
| Routing Modes | Response Style |
| System Prompts | Custom Instructions |
| Pipeline | Features |

**Slider renames (inside Response Style cards):**

| Before | After | Description |
|---|---|---|
| temperature | Creativity | How surprising vs. predictable responses are |
| top_p | Focus | How broad or precise word choices are |
| presence_penalty | Variety | How much the AI avoids repeating itself |

**Other label renames:**

| Before | After | Description |
|---|---|---|
| Context Window (slider label) | Memory Window | "How much conversation the AI remembers. Larger = richer context but uses more VRAM." |
| Backend (row label) | GPU Backend | — |

**New section: Performance**  
Merge the Backend row and Context Size section into a single `<section>` with header "Performance". Order: GPU Backend first, Memory Window second. Restart banner stays where it is (below slider).

**Custom Instructions description**  
Add a `<p class="section-desc">` below the "Custom Instructions" heading:  
`"Built-in instructions for each mode. Advanced — restart required after saving."`

**All other logic, state, error handling, and API calls are unchanged.**

---

### 2. Chat Mode Bug Fix (ct1/core/engine.py)

**File:** `ct1/core/engine.py`  
**Method:** `_call_stream` (~line 475, the `return` at the end of the streaming loop)

**Root cause:** When a thinking model emits only `reasoning_content` tokens (no `content` tokens), `text` stays `""`. The `done` event then sends `response: ""` → frontend renders no ai-bubble, leaving the answer trapped in the thinking trace.

The non-streaming `_call` already handles this fallback correctly (lines 320–326). `_call_stream` needs the same.

**Fix — replace the return at end of `_call_stream`:**
```python
# Before
return {"text": text.strip(), "thinking": thinking.strip()}

# After
if not text and thinking:
    text, thinking = thinking, ""
return {"text": text.strip(), "thinking": thinking.strip()}
```

No frontend changes needed.

---

### 3. Mode Order (ct1/web/src/lib/components/ChatInput.svelte)

**File:** `ct1/web/src/lib/components/ChatInput.svelte`  
**Lines:** 16–22 (the `modes` array)

**Change:**
```typescript
// Before
{ key: 'auto', label: 'Auto' },
{ key: 'design', label: 'Design' },
{ key: 'code', label: 'Code' },
{ key: 'chat', label: 'Chat' },
{ key: 'computer', label: 'Computer' },

// After
{ key: 'chat', label: 'Chat' },
{ key: 'design', label: 'Design' },
{ key: 'code', label: 'Code' },
{ key: 'computer', label: 'Computer' },
{ key: 'auto', label: 'Auto' },
```

---

## Files Touched

1. `ct1/web/src/routes/settings/+page.svelte` — labels, descriptions, section merge
2. `ct1/core/engine.py` — 2-line streaming fallback fix
3. `ct1/web/src/lib/components/ChatInput.svelte` — mode array reorder
