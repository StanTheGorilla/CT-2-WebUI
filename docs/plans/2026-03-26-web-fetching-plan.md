# Web Fetching & Scraping — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let users paste URLs in chat; the system fetches the page, extracts clean text, and injects it into the model's context as reference material.

**Architecture:** Backend-only fetching in `api.py` (same pattern as workspace file injection). New standalone `web_fetcher.py` module handles HTTP + extraction via trafilatura. Frontend receives WebSocket events for status/preview.

**Tech Stack:** httpx (existing), trafilatura (new), beautifulsoup4 (existing, fallback), urllib.robotparser (stdlib)

**Design doc:** `docs/plans/2026-03-26-web-fetching-design.md`

---

### Task 1: Install trafilatura dependency

**Files:**
- Modify: `ct1/requirements.txt`

**Step 1: Add trafilatura to requirements**

Add this line to `ct1/requirements.txt`:
```
trafilatura>=2.0.0
```

**Step 2: Install it**

Run: `pip install trafilatura`

**Step 3: Verify import**

Run: `python -c "import trafilatura; print(trafilatura.__version__)"`
Expected: version number printed, no errors

**Step 4: Commit**

```bash
git add ct1/requirements.txt
git commit -m "deps: add trafilatura for web content extraction"
```

---

### Task 2: Create web_fetcher.py — robots.txt checking

**Files:**
- Create: `ct1/core/web_fetcher.py`
- Create: `ct1/tests/test_web_fetcher.py`

**Step 1: Write the failing test**

Create `ct1/tests/test_web_fetcher.py`:
```python
"""Tests for ct1.core.web_fetcher."""
import pytest
from ct1.core.web_fetcher import FetchResult, _check_robots, _extract_domain


def test_extract_domain():
    assert _extract_domain("https://example.com/page") == "example.com"
    assert _extract_domain("https://en.wikipedia.org/wiki/Python") == "en.wikipedia.org"
    assert _extract_domain("http://localhost:3000/test") == "localhost:3000"


def test_fetch_result_dataclass():
    r = FetchResult(
        url="https://example.com",
        title="Example",
        content="Hello world",
        content_length=11,
        truncated=False,
        error=None,
    )
    assert r.url == "https://example.com"
    assert r.error is None


def test_fetch_result_error():
    r = FetchResult(
        url="https://example.com",
        title="",
        content="",
        content_length=0,
        truncated=False,
        error="Connection refused",
    )
    assert r.error == "Connection refused"
```

**Step 2: Run test to verify it fails**

Run: `pytest ct1/tests/test_web_fetcher.py -v`
Expected: FAIL — module not found

**Step 3: Write the module skeleton with FetchResult and helpers**

Create `ct1/core/web_fetcher.py`:
```python
"""Web content fetcher — fetch URLs, extract clean text via trafilatura.

Standalone module. No dependency on other CT-2 modules.
Designed to be callable from api.py (user-initiated) or orchestrator (future model-initiated).
"""
import re
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

_USER_AGENT = "CT-2/1.0"
_TIMEOUT = 10.0
_MAX_URLS_PER_MESSAGE = 3

# Cache parsed robots.txt per domain (lives for server lifetime)
_robots_cache: dict[str, RobotFileParser | None] = {}

# Regex to find URLs in text
URL_PATTERN = re.compile(r'https?://[^\s<>"\')\]]+')


@dataclass
class FetchResult:
    url: str
    title: str
    content: str
    content_length: int
    truncated: bool
    error: str | None


def _extract_domain(url: str) -> str:
    """Extract domain (with port) from a URL."""
    parsed = urlparse(url)
    return parsed.netloc


async def _check_robots(url: str) -> bool:
    """Check if URL is allowed by robots.txt. Returns True if allowed."""
    parsed = urlparse(url)
    domain = parsed.netloc
    robots_url = f"{parsed.scheme}://{domain}/robots.txt"

    if domain not in _robots_cache:
        rp = RobotFileParser()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(robots_url, follow_redirects=True)
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                else:
                    # No robots.txt or error → assume allowed
                    _robots_cache[domain] = None
                    return True
        except Exception:
            # Network error fetching robots.txt → assume allowed
            _robots_cache[domain] = None
            return True
        _robots_cache[domain] = rp

    rp = _robots_cache[domain]
    if rp is None:
        return True
    return rp.can_fetch(_USER_AGENT, url)


def extract_urls(text: str) -> list[str]:
    """Extract unique URLs from text. Returns up to _MAX_URLS_PER_MESSAGE."""
    if isinstance(text, list):
        # Multimodal content — extract from text parts
        parts = [p.get("text", "") for p in text if isinstance(p, dict) and p.get("type") == "text"]
        text = " ".join(parts)
    urls = URL_PATTERN.findall(text)
    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for u in urls:
        # Strip trailing punctuation that's not part of URL
        u = u.rstrip(".,;:!?")
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique[:_MAX_URLS_PER_MESSAGE]
```

**Step 4: Run tests**

Run: `pytest ct1/tests/test_web_fetcher.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add ct1/core/web_fetcher.py ct1/tests/test_web_fetcher.py
git commit -m "feat(web-fetch): add web_fetcher skeleton with FetchResult, URL extraction, robots.txt"
```

---

### Task 3: Implement fetch_url with trafilatura extraction

**Files:**
- Modify: `ct1/core/web_fetcher.py`
- Modify: `ct1/tests/test_web_fetcher.py`

**Step 1: Write the failing tests**

Append to `ct1/tests/test_web_fetcher.py`:
```python
def test_extract_urls_basic():
    text = "Check https://example.com and https://test.org/page for details"
    urls = extract_urls(text)
    assert urls == ["https://example.com", "https://test.org/page"]


def test_extract_urls_deduplication():
    text = "Visit https://example.com twice: https://example.com"
    urls = extract_urls(text)
    assert urls == ["https://example.com"]


def test_extract_urls_max_cap():
    text = " ".join(f"https://site{i}.com" for i in range(10))
    urls = extract_urls(text)
    assert len(urls) == 3  # _MAX_URLS_PER_MESSAGE


def test_extract_urls_strips_trailing_punctuation():
    text = "See https://example.com/page, and https://test.org."
    urls = extract_urls(text)
    assert urls == ["https://example.com/page", "https://test.org"]


def test_extract_urls_multimodal():
    content = [
        {"type": "text", "text": "Check https://example.com"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
    ]
    urls = extract_urls(content)
    assert urls == ["https://example.com"]


def test_truncate_content():
    from ct1.core.web_fetcher import _truncate_content
    # Short content — no truncation
    short = "Hello world"
    result, truncated = _truncate_content(short, 1000)
    assert result == short
    assert not truncated

    # Long content — truncated at paragraph break
    paragraphs = "\n\n".join(f"Paragraph {i} with some text." for i in range(100))
    result, truncated = _truncate_content(paragraphs, 200)
    assert len(result) <= 250  # 200 + truncation marker
    assert truncated
    assert "[... content truncated" in result


@pytest.mark.asyncio
async def test_fetch_url_invalid_url():
    from ct1.core.web_fetcher import fetch_url
    result = await fetch_url("not-a-url")
    assert result.error is not None


@pytest.mark.asyncio
async def test_fetch_url_unreachable():
    from ct1.core.web_fetcher import fetch_url
    result = await fetch_url("https://localhost:19999/nonexistent")
    assert result.error is not None
    assert result.content == ""
```

**Step 2: Run tests to verify they fail**

Run: `pytest ct1/tests/test_web_fetcher.py -v`
Expected: FAIL — missing functions

**Step 3: Implement fetch_url and _truncate_content**

Add to `ct1/core/web_fetcher.py`:
```python
def _truncate_content(text: str, max_chars: int) -> tuple[str, bool]:
    """Truncate text at last paragraph break before max_chars.
    Returns (truncated_text, was_truncated)."""
    if len(text) <= max_chars:
        return text, False

    # Find last paragraph break before limit
    cut = text[:max_chars]
    last_break = cut.rfind("\n\n")
    if last_break > max_chars // 2:
        cut = cut[:last_break]
    else:
        # No good paragraph break — cut at last sentence end
        last_period = cut.rfind(". ")
        if last_period > max_chars // 2:
            cut = cut[:last_period + 1]

    return (
        f"{cut}\n\n[... content truncated, {len(text)} chars total ...]",
        True,
    )


def _extract_title(html: str) -> str:
    """Extract page title from HTML."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("title")
    return tag.get_text(strip=True) if tag else ""


async def fetch_url(url: str, max_chars: int = 24000) -> FetchResult:
    """Fetch a URL and extract clean readable text.

    Args:
        url: The URL to fetch.
        max_chars: Maximum characters of extracted content to return.

    Returns:
        FetchResult with extracted content or error.
    """
    # Validate URL
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return FetchResult(
            url=url, title="", content="", content_length=0,
            truncated=False, error="Invalid URL — must be http:// or https://",
        )

    # Check robots.txt
    try:
        allowed = await _check_robots(url)
        if not allowed:
            return FetchResult(
                url=url, title="", content="", content_length=0,
                truncated=False, error="Blocked by robots.txt",
            )
    except Exception:
        pass  # robots.txt check failure → proceed with fetch

    # Fetch page
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.1",
            },
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.TimeoutException:
        return FetchResult(
            url=url, title="", content="", content_length=0,
            truncated=False, error=f"Timeout after {_TIMEOUT}s",
        )
    except httpx.HTTPStatusError as e:
        return FetchResult(
            url=url, title="", content="", content_length=0,
            truncated=False, error=f"HTTP {e.response.status_code}",
        )
    except Exception as e:
        return FetchResult(
            url=url, title="", content="", content_length=0,
            truncated=False, error=str(e),
        )

    html = resp.text
    final_url = str(resp.url)
    title = _extract_title(html)

    # Extract content — trafilatura first, BS4 fallback
    content = None
    try:
        import trafilatura
        content = trafilatura.extract(
            html,
            include_links=False,
            include_tables=True,
            include_comments=False,
        )
    except Exception:
        pass

    if not content:
        # Fallback: BS4 get_text with basic boilerplate removal
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup.find_all(["script", "style", "nav", "footer",
                                      "aside", "header", "noscript"]):
                tag.decompose()
            content = soup.get_text(separator="\n", strip=True)
            # Collapse excessive blank lines
            content = re.sub(r"\n{3,}", "\n\n", content)
        except Exception:
            content = ""

    if not content:
        return FetchResult(
            url=final_url, title=title, content="", content_length=0,
            truncated=False, error="Could not extract readable content from page",
        )

    original_length = len(content)
    content, truncated = _truncate_content(content, max_chars)

    return FetchResult(
        url=final_url, title=title, content=content,
        content_length=original_length, truncated=truncated, error=None,
    )
```

**Step 4: Run tests**

Run: `pytest ct1/tests/test_web_fetcher.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add ct1/core/web_fetcher.py ct1/tests/test_web_fetcher.py
git commit -m "feat(web-fetch): implement fetch_url with trafilatura extraction and truncation"
```

---

### Task 4: Wire URL fetching into api.py WebSocket handler

**Files:**
- Modify: `ct1/server/api.py:313-350` (inside `run_think()`, after workspace injection)

**Step 1: Add URL fetching block after workspace injection**

In `api.py`, inside `run_think()`, after the workspace context injection block (ends around line 344) and before the `result = await _orch.think(...)` call, add:

```python
                    # ── URL content fetching ──
                    # Detect URLs in user message, fetch pages, inject as context
                    from ct1.core.web_fetcher import extract_urls, fetch_url as _fetch_url

                    goal_text_for_urls = actual_goal if isinstance(actual_goal, str) else " ".join(
                        p.get("text", "") for p in actual_goal if isinstance(p, dict) and p.get("type") == "text"
                    )
                    detected_urls = extract_urls(goal_text_for_urls)

                    if detected_urls:
                        # Calculate per-URL budget: half of available context, split across URLs
                        ctx_size = _cfg.get("llama_server", {}).get("context_size", 16384)
                        budget_chars = int((ctx_size * 3.5 - 2000) / 2 / len(detected_urls))
                        budget_chars = max(budget_chars, 500)

                        if len(detected_urls) > 3:
                            queue.put_nowait({
                                "event": "warning",
                                "message": f"Found {len(detected_urls)} URLs, fetching first 3 only.",
                            })

                        fetched_blocks = []
                        fetched_meta = []  # For frontend display

                        for u in detected_urls:
                            queue.put_nowait({"event": "url_fetching", "url": u})
                            try:
                                fr = await _fetch_url(u, max_chars=budget_chars)
                                if fr.error:
                                    queue.put_nowait({
                                        "event": "url_failed",
                                        "url": u, "error": fr.error,
                                    })
                                else:
                                    fetched_blocks.append(
                                        f'[FETCHED CONTENT FROM: {fr.url} — "{fr.title}"]\n'
                                        f'{fr.content}\n'
                                        f'[END FETCHED CONTENT]'
                                    )
                                    fetched_meta.append({
                                        "url": fr.url,
                                        "title": fr.title,
                                        "content": fr.content[:500],
                                        "content_length": fr.content_length,
                                        "truncated": fr.truncated,
                                    })
                                    queue.put_nowait({
                                        "event": "url_fetched",
                                        "url": fr.url,
                                        "title": fr.title,
                                        "content_length": fr.content_length,
                                        "truncated": fr.truncated,
                                        "preview": fr.content[:500],
                                    })
                            except Exception as e:
                                queue.put_nowait({
                                    "event": "url_failed",
                                    "url": u, "error": str(e),
                                })

                        if fetched_blocks:
                            ctx = "\n\n".join(fetched_blocks)
                            if isinstance(actual_goal, str):
                                actual_goal = f"{ctx}\n\n{actual_goal}"
                            elif isinstance(actual_goal, list):
                                for part in actual_goal:
                                    if part.get("type") == "text":
                                        part["text"] = f"{ctx}\n\n{part['text']}"
                                        break
```

**Step 2: Verify the API still starts without import errors**

Run: `python -c "from ct1.server.api import app; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add ct1/server/api.py
git commit -m "feat(web-fetch): wire URL detection and fetching into WebSocket handler"
```

---

### Task 5: Strip fetched content from routing in orchestrator.py

**Files:**
- Modify: `ct1/core/orchestrator.py:45-50` (inside `_strip_file_context`)

**Step 1: Read the current function**

Read `ct1/core/orchestrator.py` lines 45-50 to see the current `_strip_file_context()`.

**Step 2: Add the strip pattern**

Add this line to `_strip_file_context()` after the existing workspace strip:
```python
text = re.sub(
    r'\[FETCHED CONTENT FROM:[^\]]*\].*?\[END FETCHED CONTENT\]\s*',
    '', text, flags=re.DOTALL,
)
```

**Step 3: Verify import still works**

Run: `python -c "from ct1.core.orchestrator import Orchestrator; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add ct1/core/orchestrator.py
git commit -m "feat(web-fetch): strip fetched content blocks from routing intent detection"
```

---

### Task 6: Frontend — chat.ts state and event handlers

**Files:**
- Modify: `ct1/web/src/lib/stores/chat.ts`

**Step 1: Add new state fields to ChatState interface** (around line 91)

Add after `savedFiles: string[];`:
```typescript
    fetchingUrls: { url: string; status: 'fetching' | 'done' | 'failed'; error?: string }[];
    fetchedContent: { url: string; title: string; content: string;
                      contentLength: number; truncated: boolean }[];
```

**Step 2: Add initial values** (around line 133)

Add after `savedFiles: [],`:
```typescript
    fetchingUrls: [],
    fetchedContent: [],
```

**Step 3: Add fetchedContent to Turn interface** (around line 14)

Add as optional field:
```typescript
    fetchedContent?: { url: string; title: string; content: string;
                       contentLength: number; truncated: boolean }[];
```

**Step 4: Add event handlers in handleEvent switch** (before the `case 'warning':` block)

```typescript
            case 'url_fetching':
                s.fetchingUrls = [...s.fetchingUrls, { url: data.url, status: 'fetching' }];
                break;
            case 'url_fetched': {
                s.fetchingUrls = s.fetchingUrls.map(f =>
                    f.url === data.url ? { ...f, status: 'done' as const } : f
                );
                s.fetchedContent = [...s.fetchedContent, {
                    url: data.url,
                    title: data.title || '',
                    content: data.preview || '',
                    contentLength: data.content_length || 0,
                    truncated: data.truncated || false,
                }];
                break;
            }
            case 'url_failed':
                s.fetchingUrls = s.fetchingUrls.map(f =>
                    f.url === data.url ? { ...f, status: 'failed' as const, error: data.error } : f
                );
                break;
```

**Step 5: Persist fetchedContent into the Turn on `done` event**

In the `done` handler, add `fetchedContent` to the turn object being pushed to conversation (around line 275-289):
```typescript
                        fetchedContent: s.fetchedContent.length > 0 ? s.fetchedContent : undefined,
```

**Step 6: Reset fetch state in sendThink**

Add to the reset block in `sendThink()` (around line 613):
```typescript
        s.fetchingUrls = [];
        s.fetchedContent = [];
```

**Step 7: Build frontend**

Run: `npm run build --prefix ct1/web`
Expected: Build succeeds

**Step 8: Commit**

```bash
git add ct1/web/src/lib/stores/chat.ts
git commit -m "feat(web-fetch): add fetch URL state, events, and turn persistence to chat store"
```

---

### Task 7: Frontend — +page.svelte display

**Files:**
- Modify: `ct1/web/src/routes/+page.svelte`

**Step 1: Add fetch status display**

After the routing phase indicator and before the generation card (search for `<!-- ==================== GENERATION ====================`), add:

```svelte
                {#if $chat.fetchingUrls.length > 0}
                    <div class="fetch-status">
                        {#each $chat.fetchingUrls as fu}
                            <div class="fetch-row" class:done={fu.status === 'done'} class:failed={fu.status === 'failed'}>
                                <span class="fetch-dot" class:pulse={fu.status === 'fetching'}></span>
                                <span class="fetch-label">
                                    {fu.status === 'fetching' ? 'Fetching' : fu.status === 'done' ? 'Fetched' : 'Failed'}
                                </span>
                                <span class="fetch-url">{fu.url.length > 60 ? fu.url.slice(0, 57) + '...' : fu.url}</span>
                                {#if fu.status === 'failed' && fu.error}
                                    <span class="fetch-error">— {fu.error}</span>
                                {/if}
                            </div>
                        {/each}
                    </div>
                {/if}

                {#if $chat.fetchedContent.length > 0}
                    {#each $chat.fetchedContent as fc}
                        <details class="fetch-card">
                            <summary class="fetch-card-header">
                                <span class="fetch-card-icon">W</span>
                                <span class="fetch-card-title">{fc.title || fc.url}</span>
                                <span class="fetch-card-meta">{formatChars(fc.contentLength)}</span>
                                {#if fc.truncated}
                                    <span class="fetch-card-trunc">truncated</span>
                                {/if}
                            </summary>
                            <pre class="fetch-card-body">{fc.content}</pre>
                        </details>
                    {/each}
                {/if}
```

**Step 2: Add CSS for fetch components**

Add to the `<style>` block:
```css
    .fetch-status { display: flex; flex-direction: column; gap: 4px; margin: 6px 0; }
    .fetch-row { display: flex; align-items: center; gap: 6px; font-size: 0.78rem; color: var(--text-2); }
    .fetch-row.done { color: var(--text-2); }
    .fetch-row.failed { color: var(--warning); }
    .fetch-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); flex-shrink: 0; }
    .fetch-dot.pulse { animation: pulse 1s infinite; }
    .fetch-url { opacity: 0.7; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 400px; }
    .fetch-error { opacity: 0.8; font-style: italic; }
    .fetch-label { font-weight: 500; min-width: 52px; }

    .fetch-card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; margin: 4px 0; overflow: hidden; }
    .fetch-card-header { display: flex; align-items: center; gap: 8px; padding: 8px 12px; cursor: pointer; font-size: 0.8rem; color: var(--text-2); }
    .fetch-card-header::-webkit-details-marker { display: none; }
    .fetch-card-icon { font-weight: 700; font-size: 0.7rem; background: var(--accent); color: var(--bg); width: 18px; height: 18px; border-radius: 4px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
    .fetch-card-title { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .fetch-card-meta { margin-left: auto; opacity: 0.6; flex-shrink: 0; }
    .fetch-card-trunc { font-size: 0.7rem; opacity: 0.5; font-style: italic; }
    .fetch-card-body { padding: 8px 12px; font-size: 0.75rem; color: var(--text-2); max-height: 200px; overflow-y: auto; white-space: pre-wrap; word-break: break-word; border-top: 1px solid var(--border); margin: 0; }
```

**Step 3: Add fetch card rendering for history turns**

In the assistant turn rendering sections (code route and text route), where `turn.reflection` is displayed, add after it:
```svelte
                            {#if turn.fetchedContent?.length}
                                {#each turn.fetchedContent as fc}
                                    <details class="fetch-card">
                                        <summary class="fetch-card-header">
                                            <span class="fetch-card-icon">W</span>
                                            <span class="fetch-card-title">{fc.title || fc.url}</span>
                                            <span class="fetch-card-meta">{formatChars(fc.contentLength)}</span>
                                        </summary>
                                        <pre class="fetch-card-body">{fc.content}</pre>
                                    </details>
                                {/each}
                            {/if}
```

**Step 4: Build frontend**

Run: `npm run build --prefix ct1/web`
Expected: Build succeeds

**Step 5: Commit**

```bash
git add ct1/web/src/routes/+page.svelte
git commit -m "feat(web-fetch): add fetch status indicators and collapsible preview cards to UI"
```

---

### Task 8: Integration test — end-to-end verification

**Files:**
- Modify: `ct1/tests/test_web_fetcher.py`

**Step 1: Add a live integration test (marked slow)**

Append to `ct1/tests/test_web_fetcher.py`:
```python
@pytest.mark.asyncio
async def test_fetch_url_real_page():
    """Integration test — fetches a real page. Requires network."""
    from ct1.core.web_fetcher import fetch_url
    result = await fetch_url("https://example.com", max_chars=5000)
    assert result.error is None
    assert result.title  # example.com has a title
    assert len(result.content) > 50
    assert "Example Domain" in result.content or "example" in result.content.lower()


@pytest.mark.asyncio
async def test_fetch_url_with_truncation():
    """Fetch a large page and verify truncation works."""
    from ct1.core.web_fetcher import fetch_url
    result = await fetch_url("https://en.wikipedia.org/wiki/Python_(programming_language)", max_chars=2000)
    # Should succeed and truncate
    if result.error is None:
        assert result.content_length > 2000
        assert result.truncated
        assert "[... content truncated" in result.content
```

**Step 2: Run all tests**

Run: `pytest ct1/tests/test_web_fetcher.py -v`
Expected: ALL PASS

**Step 3: Run full build**

Run: `npm run build --prefix ct1/web`
Expected: Build succeeds

**Step 4: Commit**

```bash
git add ct1/tests/test_web_fetcher.py
git commit -m "test(web-fetch): add integration tests for live URL fetching"
```

---

## Task dependency order

```
Task 1 (dependency) → Task 2 (skeleton) → Task 3 (fetch_url) → Task 4 (api.py wiring) → Task 5 (routing strip)
                                                                  Task 6 (chat.ts) → Task 7 (+page.svelte)
                                                                                       ↓
                                                                                   Task 8 (integration test)
```

Tasks 4-5 (backend) and 6-7 (frontend) can be done in parallel after Task 3.
