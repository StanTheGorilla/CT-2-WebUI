import pytest
from unittest.mock import MagicMock
from ct1.core.mind import Mind

def make_mind():
    return Mind("alpha", "http://localhost:8080", temperature=0.9)

def fake_response(content: str):
    mock = MagicMock()
    mock.is_success = True
    mock.json.return_value = {"choices": [{"message": {"content": content}}]}
    return mock

@pytest.mark.asyncio
async def test_think_injects_conversation_before_current_message():
    mind = make_mind()
    conversation = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello"},
    ]
    captured = {}

    async def fake_post(url, json=None, **kwargs):
        captured["messages"] = json["messages"]
        return fake_response("<think>ok</think>answer")

    mind.client.post = fake_post
    await mind.think("What is X?", conversation=conversation)

    msgs = captured["messages"]
    assert msgs[0]["role"] == "system"
    assert msgs[1] == {"role": "user", "content": "Hi"}
    assert msgs[2] == {"role": "assistant", "content": "Hello"}
    assert msgs[-1]["role"] == "user"
    assert "What is X?" in msgs[-1]["content"]

@pytest.mark.asyncio
async def test_think_no_conversation_only_system_and_user():
    mind = make_mind()
    captured = {}

    async def fake_post(url, json=None, **kwargs):
        captured["messages"] = json["messages"]
        return fake_response("answer")

    mind.client.post = fake_post
    await mind.think("Question?")
    assert len(captured["messages"]) == 2
    assert captured["messages"][0]["role"] == "system"
    assert captured["messages"][1]["role"] == "user"

@pytest.mark.asyncio
async def test_think_prior_voices_injected_into_user_content():
    mind = make_mind()
    captured = {}

    async def fake_post(url, json=None, **kwargs):
        captured["messages"] = json["messages"]
        return fake_response("answer")

    mind.client.post = fake_post
    await mind.think("What should we do?", prior_voices="alpha said: use flexbox")

    user_content = captured["messages"][-1]["content"]
    assert "alpha said: use flexbox" in user_content
    assert "What should we do?" in user_content
