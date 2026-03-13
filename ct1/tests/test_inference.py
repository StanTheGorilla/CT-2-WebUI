import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from ct1.core.mind import Mind

def test_mind_init():
    mind = Mind("alpha", base_url="http://localhost:8080", temperature=0.9)
    assert mind.name == "alpha"
    assert mind.temperature == 0.9

@pytest.mark.asyncio
async def test_mind_returns_parsed_response_with_thinking():
    mind = Mind("alpha", base_url="http://localhost:8080", temperature=0.9, enable_thinking=True)
    raw_content = "<think>\nStep 1: Analyze.\n</think>\n\nThe answer is 42."
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"choices": [{"message": {"content": raw_content}}]}
    mock_response.raise_for_status = MagicMock()

    with patch.object(mind.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await mind.think("What is the meaning?")
    assert result["conclusion"] == "The answer is 42."
    assert result["reasoning"] == "Step 1: Analyze."
    await mind.close()

@pytest.mark.asyncio
async def test_mind_with_complexity():
    mind = Mind("beta", base_url="http://localhost:8080", temperature=0.3, enable_thinking=True)
    raw_content = "Simple answer."
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"choices": [{"message": {"content": raw_content}}]}
    mock_response.raise_for_status = MagicMock()

    with patch.object(mind.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await mind.think("2+2?", complexity="brief")
    call_args = mock_post.call_args
    payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
    system_msg = payload["messages"][0]["content"]
    assert "concisely" in system_msg.lower()
    await mind.close()

@pytest.mark.asyncio
async def test_mind_thinking_disabled_returns_parsed():
    mind = Mind("gamma", base_url="http://localhost:8080", temperature=1.1, enable_thinking=False)
    raw_content = "Plain answer no thinking."
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"choices": [{"message": {"content": raw_content}}]}
    mock_response.raise_for_status = MagicMock()

    with patch.object(mind.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await mind.think("test")
    assert result["conclusion"] == "Plain answer no thinking."
    assert result["reasoning"] == ""
    await mind.close()
