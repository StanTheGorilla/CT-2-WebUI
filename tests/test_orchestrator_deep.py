import pytest
from unittest.mock import AsyncMock, MagicMock
from ct1.core.orchestrator import Orchestrator

def make_orchestrator():
    orch = Orchestrator.__new__(Orchestrator)
    orch.max_rounds = 999
    orch.confidence_threshold = 0.8
    orch.verbose = False
    orch.bus = MagicMock()
    orch.bus.clear = MagicMock()
    orch.bus.post = MagicMock()
    orch.bus.to_dict_list = MagicMock(return_value=[])
    orch.journal = MagicMock()
    orch.journal.write = MagicMock()
    orch.tension_detector = MagicMock()

    orch.brain = AsyncMock()
    orch.brain.extract_intent = AsyncMock(return_value={
        "task_type": "question",
        "what_to_produce": "an answer about consciousness",
        "requirements": [],
        "complexity": "moderate",
    })
    orch.brain.write_deliberation_brief = MagicMock(return_value="We need to answer: what is consciousness?")
    orch.brain.check_convergence = AsyncMock(return_value={
        "ready_to_execute": True,
        "reason": "all agree",
        "agreed_approach": "emergentist view",
    })
    orch.brain.synthesize = AsyncMock(return_value="Consciousness is emergent.")
    orch.brain.reflect = AsyncMock(return_value={"lesson": "test", "self_score": 0.9})

    alpha = AsyncMock()
    beta = AsyncMock()
    gamma = AsyncMock()
    for m in (alpha, beta, gamma):
        m.converse = AsyncMock(return_value="some perspective")
    orch.minds = {"alpha": alpha, "beta": beta, "gamma": gamma}

    return orch

@pytest.mark.asyncio
async def test_three_phase_pipeline_calls_extract_intent():
    orch = make_orchestrator()
    result = await orch._deliberate("what is consciousness?")
    orch.brain.extract_intent.assert_called_once()

@pytest.mark.asyncio
async def test_three_phase_pipeline_calls_all_minds_converse():
    orch = make_orchestrator()
    await orch._deliberate("what is consciousness?")
    orch.minds["alpha"].converse.assert_called()
    orch.minds["beta"].converse.assert_called()
    orch.minds["gamma"].converse.assert_called()

@pytest.mark.asyncio
async def test_three_phase_pipeline_calls_synthesize():
    orch = make_orchestrator()
    result = await orch._deliberate("what is consciousness?")
    orch.brain.synthesize.assert_called_once()
    assert result["response"] == "Consciousness is emergent."

@pytest.mark.asyncio
async def test_three_phase_stops_after_one_round_when_convergence_immediate():
    orch = make_orchestrator()
    result = await orch._deliberate("test")
    # check_convergence returns True immediately, so only 1 round
    assert result["rounds"] == 1

@pytest.mark.asyncio
async def test_three_phase_runs_multiple_rounds_until_convergence():
    orch = make_orchestrator()
    # First two checks: not ready. Third: ready.
    orch.brain.check_convergence = AsyncMock(side_effect=[
        {"ready_to_execute": False, "reason": "still debating", "agreed_approach": ""},
        {"ready_to_execute": False, "reason": "still debating", "agreed_approach": ""},
        {"ready_to_execute": True,  "reason": "agreed",         "agreed_approach": "plan X"},
    ])
    result = await orch._deliberate("build something")
    assert result["rounds"] == 3
