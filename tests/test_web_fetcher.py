"""Tests for ct2.core.web_fetcher."""

import pytest

from ct2.core.web_fetcher import (
    FetchResult,
    _extract_domain,
    _truncate_content,
    extract_urls,
    fetch_url,
)


# ---------------------------------------------------------------------------
# _extract_domain
# ---------------------------------------------------------------------------

class TestExtractDomain:
    def test_simple(self):
        assert _extract_domain("https://example.com/page") == "example.com"

    def test_with_port(self):
        assert _extract_domain("http://localhost:8080/api") == "localhost:8080"

    def test_with_subdomain(self):
        assert _extract_domain("https://docs.python.org/3/library/") == "docs.python.org"

    def test_bare_domain(self):
        assert _extract_domain("https://example.com") == "example.com"


# ---------------------------------------------------------------------------
# FetchResult
# ---------------------------------------------------------------------------

class TestFetchResult:
    def test_success(self):
        r = FetchResult(
            url="https://example.com",
            title="Example",
            content="Hello world",
            content_length=11,
            truncated=False,
        )
        assert r.url == "https://example.com"
        assert r.title == "Example"
        assert r.content == "Hello world"
        assert r.content_length == 11
        assert r.truncated is False
        assert r.error is None

    def test_error(self):
        r = FetchResult(url="ftp://bad", error="Invalid URL scheme")
        assert r.error == "Invalid URL scheme"
        assert r.content is None
        assert r.content_length == 0


# ---------------------------------------------------------------------------
# extract_urls
# ---------------------------------------------------------------------------

class TestExtractUrls:
    def test_basic(self):
        text = "Check https://example.com and http://foo.bar/page"
        urls = extract_urls(text)
        assert urls == ["https://example.com", "http://foo.bar/page"]

    def test_deduplication(self):
        text = "https://a.com https://a.com https://a.com"
        assert extract_urls(text) == ["https://a.com"]

    def test_max_cap(self):
        text = "https://a.com https://b.com https://c.com https://d.com https://e.com"
        assert len(extract_urls(text)) == 3

    def test_trailing_punctuation_stripped(self):
        text = "Visit https://example.com. Also https://foo.com, and https://bar.com!"
        urls = extract_urls(text)
        assert "https://example.com" in urls
        assert "https://foo.com" in urls
        assert "https://bar.com" in urls

    def test_multimodal_input(self):
        content = [
            {"type": "text", "text": "Look at https://a.com"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            {"type": "text", "text": "and https://b.com"},
        ]
        urls = extract_urls(content)
        assert urls == ["https://a.com", "https://b.com"]

    def test_empty_string(self):
        assert extract_urls("") == []

    def test_no_urls(self):
        assert extract_urls("just plain text, no links here") == []


# ---------------------------------------------------------------------------
# _truncate_content
# ---------------------------------------------------------------------------

class TestTruncateContent:
    def test_short_no_truncation(self):
        text = "Short text."
        result, truncated = _truncate_content(text, 1000)
        assert result == "Short text."
        assert truncated is False

    def test_long_truncated_at_paragraph(self):
        para1 = "A" * 100
        para2 = "B" * 100
        para3 = "C" * 100
        text = f"{para1}\n\n{para2}\n\n{para3}"
        # max_chars set so it cuts somewhere in para3
        result, truncated = _truncate_content(text, 250)
        assert truncated is True
        assert result.endswith(para2)
        assert para3 not in result

    def test_exact_limit(self):
        text = "X" * 500
        result, truncated = _truncate_content(text, 500)
        assert truncated is False
        assert result == text


# ---------------------------------------------------------------------------
# fetch_url – error paths (no network required)
# ---------------------------------------------------------------------------

class TestFetchUrlErrors:
    async def test_invalid_scheme(self):
        result = await fetch_url("ftp://example.com/file")
        assert result.error is not None
        assert "scheme" in result.error.lower()

    async def test_no_host(self):
        result = await fetch_url("http://")
        assert result.error is not None

    async def test_unreachable_host(self):
        # RFC-5737 TEST-NET address – guaranteed unroutable.
        result = await fetch_url("http://192.0.2.1:1/page", max_chars=100)
        assert result.error is not None


# ---------------------------------------------------------------------------
# Integration tests – require network
# ---------------------------------------------------------------------------

class TestIntegration:
    async def test_fetch_real_page(self):
        """Fetch example.com — a stable, fast page with known content."""
        result = await fetch_url("https://example.com", max_chars=5000)
        if result.error and "SSL" in result.error:
            pytest.skip("SSL certificates not configured in this environment")
        assert result.error is None
        assert result.title  # example.com has a <title>
        assert len(result.content) > 50
        assert "example" in result.content.lower()

    async def test_fetch_with_truncation(self):
        """Fetch a large Wikipedia page and verify truncation."""
        result = await fetch_url(
            "https://en.wikipedia.org/wiki/Python_(programming_language)",
            max_chars=2000,
        )
        if result.error is None:
            assert result.content_length > 2000
            assert result.truncated is True
