import pytest
from unittest.mock import MagicMock
from ct1.core.brain import Brain

def make_brain():
    return Brain(base_url="http://localhost:8080")

def fake_response(content: str):
    mock = MagicMock()
    mock.is_success = True
    mock.json.return_value = {"choices": [{"message": {"content": content}}]}
    return mock

@pytest.mark.asyncio
async def test_extract_intent_code_task():
    brain = make_brain()

    async def fake_post(url, json=None, **kwargs):
        return fake_response('{"task_type": "code", "what_to_produce": "a complete HTML website", "requirements": ["dark theme"], "complexity": "moderate"}')

    brain.client.post = fake_post
    result = await brain.extract_intent("create a dark themed HTML site")
    assert result["task_type"] == "code"
    assert "html" in result["what_to_produce"].lower()
    assert result["complexity"] == "moderate"

@pytest.mark.asyncio
async def test_extract_intent_question_task():
    brain = make_brain()

    async def fake_post(url, json=None, **kwargs):
        return fake_response('{"task_type": "question", "what_to_produce": "a direct answer explaining what consciousness is", "requirements": [], "complexity": "deep"}')

    brain.client.post = fake_post
    result = await brain.extract_intent("what is consciousness?")
    assert result["task_type"] == "question"
    assert result["complexity"] == "deep"

@pytest.mark.asyncio
async def test_extract_intent_fallback_on_bad_json():
    brain = make_brain()

    async def fake_post(url, json=None, **kwargs):
        return fake_response("not json at all")

    brain.client.post = fake_post
    result = await brain.extract_intent("do something")
    assert "task_type" in result
    assert "what_to_produce" in result
    assert result["complexity"] in ("brief", "moderate", "deep")
