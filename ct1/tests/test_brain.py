import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from ct1.core.brain import Brain

@pytest.mark.asyncio
async def test_frame_problem_returns_structured():
    brain = Brain(base_url="http://localhost:8080")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": '{"question": "What is X?", "complexity": "deep"}'}}]
    }
    with patch.object(brain.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await brain.frame_problem("Explain consciousness")
    assert result["question"] == "What is X?"
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
    assert result["question"] == "Just a plain text reframe"
    assert result["complexity"] == "moderate"
    await brain.close()

@pytest.mark.asyncio
async def test_synthesize_uses_evidence():
    brain = Brain(base_url="http://localhost:8080")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Synthesized answer."}}]
    }
    rounds_data = [{
        "round": 1,
        "question": "framed Q",
        "responses": {
            "alpha": {"reasoning": "chain A", "conclusion": "answer A"},
            "beta":  {"reasoning": "chain B", "conclusion": "answer B"},
            "gamma": {"reasoning": "chain C", "conclusion": "answer C"},
        }
    }]
    tension_summary = "All three perspectives converge."
    with patch.object(brain.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await brain.synthesize("original goal", rounds_data, tension_summary)
    call_payload = mock_post.call_args[1]["json"]
    user_msg = call_payload["messages"][1]["content"]
    assert "answer A" in user_msg
    assert "answer B" in user_msg
    assert "answer C" in user_msg
    assert result == "Synthesized answer."
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
