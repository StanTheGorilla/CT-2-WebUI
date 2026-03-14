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

def test_write_deliberation_brief_contains_what_to_produce():
    brain = make_brain()
    intent = {
        "task_type": "code",
        "what_to_produce": "a complete dark-themed HTML restaurant website",
        "requirements": ["dark background", "show menu items"],
        "complexity": "moderate",
    }
    brief = brain.write_deliberation_brief(intent)
    assert "dark-themed HTML restaurant website" in brief
    assert "dark background" in brief
    assert "menu items" in brief

@pytest.mark.asyncio
async def test_check_convergence_ready():
    brain = make_brain()
    dialogue = [
        {"mind": "alpha", "round": 1, "text": "We should use flexbox for layout"},
        {"mind": "beta",  "round": 1, "text": "Agreed on flexbox, dark bg #1a1a1a"},
        {"mind": "gamma", "round": 1, "text": "Yes, flexbox and #1a1a1a. Use system fonts."},
    ]

    async def fake_post(url, json=None, **kwargs):
        return fake_response('{"ready_to_execute": true, "reason": "all agree on approach", "agreed_approach": "flexbox layout, dark #1a1a1a background, system fonts"}')

    brain.client.post = fake_post
    result = await brain.check_convergence("build a dark site", dialogue)
    assert result["ready_to_execute"] is True
    assert "agreed_approach" in result

@pytest.mark.asyncio
async def test_check_convergence_not_ready():
    brain = make_brain()
    dialogue = [
        {"mind": "alpha", "round": 1, "text": "Use a carousel"},
        {"mind": "beta",  "round": 1, "text": "No carousel, just a grid"},
    ]

    async def fake_post(url, json=None, **kwargs):
        return fake_response('{"ready_to_execute": false, "reason": "alpha and beta disagree on layout", "agreed_approach": ""}')

    brain.client.post = fake_post
    result = await brain.check_convergence("build a site", dialogue)
    assert result["ready_to_execute"] is False

@pytest.mark.asyncio
async def test_check_convergence_fallback_on_bad_json():
    brain = make_brain()

    async def fake_post(url, json=None, **kwargs):
        return fake_response("not json")

    brain.client.post = fake_post
    # Should not raise — return a safe default
    result = await brain.check_convergence("task", [])
    assert "ready_to_execute" in result

@pytest.mark.asyncio
async def test_synthesize_code_task_forbids_placeholders_in_prompt():
    brain = make_brain()
    captured = {}

    async def fake_post(url, json=None, **kwargs):
        captured["messages"] = json["messages"]
        return fake_response("<!DOCTYPE html><html>...</html>")

    brain.client.post = fake_post
    intent = {"task_type": "code", "what_to_produce": "a dark HTML site", "requirements": [], "complexity": "moderate"}
    dialogue = [{"mind": "alpha", "round": 1, "text": "Use dark bg and flexbox"}]
    await brain.synthesize("build me a dark HTML site", intent, dialogue)

    # The prompt sent to the LLM must contain the anti-placeholder rules
    user_prompt = captured["messages"][-1]["content"]
    assert "No placeholders" in user_prompt or "placeholder" in user_prompt.lower()
    assert "complete" in user_prompt.lower()

@pytest.mark.asyncio
async def test_synthesize_question_task_uses_answer_prompt():
    brain = make_brain()
    captured = {}

    async def fake_post(url, json=None, **kwargs):
        captured["messages"] = json["messages"]
        return fake_response("The answer is 42.")

    brain.client.post = fake_post
    intent = {"task_type": "question", "what_to_produce": "answer to question", "requirements": [], "complexity": "brief"}
    dialogue = [{"mind": "alpha", "round": 1, "text": "The answer is 42"}]
    result = await brain.synthesize("what is the answer?", intent, dialogue)
    assert result == "The answer is 42."

    user_prompt = captured["messages"][-1]["content"]
    # Should not have the code-specific rules
    assert "No placeholders" not in user_prompt
