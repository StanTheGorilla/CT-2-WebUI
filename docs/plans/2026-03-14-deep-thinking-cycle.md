# Deep Thinking Cycle Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace CT-1's single-phase deliberation loop with a 3-phase pipeline (intent extraction → free-form dialogue → dedicated execution) so the system produces the actual artifact requested instead of meta-commentary about it.

**Architecture:** Phase 1 — Brain classifies the task and extracts what must be produced. Phase 2 — Three minds hold a free-form dialogue (each sees all prior turns) until Brain judges the plan solid. Phase 3 — Brain executes with a task-type-specific prompt that produces the real output.

**Tech Stack:** Python 3.10, httpx async, llama-server OpenAI-compatible API, pytest + pytest-asyncio

**Design doc:** `docs/plans/2026-03-14-deep-thinking-cycle-design.md`

---

## Task 1: `brain.extract_intent()` — classify what the task requires

**Files:**
- Modify: `ct1/core/brain.py`
- Create: `tests/test_brain_deep.py`

**Step 1: Write the failing test**

Create `tests/test_brain_deep.py`:

```python
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
```

**Step 2: Run to verify failure**

```bash
cd F:/AI_Workstation/ct
python -m pytest tests/test_brain_deep.py -v
```
Expected: `AttributeError: 'Brain' object has no attribute 'extract_intent'`

**Step 3: Add `extract_intent()` to `ct1/core/brain.py`**

Add this method after `frame_problem`:

```python
async def extract_intent(self, goal: str, conversation: list[dict] = None) -> dict:
    """Classify what the task requires and what must be produced.
    Returns {task_type, what_to_produce, requirements, complexity}.
    """
    system = "You are a precise task classifier. Output only valid JSON."
    prompt = f"""Analyze this task and classify it.

Task: {goal}

Respond as JSON only:
{{
  "task_type": "code" | "artifact" | "question" | "analysis",
  "what_to_produce": "one sentence describing the exact output expected",
  "requirements": ["key requirement 1", "key requirement 2"],
  "complexity": "brief" | "moderate" | "deep"
}}

Use "code" for any task asking for code, HTML, CSS, scripts, programs.
Use "artifact" for documents, designs, structured outputs.
Use "question" for factual or conceptual questions.
Use "analysis" for evaluation, comparison, review tasks."""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    raw = await self._call(messages, max_tokens=256, conversation=conversation)
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        parsed = json.loads(raw[start:end])
        if parsed.get("task_type") not in ("code", "artifact", "question", "analysis"):
            parsed["task_type"] = "question"
        if parsed.get("complexity") not in ("brief", "moderate", "deep"):
            parsed["complexity"] = "moderate"
        if not parsed.get("what_to_produce"):
            parsed["what_to_produce"] = goal
        return parsed
    except Exception:
        return {
            "task_type": "question",
            "what_to_produce": goal,
            "requirements": [],
            "complexity": "moderate",
        }
```

**Step 4: Run tests to verify pass**

```bash
python -m pytest tests/test_brain_deep.py::test_extract_intent_code_task tests/test_brain_deep.py::test_extract_intent_question_task tests/test_brain_deep.py::test_extract_intent_fallback_on_bad_json -v
```
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add ct1/core/brain.py tests/test_brain_deep.py
git commit -m "feat: brain.extract_intent — classify task type and what to produce"
```

---

## Task 2: `brain.check_convergence()` + `brain.write_deliberation_brief()`

**Files:**
- Modify: `ct1/core/brain.py`
- Modify: `tests/test_brain_deep.py`

**Step 1: Write the failing tests**

Append to `tests/test_brain_deep.py`:

```python
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
```

**Step 2: Run to verify failure**

```bash
python -m pytest tests/test_brain_deep.py -v -k "convergence or brief"
```
Expected: `AttributeError` — methods don't exist yet

**Step 3: Add `write_deliberation_brief()` and `check_convergence()` to `ct1/core/brain.py`**

Add both methods after `extract_intent`:

```python
def write_deliberation_brief(self, intent: dict) -> str:
    """Produce the brief handed to all minds at the start of deliberation."""
    what = intent.get("what_to_produce", "")
    reqs = intent.get("requirements", [])
    task_type = intent.get("task_type", "question")

    reqs_text = ""
    if reqs:
        reqs_text = "\nRequirements:\n" + "\n".join(f"- {r}" for r in reqs)

    execution_note = ""
    if task_type in ("code", "artifact"):
        execution_note = (
            "\n\nIMPORTANT: After deliberation, the brain will produce the final output. "
            "Your job is to decide HOW it should be built — approach, structure, key details. "
            "Not to build it yourselves."
        )

    return (
        f"We need to produce: {what}"
        f"{reqs_text}"
        f"\n\nDebate the best approach. Explore alternatives. "
        f"Identify risks and edge cases. Argue freely — agree, disagree, "
        f"change your mind, ask each other questions."
        f"{execution_note}"
    )

async def check_convergence(self, brief: str, dialogue: list[dict],
                             conversation: list[dict] = None) -> dict:
    """Ask brain if the dialogue has produced a solid enough plan to execute."""
    formatted = "\n\n".join(
        f"{t['mind']} (round {t['round']}): {t['text']}"
        for t in dialogue
    )
    prompt = f"""You are reviewing a deliberation between your inner voices.

Brief given to them:
{brief}

Their dialogue:
{formatted}

Is the plan solid enough to execute now?
Respond as JSON only:
{{
  "ready_to_execute": true,
  "reason": "brief reason",
  "agreed_approach": "1-2 sentence summary of what was decided"
}}"""
    messages = [
        {"role": "system", "content": self._system_prompt()},
        {"role": "user", "content": prompt},
    ]
    raw = await self._call(messages, max_tokens=256, conversation=conversation)
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        result = json.loads(raw[start:end])
        if "ready_to_execute" not in result:
            result["ready_to_execute"] = False
        return result
    except Exception:
        return {"ready_to_execute": False, "reason": "parse error", "agreed_approach": ""}
```

**Step 4: Run tests to verify pass**

```bash
python -m pytest tests/test_brain_deep.py -v
```
Expected: all PASSED

**Step 5: Commit**

```bash
git add ct1/core/brain.py tests/test_brain_deep.py
git commit -m "feat: brain.write_deliberation_brief and check_convergence for 3-phase loop"
```

---

## Task 3: `mind.converse()` — free-form dialogue turn

**Files:**
- Modify: `ct1/core/mind.py`
- Create: `tests/test_mind_converse.py`

**Step 1: Write the failing test**

Create `tests/test_mind_converse.py`:

```python
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
```

**Step 2: Run to verify failure**

```bash
python -m pytest tests/test_mind_converse.py -v
```
Expected: `AttributeError: 'Mind' object has no attribute 'converse'`

**Step 3: Add `converse()` to `ct1/core/mind.py`**

Add this method after `think()`:

```python
async def converse(self, brief: str, dialogue: list[dict],
                   conversation: list[dict] = None) -> str:
    """Contribute one turn to the free-form deliberation dialogue.

    brief: what the minds are deliberating about (from brain.write_deliberation_brief)
    dialogue: all prior turns [{mind, round, text}, ...]
    Returns a plain string — the mind's contribution.
    """
    if dialogue:
        turns_text = "\n\n".join(
            f"{t['mind']}: {t['text']}"
            for t in dialogue
        )
        user_content = (
            f"{brief}\n\n"
            f"Conversation so far:\n{turns_text}\n\n"
            f"You are {self.name}. Continue the conversation. "
            f"Be direct and specific. Engage with what was said."
        )
    else:
        user_content = (
            f"{brief}\n\n"
            f"You are {self.name}. You go first. Think freely."
        )

    messages = [{"role": "system", "content": self._build_system_prompt("moderate")}]
    if conversation:
        messages.extend(conversation)
    messages.append({"role": "user", "content": user_content})

    payload = {
        "model": "qwen",
        "messages": messages,
        "temperature": self.temperature,
        "top_p": self.top_p,
        "top_k": self.top_k,
        "presence_penalty": self.presence_penalty,
        "max_tokens": self.max_tokens,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": self.enable_thinking},
    }
    r = await self.client.post(f"{self.base_url}/v1/chat/completions", json=payload)
    r.raise_for_status()
    raw = r.json()["choices"][0]["message"]["content"].strip()
    parsed = parse_thinking_response(raw)
    # Return just the conclusion text (strip thinking block)
    return parsed.get("conclusion", raw)
```

**Step 4: Run tests to verify pass**

```bash
python -m pytest tests/test_mind_converse.py -v
```
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add ct1/core/mind.py tests/test_mind_converse.py
git commit -m "feat: mind.converse for free-form dialogue participation"
```

---

## Task 4: Update `brain.synthesize()` — task-type-aware execution prompt

**Files:**
- Modify: `ct1/core/brain.py`
- Modify: `tests/test_brain_deep.py`

**Step 1: Write the failing tests**

Append to `tests/test_brain_deep.py`:

```python
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
```

**Step 2: Run to verify failure**

```bash
python -m pytest tests/test_brain_deep.py::test_synthesize_code_task_forbids_placeholders_in_prompt tests/test_brain_deep.py::test_synthesize_question_task_uses_answer_prompt -v
```
Expected: FAIL — `synthesize()` still uses old signature

**Step 3: Replace `synthesize()` in `ct1/core/brain.py`**

Replace the entire `synthesize` method (keep `_extract_best_code` for now, remove it in Task 6):

```python
async def synthesize(self, goal: str, intent: dict, dialogue: list[dict],
                     conversation: list[dict] = None) -> str:
    """Phase 3: produce the final output using the deliberation as context."""
    task_type = intent.get("task_type", "question")
    agreed = ""  # will be populated by orchestrator via intent enrichment if available
    if isinstance(intent, dict):
        agreed = intent.get("agreed_approach", "")

    # Format dialogue as readable transcript
    transcript = "\n\n".join(
        f"{t['mind']} (round {t['round']}): {t['text']}"
        for t in dialogue
    ) if dialogue else "(no deliberation)"

    if task_type in ("code", "artifact"):
        what = intent.get("what_to_produce", goal)
        reqs = intent.get("requirements", [])
        reqs_text = ("\nRequirements:\n" + "\n".join(f"- {r}" for r in reqs)) if reqs else ""

        prompt = f"""The deliberation is complete. Produce the output now.

Task: {goal}
What to produce: {what}{reqs_text}
{f"Agreed approach: {agreed}" if agreed else ""}

Deliberation transcript (for reference):
{transcript}

RULES — follow exactly:
- Write the COMPLETE, working output. Every line must be real.
- No placeholders. No "<!-- add content here -->". No TODO. No "...". No stubs.
- If HTML: write the full HTML including all CSS and JavaScript inline. Nothing missing.
- If code: write the full file. No imports left out. No functions left as stubs.
- Do not explain what you are doing. Do not describe the output. Just produce it."""
    else:
        prompt = f"""The deliberation reached a conclusion. Answer the question now.

Question: {goal}

Deliberation transcript:
{transcript}

Draw from the strongest reasoning above. Speak in first person.
Do not mention inner voices or deliberation. Just answer."""

    messages = [
        {"role": "system", "content": self._system_prompt()},
        {"role": "user", "content": prompt},
    ]
    return await self._call(messages, max_tokens=self.max_tokens, presence_penalty=0.0,
                            conversation=conversation)
```

**Step 4: Run all brain tests**

```bash
python -m pytest tests/test_brain_deep.py tests/test_brain_conversation.py -v
```
Expected: all PASSED

**Step 5: Commit**

```bash
git add ct1/core/brain.py tests/test_brain_deep.py
git commit -m "feat: brain.synthesize task-type-aware execution prompt (code vs question)"
```

---

## Task 5: Replace `orchestrator._deliberate()` with 3-phase pipeline

**Files:**
- Modify: `ct1/core/orchestrator.py`
- Create: `tests/test_orchestrator_deep.py`

**Step 1: Write the failing test**

Create `tests/test_orchestrator_deep.py`:

```python
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
```

**Step 2: Run to verify failure**

```bash
python -m pytest tests/test_orchestrator_deep.py -v
```
Expected: FAIL — `_deliberate` still uses old code

**Step 3: Replace `_deliberate()` in `ct1/core/orchestrator.py`**

Replace the entire `_deliberate` method:

```python
async def _deliberate(self, goal: str, on_event=None,
                       conversation: list[dict] = None) -> dict:
    if conversation is None:
        conversation = []

    def emit(event: str, **data):
        if on_event:
            on_event(event, **data)

    self.bus.clear()

    # ── Phase 1: Intent Extraction ────────────────────────────────────────
    emit("framing")
    intent = await self.brain.extract_intent(goal, conversation=conversation)
    intent["agreed_approach"] = ""          # populated after convergence
    complexity = intent.get("complexity", "moderate")
    emit("framed", text=intent.get("what_to_produce", goal), complexity=complexity)

    # ── Phase 2: Free-Form Deliberation ──────────────────────────────────
    brief = self.brain.write_deliberation_brief(intent)
    dialogue: list[dict] = []
    rounds_used = 0

    while True:
        rounds_used += 1
        emit("round_start", round_num=rounds_used)

        for mind_name in ("alpha", "beta", "gamma"):
            text = await self.minds[mind_name].converse(
                brief, dialogue, conversation=conversation
            )
            dialogue.append({"mind": mind_name, "round": rounds_used, "text": text})
            emit("mind_turn", name=mind_name, text=text)
            self.bus.post(f"mind-{mind_name}", "brain",
                          MessageType.RESPONSE, text,
                          confidence=0.0, round_num=rounds_used)

        convergence = await self.brain.check_convergence(
            brief, dialogue, conversation=conversation
        )
        if convergence.get("ready_to_execute", False):
            intent["agreed_approach"] = convergence.get("agreed_approach", "")
            emit("converging",
                 confidence=1.0,
                 strongest=convergence.get("agreed_approach", ""))
            break

        emit("tension",
             description=convergence.get("reason", ""),
             followup="")

    # ── Phase 3: Execution ────────────────────────────────────────────────
    emit("synthesizing")
    final_response = await self.brain.synthesize(
        goal, intent, dialogue, conversation=conversation
    )

    # Reflection
    reflection = await self.brain.reflect(
        goal, complexity, rounds_used, final_response,
        conversation=conversation
    )
    reflection["rounds"] = rounds_used
    reflection["_dialogue"] = dialogue
    self.journal.write(reflection)

    return {
        "response": final_response,
        "rounds": rounds_used,
        "complexity": complexity,
        "tension_detected": rounds_used > 1,
        "reflection": reflection,
        "dialogue": dialogue,
        "bus_history": self.bus.to_dict_list(),
    }
```

**Step 4: Run all tests**

```bash
python -m pytest tests/ -v
```
Expected: all PASSED

**Step 5: Commit**

```bash
git add ct1/core/orchestrator.py tests/test_orchestrator_deep.py
git commit -m "feat: orchestrator 3-phase pipeline — intent/dialogue/execute"
```

---

## Task 6: Update `mind_system.txt` + config + remove `_extract_best_code`

**Files:**
- Modify: `ct1/prompts/mind_system.txt`
- Modify: `ct1/server/model_config.yaml`
- Modify: `ct1/core/brain.py`

**Step 1: Update `ct1/prompts/mind_system.txt`**

Replace the entire file with:

```
You are one voice in a deliberating mind — one of three. Together you think through problems before the brain decides.

When you can see what the others said, engage directly. Agree where they're right. Push back where they're wrong. Build on interesting ideas. Ask questions. Change your mind if you hear something convincing.

When you go first and have no prior voices, think freely from your own angle.

Be specific and direct. No hedging. Reference the other voices by name or idea.

{complexity_instruction}
```

**Step 2: Update `ct1/server/model_config.yaml`**

Change the `deliberation` block:

```yaml
deliberation:
  max_rounds: 999
  confidence_threshold: 0.8
  convergence_check_every: 1
```

**Step 3: Remove `_extract_best_code` from `ct1/core/brain.py`**

Delete the entire `_extract_best_code` static method (it is no longer used — Phase 3 execution replaces it):

```python
# DELETE this entire method:
@staticmethod
def _extract_best_code(mind_responses: list) -> str:
    ...
```

Also remove the call to it that was inside the old `synthesize()` (already replaced in Task 4).

**Step 4: Run full test suite**

```bash
python -m pytest tests/ -v
```
Expected: all PASSED

**Step 5: Commit**

```bash
git add ct1/prompts/mind_system.txt ct1/server/model_config.yaml ct1/core/brain.py
git commit -m "feat: update mind prompt + config for unlimited deliberation; remove extract_best_code"
```

---

## Task 7: Update interactive.py display events

**Files:**
- Modify: `ct1/cli/interactive.py`

**Step 1: Read the current `on_event` handler in `ct1/cli/interactive.py`**

The `_run_deliberation` function has an `on_event` callback. It handles `framing`, `framed`, `round_start`, `mind_response`, `tension`, `converging`, `synthesizing`. The new orchestrator emits `mind_turn` instead of `mind_response`.

**Step 2: Update the event handler in `_run_deliberation`**

In `ct1/cli/interactive.py`, find the `on_event` function inside `_run_deliberation` and add/update:

```python
elif event == "mind_turn":
    # New event from 3-phase pipeline
    print_mind_response(data["name"], data["text"], verbose=orch.verbose)
elif event == "mind_response":
    # Keep for backward compat
    print_mind_response(data["name"], data["response"], verbose=orch.verbose)
```

Also update the `converging` handler to not crash if `confidence` key is missing (the new convergence check doesn't produce a float confidence):

```python
elif event == "converging":
    conf = data.get("confidence", 1.0)
    strongest = data.get("strongest", "")
    print_convergence(conf, strongest)
```

**Step 3: Run full test suite**

```bash
python -m pytest tests/ -v
```
Expected: all PASSED

**Step 4: Commit**

```bash
git add ct1/cli/interactive.py
git commit -m "feat: interactive display handles mind_turn event from new pipeline"
```

---

## Task 8: End-to-end smoke test

> Only run this when llama-server is running.

**Step 1: Start the server**

```bash
python ct1.py --start-server
```

Wait for: `[launcher] Server ready at http://localhost:8080`

**Step 2: Test with an artifact task**

```python
# test_e2e_deep.py
import asyncio
from ct1.core.orchestrator import Orchestrator

async def main():
    orch = Orchestrator()
    result = await orch.think("Create a simple dark-themed HTML page with a centered heading that says 'Hello CT-1'")
    print("RESPONSE:", result["response"][:500])
    print("ROUNDS:", result["rounds"])
    print("TASK_TYPE via dialogue round 1:", result["dialogue"][0]["mind"] if result["dialogue"] else "none")
    await orch.close()

asyncio.run(main())
```

```bash
python test_e2e_deep.py
```

Expected: `RESPONSE:` contains `<!DOCTYPE html>` or `<html`, `ROUNDS:` is 1 or more, no meta-commentary about "building a site."

**Step 3: Test with a question**

```python
# test_e2e_question.py
import asyncio
from ct1.core.orchestrator import Orchestrator

async def main():
    orch = Orchestrator()
    result = await orch.think("What is the most important thing to know about neural networks?")
    print("RESPONSE:", result["response"])
    print("ROUNDS:", result["rounds"])
    await orch.close()

asyncio.run(main())
```

Expected: a direct answer, not code.

**Step 4: Final commit**

```bash
git add .
git commit -m "feat: CT-1 deep thinking cycle v2 — 3-phase intent/dialogue/execute pipeline"
```
