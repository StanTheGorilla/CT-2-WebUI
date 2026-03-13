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
async def test_call_injects_conversation_between_system_and_user():
    brain = make_brain()
    conversation = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
    ]
    captured = {}

    async def fake_post(url, json=None, **kwargs):
        captured["messages"] = json["messages"]
        return fake_response("ok")

    brain.client.post = fake_post
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "current question"},
    ]
    await brain._call(messages, conversation=conversation)

    msgs = captured["messages"]
    assert msgs[0]["role"] == "system"
    assert msgs[1] == {"role": "user", "content": "Hello"}
    assert msgs[2] == {"role": "assistant", "content": "Hi there"}
    assert msgs[3] == {"role": "user", "content": "current question"}

@pytest.mark.asyncio
async def test_call_no_conversation_unchanged():
    brain = make_brain()
    captured = {}

    async def fake_post(url, json=None, **kwargs):
        captured["messages"] = json["messages"]
        return fake_response("ok")

    brain.client.post = fake_post
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q"},
    ]
    await brain._call(messages)
    assert captured["messages"] == messages

@pytest.mark.asyncio
async def test_summarize_session_returns_string():
    brain = make_brain()
    conversation = [
        {"role": "user", "content": "Who was Einstein?"},
        {"role": "assistant", "content": "Albert Einstein was a physicist."},
    ]

    async def fake_post(url, json=None, **kwargs):
        return fake_response("We discussed Albert Einstein and his contributions to physics.")

    brain.client.post = fake_post
    result = await brain.summarize_session(conversation)
    assert isinstance(result, str)
    assert len(result) > 0

@pytest.mark.asyncio
async def test_summarize_session_empty_returns_none():
    brain = make_brain()
    result = await brain.summarize_session([])
    assert result is None
