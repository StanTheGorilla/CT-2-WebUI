# Web Fetching & Scraping — Design

**Date**: 2026-03-26
**Status**: Approved
**Branch**: feature/web-ui

## Problem

The local models have no access to live web content. When a user wants to reference a webpage (documentation, Wikipedia article, spec, blog post), they must manually copy-paste the content. This is friction-heavy and error-prone.

## Solution

Detect URLs in user messages, fetch the page, extract clean readable text via trafilatura, and inject it into the model's context as delimited reference material. All modes supported. Single page fetch only — no crawling, no JS rendering.

## Architecture

### New module: `ct1/core/web_fetcher.py`

Standalone async module, no dependency on other CT-2 modules.

```python
@dataclass
class FetchResult:
    url: str              # Final URL (after redirects)
    title: str            # Page title
    content: str          # Extracted text, truncated to max_chars
    content_length: int   # Original length before truncation
    truncated: bool
    error: str | None     # Error message if failed

async def fetch_url(url: str, max_chars: int = 24000) -> FetchResult
```

**Internals:**
- **robots.txt**: `urllib.robotparser` check before fetching. Cache parsed robots.txt per domain (dict keyed by domain). If disallowed → error.
- **HTTP**: `httpx.AsyncClient`, 10s timeout, follow redirects, `User-Agent: CT-2/1.0`, accept `text/html`.
- **Extraction**: `trafilatura.extract(include_links=False, include_tables=True, include_comments=False)`. Falls back to BS4 `get_text()` if trafilatura returns nothing.
- **Truncation**: If text > `max_chars`, truncate at last paragraph break before limit. Append `[... content truncated, {N} chars total ...]`.

### Context injection: `api.py`

Inside WebSocket handler's `run_think()`, after workspace file injection, before `_orch.think()`.

1. Regex extract URLs from goal text: `https?://[^\s<>"')\]]+`
2. Cap at 3 URLs per message. Warn if more.
3. For each URL:
   - Emit `url_fetching` event
   - Call `fetch_url(url, max_chars=budget)`
   - Emit `url_fetched` or `url_failed` event
4. Prepend successful fetches to goal:
```
[FETCHED CONTENT FROM: https://example.com — "Page Title"]
extracted text here...
[END FETCHED CONTENT]

{original user message}
```
5. Handle both string and multimodal goal formats.

**Context budget per URL:**
```
max_chars = (context_size * 3.5 - 2000) / 2 / num_urls
```
Fetched content gets at most half the available token budget, split across URLs. System prompt estimate: 2000 chars. If budget < 500 chars per URL, skip and warn.

### Routing strip: `orchestrator.py`

Add to `_strip_file_context()`:
```python
text = re.sub(r'\[FETCHED CONTENT FROM:[^\]]*\].*?\[END FETCHED CONTENT\]\s*',
              '', text, flags=re.DOTALL)
```

Prevents fetched content from polluting deterministic routing.

### Frontend: `chat.ts` + `+page.svelte`

**New state (chat.ts):**
```typescript
fetchingUrls: { url: string; status: 'fetching' | 'done' | 'failed' }[]
fetchedContent: { url: string; title: string; content: string;
                  contentLength: number; truncated: boolean }[]
```

**New events:**
- `url_fetching` → push to fetchingUrls
- `url_fetched` → update status, push to fetchedContent
- `url_failed` → update status, show warning

**Turn persistence:** New optional `fetchedContent` field on Turn interface, populated on `done`.

**Display (+page.svelte):**
- During fetch: inline status line "Fetching https://..."
- After fetch: collapsible card showing title, char count, preview (~500 chars when expanded)
- In history: same card from `turn.fetchedContent`
- On failure: inline error message

### Dependency

Add `trafilatura` to `ct1/requirements.txt`.

## Not in scope

- Model-initiated fetching (model decides to look something up)
- JavaScript rendering
- Crawling / link following
- Caching fetched content across messages
- Authentication / cookies for protected pages

## Future extensibility

The fetcher module is standalone and callable from anywhere. Model-initiated fetching can be added later by having the orchestrator detect `[FETCH: url]` markers in model output and calling the same `fetch_url()` function.
