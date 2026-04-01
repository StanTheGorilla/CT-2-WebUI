# Design: Validation Rework + Code Mode Fix
**Date:** 2026-04-01

## Problem

Two connected issues:

1. **Validation broken across all modes** — `ROUTE_CODE` validation runs a LLM fix cycle for Python
   syntax errors, but after the fix there is no `emit("validated")` call. The UI stays stuck with
   `review.pass = false` permanently for that turn, so the validation warning badge is always lit.
   The same Python syntax error at line 14 has been triggering a fix cycle for a week with no
   improvement because the model re-generates near-identical code.

2. **Code mode outputs wrong file type** — `downloadCode()` in `+page.svelte` defaults to `'html'`
   for anything that isn't Python or JS. History downloads use `planTypeToExt` which defaults to
   `'txt'`. Two inconsistent paths. The planner's `_SOLO_PLAN_SYSTEM` only knows 5 output types so
   Go, Rust, TypeScript, Shell etc. all fall through to `'other'` → wrong extension. HTML-specific
   pipeline phases (polish pass, broken-section retry, `wrap_html_fragment`) run on `ROUTE_CODE`
   output when `output_type` is `"html_page"` or `"other"`.

## Solution: Option B — Soft validation, no fix cycles

### Section 1 — Validation rework (`orchestrator.py`)

**Rule:** No LLM fix cycle fires for `ROUTE_CODE`. Validation is observe-only.

In Phase 5 (`ROUTE_CODE` branch):
- Run `validate_output` as before to collect issues.
- Define "catastrophic" as: output length < 50 chars or empty. Everything else is soft.
- Emit `emit("validating", soft=True, issues=issues)` regardless of issue count.
- Always follow with `emit("validated", pass=True, issues=issues)` — UI state never gets stuck.
- Remove the `emit("fixing")` + `generate(fix_prompt)` block for `ROUTE_CODE`.

HTML-specific phases skipped for `ROUTE_CODE`:
- Polish pass (`polish_html_css`) — already gated on `output_type == "html_page"`, verify it stays so.
- Broken-section retry loop — gated on `_retry_output_type in ("html_page", "other")`;
  add explicit `route != "ROUTE_CODE"` guard so Python/JS/etc. never enter this loop.
- `fix_html_structure` call — already gated on `output_type in ("html_page", "other")`, keep as-is.

### Section 2 — File extension + type system

**`formatter.py` — `detect_output_type`:**
Add detection for:
- `typescript` — starts with `import type`, `interface `, `type `, or has `: string` / `: number` patterns
- `shell` — starts with `#!/bin/bash`, `#!/bin/sh`, or `#!/usr/bin/env`
- `sql` — starts with `SELECT`, `CREATE`, `INSERT`, `DROP`, `ALTER`

**`orchestrator.py` — `_SOLO_PLAN_SYSTEM`:**
Expand planner type list:
```
"output_type":"html_page"|"python_script"|"javascript"|"typescript"|"cpp"|"go"|"rust"|"shell"|"sql"|"other"
```
Update `valid_types` tuple in `_solo_plan` to match.

**`+page.svelte` — `planTypeToExt`:**
Add mappings:
```javascript
case 'typescript': return 'ts';
case 'shell':      return 'sh';
case 'sql':        return 'sql';
```

**`+page.svelte` — `downloadCode`:**
Replace inline ext logic with `planTypeToExt($chat.plan?.output_type)`. One source of truth.
Also fix MIME type map in `downloadBlob` to include `ts`, `sh`, `sql`.

### Section 3 — Validation UI (`chat.ts` + `+page.svelte`)

**`chat.ts`:** No changes needed to event handlers — `validated` now always fires, clearing
`validationIssues`. The existing flow works correctly once the backend always emits `validated`.

**`+page.svelte` trace pill:**
The validation trace pill currently shows warning color whenever `hasValidation` is true
(`!!review || validationIssues.length > 0`). After this change `review.pass` will always be `true`
for `ROUTE_CODE`, so the pill can remain but will not show an alarming state. No UI change needed.

## Files changed

| File | Change |
|------|--------|
| `ct1/core/orchestrator.py` | Remove fix cycle for `ROUTE_CODE`; always emit `validated`; guard broken-section retry |
| `ct1/core/formatter.py` | Add `typescript`, `shell`, `sql` detection to `detect_output_type` |
| `ct1/web/src/routes/+page.svelte` | Fix `downloadCode`; expand `planTypeToExt`; fix `downloadBlob` MIME map |
| `ct1/server/model_config.yaml` | No change |

## Out of scope

- Removing validation from `ROUTE_DESIGN` or `ROUTE_COMPUTER` — those are working correctly.
- Reworking `validate_python` / `validate_cpp` logic — validators are correct, just used wrong.
- Atlas mode changes.
