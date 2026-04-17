# AI Tool Use: Autonomous Web Search & Fetch

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the single pre-processing web search with Anthropic-style tool_use so the AI searches autonomously 0–N times during generation, showing live inline activity in the UI.

**Architecture:** The local llama-server speaks OpenAI-compatible function calling (`tools` array + `tool_calls` delta chunks). `engine._call_stream` gains a tool loop: stream → detect `finish_reason: tool_calls` → execute → append messages → stream again. The pre-processing search block in api.py is deleted; tools are wired through `orchestrator.think()` and `engine.generate()` instead.

**Tech Stack:** Python asyncio, httpx SSE streaming, OpenAI function-calling JSON format, SvelteKit 5 runes, Svelte stores.

---

### Task 1: Modify `_call_stream` to support tool loops

**Files:**
- Modify: `ct1/core/engine.py:399–510`

**Context:** `_call_stream` currently streams one HTTP call and returns `{text, thinking}`. We need it to detect `finish_reason: tool_calls` in the SSE stream, call an executor, append messages, and loop.

**Step 1: Add params and accumulate tool_calls in the streaming loop**

Add to `_call_stream` signature (after existing params):
```python
async def _call_stream(self, messages: list[dict], on_token=None,
                       max_tokens: int = None,
                       presence_penalty: float = None,
                       temperature: float = None,
                       top_p: float = None,
                       conversation: list[dict] = None,
                       enable_thinking: bool = True,
                       thinking_budget: int = None,
                       check_repetition: bool = True,
                       tools: list[dict] | None = None,
                       tool_executor=None):
```

Add `tools` to payload construction (after the existing payload dict, before the `async with self.client.stream` call):
```python
if tools:
    payload["tools"] = tools
    payload["tool_choice"] = "auto"
```

Inside the streaming loop, add tool_call accumulation alongside the existing `delta` handling:
```python
# Inside the try block in the async for loop, after handling token/reason:
tool_calls_raw = delta.get("tool_calls", [])
for tc_chunk in tool_calls_raw:
    idx = tc_chunk.get("index", 0)
    while len(_pending_tool_calls) <= idx:
        _pending_tool_calls.append({"id": "", "name": "", "arguments": ""})
    if tc_chunk.get("id"):
        _pending_tool_calls[idx]["id"] = tc_chunk["id"]
    fn = tc_chunk.get("function", {})
    if fn.get("name"):
        _pending_tool_calls[idx]["name"] = fn["name"]
    if fn.get("arguments"):
        _pending_tool_calls[idx]["arguments"] += fn["arguments"]

finish_reason = chunk["choices"][0].get("finish_reason")
if finish_reason:
    _finish_reason = finish_reason
```

Declare these before the `async with self.client.stream` block:
```python
_pending_tool_calls: list[dict] = []
_finish_reason: str | None = None
```

**Step 2: Add the tool loop after the streaming block**

After the `async with self.client.stream` block ends, add:
```python
# Tool loop: if model requested tool calls, execute and continue
while _finish_reason == "tool_calls" and tool_executor and _pending_tool_calls:
    import json as _json
    # Parse arguments JSON for each tool call
    parsed_calls = []
    for tc in _pending_tool_calls:
        try:
            args = _json.loads(tc["arguments"]) if tc["arguments"] else {}
        except _json.JSONDecodeError:
            args = {}
        parsed_calls.append({"id": tc["id"], "name": tc["name"], "args": args})

    # Execute tools and get results
    tool_results = await tool_executor(parsed_calls)

    # Append assistant turn with tool_calls + tool results to messages
    messages = list(messages)
    messages.append({
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": tc["id"],
                "type": "function",
                "function": {"name": tc["name"], "arguments": _pending_tool_calls[i]["arguments"]},
            }
            for i, tc in enumerate(parsed_calls)
        ],
    })
    for tc, result in zip(parsed_calls, tool_results):
        messages.append({
            "role": "tool",
            "tool_call_id": tc["id"],
            "content": str(result),
        })

    # Reset accumulators for next stream
    _pending_tool_calls = []
    _finish_reason = None

    # Stream again with updated messages
    async with self.client.stream(
        "POST", f"{self.base_url}/v1/chat/completions", json={**payload, "messages": messages}
    ) as response:
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            data = line[6:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
                delta = chunk["choices"][0].get("delta", {})
                token = delta.get("content", "")
                reason = delta.get("reasoning_content", "")
                if token:
                    text += token
                    if on_token:
                        on_token(token, "content")
                if reason:
                    thinking += reason
                    if on_token:
                        on_token(reason, "thinking")
                tool_calls_raw = delta.get("tool_calls", [])
                for tc_chunk in tool_calls_raw:
                    idx = tc_chunk.get("index", 0)
                    while len(_pending_tool_calls) <= idx:
                        _pending_tool_calls.append({"id": "", "name": "", "arguments": ""})
                    if tc_chunk.get("id"):
                        _pending_tool_calls[idx]["id"] = tc_chunk["id"]
                    fn = tc_chunk.get("function", {})
                    if fn.get("name"):
                        _pending_tool_calls[idx]["name"] = fn["name"]
                    if fn.get("arguments"):
                        _pending_tool_calls[idx]["arguments"] += fn["arguments"]
                finish_reason = chunk["choices"][0].get("finish_reason")
                if finish_reason:
                    _finish_reason = finish_reason
            except (json.JSONDecodeError, KeyError, IndexError):
                continue
```

**Step 3: Verify no tests break**

Run: `cd ct1 && python -m pytest tests/ -v -k "not ws" 2>&1 | head -40`
Expected: same pass/fail as before (no tool tests yet — they come in Task 2).

**Step 4: Commit**
```bash
git add ct1/core/engine.py
git commit -m "feat: add tool_calls loop support to _call_stream"
```

---

### Task 2: Add `tools` and `tool_executor` params to `engine.generate` and `orchestrator.think`

**Files:**
- Modify: `ct1/core/engine.py:613–660` (`generate` method signature)
- Modify: `ct1/core/orchestrator.py:1067` (`_pipeline` method)
- Modify: `ct1/core/orchestrator.py:1691` (`think` method)

**Context:** `generate()` calls `_call_stream` internally. We need to thread `tools` and `tool_executor` from api.py → `think()` → `_pipeline()` → `generate()` → `_call_stream()`.

**Step 1: Add params to `engine.generate`**

Add `tools: list[dict] | None = None` and `tool_executor=None` to `generate`'s signature. Find every internal `_call_stream` call inside `generate` for the ROUTE_DIRECT / chat case (the "full response" generation, not planning/routing calls) and pass `tools=tools, tool_executor=tool_executor` to it.

To identify the right call sites: they are the ones that return the final user-visible text (not calls inside `generate_spec`, `reflect`, `route`, etc.). Search for the calls in `generate` that use `on_token=on_token`.

**Step 2: Add params to `orchestrator._pipeline`**

Add `tools: list[dict] | None = None` and `tool_executor=None` to `_pipeline`'s signature. Find the `await self.engine.generate(...)` calls and add `tools=tools, tool_executor=tool_executor` to each (there are ~6 call sites at lines 639, 842, 1050, 1246, 1338, 1402, 1434).

**Step 3: Add params to `orchestrator.think`**

```python
async def think(self, goal, on_event=None,
                conversation: list[dict] = None,
                mode_override: str | None = None,
                skip_refinement: bool = False,
                atlas_settings: dict | None = None,
                tools: list[dict] | None = None,
                tool_executor=None) -> dict:
    if atlas_settings and atlas_settings.get("atlasMode"):
        return await self.atlas.run(...)  # leave atlas unchanged for now
    return await self._pipeline(
        goal, on_event=on_event, conversation=conversation or [],
        mode_override=mode_override,
        skip_refinement=skip_refinement,
        tools=tools,
        tool_executor=tool_executor,
    )
```

**Step 4: Smoke test**

Run: `cd ct1 && python -m pytest tests/ -v -k "not ws" 2>&1 | head -40`
Expected: same results as before (no behaviour change yet).

**Step 5: Commit**
```bash
git add ct1/core/engine.py ct1/core/orchestrator.py
git commit -m "feat: thread tools/tool_executor through generate and think"
```

---

### Task 3: Define tool schemas and executor in api.py; remove pre-processing search

**Files:**
- Modify: `ct1/server/api.py:1127–1244` (remove search pre-processing block)
- Modify: `ct1/server/api.py` (add TOOL_SCHEMAS constant and make_tool_executor factory)

**Context:** The old pre-processing block (lines ~1127–1244) runs one search before the AI. We delete it and replace with tool_use. The URL-in-message fetching block (lines ~1245+) that fetches URLs the USER pasted stays unchanged.

**Step 1: Add TOOL_SCHEMAS near the top of api.py (after imports)**

```python
_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current information. Use when the user asks about recent events, live data, or anything your training data may not cover.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Focused search query"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetch and read the contents of a URL. Use to get full content from a specific web page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL to fetch"}
                },
                "required": ["url"],
            },
        },
    },
]
```

**Step 2: Add `make_tool_executor` factory function**

Add after TOOL_SCHEMAS:
```python
def _make_tool_executor(queue: asyncio.Queue):
    """Returns an async function that executes tool calls and emits WS events."""
    async def _executor(tool_calls: list[dict]) -> list[str]:
        from ct1.core.web_searcher import search_web, format_results_as_context
        from ct1.core.web_fetcher import fetch_url as _fetch_url
        results = []
        for tc in tool_calls:
            name = tc["name"]
            args = tc["args"]
            if name == "web_search":
                query = args.get("query", "")
                try:
                    queue.put_nowait({"event": "web_searching", "query": query})
                except asyncio.QueueFull:
                    pass
                sr = await search_web(query, max_results=8)
                try:
                    queue.put_nowait({
                        "event": "web_search_results",
                        "query": sr.query,
                        "results": [
                            {"title": r.title, "url": r.url, "snippet": r.snippet}
                            for r in sr.results
                        ],
                        "error": sr.error,
                    })
                except asyncio.QueueFull:
                    pass
                results.append(format_results_as_context(sr) if sr.results else "No results found.")
            elif name == "fetch_url":
                url = args.get("url", "")
                try:
                    queue.put_nowait({"event": "url_fetching", "url": url})
                except asyncio.QueueFull:
                    pass
                fr = await _fetch_url(url, max_chars=4000)
                if fr.error or not fr.content:
                    results.append(f"Could not fetch {url}: {fr.error or 'empty'}")
                else:
                    results.append(f"[{fr.title or url}]\n{fr.content}")
            else:
                results.append(f"Unknown tool: {name}")
        return results
    return _executor
```

**Step 3: Delete the pre-processing search block**

Delete everything from the line `# ── Web search ──` (around line 1127) through the end of its `if _sr.results:` block (around line 1244, ending just before `# ── URL content fetching ──`). Also remove the `!search` prefix from any docs/comments.

The `elif _web_search_flag` branch and related variables (`_SEARCH_PREFIX`, `_web_search_flag`, `_user_raw`, `_search_query`, `_explicit_prefix`) are all part of this block — delete them all.

**Step 4: Wire tools into the `_orch.think` call**

Find the `result = await _orch.think(actual_goal, ...)` call in the WebSocket handler (around line 1340). Replace with:

```python
_search_capability = msg.get("search_capability", False)
_tools = _TOOL_SCHEMAS if _search_capability else None
_tool_executor = _make_tool_executor(queue) if _search_capability else None

result = await _orch.think(
    actual_goal, on_event=on_event, conversation=conversation,
    mode_override=mode_override,
    skip_refinement=skip_refinement,
    atlas_settings=atlas_settings,
    tools=_tools,
    tool_executor=_tool_executor,
)
```

**Step 5: Smoke test (no frontend yet)**

Run: `cd ct1 && python -m pytest tests/ -v -k "not ws" 2>&1 | head -40`

**Step 6: Commit**
```bash
git add ct1/server/api.py
git commit -m "feat: replace pre-processing search with tool_use in api.py"
```

---

### Task 4: Move `webSearchEnabled` to preferences (persistent)

**Files:**
- Modify: `ct1/web/src/lib/stores/preferences.ts`
- Modify: `ct1/web/src/lib/stores/chat.ts`

**Context:** `webSearchEnabled` currently lives in the ephemeral chat store (resets on page reload). It needs to move to `preferences.ts` (persisted in localStorage) since it's now a capability setting, not a per-message toggle.

**Step 1: Add to preferences store**

In `preferences.ts`, add `webSearchEnabled: boolean` to the preferences type and default it to `false`. The preferences store already persists to localStorage — no extra work needed.

Find the type definition and default object in `preferences.ts` and add:
```typescript
webSearchEnabled: boolean;
// ...in defaults:
webSearchEnabled: false,
```

**Step 2: Remove from chat store**

In `chat.ts`, remove `webSearchEnabled` from the `ChatState` type, the initial state object (line ~200), and the reset block (line ~267). Remove the `toggleWebSearch` action (line ~737). Remove the line that reads `s_webSearch = s.webSearchEnabled` from `sendMessage`.

**Step 3: Update the `send` function to read from preferences**

In `chat.ts`'s `sendMessage` function, import and read `webSearchEnabled` from preferences:

```typescript
import { get } from 'svelte/store';
import { preferences } from './preferences';
// ...inside sendMessage:
const searchEnabled = get(preferences).webSearchEnabled;
// ...in the WS payload:
...(searchEnabled ? { search_capability: true } : {}),
```

Note the key changes: `web_search: true` → `search_capability: true` (matches what Task 3 reads).

**Step 4: Commit**
```bash
git add ct1/web/src/lib/stores/preferences.ts ct1/web/src/lib/stores/chat.ts
git commit -m "feat: move webSearchEnabled to persistent preferences"
```

---

### Task 5: Update frontend for multiple search events

**Files:**
- Modify: `ct1/web/src/lib/stores/chat.ts`

**Context:** `webSearchPhase` is a single-search state machine (`idle | extracting | searching | done`). Now the AI can search multiple times, so we need an array of search events to render all of them.

**Step 1: Change the search state shape**

In `ChatState`, replace:
```typescript
webSearchPhase: 'idle' | 'extracting' | 'searching' | 'done';
webSearchQuery: string | null;
webSearchResults: { title: string; url: string; snippet: string }[];
webSearchError: string | null;
```
With:
```typescript
activeSearches: { query: string; results: { title: string; url: string; snippet: string }[]; done: boolean }[];
```

Update the initial state:
```typescript
activeSearches: [],
```

Update the reset block (was lines ~267–270):
```typescript
s.activeSearches = [];
```

**Step 2: Update event handlers**

Replace the `web_search_extracting`, `web_searching`, and `web_search_results` cases:

```typescript
case 'web_searching':
    s.activeSearches = [...s.activeSearches, {
        query: data.query || '',
        results: [],
        done: false,
    }];
    break;
case 'web_search_results':
    // Update the last active search with results
    if (s.activeSearches.length > 0) {
        const last = s.activeSearches[s.activeSearches.length - 1];
        s.activeSearches = [
            ...s.activeSearches.slice(0, -1),
            { ...last, results: data.results || [], done: true },
        ];
    }
    break;
```

Remove the `web_search_extracting` case (no longer emitted).

**Step 3: Update turn save**

Find where turns are saved (around line 425) — the `webSearchResults` and `webSearchQuery` fields on the turn. Replace with saving `activeSearches` as the turn's search data. The turn type already has `webSearchResults?: ...` — update accordingly or keep backward compat by flattening the last search's results.

**Step 4: Commit**
```bash
git add ct1/web/src/lib/stores/chat.ts
git commit -m "feat: update chat store for multiple sequential search events"
```

---

### Task 6: Update ChatInput — remove toggle, add capability indicator

**Files:**
- Modify: `ct1/web/src/lib/components/ChatInput.svelte`

**Context:** The web search toggle button (around line 381–385 in ChatInput.svelte) must be removed. Replace it with a passive chip that shows "Search on" when the capability is enabled.

**Step 1: Remove the toggle button**

Find the `<button ... aria-pressed={webSearchEnabled} ...>` web search button and delete it entirely (it's the button with `class:active={webSearchEnabled}` around line 381).

**Step 2: Remove the derived `webSearchEnabled` line**

Delete line 22: `const webSearchEnabled = $derived($chat.webSearchEnabled);`

Import preferences instead:
```typescript
import { preferences } from '$lib/stores/preferences';
```

**Step 3: Add a passive capability chip**

In the mode-bar area, add a small indicator chip after the mode pills:
```svelte
{#if $preferences.webSearchEnabled}
    <span class="search-cap-chip">Search on</span>
{/if}
```

Style it:
```css
.search-cap-chip {
    font-size: 11px;
    color: var(--accent);
    opacity: 0.6;
    padding: 2px 6px;
    border: 1px solid var(--accent);
    border-radius: 10px;
    margin-left: 4px;
    pointer-events: none;
}
```

**Step 4: Commit**
```bash
git add ct1/web/src/lib/components/ChatInput.svelte
git commit -m "feat: remove per-message search toggle, add capability chip"
```

---

### Task 7: Add search toggle to Settings page

**Files:**
- Modify: `ct1/web/src/routes/settings/+page.svelte`

**Context:** The persistent "Allow AI to use web search" toggle needs to live in Settings. Find a logical place (near other capability/model settings, not inside a mode card).

**Step 1: Import preferences in settings**

```typescript
import { preferences, toggleWebSearch } from '$lib/stores/preferences';
```

Add a `toggleWebSearch` export to `preferences.ts`:
```typescript
export function toggleWebSearch() {
    preferences.update(p => ({ ...p, webSearchEnabled: !p.webSearchEnabled }));
}
```

**Step 2: Add toggle UI**

In the settings page, add a section for capabilities (or add to an existing general section):
```svelte
<div class="setting-row">
    <div class="setting-label">
        <span class="setting-name">Web search</span>
        <span class="setting-desc">Allow AI to search the web during responses</span>
    </div>
    <button
        class="toggle-btn"
        class:active={$preferences.webSearchEnabled}
        onclick={toggleWebSearch}
    >
        {$preferences.webSearchEnabled ? 'On' : 'Off'}
    </button>
</div>
```

Match existing toggle styling from the settings page.

**Step 3: Commit**
```bash
git add ct1/web/src/routes/settings/+page.svelte ct1/web/src/lib/stores/preferences.ts
git commit -m "feat: add web search capability toggle to settings"
```

---

### Task 8: Update active turn UI for inline search activity

**Files:**
- Modify: `ct1/web/src/routes/+page.svelte`

**Context:** The page renders `webSearchPhase` / `webSearchQuery` for active search indicators. Update to render `activeSearches` array instead, showing each search inline as it happens.

**Step 1: Find search indicator in the active turn area**

Search for `webSearchPhase` or `web_searching` / `webSearchQuery` in `+page.svelte`. These are the live indicators shown during generation.

**Step 2: Replace with array rendering**

Replace the single search indicator with:
```svelte
{#each $chat.activeSearches as search}
    <div class="search-indicator">
        <svg ...><!-- search icon --></svg>
        <span class="search-label">
            {search.done ? 'Searched:' : 'Searching:'}
        </span>
        <span class="search-query">{search.query}</span>
        {#if search.done}
            <span class="search-count">{search.results.length} results</span>
        {/if}
    </div>
{/each}
```

Match the existing phase indicator styling — keep it small and inline.

**Step 3: Update history rendering**

In the turn history section, find where `turn.webSearchResults` is rendered (the search result cards). Update to map from `turn.activeSearches` (or whatever field was saved in Task 5 Step 3).

**Step 4: Final smoke test**

Start the dev server: `cd ct1/web && npm run dev`
- Open the UI, go to Settings, toggle "Web search" on
- Send a message asking about current events
- Verify: "Searching: X" appears inline, then the AI answers with search context
- Send another question without search — verify no search activity

**Step 5: Commit**
```bash
git add ct1/web/src/routes/+page.svelte
git commit -m "feat: update active turn UI for multi-search tool_use indicators"
```

---

## Summary of all changed files

| File | Change |
|------|--------|
| `ct1/core/engine.py` | `_call_stream` tool loop; `generate` tool params |
| `ct1/core/orchestrator.py` | `think` + `_pipeline` tool params |
| `ct1/server/api.py` | Remove pre-processing search; add TOOL_SCHEMAS + executor; wire to think() |
| `ct1/web/src/lib/stores/preferences.ts` | Add `webSearchEnabled` + `toggleWebSearch` |
| `ct1/web/src/lib/stores/chat.ts` | Remove `webSearchEnabled`; add `activeSearches`; update event handlers |
| `ct1/web/src/lib/components/ChatInput.svelte` | Remove toggle button; add passive chip |
| `ct1/web/src/routes/settings/+page.svelte` | Add capability toggle |
| `ct1/web/src/routes/+page.svelte` | Update search indicator rendering |
