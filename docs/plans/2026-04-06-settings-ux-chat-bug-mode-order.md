# Settings UX + Chat Bug + Mode Order Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Three changes: (1) rename/restructure Settings page for non-technical users, (2) fix chat mode bug where thinking-only responses don't show as a message bubble, (3) reorder mode pills to Chat-first, Auto-last.

**Architecture:** Pure frontend label/structure changes for settings + one 2-line backend fix in the streaming engine + one array reorder in ChatInput.

**Tech Stack:** Svelte 5 (runes syntax), Python/FastAPI, pytest

---

### Task 1: Reorder mode pills

**Files:**
- Modify: `ct1/web/src/lib/components/ChatInput.svelte:16-22`

**Step 1: Apply the change**

Find this block (lines 16–22):
```typescript
const modes: { key: ModeOverride; label: string }[] = [
    { key: 'auto', label: 'Auto' },
    { key: 'design', label: 'Design' },
    { key: 'code', label: 'Code' },
    { key: 'chat', label: 'Chat' },
    { key: 'computer', label: 'Computer' },
];
```

Replace with:
```typescript
const modes: { key: ModeOverride; label: string }[] = [
    { key: 'chat', label: 'Chat' },
    { key: 'design', label: 'Design' },
    { key: 'code', label: 'Code' },
    { key: 'computer', label: 'Computer' },
    { key: 'auto', label: 'Auto' },
];
```

**Step 2: Build to verify**

```bash
cd ct1/web && npm run build 2>&1 | tail -5
```
Expected: `✓ built in` with no errors.

**Step 3: Commit**

```bash
git add ct1/web/src/lib/components/ChatInput.svelte
git commit -m "feat(ui): move Chat mode first, Auto mode last"
```

---

### Task 2: Fix chat mode thinking-only bug

**Files:**
- Modify: `ct1/core/engine.py` — end of `_call_stream` method (~line 475)
- Create: `tests/test_engine_streaming_fallback.py`

**Step 1: Write the failing test**

Create `tests/test_engine_streaming_fallback.py`:

```python
"""Test that _call_stream falls back to thinking as text when content is empty."""
import json
import pytest
from unittest.mock import MagicMock, AsyncMock
from ct1.core.engine import Engine


def _make_engine():
    engine = Engine.__new__(Engine)
    engine.thinking_budget = -1
    return engine


def _sse_line(reasoning="", content=""):
    delta = {}
    if reasoning:
        delta["reasoning_content"] = reasoning
    if content:
        delta["content"] = content
    return "data: " + json.dumps({"choices": [{"delta": delta}]})


def _mock_stream(*sse_lines):
    """Return a mock httpx stream context manager yielding the given SSE lines."""
    async def fake_aiter_lines():
        for line in sse_lines:
            yield line
        yield "data: [DONE]"

    mock_resp = MagicMock()
    mock_resp.aiter_lines = fake_aiter_lines
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=mock_resp)
    return mock_client


@pytest.mark.asyncio
async def test_thinking_only_becomes_text():
    """If model emits only reasoning_content (no content), result.text = reasoning."""
    engine = _make_engine()
    engine.client = _mock_stream(_sse_line(reasoning="Hello there!"))

    messages = [{"role": "user", "content": "hi"}]
    result = await engine._call_stream(messages, enable_thinking=True)

    assert result["text"] == "Hello there!"
    assert result["thinking"] == ""


@pytest.mark.asyncio
async def test_content_and_thinking_both_present():
    """When both content and reasoning are emitted, they are kept separate."""
    engine = _make_engine()
    engine.client = _mock_stream(
        _sse_line(reasoning="Let me think..."),
        _sse_line(content="The answer is 42."),
    )

    messages = [{"role": "user", "content": "what is the answer?"}]
    result = await engine._call_stream(messages, enable_thinking=True)

    assert result["text"] == "The answer is 42."
    assert result["thinking"] == "Let me think..."
```

**Step 2: Run test to confirm it fails (bug is present)**

```bash
cd F:/AI_Workstation/ct2/CT-2-WebUI
python -m pytest tests/test_engine_streaming_fallback.py -v 2>&1 | tail -20
```
Expected: `test_thinking_only_becomes_text FAILED` (result["text"] is "" before the fix).

**Step 3: Apply the fix**

In `ct1/core/engine.py`, find the `return` at the very end of `_call_stream` (it currently reads):
```python
        return {"text": text.strip(), "thinking": thinking.strip()}
```

Replace with:
```python
        # Fallback: if model emitted only reasoning (no content), use reasoning as response
        if not text and thinking:
            text, thinking = thinking, ""
        return {"text": text.strip(), "thinking": thinking.strip()}
```

**Step 4: Run tests to confirm they pass**

```bash
python -m pytest tests/test_engine_streaming_fallback.py -v 2>&1 | tail -10
```
Expected: both tests `PASSED`.

**Step 5: Confirm no regressions**

```bash
python -m pytest tests/ -q 2>&1 | tail -5
```
Expected: 39 passed, 18 failed (same 18 pre-existing failures — do not fix them).

**Step 6: Commit**

```bash
git add tests/test_engine_streaming_fallback.py ct1/core/engine.py
git commit -m "fix(engine): fall back to thinking as response when content stream is empty"
```

---

### Task 3: Settings page restructure

**Files:**
- Modify: `ct1/web/src/routes/settings/+page.svelte:380-531`

This task is all label and structure changes — no logic changes. Work top-to-bottom through the HTML template section.

#### 3a: Merge Backend + Context Size → "Performance"

Find and replace the entire Backend block + Context Size section (lines 380–431):

**Before:**
```svelte
    <!-- ─── Backend ─── -->
    {#if !isMac}
        <div class="setting-row">
            <label class="setting-label">Backend</label>
            <div class="backend-picker">
                <button
                    class="backend-btn"
                    class:active={activeBackend === 'vulkan'}
                    onclick={() => switchBackend('vulkan')}
                    disabled={switchingBackend}
                >Vulkan</button>
                <button
                    class="backend-btn"
                    class:active={activeBackend === 'cuda'}
                    onclick={() => switchBackend('cuda')}
                    disabled={switchingBackend}
                >CUDA</button>
            </div>
            {#if backendError}
                <p class="error-text">{backendError}</p>
            {/if}
            {#if switchingBackend}
                <p class="switching-text">Switching backend…</p>
            {/if}
        </div>
    {/if}

    <!-- ─── Context Size ─── -->
    {#if maxContextSize > 0 && activeModel}
        <section class="section">
            <h2 class="section-title">Context Size</h2>
            <div class="config-card">
                <div class="config-row">
                    <label>Context Window</label>
                    <div class="slider-container">
                        <input type="range"
                            min={CONTEXT_MIN_FLOOR}
                            max={maxContextSize}
                            bind:value={contextSize}
                        />
                        <span class="slider-value">{Math.round(contextSize / 1024)}K</span>
                    </div>
                </div>
            </div>
            {#if needsRestart}
                <div class="restart-notice">
                    <span>Restart required to apply changes.</span>
                    <button onclick={restartModel} class="restart-btn" disabled={switching}>Restart Model</button>
                </div>
            {/if}
        </section>
    {/if}
```

**After:**
```svelte
    <!-- ─── Performance ─── -->
    {#if !isMac || (maxContextSize > 0 && activeModel)}
    <section class="section">
        <h2 class="section-title">Performance</h2>

        {#if !isMac}
            <div class="setting-row">
                <label class="setting-label">GPU Backend</label>
                <div class="backend-picker">
                    <button
                        class="backend-btn"
                        class:active={activeBackend === 'vulkan'}
                        onclick={() => switchBackend('vulkan')}
                        disabled={switchingBackend}
                    >Vulkan</button>
                    <button
                        class="backend-btn"
                        class:active={activeBackend === 'cuda'}
                        onclick={() => switchBackend('cuda')}
                        disabled={switchingBackend}
                    >CUDA</button>
                </div>
                {#if backendError}
                    <p class="error-text">{backendError}</p>
                {/if}
                {#if switchingBackend}
                    <p class="switching-text">Switching backend…</p>
                {/if}
            </div>
        {/if}

        {#if maxContextSize > 0 && activeModel}
            <div class="config-card">
                <div class="config-row">
                    <label>
                        Memory Window
                        <span class="setting-desc">How much conversation the AI remembers. Larger = richer context but uses more VRAM.</span>
                    </label>
                    <div class="slider-container">
                        <input type="range"
                            min={CONTEXT_MIN_FLOOR}
                            max={maxContextSize}
                            bind:value={contextSize}
                        />
                        <span class="slider-value">{Math.round(contextSize / 1024)}K</span>
                    </div>
                </div>
            </div>
            {#if needsRestart}
                <div class="restart-notice">
                    <span>Restart required to apply changes.</span>
                    <button onclick={restartModel} class="restart-btn" disabled={switching}>Restart Model</button>
                </div>
            {/if}
        {/if}
    </section>
    {/if}
```

#### 3b: Rename "Routing Modes" → "Response Style" + human-readable slider labels

Find line ~436:
```svelte
        <h2 class="section-title">Routing Modes</h2>
```
Replace with:
```svelte
        <h2 class="section-title">Response Style</h2>
        <p class="section-desc">Fine-tune how each mode responds. Changes apply immediately.</p>
```

Find the `{#each [['temperature'...` block inside the mode cards. The current `override-key` span shows the raw key:
```svelte
                                <span class="override-key">{key}</span>
```

Replace with (add a label map just above the `{#each}` that iterates sliders, using a `@const`):
```svelte
    {#each modes as mode (mode.name)}
        <div class="mode-card">
            <div class="mode-header">
                <div class="mode-meta">
                    <span class="mode-name">{mode.name}</span>
                    <span class="mode-route">{mode.route_id.replace('ROUTE_', '')}</span>
                    {#if mode.patterns.length > 0}
                        <span class="mode-badge">{mode.patterns.length} patterns</span>
                    {/if}
                </div>
            </div>
            <div class="mode-overrides">
                {#each [['temperature', 0, 2, 0.05, 'Creativity', 'How surprising vs. predictable responses are'], ['top_p', 0, 1, 0.05, 'Focus', 'How broad or precise word choices are'], ['presence_penalty', -2, 2, 0.05, 'Variety', 'How much the AI avoids repeating itself']] as [key, min, max, step, label, desc]}
                    {@const val = (modeEdits[mode.name]?.[key as string] ?? mode.task_overrides[key as string])}
                    {#if val !== undefined}
                    <div class="override-row">
                        <span class="override-key">
                            {label}
                            <span class="setting-desc">{desc}</span>
                        </span>
                        <div class="slider-container">
                            <input type="range"
                                min={min}
                                max={max}
                                step={step}
                                value={val}
                                oninput={(e) => updateModeOverride(mode.name, key as string, Number((e.target as HTMLInputElement).value))}
                            />
                            <span class="slider-value">{(modeEdits[mode.name]?.[key as string] ?? val).toFixed(2)}</span>
                        </div>
                    </div>
                    {/if}
                {/each}
            </div>
```

The change is: the `{#each}` tuple gains two extra items per row (`label` and `desc`), and `{key}` is replaced with `{label}` + `<span class="setting-desc">{desc}</span>`.

#### 3c: Rename "System Prompts" → "Custom Instructions" + add description

Find line ~489:
```svelte
        <h2 class="section-title">System Prompts</h2>
```
Replace with:
```svelte
        <h2 class="section-title">Custom Instructions</h2>
        <p class="section-desc">Built-in instructions for each mode. Advanced — restart required after saving.</p>
```

#### 3d: Rename "Pipeline" → "Features"

Find line ~535:
```svelte
        <h2 class="section-title">Pipeline</h2>
```
Replace with:
```svelte
        <h2 class="section-title">Features</h2>
```

#### 3e: Add `.section-desc` CSS

The new `<p class="section-desc">` and `<span class="setting-desc">` elements need styles. Find the existing CSS block in the `<style>` tag of the settings page and append:

```css
.section-desc {
    font-size: 0.78rem;
    color: var(--text-muted, #888);
    margin: 2px 0 10px;
    line-height: 1.4;
}

.setting-desc {
    display: block;
    font-size: 0.72rem;
    color: var(--text-muted, #888);
    font-weight: 400;
    margin-top: 2px;
    line-height: 1.3;
}
```

**Step — Build to verify**

```bash
cd ct1/web && npm run build 2>&1 | tail -5
```
Expected: `✓ built in` with no type errors.

**Step — Commit**

```bash
git add ct1/web/src/routes/settings/+page.svelte
git commit -m "feat(settings): restructure for non-technical users — rename sections and sliders, merge Performance section"
```
