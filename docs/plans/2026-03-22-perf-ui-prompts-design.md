# CT-2 Performance, Computer Panel UI, and Computer Mode Prompts

**Date:** 2026-03-22
**Status:** Approved
**Scope:** GPU performance optimization, computer panel visual redesign, computer mode prompt engineering

---

## Problem Statement

Three issues affecting CT-2:

1. **GPU performance** — The website uses up to 60% GPU due to 18+ simultaneous `backdrop-filter: blur()` CSS effects. This competes with llama-server which also needs the GPU for inference.

2. **Computer panel UI** — The file tree + terminal sidebar looks flat and disconnected from the glass morphism design system used by the rest of the app. `background: var(--surface-solid)` with no radius, no glass treatment.

3. **Computer mode prompts** — The AI generates HTML files even when asked for Python/C++ because: (a) file markers use HTML comment syntax (`<!-- FILE: -->`) which primes the 4B model toward HTML, (b) the planner biases `output_type` toward `html_page`, (c) the reviewer evaluates output as "HTML/CSS/JS."

---

## Section 1: GPU Performance — Selective Blur Reduction

### Keep blur (3 surfaces)
- `.ai-bubble` — signature glass chat bubble
- Nav bar in `+layout.svelte` — top-level frame
- `.computer-panel` / `.preview-panel` — major panel frames

### Remove blur (switch to solid)
- Pipeline cards: `.step`, `.gen-card`, `.think-block`, `.issues-card`
- Output/trace: `.output-card`, `.summary-chip`, `.trace-pill`, `.trace-card`
- Message attachments: `.file-chip`, `.computer-files-card`
- `TerminalPanel` toolbar + input row
- `FileTree` header

### Replacement pattern
```css
/* Before */
background: var(--bubble);
backdrop-filter: var(--bubble-blur);
border: var(--bubble-border);

/* After */
background: var(--surface);
border: 1px solid var(--border);
```

### Additional performance wins
- Add `@media (prefers-reduced-motion: reduce)` to disable pulse/breathe animations
- Use `will-change: transform` only on elements during entry animation, not permanently

---

## Section 2: Computer Panel — Integrated Glass Redesign

### Panel container
- `.computer-panel` gets glass treatment: `background: var(--bubble-strong)`, `backdrop-filter: var(--bubble-blur-heavy)` (allowed — it's a major panel frame)
- Inner content gets `border-radius: var(--radius)` with `overflow: hidden` and `margin: 8px` for inset card feel

### File tree section
- Replace fixed `height: 220px` with `flex: 0 0 auto`, `max-height: 240px`
- Header: solid `var(--surface)` background (no blur per perf rules)
- File items: `border-radius: var(--radius-sm)` hover states

### Terminal section
- Toolbar/input: solid `var(--surface)` backgrounds (no blur)
- Output area: stays `var(--code-bg)`
- Clean 1px `var(--border)` divider between file tree and terminal

### Visual effect
One cohesive glass card with two solid internal regions, matching the preview panel aesthetic.

---

## Section 3: Computer Mode Prompts — Neutral Markers + Language Reinforcement

### Marker syntax change
- `<!-- FILE: path -->` becomes `[FILE: path]`
- `<!-- RUN: cmd -->` becomes `[RUN: cmd]`
- Update parsers: `_parse_multi_file()`, `_parse_run_commands()`, `_strip_run_markers()` in orchestrator.py
- Update `parseFileList()` in `+page.svelte`
- Keep old `<!-- FILE: -->` regex as fallback for backward compatibility

### New `_GENERATOR_COMPUTER_SYSTEM` prompt
- Explicit language selection: "Detect the language from the user's request. NEVER default to HTML unless the user asks for a webpage."
- Multi-language examples: Python, JS, C++, shell scripts with `[FILE: path]` format
- Remove all HTML-specific wording
- `[RUN: cmd]` examples for pip, python, node, g++

### Pipeline changes for ROUTE_COMPUTER
- **Skip planner** (Phase 2) — plan `output_type` biases toward html_page
- **Skip validation/review** (Phase 5) — reviewer evaluates as HTML/CSS/JS
- **Skip reflection** — self-score calibrated for single-file HTML, not multi-file projects
- **Add `"computer"` to `_get_task_overrides`** route map for preset tuning

---

## Files to modify

### Frontend
- `ct1/web/src/app.css` — no changes needed (variables stay the same)
- `ct1/web/src/routes/+page.svelte` — remove blur from pipeline/trace CSS, update computer panel styles, update `parseFileList()` regex
- `ct1/web/src/lib/components/TerminalPanel.svelte` — remove blur from toolbar/input
- `ct1/web/src/lib/components/FileTree.svelte` — remove blur from header, add rounded hover states

### Backend
- `ct1/core/director.py` — rewrite `_GENERATOR_COMPUTER_SYSTEM` prompt
- `ct1/core/orchestrator.py` — update parsers for new markers, skip planner/validator/reflection for ROUTE_COMPUTER, add computer to task overrides map
