# AI Tool Use: Web Search & Fetch as Autonomous Tools

**Date:** 2026-04-17  
**Status:** Approved

## Problem

Web search currently runs as a pre-processing step: one search fires before the AI generates, results are stuffed into context. The user must manually toggle it per message. This is wrong — it should work like Claude.ai: the AI decides when to search, what to search for, and how many times, all during generation.

## Goal

Web search and web fetch become Anthropic `tool_use` tools the AI calls autonomously. The user enables search as a persistent capability ("AI can search"), then gets out of the way.

## Architecture

### Backend — engine.py

Add a `tools` array to every AI request when search capability is enabled:

```python
tools = [
    {
        "name": "web_search",
        "description": "Search the web for current information.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"]
        }
    },
    {
        "name": "fetch_url",
        "description": "Fetch the contents of a URL.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"]
        }
    }
]
```

The streaming loop in `engine.py` must handle `tool_use` content blocks:
1. AI emits `tool_use` block → pause streaming
2. Backend runs `search_web(query)` or `fetch_url(url)`
3. Send `tool_result` message back to AI
4. Resume streaming
5. Loop until AI emits `end_turn` with no pending tool calls

Emit WebSocket events for each tool call so the frontend can show live activity.

### Backend — api.py

Remove the pre-processing search block (~lines 1127–1210 in api.py). Tool calls fully replace it. The `web_search` flag on the incoming message body is replaced by a capability flag checked once at request start.

### Frontend — Settings

Add a persistent "Allow AI to use web search" toggle. Stored in preferences, sent as a capability flag in the WebSocket message body.

### Frontend — ChatInput.svelte

Remove the per-message web search toggle button. Replace with a faint capability indicator (e.g., a chip showing "Search on") when the capability is active — gives the user awareness without a control they need to manage per-message.

### Frontend — Active turn UI

When the AI calls a tool mid-response, stream an inline indicator in the active generation area:

```
🔍 Searching: "SvelteKit 5 rune patterns"
🌐 Fetching: docs.svelte.dev/...
```

Uses the existing `web_searching` / `web_search_results` / `fetched_content` WebSocket events — just fired from tool calls now instead of pre-processing. History rendering of search result cards is unchanged.

## What Does NOT Change

- Workspaces and their file context — not touched
- Atlas pipeline, mode bar, preview panel — untouched
- All WebSocket event names and history rendering for search results — stay as-is
- Tier 2 polish items (workspace creation modal, undo stack UI) — separate future tasks

## Out of Scope

- Workspace file reading as a tool — deferred (existing context issues)
- Any other tool types (code execution, image generation, etc.)

## Success Criteria

- AI searches 0–N times per response with no user intervention
- Each search/fetch shows inline in the UI during generation
- Per-message toggle is gone; one persistent setting controls capability
- Existing search result cards in conversation history still render correctly
