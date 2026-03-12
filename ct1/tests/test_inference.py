import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from ct1.core.mind import Mind

def test_mind_init():
    mind = Mind("alpha", base_url="http://localhost:8080", temperature=0.9)
    assert mind.name == "alpha"
    assert mind.temperature == 0.9

@pytest.mark.asyncio
async def test_mind_returns_text_on_200():
    mind = Mind("alpha", base_url="http://localhost:8080", temperature=0.9)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"choices": [{"message": {"content": "Time is relative."}}]}
    mock_response.raise_for_status = MagicMock()

    with patch.object(mind.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await mind.think("What is time?")
    assert result == "Time is relative."
    await mind.close()
