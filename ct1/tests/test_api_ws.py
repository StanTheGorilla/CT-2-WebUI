import pytest
from unittest.mock import MagicMock
import ct1.server.api as api_mod


@pytest.fixture(autouse=True)
def mock_orchestrator(monkeypatch):
    """Mock the orchestrator so we don't need llama-server running."""
    async def fake_think(goal, on_event=None, conversation=None):
        if on_event:
            on_event("framing")
            on_event("framed", text="test output", complexity="brief")
            on_event("synthesizing")
        return {
            "response": "test response",
            "rounds": 1,
            "complexity": "brief",
            "tension_detected": False,
            "reflection": {"self_score": 0.8, "lesson": "test"},
            "dialogue": [],
            "bus_history": [],
        }

    mock_orch = MagicMock()
    mock_orch.think = fake_think
    monkeypatch.setattr(api_mod, "_orch", mock_orch)


def test_websocket_think():
    """Test that WebSocket /ws/think streams events and returns done."""
    from starlette.testclient import TestClient
    from ct1.server.api import app

    client = TestClient(app)
    with client.websocket_connect("/ws/think") as ws:
        ws.send_json({"type": "think", "goal": "test", "conversation": []})
        events = []
        while True:
            data = ws.receive_json()
            events.append(data)
            if data["event"] == "done":
                break

    event_types = [e["event"] for e in events]
    assert "framing" in event_types
    assert "framed" in event_types
    assert "synthesizing" in event_types
    assert "done" in event_types
    assert events[-1]["response"] == "test response"
