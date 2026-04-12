"""Async URL fetcher with trafilatura extraction for CT-2 chat context."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
import trafilatura
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
# A broader Accept header helps sites that serve 406/403 to minimal clients.
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}
TIMEOUT_S = 20
ROBOTS_TIMEOUT_S = 5
MAX_URLS_PER_MESSAGE = 3

URL_PATTERN = re.compile(r"https?://[^\s<>\"')\]]+")

# Domains whose robots.txt has already been checked (or failed).
_robots_cache: dict[str, bool] = {}

# Tags considered boilerplate for the BS4 fallback path.
_BOILERPLATE_TAGS = {"script", "style", "nav", "footer", "aside", "header", "noscript"}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class FetchResult:
    url: str
    title: Optional[str] = None
    content: Optional[str] = None
    content_length: int = 0
    truncated: bool = False
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_urls(text) -> list[str]:
    """Extract unique URLs from *text*, capped at MAX_URLS_PER_MESSAGE.

    *text* may be a plain string **or** a list of multimodal content dicts
    (OpenAI-style ``[{"type": "text", "text": "..."}]``).
    Trailing punctuation that is not part of the URL is stripped.
    """
    raw: str
    if isinstance(text, list):
        parts: list[str] = []
        for item in text:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        raw = " ".join(parts)
    else:
        raw = str(text)

    matches = URL_PATTERN.findall(raw)

    seen: set[str] = set()
    unique: list[str] = []
    for url in matches:
        # Strip trailing punctuation that commonly appears after pasted URLs.
        url = url.rstrip(".,;:!?")
        if url not in seen:
            seen.add(url)
            unique.append(url)

    return unique[:MAX_URLS_PER_MESSAGE]


async def fetch_url(url: str, max_chars: int = 240_000) -> FetchResult:
    """Fetch *url*, extract readable text, and return a FetchResult."""

    # 1. Validate scheme ------------------------------------------------
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return FetchResult(url=url, error="Unsupported URL scheme (only http/https)")
    if not parsed.netloc:
        return FetchResult(url=url, error="Invalid URL: no host")

    # 2. Robots.txt check -----------------------------------------------
    allowed = await _check_robots(url)
    if not allowed:
        return FetchResult(url=url, error="Blocked by robots.txt")

    # 3. HTTP GET -------------------------------------------------------
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_S,
            follow_redirects=True,
            headers=DEFAULT_HEADERS,
            http2=False,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        friendly = {
            403: "403 Forbidden — site blocked the request",
            404: "404 Not Found",
            429: "429 Too Many Requests — site rate-limited us",
            500: "500 Server Error",
            502: "502 Bad Gateway",
            503: "503 Service Unavailable",
            504: "504 Gateway Timeout",
        }.get(code, f"HTTP {code}")
        return FetchResult(url=url, error=friendly)
    except httpx.ConnectTimeout:
        return FetchResult(url=url, error="Connection timeout (site unreachable)")
    except httpx.ReadTimeout:
        return FetchResult(url=url, error="Read timeout (site too slow)")
    except httpx.ConnectError as exc:
        msg = str(exc).lower()
        if "ssl" in msg or "certificate" in msg:
            return FetchResult(url=url, error="SSL certificate error")
        if "name or service not known" in msg or "getaddrinfo" in msg:
            return FetchResult(url=url, error="Domain not found (DNS lookup failed)")
        return FetchResult(url=url, error="Could not connect to site")
    except httpx.TooManyRedirects:
        return FetchResult(url=url, error="Too many redirects")
    except Exception as exc:  # noqa: BLE001
        # Strip noisy module prefixes from httpx exceptions.
        err = str(exc).split("\n")[0][:120] or type(exc).__name__
        return FetchResult(url=url, error=err)

    # 4. Title ----------------------------------------------------------
    title = _extract_title(html)

    # 5. Content extraction – trafilatura first, BS4 fallback -----------
    content = trafilatura.extract(
        html,
        include_links=False,
        include_tables=True,
        include_comments=False,
    )

    if not content:
        content = _bs4_fallback(html)

    if not content:
        return FetchResult(url=url, title=title, error="No extractable content")

    # 6. Truncate -------------------------------------------------------
    content, truncated = _truncate_content(content, max_chars)

    return FetchResult(
        url=url,
        title=title,
        content=content,
        content_length=len(content),
        truncated=truncated,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_domain(url: str) -> str:
    """Return the network location (host[:port]) from *url*."""
    return urlparse(url).netloc


def _extract_title(html: str) -> Optional[str]:
    """Extract the <title> text from raw HTML via BeautifulSoup."""
    try:
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            return soup.title.string.strip()
    except Exception:  # noqa: BLE001
        pass
    return None


async def _check_robots(url: str) -> bool:
    """Return True if *url* is allowed by the site's robots.txt.

    Results are cached per domain. On any failure (timeout, parse error)
    the URL is optimistically allowed.
    """
    domain = _extract_domain(url)
    if domain in _robots_cache:
        return _robots_cache[domain]

    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{domain}/robots.txt"

    try:
        async with httpx.AsyncClient(
            timeout=ROBOTS_TIMEOUT_S,
            follow_redirects=True,
            headers=DEFAULT_HEADERS,
        ) as client:
            resp = await client.get(robots_url)
            if resp.status_code != 200:
                # No robots.txt or server error → allow.
                _robots_cache[domain] = True
                return True
            rp = RobotFileParser()
            rp.parse(resp.text.splitlines())
            allowed = rp.can_fetch(USER_AGENT, url)
            _robots_cache[domain] = allowed
            return allowed
    except Exception:  # noqa: BLE001
        # Any robots.txt failure → optimistically allow the fetch.
        _robots_cache[domain] = True
        return True


def _truncate_content(text: str, max_chars: int) -> tuple[str, bool]:
    """Truncate *text* at the last paragraph break before *max_chars*.

    Returns ``(text, was_truncated)``.
    """
    if len(text) <= max_chars:
        return text, False

    # Try to break at a paragraph boundary (double newline).
    candidate = text[:max_chars]
    last_para = candidate.rfind("\n\n")
    if last_para > max_chars // 4:
        return candidate[:last_para].rstrip(), True

    # Fall back to last sentence-ending punctuation.
    last_sentence = max(candidate.rfind(". "), candidate.rfind(".\n"))
    if last_sentence > max_chars // 4:
        return candidate[: last_sentence + 1].rstrip(), True

    # Hard cut as last resort.
    return candidate.rstrip(), True


def _bs4_fallback(html: str) -> Optional[str]:
    """Fallback text extraction via BeautifulSoup with boilerplate removal."""
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(_BOILERPLATE_TAGS):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text if text else None
    except Exception:  # noqa: BLE001
        return None
