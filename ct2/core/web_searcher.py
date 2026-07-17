"""Async web search via DuckDuckGo for CT-2 chat context.

Uses the duckduckgo-search library — no API key, free, minimal rate limits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Domain quality tiers
# ---------------------------------------------------------------------------

# Sites that rarely yield extractable text (login walls, video-only, JS-heavy).
# Snippets are still shown in the UI but full-page fetches are skipped.
_SKIP_FETCH_DOMAINS: frozenset[str] = frozenset({
    "tiktok.com",
    "instagram.com",
    "facebook.com",
    "twitter.com",
    "x.com",
    "pinterest.com",
    "pinterest.co.uk",
    "reddit.com",        # JS-rendered; content often behind auth
    "linkedin.com",
    "snapchat.com",
})

# Domains whose pages are usually high-quality and content-rich.
# Results from these are sorted to the front of the fetch queue.
_PRIORITY_FETCH_DOMAINS: frozenset[str] = frozenset({
    # Encyclopaedic
    "wikipedia.org",
    "britannica.com",
    # Global wire services & breaking news (highest trust for current events)
    "reuters.com",
    "apnews.com",
    "afp.com",
    # English-language broadcasters
    "bbc.com",
    "bbc.co.uk",
    "aljazeera.com",
    "cnn.com",
    "nbcnews.com",
    "abcnews.go.com",
    "cbsnews.com",
    "npr.org",
    "pbs.org",
    # Newspapers
    "theguardian.com",
    "nytimes.com",
    "washingtonpost.com",
    "wsj.com",
    "thetimes.co.uk",
    "ft.com",
    "politico.com",
    "axios.com",
    "thehill.com",
    # Middle East / regional (relevant for Iran/Israel/USA coverage)
    "haaretz.com",
    "timesofisrael.com",
    "jpost.com",
    "middleeasteye.net",
    "presstv.ir",
    "tehrannews.ir",
    # Tech
    "techcrunch.com",
    "arstechnica.com",
    "wired.com",
    "theverge.com",
    # Business
    "bloomberg.com",
    "forbes.com",
    "statista.com",
    # Entertainment
    "variety.com",
    "ign.com",
    "imdb.com",
})


def _domain_fetch_tier(url: str) -> int:
    """Return sort key: 0 = priority, 1 = normal, 2 = skip."""
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower().lstrip("www.")
    for skip in _SKIP_FETCH_DOMAINS:
        if host == skip or host.endswith("." + skip):
            return 2
    for prio in _PRIORITY_FETCH_DOMAINS:
        if host == prio or host.endswith("." + prio):
            return 0
    return 1


def prioritized_fetch_urls(results: list) -> list[str]:
    """Return result URLs sorted by fetch tier, skipping unfetchable domains."""
    ordered = sorted(results, key=lambda r: _domain_fetch_tier(r.url))
    return [r.url for r in ordered if _domain_fetch_tier(r.url) < 2]


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


@dataclass
class SearchResponse:
    query: str
    results: list[SearchResult]
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _ddg_search_sync(query: str, max_results: int) -> list[dict]:
    """Run DuckDuckGo text search synchronously (called via asyncio.to_thread)."""
    from ddgs import DDGS
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results, safesearch="off"))


async def search_web(query: str, max_results: int = 5) -> SearchResponse:
    """Search DuckDuckGo and return structured results.

    Falls back to an empty result list on any error rather than raising.
    Runs the synchronous DDGS client in a thread to avoid blocking the event loop.
    """
    import asyncio

    if not query or not query.strip():
        return SearchResponse(query=query, results=[], error="Empty query")

    try:
        raw = await asyncio.to_thread(_ddg_search_sync, query.strip(), max_results)
        results = [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("href", ""),
                snippet=r.get("body", ""),
            )
            for r in (raw or [])
            if r.get("href")
        ]
        return SearchResponse(query=query, results=results)

    except Exception as exc:  # noqa: BLE001
        return SearchResponse(query=query, results=[], error=str(exc))


def format_results_as_context(resp: SearchResponse) -> str:
    """Format search results into a context block for the LLM."""
    if resp.error and not resp.results:
        return f"[WEB SEARCH for '{resp.query}' failed: {resp.error}]"

    from datetime import datetime as _dt
    _now = _dt.now().strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "--- WEB SEARCH CONTEXT ---",
        f"Query: {resp.query}",
        f"Search performed: {_now}",
        "The following information was retrieved from the web.",
        "Use it to answer the user's question accurately and up to date. Do NOT reproduce it verbatim.",
        "",
        "Search result snippets:",
    ]
    for i, r in enumerate(resp.results, 1):
        lines.append(f"{i}. {r.title}")
        lines.append(f"   Source: {r.url}")
        if r.snippet:
            lines.append(f"   {r.snippet}")
    return "\n".join(lines)
