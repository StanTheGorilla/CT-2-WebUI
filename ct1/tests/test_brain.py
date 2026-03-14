import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from ct1.core.brain import Brain

@pytest.mark.asyncio
async def test_frame_problem_returns_structured():
    brain = Brain(base_url="http://localhost:8080")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": '{"question": "What is the boiling point of water?", "complexity": "deep"}'}}]
    }
    with patch.object(brain.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await brain.frame_problem("Explain consciousness")
    assert result["question"] == "What is the boiling point of water?"
    assert result["complexity"] == "deep"
    await brain.close()

@pytest.mark.asyncio
async def test_frame_problem_fallback_on_bad_json():
    brain = Brain(base_url="http://localhost:8080")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Just a plain text reframe"}}]
    }
    with patch.object(brain.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await brain.frame_problem("simple question")
    assert result["question"] == "simple question"
    assert result["complexity"] == "moderate"
    await brain.close()

@pytest.mark.asyncio
async def test_detect_tension_includes_strongest_voice():
    brain = Brain(base_url="http://localhost:8080")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": '{"agreement": true, "tension_description": "", "followup_question": "", "confidence": 0.9, "strongest_voice": "beta"}'}}]
    }
    with patch.object(brain.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await brain.detect_tension("goal", "a", "b", "c")
    assert result["strongest_voice"] == "beta"
    await brain.close()

@pytest.mark.asyncio
async def test_reflect_includes_complexity():
    brain = Brain(base_url="http://localhost:8080")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": '{"goal": "test", "complexity": "deep", "rounds": 1, "mind_contributions": {}, "outcome": "x", "lesson": "y", "complexity_correct": true, "self_score": 0.8}'}}]
    }
    with patch.object(brain.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await brain.reflect("test", "deep", 1, "outcome")
    assert result["complexity"] == "deep"
    assert result["complexity_correct"] == True
    await brain.close()

# --- Conversation injection tests ---

CONV = [
    {"role": "user", "content": "prior turn"},
    {"role": "assistant", "content": "prior reply"},
]

@pytest.mark.asyncio
async def test_frame_problem_conversation_injection():
    brain = Brain(base_url="http://localhost:8080")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": '{"question": "reframed?", "complexity": "moderate"}'}}]
    }
    with patch.object(brain.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        await brain.frame_problem("some goal", conversation=CONV)
    messages = mock_post.call_args[1]["json"]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "user", "content": "prior turn"}
    assert messages[2] == {"role": "assistant", "content": "prior reply"}
    assert messages[-1]["role"] == "user"
    assert messages[-1] != messages[1]
    await brain.close()

@pytest.mark.asyncio
async def test_detect_tension_conversation_injection():
    brain = Brain(base_url="http://localhost:8080")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": '{"agreement": true, "tension_description": "", "followup_question": "", "confidence": 0.9, "strongest_voice": "alpha"}'}}]
    }
    with patch.object(brain.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        await brain.detect_tension("goal", "a", "b", "c", conversation=CONV)
    messages = mock_post.call_args[1]["json"]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "user", "content": "prior turn"}
    assert messages[2] == {"role": "assistant", "content": "prior reply"}
    assert messages[-1]["role"] == "user"
    assert messages[-1] != messages[1]
    await brain.close()

@pytest.mark.asyncio
async def test_reflect_conversation_injection():
    brain = Brain(base_url="http://localhost:8080")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": '{"goal": "g", "complexity": "brief", "rounds": 1, "mind_contributions": {}, "outcome": "o", "lesson": "l", "complexity_correct": true, "self_score": 0.7}'}}]
    }
    with patch.object(brain.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        await brain.reflect("g", "brief", 1, "outcome", conversation=CONV)
    messages = mock_post.call_args[1]["json"]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "user", "content": "prior turn"}
    assert messages[2] == {"role": "assistant", "content": "prior reply"}
    assert messages[-1]["role"] == "user"
    assert messages[-1] != messages[1]
    await brain.close()
