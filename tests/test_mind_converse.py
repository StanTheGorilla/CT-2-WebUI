import pytest
from unittest.mock import MagicMock
from ct1.core.mind import Mind

def make_mind(name="alpha"):
    return Mind(name, "http://localhost:8080", temperature=0.9)

def fake_response(content: str):
    mock = MagicMock()
    mock.is_success = True
    mock.json.return_value = {"choices": [{"message": {"content": content}}]}
    return mock

@pytest.mark.asyncio
async def test_converse_empty_dialogue_just_gets_brief():
    mind = make_mind()
    captured = {}

    async def fake_post(url, json=None, **kwargs):
        captured["messages"] = json["messages"]
        return fake_response("I think we should use flexbox")

    mind.client.post = fake_post
    result = await mind.converse("We need to build a dark site.", dialogue=[])
    assert isinstance(result, str)
    assert len(result) > 0
    # system + user only, no dialogue injected
    assert len(captured["messages"]) == 2

@pytest.mark.asyncio
async def test_converse_injects_prior_dialogue():
    mind = make_mind("beta")
    captured = {}
    dialogue = [
        {"mind": "alpha", "round": 1, "text": "Use a dark background and flexbox"},
    ]

    async def fake_post(url, json=None, **kwargs):
        captured["messages"] = json["messages"]
        return fake_response("I disagree with alpha on flexbox")

    mind.client.post = fake_post
    await mind.converse("Build a dark site.", dialogue=dialogue)

    user_content = captured["messages"][-1]["content"]
    assert "alpha" in user_content
    assert "flexbox" in user_content

@pytest.mark.asyncio
async def test_converse_injects_conversation_history():
    mind = make_mind()
    captured = {}
    conversation = [
        {"role": "user", "content": "prior user turn"},
        {"role": "assistant", "content": "prior response"},
    ]

    async def fake_post(url, json=None, **kwargs):
        captured["messages"] = json["messages"]
        return fake_response("ok")

    mind.client.post = fake_post
    await mind.converse("brief", dialogue=[], conversation=conversation)

    roles = [m["role"] for m in captured["messages"]]
    assert roles[0] == "system"
    assert "user" in roles[1:]
    assert "assistant" in roles[1:]

@pytest.mark.asyncio
async def test_converse_returns_plain_string_not_dict():
    mind = make_mind()

    async def fake_post(url, json=None, **kwargs):
        return fake_response("<think>thinking</think>my actual response")

    mind.client.post = fake_post
    result = await mind.converse("brief", dialogue=[])
    # Must be a plain string (thinking stripped)
    assert isinstance(result, str)
    assert "<think>" not in result
