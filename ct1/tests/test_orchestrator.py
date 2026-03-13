import pytest
from unittest.mock import AsyncMock, MagicMock
from ct1.core.orchestrator import Orchestrator

@pytest.fixture
def mock_orch():
    orch = object.__new__(Orchestrator)
    orch.max_rounds = 3
    orch.confidence_threshold = 0.8
    orch.verbose = False

    orch.brain = MagicMock()
    orch.brain.lessons = []
    orch.brain.frame_problem = AsyncMock(return_value={
        "question": "framed question",
        "complexity": "moderate"
    })
    orch.brain.detect_tension = AsyncMock(return_value={
        "agreement": True,
        "tension_description": "",
        "followup_question": "",
        "confidence": 0.9,
        "strongest_voice": "alpha"
    })
    orch.brain.synthesize = AsyncMock(return_value="final answer")
    orch.brain.reflect = AsyncMock(return_value={
        "goal": "test", "complexity": "moderate", "rounds": 1,
        "mind_contributions": {},
        "outcome": "final answer",
        "lesson": "test lesson",
        "complexity_correct": True,
        "self_score": 0.85
    })

    orch.minds = {
        "alpha": MagicMock(think=AsyncMock(return_value={"reasoning": "thought A", "conclusion": "answer A"})),
        "beta":  MagicMock(think=AsyncMock(return_value={"reasoning": "thought B", "conclusion": "answer B"})),
        "gamma": MagicMock(think=AsyncMock(return_value={"reasoning": "thought C", "conclusion": "answer C"})),
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
async def test_deliberate_passes_complexity_to_minds(mock_orch):
    await mock_orch._deliberate("test question")
    mock_orch.minds["alpha"].think.assert_called_once()
    call_args = mock_orch.minds["alpha"].think.call_args
    # complexity should be passed as keyword argument
    assert call_args.kwargs.get("complexity") == "moderate"

@pytest.mark.asyncio
async def test_deliberate_stores_reasoning_in_rounds(mock_orch):
    result = await mock_orch._deliberate("test question")
    rounds_data = result["rounds_data"]
    assert rounds_data[0]["responses"]["alpha"]["reasoning"] == "thought A"
    assert rounds_data[0]["responses"]["alpha"]["conclusion"] == "answer A"

@pytest.mark.asyncio
async def test_deliberate_returns_complexity(mock_orch):
    result = await mock_orch._deliberate("test question")
    assert result["complexity"] == "moderate"

@pytest.mark.asyncio
async def test_deliberate_multiple_rounds_when_tension(mock_orch):
    mock_orch.brain.detect_tension = AsyncMock(side_effect=[
        {"agreement": False, "tension_description": "disagreement",
         "followup_question": "clarify?", "confidence": 0.3, "strongest_voice": "beta"},
        {"agreement": True, "tension_description": "",
         "followup_question": "", "confidence": 0.9, "strongest_voice": "alpha"},
    ])
    result = await mock_orch._deliberate("test question")
    assert result["rounds"] == 2
    assert result["tension_detected"] == True

@pytest.mark.asyncio
async def test_deliberate_writes_journal(mock_orch):
    await mock_orch._deliberate("test question")
    mock_orch.journal.write.assert_called_once()

@pytest.mark.asyncio
async def test_deliberate_passes_complexity_to_reflect(mock_orch):
    await mock_orch._deliberate("test question")
    mock_orch.brain.reflect.assert_called_once()
    call_args = mock_orch.brain.reflect.call_args[0]
    # reflect(goal, complexity, rounds, outcome)
    assert call_args[1] == "moderate"
