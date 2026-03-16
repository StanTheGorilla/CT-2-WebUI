# Glassmorphism + ASCII Art UI Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform CT-2 web UI from flat Apple-light to glassmorphism with ASCII art background, cool greige palette, floating input island, and fix preview iframe sandbox.

**Architecture:** CSS-first redesign. Replace color variables and add glass utility values in app.css. Add ASCII art layer in layout. Update each component's styles for frosted glass. Fix iframe security.

**Tech Stack:** SvelteKit 5, CSS (backdrop-filter, rgba), HTML (pre for ASCII art)

---

### Task 1: Update Color Palette & Add Glass Variables in app.css

**Files:**
- Modify: `ct1/web/src/app.css`

**Step 1: Replace CSS variables and add glass utilities**

Replace the `:root` block and add a `.glass` utility:

```css
:root {
    --bg: #EDEAE6;
    --surface: rgba(255, 255, 255, 0.80);
    --surface-hover: rgba(255, 255, 255, 0.90);
    --surface-solid: #FFFFFF;
    --border: rgba(168, 160, 160, 0.25);
    --text: #2C2A28;
    --text-secondary: #7A7572;
    --text-muted: #B5B0AC;

    --accent: #A8A0A0;
    --specialist: #AF52DE;
    --brain: #FF9500;
    --success: #34C759;
    --warning: #FF9F0A;
    --error: #FF3B30;

    --shadow-sm: 0 2px 8px rgba(0,0,0,0.04);
    --shadow-md: 0 4px 16px rgba(0,0,0,0.06);
    --shadow-lg: 0 8px 32px rgba(0,0,0,0.08);

    --glass-blur: blur(16px);
    --glass-border: 1px solid rgba(168, 160, 160, 0.25);
    --glass-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);

    --font-body: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    --font-mono: 'JetBrains Mono', 'SF Mono', monospace;
    --radius: 12px;
    --radius-pill: 20px;
    --transition: 200ms ease;
    --spring: cubic-bezier(0.34, 1.56, 0.64, 1);
    --spring-soft: cubic-bezier(0.34, 1.3, 0.64, 1);
    --spring-duration: 400ms;
}
```

Also update `::selection` from `var(--accent)` to `#8A8280` (slightly darker greige for selection visibility).

**Step 2: Verify build**

Run: `cd F:/AI_Workstation/ct/.worktrees/web-ui/ct1/web && npm run build 2>&1 | head -5`
Expected: Build starts without CSS errors

**Step 3: Commit**

```bash
git add ct1/web/src/app.css
git commit -m "style: swap palette to warm greige, add glass CSS variables"
```

---

### Task 2: Add ASCII Art Background Layer in Layout

**Files:**
- Modify: `ct1/web/src/routes/+layout.svelte`

**Step 1: Add ASCII art div and update styles**

Add an ASCII art background div inside `.app`, before the header. The art is a circuit-board/brain pattern rendered in light greige monospace text. It sits fixed behind everything.

In the `<div class="app">`, add as first child:

```svelte
<div class="ascii-bg" aria-hidden="true">
<pre>{@html asciiArt}</pre>
</div>
```

In the `<script>` block, add the ASCII art string:

```typescript
const asciiArt = `
+-------+    .----.    +-------+    .----.    +-------+    .----.    +-------+
|  .-.  |---( C T )----|  .-.  |---( 0 1 )----|  .-.  |---( A I )----|  .-.  |
| /   \\ |    '----'    | /   \\ |    '----'    | /   \\ |    '----'    | /   \\ |
|( o.o )|    ||  ||    |( _._ )|    ||  ||    |( ^.^ )|    ||  ||    |( o.o )|
| \\   / |    ||  ||    | \\   / |    ||  ||    | \\   / |    ||  ||    | \\   / |
|  '-'  |====''  ''====|  '-'  |====''  ''====|  '-'  |====''  ''====|  '-'  |
+-------+              +-------+              +-------+              +-------+
    ||    ___......___      ||    ___......___      ||    ___......___     ||
    ||   / ========= \\     ||   / ========= \\     ||   / ========= \\    ||
    ||  | +---------+ |    ||  | +---------+ |    ||  | +---------+ |   ||
    ||  | | PROCESS | |    ||  | | MEMORY  | |    ||  | | OUTPUT  | |   ||
    ||  | +---------+ |    ||  | +---------+ |    ||  | +---------+ |   ||
    ||  | |  >>===>>| |    ||  | |  <>==<> | |    ||  | |  <<===<<| |   ||
    ||  | |  ||   || | |    ||  | |  ||   || | |    ||  | |  ||   || | |   ||
    ||  | |  vv   vv | |    ||  | |  ^^   ^^ | |    ||  | |  vv   vv | |   ||
    ||   \\ ========= /     ||   \\ ========= /     ||   \\ ========= /    ||
    ||    '''......'''      ||    '''......'''      ||    '''......'''     ||
====++====================++====================++====================++====
    ::      ::      ::      ::      ::      ::      ::      ::      ::
  .-||-.  .-||-.  .-||-.  .-||-.  .-||-.  .-||-.  .-||-.  .-||-.  .-||-.
  | [] |  | [] |  | [] |  | [] |  | [] |  | [] |  | [] |  | [] |  | [] |
  '----'  '----'  '----'  '----'  '----'  '----'  '----'  '----'  '----'
    ||      ||      ||      ||      ||      ||      ||      ||      ||
+---++------++------++------++------++------++------++------++------++---+
|                         NEURAL  PATHWAY  BUS                           |
+---++------++------++------++------++------++------++------++------++---+
    ||      ||      ||      ||      ||      ||      ||      ||      ||
  .-||-.  .-||-.  .-||-.  .-||-.  .-||-.  .-||-.  .-||-.  .-||-.  .-||-.
  |<-->|  |<-->|  |<-->|  |<-->|  |<-->|  |<-->|  |<-->|  |<-->|  |<-->|
  '----'  '----'  '----'  '----'  '----'  '----'  '----'  '----'  '----'
    ::      ::      ::      ::      ::      ::      ::      ::      ::
====++====================++====================++====================++====
    ||    ___......___      ||    ___......___      ||    ___......___     ||
    ||   / ========= \\     ||   / ========= \\     ||   / ========= \\    ||
    ||  | +---------+ |    ||  | +---------+ |    ||  | +---------+ |   ||
    ||  | | REASON  | |    ||  | | REFLECT | |    ||  | | CREATE  | |   ||
    ||  | +---------+ |    ||  | +---------+ |    ||  | +---------+ |   ||
    ||   \\ ========= /     ||   \\ ========= /     ||   \\ ========= /    ||
    ||    '''......'''      ||    '''......'''      ||    '''......'''     ||
+-------+    .----.    +-------+    .----.    +-------+    .----.    +-------+
|  .-.  |---( ** )----|  .-.  |---( << )----|  .-.  |---( >> )----|  .-.  |
| /   \\ |    '----'    | /   \\ |    '----'    | /   \\ |    '----'    | /   \\ |
|( o.o )|              |( _._ )|              |( ^.^ )|              |( o.o )|
| \\   / |==============| \\   / |==============| \\   / |==============| \\   / |
|  '-'  |              |  '-'  |              |  '-'  |              |  '-'  |
+-------+              +-------+              +-------+              +-------+
`.trim();
```

Add CSS for the ASCII background:

```css
.ascii-bg {
    position: fixed;
    inset: 0;
    z-index: 0;
    overflow: hidden;
    pointer-events: none;
    display: flex;
    align-items: center;
    justify-content: center;
}
.ascii-bg pre {
    font-family: var(--font-mono);
    font-size: 11px;
    line-height: 1.3;
    color: #C8C2BC;
    white-space: pre;
    margin: 0;
    padding: 0;
    background: none;
    border: none;
    user-select: none;
}
```

Update `.status-strip` to glass:

```css
.status-strip {
    height: 44px;
    display: flex;
    align-items: center;
    padding: 0 20px;
    background: var(--surface);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border-bottom: var(--glass-border);
    box-shadow: var(--glass-shadow);
    flex-shrink: 0;
    z-index: 100;
    position: relative;
}
```

Update `.app` to set position relative, and `main` to `position: relative; z-index: 1;`.

Update `.strip-nav a.active` from `color: var(--accent)` to `color: var(--text)` (greige accent is too close to inactive text).

**Step 2: Verify build**

Run: `cd F:/AI_Workstation/ct/.worktrees/web-ui/ct1/web && npm run build 2>&1 | head -5`

**Step 3: Commit**

```bash
git add ct1/web/src/routes/+layout.svelte
git commit -m "style: add ASCII art background layer and glass header"
```

---

### Task 3: Glass Chat Bubbles & Stream Cards in +page.svelte

**Files:**
- Modify: `ct1/web/src/routes/+page.svelte`

**Step 1: Update chat panel and bubble styles**

Replace these CSS rules in the `<style>` block:

`.user-msg`: Change `background: var(--accent)` to `background: rgba(168, 160, 160, 0.85)`. Add `backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);`. Change `box-shadow: var(--shadow-sm)` to `box-shadow: var(--glass-shadow)`.

`.assistant-msg`: Change `background: var(--surface)` stays. Add `backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);`. Change `border` to `var(--glass-border)`. Change `box-shadow` to `var(--glass-shadow)`.

`.stream-card`: Add `backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);`. Change border to `var(--glass-border)`. Change `box-shadow` to `var(--glass-shadow)` (add it).

`.validation`: Add `backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);`.

`.messages`: Add `position: relative; z-index: 1;`.

**Step 2: Verify build**

Run: `cd F:/AI_Workstation/ct/.worktrees/web-ui/ct1/web && npm run build 2>&1 | head -5`

**Step 3: Commit**

```bash
git add ct1/web/src/routes/+page.svelte
git commit -m "style: glass chat bubbles and stream cards"
```

---

### Task 4: Floating Input Island

**Files:**
- Modify: `ct1/web/src/lib/components/ChatInput.svelte`

**Step 1: Update ChatInput styles for floating island**

Replace `.chat-input` styles:

```css
.chat-input {
    padding: 12px 20px 20px;
    background: transparent;
    flex-shrink: 0;
    position: relative;
    z-index: 2;
}
```

Replace `.input-row` styles:

```css
.input-row {
    display: flex;
    align-items: flex-end;
    gap: 8px;
    max-width: 680px;
    margin: 0 auto;
    background: rgba(255, 255, 255, 0.85);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid rgba(168, 160, 160, 0.25);
    border-radius: 28px;
    padding: 8px 8px 8px 20px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.08);
    transition: border-color var(--transition), box-shadow var(--transition);
}
```

Replace `.input-row:focus-within`:

```css
.input-row:focus-within {
    border-color: rgba(168, 160, 160, 0.5);
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.08), 0 0 0 3px rgba(168, 160, 160, 0.15);
}
```

Replace `.send-btn` background:

```css
.send-btn {
    width: 36px;
    height: 36px;
    border: none;
    border-radius: 50%;
    background: var(--accent);
    color: white;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    transition: opacity var(--transition), transform var(--spring-duration) var(--spring);
}
```

**Step 2: Verify build**

Run: `cd F:/AI_Workstation/ct/.worktrees/web-ui/ct1/web && npm run build 2>&1 | head -5`

**Step 3: Commit**

```bash
git add ct1/web/src/lib/components/ChatInput.svelte
git commit -m "style: floating glass input island with greige accent"
```

---

### Task 5: Glass ResponsePanel

**Files:**
- Modify: `ct1/web/src/lib/components/ResponsePanel.svelte`

**Step 1: Update response panel to glass**

Replace `.response` styles:

```css
.response {
    background: var(--surface);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border-radius: var(--radius);
    border: var(--glass-border);
    box-shadow: var(--glass-shadow);
    animation: springIn var(--spring-duration) var(--spring) both;
}
```

Replace `.thinking-body` background:
```css
background: rgba(237, 234, 230, 0.5);
```

**Step 2: Commit**

```bash
git add ct1/web/src/lib/components/ResponsePanel.svelte
git commit -m "style: glass response panel"
```

---

### Task 6: Glass SpecialistCard

**Files:**
- Modify: `ct1/web/src/lib/components/SpecialistCard.svelte`

**Step 1: Update panel to glass**

Replace `.panel` styles:

```css
.panel {
    background: var(--surface);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border-radius: var(--radius);
    border: var(--glass-border);
    box-shadow: var(--glass-shadow);
    overflow: hidden;
    animation: expandY var(--spring-duration) var(--spring) both;
}
```

Replace `.section-pill` background to `rgba(237, 234, 230, 0.5)`.

**Step 2: Commit**

```bash
git add ct1/web/src/lib/components/SpecialistCard.svelte
git commit -m "style: glass specialist card"
```

---

### Task 7: Glass ReflectionBar

**Files:**
- Modify: `ct1/web/src/lib/components/ReflectionBar.svelte`

**Step 1: Update bar and detail to glass**

Replace `.bar` styles:

```css
.bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    background: var(--surface);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border: var(--glass-border);
    border-radius: var(--radius);
    padding: 8px 16px;
    cursor: pointer;
    transition: background var(--transition);
    font-family: var(--font-body);
}
```

Replace `.detail` background to `var(--surface)` and add `backdrop-filter: var(--glass-blur); -webkit-backdrop-filter: var(--glass-blur);`.

**Step 2: Commit**

```bash
git add ct1/web/src/lib/components/ReflectionBar.svelte
git commit -m "style: glass reflection bar"
```

---

### Task 8: Glass SplitPane Divider & PreviewPanel

**Files:**
- Modify: `ct1/web/src/lib/components/SplitPane.svelte`
- Modify: `ct1/web/src/lib/components/PreviewPanel.svelte`

**Step 1: Update divider to glass**

Replace `.divider` background to `rgba(168, 160, 160, 0.2)` and hover to `rgba(168, 160, 160, 0.4)`.

**Step 2: Fix PreviewPanel sandbox and glass**

Change iframe sandbox from:
```html
sandbox="allow-scripts allow-same-origin"
```
to:
```html
sandbox="allow-scripts"
```

Update `.preview-panel` to:
```css
.preview-panel {
    display: flex;
    flex-direction: column;
    height: 100%;
    background: var(--surface);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
}
```

Update `.tab-bar` border-bottom to `var(--glass-border)`.

Update `.tabs` background to `rgba(237, 234, 230, 0.5)`.

Update `.copy-btn:hover` from `border-color: var(--accent); color: var(--accent)` to `border-color: var(--text-secondary); color: var(--text)`.

**Step 3: Commit**

```bash
git add ct1/web/src/lib/components/SplitPane.svelte ct1/web/src/lib/components/PreviewPanel.svelte
git commit -m "style: glass split pane + fix iframe sandbox security"
```

---

### Task 9: Final Build Verification

**Step 1: Full build**

Run: `cd F:/AI_Workstation/ct/.worktrees/web-ui/ct1/web && npm run build`

Expected: Build succeeds (only chunk size warning from KaTeX/highlight.js is OK).

**Step 2: Visual check list**

Manually verify in browser at `http://localhost:5173` (run `npx vite dev`):
- [ ] Warm off-white background with ASCII art visible
- [ ] All panels have frosted glass effect
- [ ] Input is a floating centered island
- [ ] No blue anywhere — all greige accents
- [ ] Preview panel iframe loads without console security errors
- [ ] ASCII art shows through panels as ghostly texture
