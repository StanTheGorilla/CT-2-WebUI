import pytest
from unittest.mock import AsyncMock, MagicMock
from ct1.core.orchestrator import Orchestrator

@pytest.fixture
def mock_orch():
    """Build an Orchestrator with all dependencies mocked."""
    orch = object.__new__(Orchestrator)
    orch.max_rounds = 3
    orch.confidence_threshold = 0.8

    orch.brain = MagicMock()
    orch.brain.lessons = []
    orch.brain.frame_problem = AsyncMock(return_value="framed question")
    orch.brain.detect_tension = AsyncMock(return_value={
        "agreement": True,
        "tension_description": "",
        "followup_question": "",
        "confidence": 0.9
    })
    orch.brain.synthesize = AsyncMock(return_value="final answer")
    orch.brain.reflect = AsyncMock(return_value={
        "goal": "test", "rounds": 1,
        "mind_contributions": {},
        "outcome": "final answer",
        "lesson": "test lesson",
        "self_score": 0.85
    })

    orch.minds = {
        "alpha": MagicMock(think=AsyncMock(return_value="alpha response")),
        "beta":  MagicMock(think=AsyncMock(return_value="beta response")),
        "gamma": MagicMock(think=AsyncMock(return_value="gamma response")),
    }

    from ct1.core.message_bus import MessageBus
    orch.bus = MessageBus()

    from ct1.core.tension_detector import TensionDetector
    orch.tension_detector = TensionDetector()

    orch.journal = MagicMock()
    orch.journal.write = MagicMock()

    orch.journal_reader = MagicMock()
    orch.journal_reader.get_recent_lessons = MagicMock(return_value=[])

    return orch

@pytest.mark.asyncio
async def test_deliberate_returns_response(mock_orch):
    result = await mock_orch._deliberate("test question")
    assert result["response"] == "final answer"
    assert result["rounds"] == 1

@pytest.mark.asyncio
async def test_deliberate_calls_all_minds(mock_orch):
    await mock_orch._deliberate("test question")
    mock_orch.minds["alpha"].think.assert_called_once()
    mock_orch.minds["beta"].think.assert_called_once()
    mock_orch.minds["gamma"].think.assert_called_once()

@pytest.mark.asyncio
async def test_deliberate_writes_journal(mock_orch):
    await mock_orch._deliberate("test question")
    mock_orch.journal.write.assert_called_once()

@pytest.mark.asyncio
async def test_deliberate_multiple_rounds_when_tension(mock_orch):
    # First call: tension detected (confidence low, no agreement)
    # Second call: agreement (confidence high)
    mock_orch.brain.detect_tension = AsyncMock(side_effect=[
        {"agreement": False, "tension_description": "disagreement",
         "followup_question": "clarify?", "confidence": 0.3},
        {"agreement": True, "tension_description": "",
         "followup_question": "", "confidence": 0.9},
    ])
    result = await mock_orch._deliberate("test question")
    assert result["rounds"] == 2
    assert result["tension_detected"] == True
