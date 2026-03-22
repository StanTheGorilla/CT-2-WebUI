# CT-2 Performance, Computer Panel UI, and Computer Mode Prompts — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce GPU usage by removing unnecessary `backdrop-filter: blur()`, redesign the computer panel with integrated glass aesthetics, and fix computer mode prompts so the AI generates the correct file types instead of always defaulting to HTML.

**Architecture:** CSS changes replace `backdrop-filter` with solid backgrounds on 15+ elements while preserving blur on 3 key surfaces. Computer panel gets glass container treatment with inset card layout. Backend changes rewrite the computer mode system prompt with language-neutral `[FILE:]` markers, and skip the planner/validator/reflection pipeline phases for ROUTE_COMPUTER.

**Tech Stack:** SvelteKit 5 (Svelte 5 runes) / CSS custom properties, Python 3.10+ / FastAPI, llama.cpp (4B model)

---

### Task 1: Remove backdrop-filter from pipeline cards in +page.svelte

**Files:**
- Modify: `ct1/web/src/routes/+page.svelte:1024-1036` (`.step`)
- Modify: `ct1/web/src/routes/+page.svelte:1061-1072` (`.gen-card`)
- Modify: `ct1/web/src/routes/+page.svelte:1150-1160` (`.think-block`)
- Modify: `ct1/web/src/routes/+page.svelte:1197-1207` (`.issues-card`)
- Modify: `ct1/web/src/routes/+page.svelte:1239-1248` (`.output-card`)

**Step 1: Replace blur with solid backgrounds on pipeline cards**

In each of these CSS blocks, replace the 3-line blur pattern:
```css
/* REMOVE these 3 lines wherever they appear: */
background: var(--bubble);
backdrop-filter: var(--bubble-blur);
-webkit-backdrop-filter: var(--bubble-blur);
border: var(--bubble-border);

/* REPLACE with: */
background: var(--surface);
border: 1px solid var(--border);
```

Apply to:
- `.step` (line 1027-1031): replace background/backdrop/border
- `.gen-card` (line 1062-1065): replace background/backdrop/border
- `.think-block` (line 1151-1154): replace background/backdrop/border
- `.issues-card` (line 1198-1201): replace background/backdrop/border
- `.output-card` (line 1240-1243): replace background/backdrop/border

Keep all other properties (border-radius, box-shadow, animations) unchanged.

**Step 2: Verify build**

Run: `cd ct1/web && npm run build`
Expected: Build succeeds with no errors.

**Step 3: Commit**

```bash
git add ct1/web/src/routes/+page.svelte
git commit -m "perf: remove backdrop-filter from pipeline cards"
```

---

### Task 2: Remove backdrop-filter from trace/summary elements in +page.svelte

**Files:**
- Modify: `ct1/web/src/routes/+page.svelte:897-912` (`.file-chip`)
- Modify: `ct1/web/src/routes/+page.svelte:1300-1311` (`.summary-chip`)
- Modify: `ct1/web/src/routes/+page.svelte:1319-1335` (`.trace-pill`)
- Modify: `ct1/web/src/routes/+page.svelte:1361-1371` (`.trace-card`)
- Modify: `ct1/web/src/routes/+page.svelte:1485-1495` (`.computer-files-card`)

**Step 1: Replace blur with solid backgrounds on trace/summary elements**

Apply the same replacement pattern to:

`.file-chip` (lines 900-903):
```css
/* Replace */
background: var(--bubble-strong);
backdrop-filter: var(--bubble-blur);
-webkit-backdrop-filter: var(--bubble-blur);
border: var(--bubble-border);
/* With */
background: var(--surface);
border: 1px solid var(--border);
```

`.summary-chip` (lines 1303-1307):
```css
/* Replace */
background: var(--bubble);
backdrop-filter: var(--bubble-blur);
-webkit-backdrop-filter: var(--bubble-blur);
border: var(--bubble-border);
/* With */
background: var(--surface);
border: 1px solid var(--border);
```

`.trace-pill` (lines 1322-1326):
```css
/* Replace */
background: var(--bubble);
backdrop-filter: var(--bubble-blur);
-webkit-backdrop-filter: var(--bubble-blur);
border: var(--bubble-border);
/* With */
background: var(--surface);
border: 1px solid var(--border);
```

`.trace-card` (lines 1362-1366):
```css
/* Replace */
background: var(--bubble);
backdrop-filter: var(--bubble-blur);
-webkit-backdrop-filter: var(--bubble-blur);
border: var(--bubble-border);
/* With */
background: var(--surface);
border: 1px solid var(--border);
```

`.computer-files-card` (lines 1486-1489):
```css
/* Replace */
background: var(--bubble);
backdrop-filter: var(--bubble-blur);
-webkit-backdrop-filter: var(--bubble-blur);
border: var(--bubble-border-light);
/* With */
background: var(--surface);
border: 1px solid var(--border);
```

**Step 2: Verify build**

Run: `cd ct1/web && npm run build`
Expected: Build succeeds.

**Step 3: Commit**

```bash
git add ct1/web/src/routes/+page.svelte
git commit -m "perf: remove backdrop-filter from trace pills, summary chips, file cards"
```

---

### Task 3: Remove backdrop-filter from TerminalPanel and FileTree

**Files:**
- Modify: `ct1/web/src/lib/components/TerminalPanel.svelte:128-135` (`.term-toolbar`)
- Modify: `ct1/web/src/lib/components/TerminalPanel.svelte:196-203` (`.term-input-row`)
- Modify: `ct1/web/src/lib/components/FileTree.svelte:112-118` (`.tree-header`)

**Step 1: Replace blur in TerminalPanel toolbar**

In `.term-toolbar` (lines 130-132):
```css
/* Replace */
background: var(--bubble);
backdrop-filter: var(--bubble-blur);
-webkit-backdrop-filter: var(--bubble-blur);
border-bottom: var(--bubble-border-light);
/* With */
background: var(--surface);
border-bottom: 1px solid var(--border);
```

In `.term-input-row` (lines 199-202):
```css
/* Replace */
background: var(--bubble);
backdrop-filter: var(--bubble-blur);
-webkit-backdrop-filter: var(--bubble-blur);
border-top: var(--bubble-border-light);
/* With */
background: var(--surface);
border-top: 1px solid var(--border);
```

**Step 2: Replace blur in FileTree header**

In `.tree-header` (lines 114-117):
```css
/* Replace */
background: var(--bubble);
backdrop-filter: var(--bubble-blur);
-webkit-backdrop-filter: var(--bubble-blur);
border-bottom: var(--bubble-border-light);
/* With */
background: var(--surface);
border-bottom: 1px solid var(--border);
```

**Step 3: Verify build**

Run: `cd ct1/web && npm run build`
Expected: Build succeeds.

**Step 4: Commit**

```bash
git add ct1/web/src/lib/components/TerminalPanel.svelte ct1/web/src/lib/components/FileTree.svelte
git commit -m "perf: remove backdrop-filter from terminal and file tree headers"
```

---

### Task 4: Add prefers-reduced-motion and optimize donut animation

**Files:**
- Modify: `ct1/web/src/app.css` — add reduced motion media query at end
- Modify: `ct1/web/src/routes/+layout.svelte:115` — reduce donut frame rate

**Step 1: Add reduced motion support in app.css**

Append at end of `ct1/web/src/app.css`:
```css
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
    }
}
```

**Step 2: Reduce donut frame rate**

In `ct1/web/src/routes/+layout.svelte` line 115, change:
```javascript
const id = setInterval(renderFrame, 50);
```
to:
```javascript
const id = setInterval(renderFrame, 100);
```

This halves the CPU cost (10fps instead of 20fps — the donut is a background texture, not interactive).

**Step 3: Verify build**

Run: `cd ct1/web && npm run build`
Expected: Build succeeds.

**Step 4: Commit**

```bash
git add ct1/web/src/app.css ct1/web/src/routes/+layout.svelte
git commit -m "perf: add prefers-reduced-motion, reduce donut framerate"
```

---

### Task 5: Redesign computer panel with integrated glass layout

**Files:**
- Modify: `ct1/web/src/routes/+page.svelte:1453-1473` (`.computer-panel`, `.computer-split`, `.computer-files`, `.computer-term`)
- Modify: `ct1/web/src/routes/+page.svelte:767-800` (computer panel HTML)

**Step 1: Replace computer panel CSS**

Replace the entire computer panel CSS block (lines 1453-1473) with:
```css
    .computer-panel {
        top: 56px;
        background: var(--bubble-strong);
        backdrop-filter: var(--bubble-blur-heavy);
        -webkit-backdrop-filter: var(--bubble-blur-heavy);
        border-left: 1px solid var(--border);
    }
    .computer-split {
        display: flex;
        flex-direction: column;
        height: 100%;
        margin: 8px;
        border-radius: var(--radius);
        overflow: hidden;
        background: var(--surface-solid);
        border: 1px solid var(--border);
        box-shadow: var(--shadow-sm);
    }
    .computer-files {
        flex: 0 0 auto;
        max-height: 240px;
        overflow: hidden;
        border-bottom: 1px solid var(--border);
    }
    .computer-term {
        flex: 1;
        overflow: hidden;
    }
```

**Step 2: Update FileTree hover states**

In `ct1/web/src/lib/components/FileTree.svelte`, update `.tree-file` (line 172):
```css
    .tree-file {
        /* keep existing properties */
        border-radius: var(--radius-sm);
        margin: 0 4px;
        width: calc(100% - 8px);
    }
```

Change the existing `border-radius: 0;` to `border-radius: var(--radius-sm);` and add margin + width.

**Step 3: Verify build**

Run: `cd ct1/web && npm run build`
Expected: Build succeeds.

**Step 4: Commit**

```bash
git add ct1/web/src/routes/+page.svelte ct1/web/src/lib/components/FileTree.svelte
git commit -m "feat: redesign computer panel with integrated glass layout"
```

---

### Task 6: Rewrite computer mode system prompt

**Files:**
- Modify: `ct1/core/director.py:73-96` (`_GENERATOR_COMPUTER_SYSTEM`)

**Step 1: Replace the prompt**

Replace lines 73-96 (`_GENERATOR_COMPUTER_SYSTEM = (` through the closing `)`) with:

```python
_GENERATOR_COMPUTER_SYSTEM = (
    "You are the CT-2 Director, an expert full-stack developer.\n"
    "You create complete project files in ANY programming language.\n\n"
    "LANGUAGE SELECTION — critical:\n"
    "- Read the user's request carefully to determine the language.\n"
    "- Python request → write .py files. C++ request → write .cpp/.h files.\n"
    "- JavaScript request → write .js files. HTML/website request → write .html files.\n"
    "- NEVER default to HTML. Only use HTML if the user explicitly asks for a webpage.\n\n"
    "OUTPUT FORMAT — file markers:\n"
    "[FILE: path/to/file.ext]\n"
    "file content here\n"
    "[FILE: another/file.py]\n"
    "file content here\n\n"
    "RULES:\n"
    "- Every file MUST start with a [FILE: path] marker on its own line\n"
    "- Use relative paths (e.g. main.py, src/utils.js, include/math.h)\n"
    "- Write COMPLETE file contents — no placeholders, no TODOs, no stubs\n"
    "- No markdown fences. No explanations outside file markers.\n"
    "- For Python: include requirements.txt if external packages are needed\n"
    "- For C/C++: include a Makefile or CMakeLists.txt if appropriate\n"
    "- For Node.js: include package.json if npm packages are needed\n\n"
    "TERMINAL COMMANDS — to run commands after files are saved:\n"
    "[RUN: command here]\n"
    "Place RUN markers AFTER all FILE markers. They execute in the workspace directory.\n"
    "Examples:\n"
    "  [RUN: pip install -r requirements.txt]\n"
    "  [RUN: python main.py]\n"
    "  [RUN: node index.js]\n"
    "  [RUN: g++ -o main main.cpp && ./main]\n"
    "  [RUN: npm install && npm start]\n"
    "Only include RUN commands when the user would expect execution.\n\n"
    "EXAMPLES:\n\n"
    "User: \"create a python calculator\"\n"
    "[FILE: main.py]\n"
    "def add(a, b): return a + b\n"
    "...\n\n"
    "User: \"make a sorting algorithm in C++\"\n"
    "[FILE: sort.cpp]\n"
    "#include <iostream>\n"
    "...\n\n"
    "User: \"build a todo app website\"\n"
    "[FILE: index.html]\n"
    "<!DOCTYPE html>\n"
    "...\n"
)
```

**Step 2: Commit**

```bash
git add ct1/core/director.py
git commit -m "feat: rewrite computer mode prompt with language-neutral markers"
```

---

### Task 7: Update marker parsers in orchestrator.py

**Files:**
- Modify: `ct1/core/orchestrator.py:400-403` (`_parse_run_commands`)
- Modify: `ct1/core/orchestrator.py:405-407` (`_strip_run_markers`)
- Modify: `ct1/core/orchestrator.py:409-465` (`_parse_multi_file`)

**Step 1: Update `_parse_run_commands` (line 402)**

Replace:
```python
return re.findall(r'<!--\s*RUN:\s*(.+?)\s*-->', text)
```
With:
```python
# Support both new [RUN: cmd] and legacy <!-- RUN: cmd --> markers
return re.findall(r'(?:\[RUN:\s*(.+?)\]|<!--\s*RUN:\s*(.+?)\s*-->)', text)
```

Wait — `re.findall` with two groups returns tuples. Fix:
```python
matches = re.findall(r'\[RUN:\s*(.+?)\]', text)
# Fallback: legacy HTML markers
if not matches:
    matches = re.findall(r'<!--\s*RUN:\s*(.+?)\s*-->', text)
return matches
```

**Step 2: Update `_strip_run_markers` (line 407)**

Replace:
```python
return re.sub(r'<!--\s*RUN:\s*.+?\s*-->\s*', '', text).strip()
```
With:
```python
text = re.sub(r'\[RUN:\s*.+?\]\s*', '', text)
text = re.sub(r'<!--\s*RUN:\s*.+?\s*-->\s*', '', text)  # legacy
return text.strip()
```

**Step 3: Update `_parse_multi_file` (lines 423-424)**

Replace the Pattern 1 section. Line 424:
```python
parts = re.split(r'<!--\s*FILE:\s*(.+?)\s*-->', text)
```
With:
```python
# Try new [FILE: path] markers first
parts = re.split(r'\[FILE:\s*(.+?)\]', text)
if len(parts) <= 2:
    # Fallback: legacy <!-- FILE: path --> markers
    parts = re.split(r'<!--\s*FILE:\s*(.+?)\s*-->', text)
```

**Step 4: Commit**

```bash
git add ct1/core/orchestrator.py
git commit -m "feat: update parsers for [FILE:] and [RUN:] markers with legacy fallback"
```

---

### Task 8: Skip planner, validator, and reflection for ROUTE_COMPUTER

**Files:**
- Modify: `ct1/core/orchestrator.py:666` (Phase 2 planner gate)
- Modify: `ct1/core/orchestrator.py:751` (Phase 5 validator gate)
- Modify: `ct1/core/orchestrator.py:846` (Reflection gate)
- Modify: `ct1/core/orchestrator.py:389-395` (`_get_task_overrides` route map)

**Step 1: Gate planner for ROUTE_COMPUTER**

Line 666, change:
```python
if is_code and not is_edit and self.specialist:
```
To:
```python
if is_code and not is_edit and self.specialist and route != "ROUTE_COMPUTER":
```

**Step 2: Gate validator for ROUTE_COMPUTER**

Line 751, change:
```python
if is_code and not is_edit:
```
To:
```python
if is_code and not is_edit and route != "ROUTE_COMPUTER":
```

**Step 3: Gate reflection for ROUTE_COMPUTER**

Line 846, change:
```python
if is_code:
```
To:
```python
if is_code and route != "ROUTE_COMPUTER":
```

**Step 4: Add computer to task overrides map**

Lines 389-395, change the `route_map` dict:
```python
route_map = {
    "ROUTE_CODE": "code",
    "ROUTE_DESIGN": "design",
    "ROUTE_DIRECT": "direct",
}
```
To:
```python
route_map = {
    "ROUTE_CODE": "code",
    "ROUTE_DESIGN": "design",
    "ROUTE_DIRECT": "direct",
    "ROUTE_COMPUTER": "computer",
}
```

**Step 5: Commit**

```bash
git add ct1/core/orchestrator.py
git commit -m "feat: skip planner/validator/reflection for ROUTE_COMPUTER"
```

---

### Task 9: Update parseFileList regex in +page.svelte

**Files:**
- Modify: `ct1/web/src/routes/+page.svelte:252-255` (`parseFileList` function)

**Step 1: Update the regex**

Replace lines 252-255:
```typescript
/** Parse <!-- FILE: path --> markers from computer mode response */
function parseFileList(text: string): string[] {
    const matches = text.matchAll(/<!--\s*FILE:\s*(.+?)\s*-->/g);
    return [...matches].map(m => m[1].trim());
}
```
With:
```typescript
/** Parse [FILE: path] markers from computer mode response (with legacy fallback) */
function parseFileList(text: string): string[] {
    let matches = [...text.matchAll(/\[FILE:\s*(.+?)\]/g)];
    if (matches.length === 0) {
        matches = [...text.matchAll(/<!--\s*FILE:\s*(.+?)\s*-->/g)];
    }
    return matches.map(m => m[1].trim());
}
```

**Step 2: Verify build**

Run: `cd ct1/web && npm run build`
Expected: Build succeeds.

**Step 3: Commit**

```bash
git add ct1/web/src/routes/+page.svelte
git commit -m "feat: update parseFileList for [FILE:] markers with legacy fallback"
```

---

### Task 10: Final build and verification

**Step 1: Full frontend build**

Run: `cd ct1/web && npm run build`
Expected: Build succeeds, output written to `ct1/web/build/`.

**Step 2: Verify Python imports**

Run: `cd F:/AI_Workstation/web-ui && python -c "from ct1.core.orchestrator import Orchestrator; from ct1.core.director import Director; print('OK')"`
Expected: Prints `OK`.

**Step 3: Spot-check regex changes**

Run: `cd F:/AI_Workstation/web-ui && python -c "
from ct1.core.orchestrator import Orchestrator
# Test new markers
text = '[FILE: main.py]\nprint(\"hello\")\n[FILE: utils.py]\ndef add(a,b): return a+b\n[RUN: python main.py]'
files = Orchestrator._parse_multi_file(text)
cmds = Orchestrator._parse_run_commands(text)
print(f'Files: {[f[\"path\"] for f in files]}')
print(f'Commands: {cmds}')
# Test legacy markers
text2 = '<!-- FILE: old.html -->\n<html></html>'
files2 = Orchestrator._parse_multi_file(text2)
print(f'Legacy: {[f[\"path\"] for f in files2]}')
"`
Expected:
```
Files: ['main.py', 'utils.py']
Commands: ['python main.py']
Legacy: ['old.html']
```
