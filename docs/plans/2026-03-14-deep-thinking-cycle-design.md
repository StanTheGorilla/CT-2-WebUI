# CT-1: Deep Thinking Cycle — Design Document

**Date:** 2026-03-14
**Status:** Approved
**Replaces:** The single-phase deliberation loop in `ct1/core/orchestrator.py`

---

## Problem

The current thinking cycle treats every task as a discussion topic. When given "build an HTML website", the minds debate *the concept of* building a website instead of *actually building* it. The `_extract_best_code` fallback only works if a mind happened to write code unprompted — none do because their role is to "think", not "execute." The result is meta-commentary about the task instead of the task itself.

Secondary problems:
- Deliberation is capped at 3 rounds, too shallow for complex tasks
- No phase that explicitly produces the output artifact
- No explicit intent extraction — the system doesn't know what it's supposed to produce

---

## Design

### Three Phases

```
INPUT
  ↓
PHASE 1 — INTENT EXTRACTION  (Brain, 1 call)
  ↓
PHASE 2 — FREE-FORM DELIBERATION  (Minds, unlimited rounds)
  ↓
PHASE 3 — EXECUTION  (Brain, 1 call)
  ↓
OUTPUT
```

---

### Phase 1: Intent Extraction

Brain makes a single call to extract what the task actually requires:

```json
{
  "task_type": "question" | "code" | "artifact" | "analysis",
  "what_to_produce": "concrete description of expected output",
  "requirements": ["key constraint 1", "key constraint 2", "..."],
  "complexity": "brief" | "moderate" | "deep"
}
```

This is a lightweight framing call — not a restatement of the question, but a classification that drives the rest of the pipeline. The `task_type` determines how Phase 3 executes.

---

### Phase 2: Free-Form Deliberation

**Brief** (`brain.write_deliberation_brief(intent)`):

The brain produces a deliberation brief — not a question, but a spec + debate prompt:
```
We need to produce: [what_to_produce]
Requirements: [requirements]

Debate the best approach. Explore alternatives. Identify risks.
Argue freely — agree, disagree, change your mind. Be specific.
```

**Dialogue state** — a flat list of turns, grows throughout deliberation:
```python
dialogue: list[dict]  # [{"mind": "alpha", "turn": 1, "text": "..."}, ...]
```

**Each round:** alpha speaks → beta responds → gamma responds → alpha responds → ...
Every mind sees ALL prior dialogue turns (the full conversation so far).

**Per-mind prompt structure:**
```
[system prompt]
[conversation history: prior user/assistant turns]
[deliberation brief]
[all dialogue turns so far]
"Now respond. Be direct, be specific, engage with what was said."
```

**Convergence check** — after each full round (all 3 minds have spoken), brain makes one call:
```json
{
  "ready_to_execute": true,
  "reason": "...",
  "agreed_approach": "brief summary of what was decided"
}
```

If `ready_to_execute` is false, another round begins. No round cap — continues until brain is satisfied.

---

### Phase 3: Execution

Brain receives: original input + intent + full dialogue transcript + `agreed_approach`.

**For `code` / `artifact` tasks:**
```
The plan is decided. Produce the output now.
Task: [original input]
Agreed approach: [agreed_approach]
Full deliberation for reference: [dialogue transcript]

RULES:
- Write the complete, working [file type]. Every line real.
- No placeholders. No TODO. No stubs. No "<!-- add content here -->".
- Do not explain what you're doing. Just produce the output.
```

**For `question` / `analysis` tasks:**
```
The deliberation reached consensus. Answer the question now.
Draw from the best reasoning in the deliberation.
Speak in first person. Do not mention the inner voices.
```

---

## Files Changed

| File | Change |
|------|--------|
| `ct1/core/brain.py` | Add `extract_intent()`, add `check_convergence()`, update `synthesize()` to accept `dialogue + intent` |
| `ct1/core/mind.py` | Add `converse(dialogue, brief, ...)` method; keep `think()` for backward compat |
| `ct1/core/orchestrator.py` | Replace `_deliberate()` with 3-phase pipeline; remove `_extract_best_code` from brain.py |
| `ct1/prompts/mind_system.txt` | Update to reflect free-form dialogue role |
| `ct1/server/model_config.yaml` | Update deliberation config |

---

## Config Changes

```yaml
deliberation:
  max_rounds: 999           # effectively unlimited — brain decides when to stop
  confidence_threshold: 0.8
  convergence_check_every: 1  # check after every full round
```

---

## Key Invariants

1. **Phase 3 always produces the artifact** — execution is structurally separate from deliberation, with a task-type-specific prompt that cannot produce meta-commentary
2. **No code extraction heuristic** — `_extract_best_code` is removed; the brain produces the final output directly
3. **Minds never build, only deliberate** — production is the brain's exclusive responsibility in Phase 3
4. **Dialogue is a real conversation** — every mind sees every prior turn, enabling genuine back-and-forth
5. **No round cap** — the system runs until the brain judges the plan solid enough to execute
