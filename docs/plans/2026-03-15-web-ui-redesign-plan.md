# CT-2 Web UI Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild the CT-2 frontend into a light-themed, Apple-inspired split-pane interface with live code preview, elastic spring animations, and proper output readability.

**Architecture:** Full rewrite of Svelte components and CSS. The chat.ts store, ws.ts WebSocket client, and all Python backend remain completely untouched. New components: SplitPane (draggable resizer), PreviewPanel (iframe + code view), StatusStrip (phase indicator). Existing components restyled for light theme with spring animations.

**Tech Stack:** SvelteKit 5 (runes: $state, $derived, $props, $effect), CSS custom properties, highlight.js (github light theme), Inter + JetBrains Mono fonts.

**Design doc:** `docs/plans/2026-03-15-web-ui-redesign-design.md`

---

### Task 1: Rewrite app.css — Light Theme & Animation System

**Files:**
- Modify: `ct1/web/src/app.css`

**Step 1: Replace the entire file with the new design system**

```css
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
    --bg: #F5F5F7;
    --surface: #FFFFFF;
    --surface-hover: #E8E8ED;
    --border: #D1D1D6;
    --text: #1D1D1F;
    --text-secondary: #6E6E73;
    --text-muted: #AEAEB2;

    --accent: #007AFF;
    --specialist: #AF52DE;
    --brain: #FF9500;
    --success: #34C759;
    --warning: #FF9F0A;
    --error: #FF3B30;

    --shadow-sm: 0 1px 3px rgba(0,0,0,0.08);
    --shadow-md: 0 4px 12px rgba(0,0,0,0.08);
    --shadow-lg: 0 8px 30px rgba(0,0,0,0.12);

    --font-body: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    --font-mono: 'JetBrains Mono', 'SF Mono', monospace;
    --radius: 12px;
    --radius-pill: 20px;
    --transition: 200ms ease;
    --spring: cubic-bezier(0.34, 1.56, 0.64, 1);
    --spring-soft: cubic-bezier(0.34, 1.3, 0.64, 1);
    --spring-duration: 400ms;
}

*, *::before, *::after {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

html, body {
    height: 100%;
    background: var(--bg);
    color: var(--text);
    font-family: var(--font-body);
    font-size: 14px;
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
}

a {
    color: var(--accent);
    text-decoration: none;
    transition: opacity var(--transition);
}
a:hover { opacity: 0.8; }

h1, h2, h3, h4 {
    font-weight: 600;
    letter-spacing: -0.02em;
    color: var(--text);
}

code, pre {
    font-family: var(--font-mono);
    font-size: 13px;
}

pre {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px;
    overflow-x: auto;
}

::selection {
    background: var(--accent);
    color: white;
}

::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

/* Spring animation keyframes */
@keyframes springIn {
    0% { opacity: 0; transform: scale(0.92); }
    60% { opacity: 1; transform: scale(1.03); }
    100% { transform: scale(1); }
}

@keyframes springPop {
    0% { opacity: 0; transform: scale(0.5); }
    50% { transform: scale(1.08); }
    75% { transform: scale(0.97); }
    100% { opacity: 1; transform: scale(1); }
}

@keyframes slideInRight {
    0% { transform: translateX(100%); }
    60% { transform: translateX(-3%); }
    100% { transform: translateX(0); }
}

@keyframes slideOutRight {
    0% { transform: translateX(0); }
    100% { transform: translateX(100%); }
}

@keyframes pulse {
    0%, 100% { opacity: 0.4; }
    50% { opacity: 1; }
}

@keyframes expandY {
    0% { opacity: 0; transform: scaleY(0.95) translateY(-8px); }
    60% { transform: scaleY(1.02) translateY(0); }
    100% { opacity: 1; transform: scaleY(1) translateY(0); }
}
```

**Step 2: Verify build**

Run: `cd ct1/web && npm run build`
Expected: Build succeeds with no errors

**Step 3: Commit**

```bash
git add ct1/web/src/app.css
git commit -m "feat: rewrite app.css with light Apple theme and spring animations"
```

---

### Task 2: Rewrite +layout.svelte — Status Strip

**Files:**
- Modify: `ct1/web/src/routes/+layout.svelte`

**Context:** The current layout has a dark header with "CT-1" logo and nav links. Replace with a 44px status strip that shows the current pipeline phase.

**Step 1: Replace the layout file**

```svelte
<script lang="ts">
    import '../app.css';
    import { chat } from '$lib/stores/chat';
    import { page } from '$app/stores';

    const phaseLabels: Record<string, string> = {
        idle: '',
        routing: 'Classifying...',
        consulting: 'Consulting specialist...',
        generating: 'Generating...',
        validating: 'Validating...',
        fixing: 'Fixing issues...',
        done: 'Done',
    };

    let phaseText = $derived(phaseLabels[$chat.phase] || '');
    let isActive = $derived($chat.phase !== 'idle' && $chat.phase !== 'done');
</script>

<div class="app">
    <header class="status-strip">
        <a href="/" class="logo">CT-2</a>

        <div class="phase-indicator">
            {#if isActive}
                <span class="phase-dot"></span>
            {/if}
            {#if phaseText}
                <span class="phase-text" class:active={isActive}>{phaseText}</span>
            {/if}
        </div>

        <nav class="strip-nav">
            <a href="/journal" class:active={$page.url.pathname === '/journal'}>Journal</a>
            <a href="/settings" class:active={$page.url.pathname === '/settings'}>Settings</a>
        </nav>
    </header>

    <main>
        <slot />
    </main>
</div>

<style>
    .app {
        display: flex;
        flex-direction: column;
        height: 100vh;
        overflow: hidden;
    }

    .status-strip {
        height: 44px;
        display: flex;
        align-items: center;
        padding: 0 20px;
        background: var(--surface);
        border-bottom: 1px solid var(--border);
        box-shadow: var(--shadow-sm);
        flex-shrink: 0;
        z-index: 100;
    }

    .logo {
        font-weight: 600;
        font-size: 15px;
        color: var(--text);
        letter-spacing: -0.02em;
    }
    .logo:hover { opacity: 1; }

    .phase-indicator {
        flex: 1;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
    }

    .phase-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: var(--accent);
        animation: pulse 1.5s ease-in-out infinite;
    }

    .phase-text {
        font-size: 13px;
        color: var(--text-muted);
        transition: color var(--transition);
    }
    .phase-text.active {
        color: var(--text-secondary);
    }

    .strip-nav {
        display: flex;
        gap: 16px;
    }

    .strip-nav a {
        font-size: 13px;
        color: var(--text-secondary);
        font-weight: 500;
        transition: color var(--transition);
    }
    .strip-nav a:hover { opacity: 1; color: var(--text); }
    .strip-nav a.active { color: var(--accent); }

    main {
        flex: 1;
        overflow: hidden;
    }
</style>
```

**Step 2: Verify build**

Run: `cd ct1/web && npm run build`
Expected: Build succeeds

**Step 3: Commit**

```bash
git add ct1/web/src/routes/+layout.svelte
git commit -m "feat: replace header with status strip showing pipeline phase"
```

---

### Task 3: Create SplitPane.svelte — Draggable Resizer

**Files:**
- Create: `ct1/web/src/lib/components/SplitPane.svelte`

**Context:** This is the core layout component. It renders two slots (left/right) with a draggable divider between them. The right panel can be shown/hidden. When hidden, left panel fills 100%.

**Step 1: Create the component**

```svelte
<script lang="ts">
    import { onMount } from 'svelte';

    let { showRight = false, initialRatio = 0.5 }:
        { showRight?: boolean; initialRatio?: number } = $props();

    let ratio = $state(initialRatio);
    let dragging = $state(false);
    let container: HTMLElement;

    function onPointerDown(e: PointerEvent) {
        dragging = true;
        (e.target as HTMLElement).setPointerCapture(e.pointerId);
    }

    function onPointerMove(e: PointerEvent) {
        if (!dragging || !container) return;
        const rect = container.getBoundingClientRect();
        let newRatio = (e.clientX - rect.left) / rect.width;
        newRatio = Math.max(0.3, Math.min(0.7, newRatio));
        ratio = newRatio;
    }

    function onPointerUp() {
        dragging = false;
    }
</script>

<div
    class="split-pane"
    class:has-right={showRight}
    class:dragging
    bind:this={container}
>
    <div
        class="pane left"
        style={showRight ? `width: ${ratio * 100}%` : 'width: 100%'}
    >
        <slot name="left" />
    </div>

    {#if showRight}
        <div
            class="divider"
            role="separator"
            onpointerdown={onPointerDown}
            onpointermove={onPointerMove}
            onpointerup={onPointerUp}
        >
            <div class="divider-handle"></div>
        </div>

        <div
            class="pane right"
            style="width: {(1 - ratio) * 100}%"
        >
            <slot name="right" />
        </div>
    {/if}
</div>

<style>
    .split-pane {
        display: flex;
        height: 100%;
        overflow: hidden;
    }

    .pane {
        height: 100%;
        overflow: hidden;
        transition: width 500ms var(--spring-soft);
    }
    .dragging .pane {
        transition: none;
        user-select: none;
    }

    .pane.right {
        animation: slideInRight 500ms var(--spring-soft) both;
    }

    .left { min-width: 0; }
    .right { min-width: 0; }

    .divider {
        width: 6px;
        flex-shrink: 0;
        cursor: col-resize;
        background: var(--border);
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background var(--transition);
        position: relative;
        z-index: 10;
    }
    .divider:hover {
        background: var(--text-muted);
    }

    .divider-handle {
        width: 2px;
        height: 32px;
        border-radius: 1px;
        background: var(--text-muted);
        opacity: 0;
        transition: opacity var(--transition);
    }
    .divider:hover .divider-handle {
        opacity: 1;
    }
</style>
```

**Step 2: Verify build**

Run: `cd ct1/web && npm run build`
Expected: Build succeeds (component not yet used)

**Step 3: Commit**

```bash
git add ct1/web/src/lib/components/SplitPane.svelte
git commit -m "feat: add SplitPane component with draggable divider"
```

---

### Task 4: Create PreviewPanel.svelte — Iframe + Code View

**Files:**
- Create: `ct1/web/src/lib/components/PreviewPanel.svelte`

**Context:** Right panel of the split pane. Has two tabs (Preview / Code). Preview renders HTML in an iframe. Code shows syntax-highlighted source with copy button and line numbers.

**Step 1: Create the component**

```svelte
<script lang="ts">
    import hljs from 'highlight.js/lib/core';
    import xml from 'highlight.js/lib/languages/xml';
    import css from 'highlight.js/lib/languages/css';
    import javascript from 'highlight.js/lib/languages/javascript';

    hljs.registerLanguage('xml', xml);
    hljs.registerLanguage('css', css);
    hljs.registerLanguage('javascript', javascript);

    let { code, onClose }:
        { code: string; onClose: () => void } = $props();

    let activeTab = $state<'preview' | 'code'>('preview');
    let copied = $state(false);
    let iframe: HTMLIFrameElement;

    let highlighted = $derived(() => {
        if (!code) return '';
        try {
            return hljs.highlight(code, { language: 'xml' }).value;
        } catch {
            return code.replace(/</g, '&lt;').replace(/>/g, '&gt;');
        }
    });

    let lines = $derived(() => {
        return code ? code.split('\n') : [];
    });

    async function copyCode() {
        await navigator.clipboard.writeText(code);
        copied = true;
        setTimeout(() => { copied = false; }, 2000);
    }

    $effect(() => {
        if (iframe && code && activeTab === 'preview') {
            iframe.srcdoc = code;
        }
    });
</script>

<div class="preview-panel">
    <div class="tab-bar">
        <div class="tabs">
            <button
                class="tab"
                class:active={activeTab === 'preview'}
                onclick={() => activeTab = 'preview'}
            >Preview</button>
            <button
                class="tab"
                class:active={activeTab === 'code'}
                onclick={() => activeTab = 'code'}
            >Code</button>
        </div>
        <button class="close-btn" onclick={onClose}>✕</button>
    </div>

    <div class="tab-content">
        {#if activeTab === 'preview'}
            <iframe
                bind:this={iframe}
                title="Preview"
                sandbox="allow-scripts allow-same-origin"
                class="preview-iframe"
            ></iframe>
        {:else}
            <div class="code-view">
                <button
                    class="copy-btn"
                    class:copied
                    onclick={copyCode}
                >
                    {copied ? 'Copied ✓' : 'Copy'}
                </button>
                <div class="code-scroll">
                    <table class="code-table">
                        <tbody>
                            {#each lines() as line, i}
                                <tr>
                                    <td class="line-num">{i + 1}</td>
                                    <td class="line-code"><pre>{line}</pre></td>
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                </div>
            </div>
        {/if}
    </div>
</div>

<style>
    .preview-panel {
        display: flex;
        flex-direction: column;
        height: 100%;
        background: var(--surface);
    }

    .tab-bar {
        height: 40px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 12px;
        border-bottom: 1px solid var(--border);
        flex-shrink: 0;
    }

    .tabs {
        display: flex;
        background: var(--bg);
        border-radius: 8px;
        padding: 2px;
    }

    .tab {
        font-family: var(--font-body);
        font-size: 12px;
        font-weight: 500;
        padding: 4px 14px;
        border: none;
        border-radius: 6px;
        cursor: pointer;
        background: transparent;
        color: var(--text-secondary);
        transition: all var(--transition);
    }
    .tab.active {
        background: var(--surface);
        color: var(--text);
        box-shadow: var(--shadow-sm);
    }

    .close-btn {
        width: 28px;
        height: 28px;
        border: none;
        border-radius: 8px;
        background: transparent;
        color: var(--text-muted);
        font-size: 14px;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all var(--transition);
    }
    .close-btn:hover {
        background: var(--surface-hover);
        color: var(--text);
    }

    .tab-content {
        flex: 1;
        overflow: hidden;
    }

    .preview-iframe {
        width: 100%;
        height: 100%;
        border: none;
        background: white;
    }

    .code-view {
        height: 100%;
        position: relative;
        overflow: hidden;
    }

    .copy-btn {
        position: absolute;
        top: 12px;
        right: 12px;
        z-index: 5;
        font-family: var(--font-body);
        font-size: 12px;
        font-weight: 500;
        padding: 5px 14px;
        border: 1px solid var(--border);
        border-radius: var(--radius-pill);
        background: var(--surface);
        color: var(--text-secondary);
        cursor: pointer;
        transition: all var(--spring-duration) var(--spring);
    }
    .copy-btn:hover {
        border-color: var(--accent);
        color: var(--accent);
    }
    .copy-btn.copied {
        border-color: var(--success);
        color: var(--success);
        animation: springPop 400ms var(--spring) both;
    }

    .code-scroll {
        height: 100%;
        overflow: auto;
        padding: 12px 0;
    }

    .code-table {
        border-collapse: collapse;
        width: 100%;
        font-family: var(--font-mono);
        font-size: 13px;
        line-height: 1.6;
    }

    .line-num {
        width: 50px;
        padding: 0 12px 0 16px;
        text-align: right;
        color: var(--text-muted);
        user-select: none;
        vertical-align: top;
        font-size: 12px;
    }

    .line-code {
        padding: 0 16px 0 8px;
        white-space: pre-wrap;
        word-break: break-all;
        color: var(--text);
    }
    .line-code pre {
        margin: 0;
        padding: 0;
        background: none;
        border: none;
        font: inherit;
        color: inherit;
    }
</style>
```

**Step 2: Verify build**

Run: `cd ct1/web && npm run build`
Expected: Build succeeds

**Step 3: Commit**

```bash
git add ct1/web/src/lib/components/PreviewPanel.svelte
git commit -m "feat: add PreviewPanel with iframe preview and code view with copy"
```

---

### Task 5: Restyle ChatInput.svelte — Pill Shape Light Theme

**Files:**
- Modify: `ct1/web/src/lib/components/ChatInput.svelte`

**Step 1: Replace the entire file**

```svelte
<script lang="ts">
    import { chat, sendThink } from '$lib/stores/chat';

    let input = $state('');
    let textarea: HTMLTextAreaElement;

    const disabled = $derived($chat.phase !== 'idle' && $chat.phase !== 'done');

    function submit() {
        const text = input.trim();
        if (!text || disabled) return;
        sendThink(text);
        input = '';
        if (textarea) textarea.style.height = 'auto';
    }

    function onKeydown(e: KeyboardEvent) {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            submit();
        }
    }

    function autoGrow() {
        if (!textarea) return;
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
    }
</script>

<div class="chat-input">
    <div class="input-row">
        <textarea
            bind:this={textarea}
            bind:value={input}
            onkeydown={onKeydown}
            oninput={autoGrow}
            placeholder="Message CT-2... (Ctrl+Enter)"
            rows="1"
            {disabled}
        ></textarea>
        <button class="send-btn" onclick={submit} {disabled}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
        </button>
    </div>
</div>

<style>
    .chat-input {
        padding: 12px 16px;
        border-top: 1px solid var(--border);
        background: var(--bg);
        flex-shrink: 0;
    }

    .input-row {
        display: flex;
        align-items: flex-end;
        gap: 8px;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: var(--radius-pill);
        padding: 6px 6px 6px 18px;
        box-shadow: var(--shadow-sm);
        transition: border-color var(--transition), box-shadow var(--transition);
    }
    .input-row:focus-within {
        border-color: var(--accent);
        box-shadow: 0 0 0 3px rgba(0, 122, 255, 0.12);
    }

    textarea {
        flex: 1;
        background: none;
        color: var(--text);
        border: none;
        font-family: var(--font-body);
        font-size: 14px;
        line-height: 1.5;
        resize: none;
        outline: none;
        padding: 6px 0;
    }
    textarea::placeholder {
        color: var(--text-muted);
    }
    textarea:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .send-btn {
        width: 32px;
        height: 32px;
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
    .send-btn:hover:not(:disabled) {
        opacity: 0.85;
    }
    .send-btn:active:not(:disabled) {
        transform: scale(0.92);
    }
    .send-btn:disabled {
        opacity: 0.3;
        cursor: not-allowed;
    }
</style>
```

**Step 2: Verify build**

Run: `cd ct1/web && npm run build`
Expected: Build succeeds

**Step 3: Commit**

```bash
git add ct1/web/src/lib/components/ChatInput.svelte
git commit -m "feat: restyle ChatInput with pill shape and light theme"
```

---

### Task 6: Restyle ResponsePanel.svelte — Light Theme

**Files:**
- Modify: `ct1/web/src/lib/components/ResponsePanel.svelte`

**Step 1: Replace the entire file**

```svelte
<script lang="ts">
    import { render } from '$lib/markdown';
    let { response, thinking = '', label = 'CT-2' }: { response: string; thinking?: string; label?: string } = $props();

    let showThinking = $state(false);
</script>

<div class="response">
    <div class="response-header">
        <span class="dot"></span>
        <span class="label">{label}</span>
        {#if thinking}
            <button class="thinking-toggle" onclick={() => showThinking = !showThinking}>
                {showThinking ? 'Hide' : 'Show'} thinking
            </button>
        {/if}
    </div>

    {#if showThinking && thinking}
        <div class="thinking-body">{@html render(thinking)}</div>
    {/if}

    <div class="response-body">{@html render(response)}</div>
</div>

<style>
    .response {
        background: var(--surface);
        border-radius: var(--radius);
        border: 1px solid var(--border);
        box-shadow: var(--shadow-sm);
        animation: springIn var(--spring-duration) var(--spring) both;
    }
    .response-header {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 10px 16px;
        border-bottom: 1px solid var(--border);
    }
    .dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: var(--brain);
    }
    .label {
        color: var(--brain);
        font-size: 13px;
        font-weight: 600;
    }
    .thinking-toggle {
        margin-left: auto;
        background: none;
        border: 1px solid var(--border);
        border-radius: 6px;
        color: var(--text-secondary);
        font-family: var(--font-body);
        font-size: 12px;
        padding: 3px 10px;
        cursor: pointer;
        transition: all var(--transition);
    }
    .thinking-toggle:hover {
        color: var(--text);
        border-color: var(--text-secondary);
    }
    .thinking-body {
        padding: 12px 16px;
        background: var(--bg);
        border-bottom: 1px solid var(--border);
        color: var(--text-secondary);
        font-size: 13px;
        line-height: 1.6;
        font-style: italic;
    }
    .thinking-body :global(p) { margin-bottom: 8px; }
    .thinking-body :global(p:last-child) { margin-bottom: 0; }
    .response-body {
        padding: 16px;
        color: var(--text);
        font-size: 14px;
        line-height: 1.7;
    }
    .response-body :global(pre) {
        position: relative;
        margin: 12px 0;
    }
    .response-body :global(code) { font-size: 13px; }
    .response-body :global(p) { margin-bottom: 10px; }
    .response-body :global(p:last-child) { margin-bottom: 0; }
    .response-body :global(h1),
    .response-body :global(h2),
    .response-body :global(h3) { margin: 16px 0 6px; }
    .response-body :global(ul),
    .response-body :global(ol) { padding-left: 20px; margin-bottom: 10px; }
</style>
```

**Step 2: Verify build**

Run: `cd ct1/web && npm run build`
Expected: Build succeeds

**Step 3: Commit**

```bash
git add ct1/web/src/lib/components/ResponsePanel.svelte
git commit -m "feat: restyle ResponsePanel with light theme and spring animation"
```

---

### Task 7: Restyle SpecialistCard.svelte — Light Theme

**Files:**
- Modify: `ct1/web/src/lib/components/SpecialistCard.svelte`

**Step 1: Replace the entire file**

```svelte
<script lang="ts">
    import type { SpecialistData } from '$lib/stores/chat';
    let { data }: { data: SpecialistData } = $props();

    let collapsed = $state(false);
</script>

<div class="panel">
    <div class="panel-header">
        <button class="title-btn" onclick={() => collapsed = !collapsed}>
            <span class="accent-bar"></span>
            <span class="title">Specialist Brief</span>
            <span class="chevron">{collapsed ? '+' : '\u2212'}</span>
        </button>
    </div>
    {#if !collapsed}
        <div class="panel-body">
            {#if data.palette}
                <div class="section">
                    <span class="section-label">Palette</span>
                    <div class="swatches">
                        {#each Object.entries(data.palette) as [name, hex]}
                            <div class="swatch">
                                <div class="color" style="background: {hex}"></div>
                                <span class="color-name">{name}</span>
                                <span class="color-hex">{hex}</span>
                            </div>
                        {/each}
                    </div>
                </div>
            {/if}

            {#if data.typography}
                <div class="section">
                    <span class="section-label">Typography</span>
                    <div class="typo-grid">
                        {#each Object.entries(data.typography) as [key, val]}
                            <div class="typo-item">
                                <span class="typo-key">{key.replace(/_/g, ' ')}</span>
                                <span class="typo-val">{val}</span>
                            </div>
                        {/each}
                    </div>
                </div>
            {/if}

            {#if data.sections && data.sections.length > 0}
                <div class="section">
                    <span class="section-label">Sections</span>
                    <div class="section-list">
                        {#each data.sections as sec, i}
                            <span class="section-pill">{i + 1}. {sec}</span>
                        {/each}
                    </div>
                </div>
            {/if}

            {#if data.rationale}
                <div class="section">
                    <span class="section-label">Rationale</span>
                    <p class="rationale">{data.rationale}</p>
                </div>
            {/if}
        </div>
    {/if}
</div>

<style>
    .panel {
        background: var(--surface);
        border-radius: var(--radius);
        border: 1px solid var(--border);
        box-shadow: var(--shadow-sm);
        overflow: hidden;
        animation: expandY var(--spring-duration) var(--spring) both;
    }
    .panel-header {
        padding: 0;
    }
    .title-btn {
        display: flex;
        align-items: center;
        gap: 10px;
        width: 100%;
        background: none;
        border: none;
        cursor: pointer;
        padding: 10px 16px;
        transition: background var(--transition);
    }
    .title-btn:hover { background: var(--surface-hover); }
    .accent-bar {
        width: 3px;
        height: 16px;
        border-radius: 2px;
        background: var(--specialist);
    }
    .title {
        font-size: 13px;
        font-weight: 600;
        color: var(--specialist);
        text-transform: uppercase;
        letter-spacing: 0.04em;
        flex: 1;
        text-align: left;
    }
    .chevron { color: var(--text-muted); font-size: 16px; }
    .panel-body {
        padding: 12px 16px;
        display: flex;
        flex-direction: column;
        gap: 14px;
        border-top: 1px solid var(--border);
    }

    .section { display: flex; flex-direction: column; gap: 6px; }
    .section-label {
        font-size: 11px;
        font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .swatches { display: flex; flex-wrap: wrap; gap: 8px; }
    .swatch { display: flex; align-items: center; gap: 6px; }
    .color {
        width: 18px;
        height: 18px;
        border-radius: 4px;
        border: 1px solid var(--border);
        box-shadow: var(--shadow-sm);
    }
    .color-name { font-size: 12px; color: var(--text-secondary); }
    .color-hex { font-size: 11px; color: var(--text-muted); font-family: var(--font-mono); }

    .typo-grid { display: flex; flex-direction: column; gap: 3px; }
    .typo-item { display: flex; gap: 8px; font-size: 13px; }
    .typo-key { color: var(--text-secondary); text-transform: capitalize; min-width: 110px; }
    .typo-val { color: var(--text); font-weight: 500; }

    .section-list { display: flex; flex-wrap: wrap; gap: 6px; }
    .section-pill {
        background: var(--bg);
        color: var(--text-secondary);
        font-size: 12px;
        padding: 3px 10px;
        border-radius: 16px;
        border: 1px solid var(--border);
    }

    .rationale { font-size: 13px; color: var(--text-secondary); font-style: italic; margin: 0; }
</style>
```

**Step 2: Verify build**

Run: `cd ct1/web && npm run build`
Expected: Build succeeds

**Step 3: Commit**

```bash
git add ct1/web/src/lib/components/SpecialistCard.svelte
git commit -m "feat: restyle SpecialistCard with light theme and purple accent"
```

---

### Task 8: Restyle ReflectionBar.svelte — Light Theme

**Files:**
- Modify: `ct1/web/src/lib/components/ReflectionBar.svelte`

**Step 1: Replace the entire file**

```svelte
<script lang="ts">
    import type { Reflection } from '$lib/stores/chat';
    let { reflection }: { reflection: Reflection } = $props();

    let expanded = $state(false);
    let score = $derived(reflection.self_score ?? 0.5);
    let scoreColor = $derived(score >= 0.7 ? 'var(--success)' : score >= 0.4 ? 'var(--warning)' : 'var(--error)');
</script>

<button class="bar" onclick={() => expanded = !expanded}>
    <div class="metrics">
        <span class="metric">
            <span class="score-dot" style="background: {scoreColor}"></span>
            {(score * 100).toFixed(0)}%
        </span>
    </div>
    <span class="expand">{expanded ? '\u2212' : '+'}</span>
</button>

{#if expanded && reflection.lesson}
    <div class="detail">
        <span class="lesson-label">Lesson:</span> {reflection.lesson}
    </div>
{/if}

<style>
    .bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        width: 100%;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        padding: 8px 16px;
        cursor: pointer;
        transition: background var(--transition);
        font-family: var(--font-body);
    }
    .bar:hover { background: var(--surface-hover); }
    .metrics { display: flex; align-items: center; gap: 12px; }
    .metric {
        color: var(--text-secondary);
        font-size: 13px;
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .score-dot { width: 8px; height: 8px; border-radius: 50%; }
    .expand { color: var(--text-muted); font-size: 16px; }
    .detail {
        background: var(--surface);
        border: 1px solid var(--border);
        border-top: none;
        border-radius: 0 0 var(--radius) var(--radius);
        padding: 10px 16px;
        margin-top: -12px;
        font-size: 13px;
        color: var(--text-secondary);
    }
    .lesson-label {
        color: var(--text-muted);
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
</style>
```

**Step 2: Verify build**

Run: `cd ct1/web && npm run build`
Expected: Build succeeds

**Step 3: Commit**

```bash
git add ct1/web/src/lib/components/ReflectionBar.svelte
git commit -m "feat: restyle ReflectionBar with light theme"
```

---

### Task 9: Switch highlight.js to Light Theme

**Files:**
- Modify: `ct1/web/src/lib/markdown.ts`

**Context:** Currently imports `github-dark` theme. Switch to `github` (light) theme.

**Step 1: Read the current file and change the CSS import**

Change the highlight.js CSS import from `github-dark` to `github`:
```
import 'highlight.js/styles/github-dark.css';
```
becomes:
```
import 'highlight.js/styles/github.css';
```

No other changes to the file.

**Step 2: Verify build**

Run: `cd ct1/web && npm run build`
Expected: Build succeeds

**Step 3: Commit**

```bash
git add ct1/web/src/lib/markdown.ts
git commit -m "feat: switch highlight.js to github light theme"
```

---

### Task 10: Rewrite +page.svelte — Split Pane Layout

**Files:**
- Modify: `ct1/web/src/routes/+page.svelte`

**Context:** This is the big one. Replaces the current single-column 800px layout with the full-width split-pane design. Chat on the left, preview panel on the right (only when code is generated). All streaming outputs restyled for light theme, no max-height cutoff.

**Step 1: Replace the entire file**

```svelte
<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { chat, connect, disconnect } from '$lib/stores/chat';
    import { render } from '$lib/markdown';
    import ChatInput from '$lib/components/ChatInput.svelte';
    import SpecialistCard from '$lib/components/SpecialistCard.svelte';
    import ResponsePanel from '$lib/components/ResponsePanel.svelte';
    import ReflectionBar from '$lib/components/ReflectionBar.svelte';
    import SplitPane from '$lib/components/SplitPane.svelte';
    import PreviewPanel from '$lib/components/PreviewPanel.svelte';

    onMount(() => connect());
    onDestroy(() => disconnect());

    let isCode = $derived(
        $chat.route === 'ROUTE_DESIGN' || $chat.route === 'ROUTE_CODE'
    );

    let showPreview = $state(false);
    let previewCode = $derived($chat.response || $chat.streamingText || '');

    // Auto-open preview when code starts streaming
    $effect(() => {
        if (isCode && $chat.streamingText && !showPreview) {
            showPreview = true;
        }
    });

    // Close preview for non-code
    $effect(() => {
        if ($chat.phase === 'routing') {
            showPreview = false;
        }
    });

    let messagesEl: HTMLElement;

    // Auto-scroll chat
    $effect(() => {
        // Track changes that should trigger scroll
        $chat.streamingText;
        $chat.specialistStream;
        $chat.response;
        $chat.phase;
        if (messagesEl) {
            requestAnimationFrame(() => {
                messagesEl.scrollTop = messagesEl.scrollHeight;
            });
        }
    });

    let history = $derived(() => {
        const conv = $chat.conversation;
        if ($chat.phase !== 'idle' && $chat.phase !== 'done') {
            return conv.slice(0, -1);
        }
        let lastUserIdx = -1;
        for (let i = conv.length - 1; i >= 0; i--) {
            if (conv[i].role === 'user') { lastUserIdx = i; break; }
        }
        return lastUserIdx > 0 ? conv.slice(0, lastUserIdx) : [];
    });

    const routeLabels: Record<string, string> = {
        'ROUTE_DESIGN': 'Design',
        'ROUTE_CODE': 'Code',
        'ROUTE_DIRECT': 'Direct',
    };
    const routeColors: Record<string, string> = {
        'ROUTE_DESIGN': 'var(--specialist)',
        'ROUTE_CODE': 'var(--accent)',
        'ROUTE_DIRECT': 'var(--success)',
    };
</script>

<SplitPane showRight={showPreview}>
    <div slot="left" class="chat-panel">
        <div class="messages" bind:this={messagesEl}>
            <!-- Previous conversation history -->
            {#each history() as turn}
                {#if turn.role === 'user'}
                    <div class="user-msg"><p>{turn.content}</p></div>
                {:else}
                    <div class="assistant-msg">{@html render(turn.content)}</div>
                {/if}
            {/each}

            <!-- Current active turn -->
            {#if $chat.phase !== 'idle'}
                {#each $chat.conversation as turn, i}
                    {#if turn.role === 'user' && i >= history().length}
                        <div class="user-msg"><p>{turn.content}</p></div>
                    {/if}
                {/each}
            {/if}

            <!-- Route badge -->
            {#if $chat.route}
                <div class="badge-row">
                    <span class="route-badge" style="background: {routeColors[$chat.route] || 'var(--accent)'}">
                        {routeLabels[$chat.route] || $chat.route}
                    </span>
                </div>
            {/if}

            <!-- Specialist streaming -->
            {#if $chat.phase === 'consulting' && $chat.specialistStream}
                <div class="stream-card specialist-accent">
                    <div class="stream-header">
                        <span class="stream-dot specialist"></span>
                        <span class="stream-label">Specialist</span>
                    </div>
                    <pre class="stream-text">{$chat.specialistStream}</pre>
                </div>
            {/if}

            <!-- Specialist card -->
            {#if $chat.specialistData}
                <SpecialistCard data={$chat.specialistData} />
            {/if}

            <!-- Director streaming (thinking + output) -->
            {#if ($chat.phase === 'generating' || $chat.phase === 'fixing') && ($chat.streamingThinking || $chat.streamingText)}
                {#if $chat.streamingThinking}
                    <div class="stream-card muted-accent">
                        <div class="stream-header">
                            <span class="stream-label">Thinking</span>
                        </div>
                        <pre class="stream-text">{$chat.streamingThinking}</pre>
                    </div>
                {/if}

                {#if $chat.streamingText && !isCode}
                    <div class="stream-card brain-accent">
                        <div class="stream-header">
                            <span class="stream-dot brain"></span>
                            <span class="stream-label">Response</span>
                            <span class="stream-count">{$chat.streamingText.length} chars</span>
                        </div>
                        <pre class="stream-text">{$chat.streamingText}</pre>
                    </div>
                {/if}

                {#if isCode}
                    <div class="stream-card brain-accent">
                        <div class="stream-header">
                            <span class="stream-dot brain"></span>
                            <span class="stream-label">Generating code</span>
                            <span class="stream-count">{$chat.streamingText.length} chars</span>
                        </div>
                    </div>
                {/if}
            {/if}

            <!-- Validation issues -->
            {#if $chat.validationIssues.length > 0}
                <div class="validation">
                    <div class="validation-header">
                        <span class="dot-warn"></span> Validation
                        {#if $chat.review}
                            <span class="review-verdict" class:pass={$chat.review.pass} class:fail={!$chat.review.pass}>
                                {$chat.review.pass ? 'PASS' : 'FAIL'}
                            </span>
                        {/if}
                    </div>
                    <ul>
                        {#each $chat.validationIssues as issue}
                            <li>{issue}</li>
                        {/each}
                    </ul>
                </div>
            {/if}

            <!-- Final response (non-code only; code goes to preview panel) -->
            {#if $chat.response && !isCode}
                <ResponsePanel response={$chat.response} thinking={$chat.thinking} />
            {/if}

            {#if $chat.response && isCode}
                <div class="code-done-msg">
                    <span class="stream-dot brain"></span>
                    Code generated — see preview panel →
                </div>
            {/if}

            {#if $chat.reflection}
                <ReflectionBar reflection={$chat.reflection} />
            {/if}
        </div>

        <ChatInput />
    </div>

    <div slot="right">
        {#if showPreview}
            <PreviewPanel
                code={previewCode}
                onClose={() => { showPreview = false; }}
            />
        {/if}
    </div>
</SplitPane>

<style>
    .chat-panel {
        display: flex;
        flex-direction: column;
        height: 100%;
    }

    .messages {
        flex: 1;
        overflow-y: auto;
        scroll-behavior: smooth;
        display: flex;
        flex-direction: column;
        gap: 12px;
        padding: 20px;
    }

    /* User bubble */
    .user-msg {
        align-self: flex-end;
        background: var(--accent);
        color: white;
        padding: 10px 18px;
        border-radius: 20px 20px 6px 20px;
        max-width: 65%;
        font-size: 14px;
        box-shadow: var(--shadow-sm);
        animation: springIn 300ms var(--spring) both;
    }
    .user-msg p { margin: 0; }

    /* Assistant bubble */
    .assistant-msg {
        align-self: flex-start;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 6px 20px 20px 20px;
        padding: 14px 18px;
        color: var(--text);
        font-size: 14px;
        line-height: 1.7;
        max-width: 80%;
        box-shadow: var(--shadow-sm);
        animation: springIn 300ms var(--spring) both;
    }
    .assistant-msg :global(pre) { margin: 10px 0; overflow-x: auto; }
    .assistant-msg :global(code) { font-size: 13px; }
    .assistant-msg :global(p) { margin-bottom: 8px; }
    .assistant-msg :global(p:last-child) { margin-bottom: 0; }

    /* Route badge */
    .badge-row { display: flex; }
    .route-badge {
        color: white;
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        padding: 3px 14px;
        border-radius: var(--radius-pill);
        animation: springPop 400ms var(--spring) both;
    }

    /* Streaming cards */
    .stream-card {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        overflow: hidden;
        animation: expandY var(--spring-duration) var(--spring) both;
    }
    .specialist-accent { border-left: 3px solid var(--specialist); }
    .brain-accent { border-left: 3px solid var(--brain); }
    .muted-accent { border-left: 3px solid var(--text-muted); }

    .stream-header {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 14px;
        border-bottom: 1px solid var(--border);
    }
    .stream-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        animation: pulse 1.5s ease-in-out infinite;
    }
    .stream-dot.specialist { background: var(--specialist); }
    .stream-dot.brain { background: var(--brain); }
    .stream-label {
        font-size: 11px;
        font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .stream-count {
        margin-left: auto;
        font-size: 11px;
        font-family: var(--font-mono);
        color: var(--text-muted);
    }
    .stream-text {
        font-family: var(--font-mono);
        font-size: 12px;
        color: var(--text-secondary);
        white-space: pre-wrap;
        word-break: break-all;
        margin: 0;
        padding: 12px 14px;
        line-height: 1.5;
        background: none;
        border: none;
        border-radius: 0;
    }

    /* Code done indicator */
    .code-done-msg {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 13px;
        color: var(--text-secondary);
        padding: 8px 0;
        animation: springIn 300ms var(--spring) both;
    }

    /* Validation */
    .validation {
        background: var(--surface);
        border: 1px solid rgba(255, 159, 10, 0.2);
        border-radius: var(--radius);
        padding: 14px 16px;
    }
    .validation-header {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 12px;
        font-weight: 600;
        color: var(--warning);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 10px;
    }
    .dot-warn {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: var(--warning);
    }
    .review-verdict {
        margin-left: auto;
        font-size: 11px;
        padding: 2px 8px;
        border-radius: 6px;
        font-weight: 700;
    }
    .review-verdict.pass { background: var(--success); color: white; }
    .review-verdict.fail { background: var(--error); color: white; }
    .validation ul {
        list-style: none;
        display: flex;
        flex-direction: column;
        gap: 4px;
    }
    .validation li {
        font-size: 13px;
        color: var(--text-secondary);
        padding-left: 14px;
        position: relative;
    }
    .validation li::before {
        content: '\u00d7';
        position: absolute;
        left: 0;
        color: var(--warning);
        font-weight: bold;
    }
</style>
```

**Step 2: Verify build**

Run: `cd ct1/web && npm run build`
Expected: Build succeeds

**Step 3: Commit**

```bash
git add ct1/web/src/routes/+page.svelte
git commit -m "feat: rewrite chat page with split pane layout and light theme"
```

---

### Task 11: Final Build Verification

**Step 1: Full build**

Run: `cd ct1/web && npm run build`
Expected: Build succeeds with no errors

**Step 2: Check the build output exists**

Run: `ls ct1/web/build/index.html`
Expected: File exists

**Step 3: Commit any remaining changes**

```bash
git add -A ct1/web/
git commit -m "chore: final build verification for UI redesign"
```

---
