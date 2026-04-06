"""Test that _call_stream falls back to thinking as text when content is empty."""
import json
import pytest
from unittest.mock import MagicMock, AsyncMock
from ct1.core.engine import Engine


def _make_engine():
    engine = Engine.__new__(Engine)
    engine.thinking_budget = -1
    engine.vision_supported = True
    engine.context_size = 4096
    engine.temperature = 0.7
    engine.top_p = 0.9
    engine.top_k = 40
    engine.presence_penalty = 0.0
    engine.frequency_penalty = 0.0
    engine.max_tokens = 512
    engine.base_url = "http://localhost:8080"
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
