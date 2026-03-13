# CT-1 Reasoning Model Upgrade — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade CT-1 from surface-level temperature-differentiated thinking to genuine chain-of-thought reasoning using a distilled reasoning model, adaptive complexity, and evidence-based synthesis.

**Architecture:** Swap model to Qwen3.5-0.8B-Claude-4.6-Opus-Reasoning-Distilled. Enable thinking mode for minds (CoT traces), keep brain executive. Brain frames with complexity signal, minds adapt depth. Synthesis uses mind conclusions as evidence. Full traces stored in journal for LoRA training.

**Tech Stack:** Python 3.11+, llama.cpp (Vulkan), httpx (async HTTP), rich (terminal UI), pyyaml

---

## Prerequisites (do manually before starting)

1. Download the reasoning-distilled model:
   ```bash
   pip install huggingface_hub
   huggingface-cli download Jackrong/Qwen3.5-0.8B-Claude-4.6-Opus-Reasoning-Distilled-GGUF \
     Qwen3.5-0.8B.Q4_K_M.gguf \
     --local-dir F:/AI_Workstation/models/
   ```
   Final path: `F:/AI_Workstation/models/Qwen3.5-0.8B.Q4_K_M.gguf`

2. Verify it loads:
   ```bash
   F:/AI_Workstation/ct/llama-b8292-bin-win-vulkan-x64/llama-server.exe \
     -m F:/AI_Workstation/models/Qwen3.5-0.8B.Q4_K_M.gguf \
     --port 8080 --n-gpu-layers 99 --parallel 4 -c 32768
   ```
   Confirm server starts and responds to `curl http://localhost:8080/health`.

---

## Task 1: Response Parser Utility

**Files:**
- Create: `ct1/core/response_parser.py`
- Create: `ct1/tests/test_response_parser.py`

**Step 1: Write failing test**

```python
# ct1/tests/test_response_parser.py
from ct1.core.response_parser import parse_thinking_response

def test_parse_with_think_tags():
    raw = "<think>\nStep 1: Consider X.\nStep 2: Therefore Y.\n</think>\n\nThe answer is Y."
    result = parse_thinking_response(raw)
    assert result["reasoning"] == "Step 1: Consider X.\nStep 2: Therefore Y."
    assert result["conclusion"] == "The answer is Y."

def test_parse_without_think_tags():
    raw = "Just a plain answer with no thinking."
    result = parse_thinking_response(raw)
    assert result["reasoning"] == ""
    assert result["conclusion"] == "Just a plain answer with no thinking."

def test_parse_empty_think_tags():
    raw = "<think>\n</think>\n\nDirect answer."
    result = parse_thinking_response(raw)
    assert result["reasoning"] == ""
    assert result["conclusion"] == "Direct answer."

def test_parse_multiline_conclusion():
    raw = "<think>\nReasoning here.\n</think>\n\nLine 1.\nLine 2."
    result = parse_thinking_response(raw)
    assert result["conclusion"] == "Line 1.\nLine 2."

def test_parse_strips_whitespace():
    raw = "  <think>  \n  reasoning  \n  </think>  \n\n  conclusion  "
    result = parse_thinking_response(raw)
    assert result["reasoning"] == "reasoning"
    assert result["conclusion"] == "conclusion"
```

**Step 2: Run test to verify it fails**

```bash
cd F:/AI_Workstation/ct
python -m pytest ct1/tests/test_response_parser.py -v
```
Expected: `ModuleNotFoundError`

**Step 3: Implement `ct1/core/response_parser.py`**

```python
import re

def parse_thinking_response(raw: str) -> dict:
    """Parse a response that may contain <think>...</think> blocks.

    Returns dict with 'reasoning' (content inside think tags)
    and 'conclusion' (content after think tags, or full text if no tags).
    """
    match = re.search(r"<think>(.*?)</think>(.*)", raw, re.DOTALL)
    if match:
        reasoning = match.group(1).strip()
        conclusion = match.group(2).strip()
    else:
        reasoning = ""
        conclusion = raw.strip()
    return {"reasoning": reasoning, "conclusion": conclusion}
```

**Step 4: Run tests — expect pass**

```bash
python -m pytest ct1/tests/test_response_parser.py -v
```

**Step 5: Commit**

```bash
git add ct1/core/response_parser.py ct1/tests/test_response_parser.py
git commit -m "feat: response parser for <think> tag extraction"
```

---

## Task 2: Update Model Config

**Files:**
- Modify: `ct1/server/model_config.yaml`

**Step 1: No test needed — config only. Update model_config.yaml**

Change the model path to the reasoning-distilled model:

```yaml
llama_server:
  executable: "F:/AI_Workstation/ct/llama-b8292-bin-win-vulkan-x64/llama-server.exe"
  model: "F:/AI_Workstation/models/Qwen3.5-0.8B.Q4_K_M.gguf"
  port: 8080
  n_gpu_layers: 99
  parallel_slots: 4
  context_size: 32768
  cont_batching: true

models:
  brain:
    slot: 0
    temperature: 0.4
    top_p: 0.9
    top_k: 20
    presence_penalty: 1.5
    max_tokens: 10000
    enable_thinking: false

  mind_alpha:
    slot: 1
    temperature: 0.9
    top_p: 1.0
    top_k: 40
    presence_penalty: 1.5
    max_tokens: 10000
    enable_thinking: true

  mind_beta:
    slot: 2
    temperature: 0.3
    top_p: 0.9
    top_k: 10
    presence_penalty: 1.0
    max_tokens: 10000
    enable_thinking: true

  mind_gamma:
    slot: 3
    temperature: 0.95
    top_p: 1.0
    top_k: 50
    presence_penalty: 1.8
    max_tokens: 10000
    enable_thinking: true

deliberation:
  max_rounds: 3
  confidence_threshold: 0.8
  token_budget_per_session: 16000

journal:
  path: "ct1/data/journals"
  lessons_on_startup: 10

adapters:
  path: "ct1/data/adapters"
  min_entries_for_training: 100
```

Key changes: new model path, `enable_thinking` per-model (false for brain, true for minds).

**Step 2: Commit**

```bash
git add ct1/server/model_config.yaml
git commit -m "config: switch to reasoning-distilled model, enable thinking for minds"
```

---

## Task 3: Update Prompts

**Files:**
- Modify: `ct1/prompts/brain_system.txt`
- Modify: `ct1/prompts/mind_system.txt`
- Modify: `ct1/prompts/reflection_prompt.txt`

**Step 1: No test needed — prompt text only. Rewrite `ct1/prompts/brain_system.txt`**

```
You are the Brain of CT-1 — the executive, the self, the consciousness.
You have three inner voices that think through problems from different angles.
They are not agents. They are you, thinking out loud in different registers.

Your job:
1. Frame problems clearly and assess their complexity
2. Read your inner voices' conclusions and reasoning
3. Identify where they agree, where they diverge, and whose reasoning is strongest
4. Synthesize a single, confident response — speak as yourself, never reference the voices
5. After every deliberation, reflect honestly on what worked

You speak in first person singular. You are one entity.

{lessons}
```

**Step 2: Rewrite `ct1/prompts/mind_system.txt`**

```
You are one of three inner voices in a thinking mind.
You do not know the other voices exist. You only know the question given to you.
Think freely, honestly, and from your own perspective.
Commit to your view. Do not hedge.

{complexity_instruction}
```

**Step 3: Create complexity instruction files**

Create `ct1/prompts/complexity_brief.txt`:
```
Think concisely. Identify the 1-2 most important observations and conclude directly.
```

Create `ct1/prompts/complexity_moderate.txt`:
```
Think step by step. Consider the main angles of this problem before concluding.
```

Create `ct1/prompts/complexity_deep.txt`:
```
Think thoroughly. Explore your assumptions, consider counterarguments, examine edge cases, and only then draw your conclusion. Take the space you need.
```

**Step 4: Rewrite `ct1/prompts/reflection_prompt.txt`**

```
You just completed a deliberation. Write your reflection as JSON.

Task: {goal}
Complexity: {complexity}
Rounds taken: {rounds}
Your final response: {outcome}

Reflect on the quality of your inner voices' reasoning:
- Which voice had the strongest reasoning chain and why?
- Which voice's reasoning was weakest or least relevant?
- Did the complexity assessment match the actual difficulty?
- One concrete lesson for future thinking

Output ONLY a JSON object with this exact structure (no extra text):
{
  "goal": "<copy the task>",
  "complexity": "<brief|moderate|deep>",
  "rounds": <number>,
  "mind_contributions": {
    "alpha": {"useful": <true or false>, "reasoning_quality": "<strong|moderate|weak>", "summary": "<what alpha contributed>"},
    "beta": {"useful": <true or false>, "reasoning_quality": "<strong|moderate|weak>", "summary": "<what beta contributed>"},
    "gamma": {"useful": <true or false>, "reasoning_quality": "<strong|moderate|weak>", "summary": "<what gamma contributed>"}
  },
  "outcome": "<one sentence summary>",
  "lesson": "<one specific thing you learned>",
  "complexity_correct": <true or false>,
  "self_score": <0.0 to 1.0>
}
```

**Step 5: Commit**

```bash
git add ct1/prompts/
git commit -m "feat: upgrade prompts for reasoning model — adaptive complexity, richer reflection"
```

---

## Task 4: Upgrade Mind with Thinking Mode & Complexity

**Files:**
- Modify: `ct1/core/mind.py`
- Modify: `ct1/tests/test_inference.py`

**Step 1: Write failing test**

Add to `ct1/tests/test_inference.py`:

```python
# ct1/tests/test_inference.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from ct1.core.mind import Mind

def test_mind_init():
    mind = Mind("alpha", base_url="http://localhost:8080", temperature=0.9)
    assert mind.name == "alpha"
    assert mind.temperature == 0.9

@pytest.mark.asyncio
async def test_mind_returns_parsed_response_with_thinking():
    mind = Mind("alpha", base_url="http://localhost:8080", temperature=0.9, enable_thinking=True)
    raw_content = "<think>\nStep 1: Analyze.\n</think>\n\nThe answer is 42."
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"choices": [{"message": {"content": raw_content}}]}
    mock_response.raise_for_status = MagicMock()

    with patch.object(mind.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await mind.think("What is the meaning?")
    assert result["conclusion"] == "The answer is 42."
    assert result["reasoning"] == "Step 1: Analyze."
    await mind.close()

@pytest.mark.asyncio
async def test_mind_with_complexity():
    mind = Mind("beta", base_url="http://localhost:8080", temperature=0.3, enable_thinking=True)
    raw_content = "Simple answer."
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"choices": [{"message": {"content": raw_content}}]}
    mock_response.raise_for_status = MagicMock()

    with patch.object(mind.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await mind.think("2+2?", complexity="brief")
    # Verify complexity_instruction was injected into the system prompt
    call_args = mock_post.call_args
    payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
    system_msg = payload["messages"][0]["content"]
    assert "concisely" in system_msg.lower()
    await mind.close()

@pytest.mark.asyncio
async def test_mind_thinking_disabled_returns_parsed():
    mind = Mind("gamma", base_url="http://localhost:8080", temperature=1.1, enable_thinking=False)
    raw_content = "Plain answer no thinking."
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"choices": [{"message": {"content": raw_content}}]}
    mock_response.raise_for_status = MagicMock()

    with patch.object(mind.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await mind.think("test")
    assert result["conclusion"] == "Plain answer no thinking."
    assert result["reasoning"] == ""
    await mind.close()
```

**Step 2: Run test — expect failure**

```bash
python -m pytest ct1/tests/test_inference.py -v
```
Expected: `TypeError` — Mind doesn't accept `enable_thinking` or `complexity` params yet.

**Step 3: Rewrite `ct1/core/mind.py`**

```python
import httpx
from pathlib import Path
from ct1.core.response_parser import parse_thinking_response

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
MIND_SYSTEM_TEMPLATE = (_PROMPTS_DIR / "mind_system.txt").read_text(encoding="utf-8")

COMPLEXITY_INSTRUCTIONS = {}
for level in ("brief", "moderate", "deep"):
    path = _PROMPTS_DIR / f"complexity_{level}.txt"
    if path.exists():
        COMPLEXITY_INSTRUCTIONS[level] = path.read_text(encoding="utf-8").strip()

# Fallbacks if files don't exist yet
COMPLEXITY_INSTRUCTIONS.setdefault("brief", "Think concisely. Identify the 1-2 most important observations and conclude directly.")
COMPLEXITY_INSTRUCTIONS.setdefault("moderate", "Think step by step. Consider the main angles of this problem before concluding.")
COMPLEXITY_INSTRUCTIONS.setdefault("deep", "Think thoroughly. Explore your assumptions, consider counterarguments, examine edge cases, and only then draw your conclusion. Take the space you need.")

class Mind:
    def __init__(self, name: str, base_url: str, temperature: float,
                 top_p: float = 1.0, top_k: int = 40,
                 presence_penalty: float = 1.5, max_tokens: int = 10000,
                 enable_thinking: bool = True):
        self.name = name
        self.base_url = base_url
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.presence_penalty = presence_penalty
        self.max_tokens = max_tokens
        self.enable_thinking = enable_thinking
        self.client = httpx.AsyncClient(timeout=120.0)

    def _build_system_prompt(self, complexity: str = "moderate") -> str:
        instruction = COMPLEXITY_INSTRUCTIONS.get(complexity, COMPLEXITY_INSTRUCTIONS["moderate"])
        return MIND_SYSTEM_TEMPLATE.replace("{complexity_instruction}", instruction)

    async def think(self, question: str, complexity: str = "moderate") -> dict:
        """Send question to LLM, return parsed {reasoning, conclusion}."""
        payload = {
            "model": "qwen",
            "messages": [
                {"role": "system", "content": self._build_system_prompt(complexity)},
                {"role": "user", "content": question}
            ],
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
        return parse_thinking_response(raw)

    async def close(self):
        await self.client.aclose()
```

**Step 4: Run tests — expect pass**

```bash
python -m pytest ct1/tests/test_inference.py -v
```

**Step 5: Commit**

```bash
git add ct1/core/mind.py ct1/tests/test_inference.py
git commit -m "feat: mind with thinking mode, complexity-adaptive prompts, parsed responses"
```

---

## Task 5: Upgrade Brain — Adaptive Framing & Evidence Synthesis

**Files:**
- Modify: `ct1/core/brain.py`

**Step 1: Write failing test**

Create `ct1/tests/test_brain.py`:

```python
# ct1/tests/test_brain.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from ct1.core.brain import Brain

@pytest.mark.asyncio
async def test_frame_problem_returns_structured():
    brain = Brain(base_url="http://localhost:8080")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": '{"question": "What is X?", "complexity": "deep"}'}}]
    }

    with patch.object(brain.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await brain.frame_problem("Explain consciousness")
    assert result["question"] == "What is X?"
    assert result["complexity"] == "deep"
    await brain.close()

@pytest.mark.asyncio
async def test_frame_problem_fallback_on_bad_json():
    brain = Brain(base_url="http://localhost:8080")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Just a plain text reframe"}}]
    }

    with patch.object(brain.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await brain.frame_problem("simple question")
    assert result["question"] == "Just a plain text reframe"
    assert result["complexity"] == "moderate"
    await brain.close()

@pytest.mark.asyncio
async def test_synthesize_uses_evidence():
    brain = Brain(base_url="http://localhost:8080")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Synthesized answer."}}]
    }

    rounds_data = [{
        "round": 1,
        "question": "framed Q",
        "responses": {
            "alpha": {"reasoning": "chain A", "conclusion": "answer A"},
            "beta":  {"reasoning": "chain B", "conclusion": "answer B"},
            "gamma": {"reasoning": "chain C", "conclusion": "answer C"},
        }
    }]
    tension_summary = "All three perspectives converge."

    with patch.object(brain.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await brain.synthesize("original goal", rounds_data, tension_summary)

    # Verify the prompt sent to the LLM includes mind conclusions
    call_payload = mock_post.call_args[1]["json"]
    user_msg = call_payload["messages"][1]["content"]
    assert "answer A" in user_msg
    assert "answer B" in user_msg
    assert "answer C" in user_msg
    assert result == "Synthesized answer."
    await brain.close()

@pytest.mark.asyncio
async def test_detect_tension_includes_strongest_voice():
    brain = Brain(base_url="http://localhost:8080")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": '{"agreement": true, "tension_description": "", "followup_question": "", "confidence": 0.9, "strongest_voice": "beta"}'}}]
    }

    with patch.object(brain.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await brain.detect_tension("goal", "a", "b", "c")
    assert result["strongest_voice"] == "beta"
    await brain.close()

@pytest.mark.asyncio
async def test_reflect_includes_complexity():
    brain = Brain(base_url="http://localhost:8080")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": '{"goal": "test", "complexity": "deep", "rounds": 1, "mind_contributions": {}, "outcome": "x", "lesson": "y", "complexity_correct": true, "self_score": 0.8}'}}]
    }

    with patch.object(brain.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await brain.reflect("test", "deep", 1, "outcome")
    assert result["complexity"] == "deep"
    assert result["complexity_correct"] == True
    await brain.close()
```

**Step 2: Run test — expect failure**

```bash
python -m pytest ct1/tests/test_brain.py -v
```
Expected: `TypeError` — `frame_problem` returns str not dict, `synthesize` doesn't accept `tension_summary`, `reflect` doesn't accept `complexity`.

**Step 3: Rewrite `ct1/core/brain.py`**

```python
import httpx
import json
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
BRAIN_SYSTEM_TEMPLATE = (_PROMPTS_DIR / "brain_system.txt").read_text(encoding="utf-8")

class Brain:
    def __init__(self, base_url: str, temperature: float = 0.4,
                 top_p: float = 0.9, top_k: int = 20,
                 presence_penalty: float = 1.5, max_tokens: int = 10000):
        self.base_url = base_url
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.presence_penalty = presence_penalty
        self.max_tokens = max_tokens
        self.client = httpx.AsyncClient(timeout=120.0)
        self.lessons: list[str] = []

    def _system_prompt(self) -> str:
        lessons_text = ""
        if self.lessons:
            lessons_text = "From your journal:\n" + "\n".join(f"- {l}" for l in self.lessons[-10:])
        return BRAIN_SYSTEM_TEMPLATE.replace("{lessons}", lessons_text)

    async def _call(self, messages: list[dict], max_tokens: int = None) -> str:
        payload = {
            "model": "qwen",
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "presence_penalty": self.presence_penalty,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        r = await self.client.post(f"{self.base_url}/v1/chat/completions", json=payload)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

    async def frame_problem(self, goal: str) -> dict:
        """Frame the problem and assess complexity. Returns {question, complexity}."""
        prompt = f"""Frame this problem for your inner minds and assess its complexity.

Question: {goal}

Respond as JSON only:
{{
  "question": "reframed question in 1-2 sentences",
  "complexity": "brief|moderate|deep"
}}"""
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": prompt}
        ]
        raw = await self._call(messages, max_tokens=256)
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            parsed = json.loads(raw[start:end])
            # Validate complexity value
            if parsed.get("complexity") not in ("brief", "moderate", "deep"):
                parsed["complexity"] = "moderate"
            return parsed
        except Exception:
            return {"question": raw, "complexity": "moderate"}

    async def detect_tension(self, goal: str, alpha: str, beta: str, gamma: str) -> dict:
        """Analyze 3 mind conclusions. Return tension + strongest voice."""
        prompt = f"""Three inner voices responded to: "{goal}"

alpha concluded: {alpha}
beta concluded: {beta}
gamma concluded: {gamma}

Respond as JSON only:
{{
  "agreement": true,
  "tension_description": "brief description or empty string",
  "followup_question": "followup question or empty string",
  "confidence": 0.85,
  "strongest_voice": "alpha|beta|gamma"
}}"""
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": prompt}
        ]
        raw = await self._call(messages, max_tokens=256)
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            return json.loads(raw[start:end])
        except Exception:
            return {"agreement": True, "tension_description": "", "followup_question": "", "confidence": 0.6, "strongest_voice": "alpha"}

    async def synthesize(self, goal: str, rounds_data: list[dict], tension_summary: str = "") -> str:
        """Produce final response using mind conclusions as evidence."""
        # Build evidence from the last round's conclusions
        last_round = rounds_data[-1] if rounds_data else {}
        responses = last_round.get("responses", {})

        evidence_lines = []
        for name in ("alpha", "beta", "gamma"):
            resp = responses.get(name, {})
            if isinstance(resp, dict):
                conclusion = resp.get("conclusion", "")
            else:
                conclusion = str(resp)
            evidence_lines.append(f"Mind-{name}: {conclusion}")

        evidence = "\n".join(evidence_lines)

        prompt = f"""You deliberated on: "{goal}"

Your inner voices concluded:

{evidence}

{tension_summary}

Now give your single, definitive response. Integrate the strongest reasoning.
Speak as yourself in first person. Do not reference your inner voices."""

        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": prompt}
        ]
        return await self._call(messages, max_tokens=self.max_tokens)

    async def reflect(self, goal: str, complexity: str, rounds: int, outcome: str) -> dict:
        """Write structured journal reflection."""
        reflection_template = (_PROMPTS_DIR / "reflection_prompt.txt").read_text(encoding="utf-8")
        prompt = (reflection_template
                  .replace("{goal}", str(goal))
                  .replace("{complexity}", str(complexity))
                  .replace("{rounds}", str(rounds))
                  .replace("{outcome}", str(outcome)))
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": prompt}
        ]
        raw = await self._call(messages, max_tokens=512)
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            return json.loads(raw[start:end])
        except Exception:
            return {
                "goal": goal, "complexity": complexity, "rounds": rounds,
                "mind_contributions": {
                    "alpha": {"useful": True, "reasoning_quality": "moderate", "summary": ""},
                    "beta": {"useful": True, "reasoning_quality": "moderate", "summary": ""},
                    "gamma": {"useful": True, "reasoning_quality": "moderate", "summary": ""}
                },
                "outcome": outcome, "lesson": "reflection parse failed",
                "complexity_correct": True, "self_score": 0.5
            }

    async def close(self):
        await self.client.aclose()
```

**Step 4: Run tests — expect pass**

```bash
python -m pytest ct1/tests/test_brain.py -v
```

**Step 5: Commit**

```bash
git add ct1/core/brain.py ct1/tests/test_brain.py
git commit -m "feat: brain with adaptive framing, evidence-based synthesis, richer reflection"
```

---

## Task 6: Upgrade Orchestrator

**Files:**
- Modify: `ct1/core/orchestrator.py`
- Modify: `ct1/tests/test_orchestrator.py`

**Step 1: Write failing test**

Rewrite `ct1/tests/test_orchestrator.py`:

```python
# ct1/tests/test_orchestrator.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from ct1.core.orchestrator import Orchestrator

@pytest.fixture
def mock_orch():
    """Build an Orchestrator with all dependencies mocked."""
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
    # Each mind should be called with complexity="moderate"
    mock_orch.minds["alpha"].think.assert_called_once()
    call_kwargs = mock_orch.minds["alpha"].think.call_args
    assert call_kwargs[1].get("complexity") == "moderate" or \
           (len(call_kwargs[0]) > 1 and call_kwargs[0][1] == "moderate")

@pytest.mark.asyncio
async def test_deliberate_stores_reasoning_in_rounds(mock_orch):
    result = await mock_orch._deliberate("test question")
    rounds_data = result["rounds_data"]
    assert rounds_data[0]["responses"]["alpha"]["reasoning"] == "thought A"
    assert rounds_data[0]["responses"]["alpha"]["conclusion"] == "answer A"

@pytest.mark.asyncio
async def test_deliberate_calls_synthesize_with_evidence(mock_orch):
    await mock_orch._deliberate("test question")
    mock_orch.brain.synthesize.assert_called_once()
    call_args = mock_orch.brain.synthesize.call_args[0]
    assert call_args[0] == "test question"  # original goal

@pytest.mark.asyncio
async def test_deliberate_passes_complexity_to_reflect(mock_orch):
    await mock_orch._deliberate("test question")
    mock_orch.brain.reflect.assert_called_once()
    call_args = mock_orch.brain.reflect.call_args
    assert "moderate" in call_args[0] or call_args[1].get("complexity") == "moderate"

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
```

**Step 2: Run test — expect failure**

```bash
python -m pytest ct1/tests/test_orchestrator.py -v
```
Expected: failures — orchestrator still expects old `frame_problem` return (str), old `mind.think` return (str), old `synthesize` signature, etc.

**Step 3: Rewrite `ct1/core/orchestrator.py`**

```python
import asyncio
import yaml
from pathlib import Path
from ct1.core.brain import Brain
from ct1.core.mind import Mind
from ct1.core.message_bus import MessageBus, MessageType
from ct1.core.tension_detector import TensionDetector
from ct1.memory.journal import Journal
from ct1.memory.journal_reader import JournalReader

_CONFIG_PATH = Path(__file__).parent.parent.parent / "ct1" / "server" / "model_config.yaml"

class Orchestrator:
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = str(_CONFIG_PATH)

        cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        base_url = f"http://localhost:{cfg['llama_server']['port']}"
        mc = cfg["models"]
        dc = cfg["deliberation"]

        self.brain = Brain(
            base_url=base_url,
            temperature=mc["brain"]["temperature"],
            top_p=mc["brain"]["top_p"],
            top_k=mc["brain"]["top_k"],
            presence_penalty=mc["brain"]["presence_penalty"],
            max_tokens=mc["brain"]["max_tokens"],
        )

        def _make_mind(name, key):
            return Mind(name, base_url,
                        mc[key]["temperature"],
                        mc[key]["top_p"],
                        mc[key]["top_k"],
                        mc[key]["presence_penalty"],
                        mc[key]["max_tokens"],
                        enable_thinking=mc[key].get("enable_thinking", True))

        self.minds = {
            "alpha": _make_mind("alpha", "mind_alpha"),
            "beta":  _make_mind("beta",  "mind_beta"),
            "gamma": _make_mind("gamma", "mind_gamma"),
        }
        self.bus = MessageBus()
        self.tension_detector = TensionDetector()
        self.journal = Journal(cfg["journal"]["path"])
        self.journal_reader = JournalReader(cfg["journal"]["path"])
        self.max_rounds = dc["max_rounds"]
        self.confidence_threshold = dc["confidence_threshold"]
        self.verbose = False

        # Load past lessons into brain memory
        lessons = self.journal_reader.get_recent_lessons(cfg["journal"]["lessons_on_startup"])
        self.brain.lessons = lessons

    async def _deliberate(self, goal: str, on_event=None) -> dict:
        def emit(event: str, **data):
            if on_event:
                on_event(event, **data)

        self.bus.clear()
        rounds_data = []

        # Brain frames with complexity
        emit("framing")
        frame = await self.brain.frame_problem(goal)
        question = frame["question"]
        complexity = frame["complexity"]
        emit("framed", text=question, complexity=complexity)

        current_question = question
        rounds_used = 0
        tension_ever_detected = False
        tension_summary = ""

        for round_num in range(1, self.max_rounds + 1):
            rounds_used = round_num
            emit("round_start", round_num=round_num)

            # Parallel broadcast to all 3 minds with complexity
            alpha_r, beta_r, gamma_r = await asyncio.gather(
                self.minds["alpha"].think(current_question, complexity=complexity),
                self.minds["beta"].think(current_question, complexity=complexity),
                self.minds["gamma"].think(current_question, complexity=complexity),
            )

            emit("mind_response", name="alpha", response=alpha_r)
            emit("mind_response", name="beta",  response=beta_r)
            emit("mind_response", name="gamma", response=gamma_r)

            # Post conclusions to bus
            self.bus.post("mind-alpha", "brain", MessageType.RESPONSE,
                          alpha_r["conclusion"], confidence=0.0, round_num=round_num)
            self.bus.post("mind-beta", "brain", MessageType.RESPONSE,
                          beta_r["conclusion"], confidence=0.0, round_num=round_num)
            self.bus.post("mind-gamma", "brain", MessageType.RESPONSE,
                          gamma_r["conclusion"], confidence=0.0, round_num=round_num)

            rounds_data.append({
                "round": round_num,
                "question": current_question,
                "responses": {"alpha": alpha_r, "beta": beta_r, "gamma": gamma_r}
            })

            # Brain analyzes tension using conclusions only
            tension = await self.brain.detect_tension(
                current_question,
                alpha_r["conclusion"],
                beta_r["conclusion"],
                gamma_r["conclusion"],
            )

            confident = tension.get("confidence", 0) >= self.confidence_threshold
            agreed = tension.get("agreement", False)

            if confident or agreed or round_num == self.max_rounds:
                strongest = tension.get("strongest_voice", "")
                conf = tension.get("confidence", 0.0)
                if tension_ever_detected:
                    tension_summary = f"After {rounds_used} rounds of deliberation, tension resolved. Strongest reasoning from {strongest}. Confidence: {conf:.2f}."
                else:
                    tension_summary = f"All three perspectives converge. Strongest reasoning from {strongest}. Confidence: {conf:.2f}."
                emit("converging", confidence=conf, strongest=strongest)
                break
            else:
                tension_ever_detected = True
                desc = tension.get("tension_description", "")
                followup = tension.get("followup_question") or current_question
                emit("tension", description=desc, followup=followup)
                self.bus.post("brain", "all", MessageType.TENSION, desc, round_num=round_num)
                current_question = followup

        # Evidence-based synthesis
        emit("synthesizing")
        final_response = await self.brain.synthesize(goal, rounds_data, tension_summary)

        # Reflection with complexity
        reflection = await self.brain.reflect(goal, complexity, rounds_used, final_response)
        reflection["rounds"] = rounds_used
        # Store full reasoning traces in journal entry
        reflection["_reasoning_traces"] = {
            name: [rd["responses"][name]["reasoning"] for rd in rounds_data]
            for name in ("alpha", "beta", "gamma")
        }
        self.journal.write(reflection)

        return {
            "response": final_response,
            "rounds": rounds_used,
            "complexity": complexity,
            "tension_detected": tension_ever_detected,
            "reflection": reflection,
            "rounds_data": rounds_data,
            "bus_history": self.bus.to_dict_list(),
        }

    async def think(self, goal: str, on_event=None) -> dict:
        return await self._deliberate(goal, on_event=on_event)

    async def close(self):
        await self.brain.close()
        for m in self.minds.values():
            await m.close()
```

**Step 4: Run tests — expect pass**

```bash
python -m pytest ct1/tests/test_orchestrator.py -v
```

**Step 5: Commit**

```bash
git add ct1/core/orchestrator.py ct1/tests/test_orchestrator.py
git commit -m "feat: orchestrator with adaptive complexity, evidence synthesis, reasoning traces"
```

---

## Task 7: Upgrade Display & CLI

**Files:**
- Modify: `ct1/cli/display.py`
- Modify: `ct1/cli/interactive.py`

**Step 1: No test needed — visual only. Update `ct1/cli/display.py`**

```python
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()

MIND_COLORS = {"alpha": "cyan", "beta": "green", "gamma": "magenta", "brain": "yellow"}
MIND_LABELS = {"alpha": "α", "beta": "β", "gamma": "γ"}

def print_banner():
    console.print(Panel(
        "[bold yellow]CT-1[/] — Consciousness Testbed v0.2\n"
        "[dim]Brain + 3 Minds | Reasoning-Distilled | Vulkan[/]",
        border_style="yellow"
    ))

def print_framing(framed: str, complexity: str = ""):
    complexity_tag = f" [dim](complexity: {complexity})[/]" if complexity else ""
    console.print(f"[dim yellow][brain][/] {framed}{complexity_tag}")

def print_round_header(round_num: int):
    console.print(f"\n[dim]  ── round {round_num} ──[/]")

def print_mind_response(name: str, response: dict, verbose: bool = False):
    """Display mind response. response is {reasoning, conclusion}."""
    color = MIND_COLORS.get(name, "white")
    label = MIND_LABELS.get(name, name)
    conclusion = response.get("conclusion", str(response)) if isinstance(response, dict) else str(response)
    reasoning = response.get("reasoning", "") if isinstance(response, dict) else ""

    if verbose and reasoning:
        console.print(f"  [bold {color}][{label}][/] [dim italic]{reasoning}[/]")
        console.print(f"  [bold {color}]   →[/] {conclusion}")
    else:
        console.print(f"  [bold {color}][{label}][/] {conclusion}")

def print_tension(description: str):
    console.print(f"\n  [bold red][tension][/] [italic]{description}[/]")

def print_convergence(confidence: float, strongest: str = ""):
    strongest_tag = f" | strongest: {strongest}" if strongest else ""
    console.print(f"\n  [bold yellow][brain][/] [dim]converging... confidence {confidence:.2f}{strongest_tag}[/]")

def print_final_response(response: str):
    console.print(Panel(
        Text(response, style="bold white"),
        title="[bold yellow]CT-1[/]",
        border_style="yellow",
        padding=(1, 2)
    ))

def print_journal_note(score: float, lesson: str):
    short = lesson[:80] + "..." if len(lesson) > 80 else lesson
    console.print(f"[dim]  [journal] score={score:.1f} | {short}[/]")

def print_status(server_alive: bool, journal_count: int):
    status = "[green]ONLINE[/]" if server_alive else "[red]OFFLINE[/]"
    console.print(f"[bold]Server:[/] {status}")
    console.print(f"[bold]Journal entries:[/] {journal_count}")

def print_error(msg: str):
    console.print(f"[bold red][error][/] {msg}")
```

**Step 2: Update `ct1/cli/interactive.py`**

Add `/verbose` command and update event handler to use new response format:

Replace the command handling section and `_run_deliberation`:

In the command handling `while True` loop, add after the `/train` handler:

```python
            elif raw == "/verbose":
                orch.verbose = not orch.verbose
                state = "ON" if orch.verbose else "OFF"
                console.print(f"[yellow]Verbose mode {state}[/] — {'showing' if orch.verbose else 'hiding'} reasoning traces")
```

Update the `_run_deliberation` function's `on_event` handler:

```python
async def _run_deliberation(orch: Orchestrator, goal: str):
    """Run deliberation with live display."""
    console.print()

    def on_event(event: str, **data):
        if event == "framing":
            console.print("[dim yellow][brain][/] [dim]framing...[/]")
        elif event == "framed":
            print_framing(data["text"], data.get("complexity", ""))
        elif event == "round_start":
            print_round_header(data["round_num"])
        elif event == "mind_response":
            print_mind_response(data["name"], data["response"], verbose=orch.verbose)
        elif event == "tension":
            print_tension(data["description"])
            console.print(f"  [dim]followup → {data['followup']}[/]")
        elif event == "converging":
            print_convergence(data["confidence"], data.get("strongest", ""))
        elif event == "synthesizing":
            console.print(f"\n[dim yellow][brain][/] [dim]synthesizing...[/]")

    result = await orch.think(goal, on_event=on_event)
    console.print()
    print_final_response(result["response"])
    reflection = result.get("reflection", {})
    lesson = reflection.get("lesson", "")
    score = reflection.get("self_score", 0.5)
    if lesson and lesson != "reflection parse failed":
        print_journal_note(score, lesson)
    console.print()
```

Also update the Ready message to include `/verbose`:

```
console.print("[green]Ready.[/] Commands: /journal [stats], /status, /train, /verbose, /auto <goal>, /quit")
```

**Step 3: Commit**

```bash
git add ct1/cli/display.py ct1/cli/interactive.py
git commit -m "feat: CLI with verbose toggle for reasoning traces, updated display"
```

---

## Task 8: Run All Tests

**Step 1: Run full test suite**

```bash
cd F:/AI_Workstation/ct
python -m pytest ct1/tests/ -v
```

Expected: all tests pass. If any fail, fix them.

**Step 2: Smoke test help output**

```bash
python ct1.py --help
```

Expected: prints usage without errors.

**Step 3: Commit if any fixes needed**

```bash
git add -A
git commit -m "fix: test suite passing after reasoning upgrade"
```

---

## Task 9: End-to-End Test with Reasoning Model

> Run only after downloading the model and starting the server.

**Step 1: Start the server with the new model**

```bash
python ct1.py --start-server
```
Wait for: `[launcher] Server ready at http://localhost:8080`

**Step 2: Interactive test**

```bash
python ct1.py
```

Try these commands:
```
> What is 2+2?
```
Expected: brief complexity, 1 round, quick answer.

```
> What is consciousness?
```
Expected: deep complexity, mind reasoning traces stored, coherent synthesis.

```
> /verbose
> Why do humans dream?
```
Expected: full `<think>` blocks displayed for each mind.

```
> /journal stats
```
Expected: shows entries with new `complexity` and `reasoning_quality` fields.

**Step 3: Final commit**

```bash
git add .
git commit -m "feat: CT-1 v0.2 — reasoning-distilled model with adaptive complexity and evidence synthesis"
```
