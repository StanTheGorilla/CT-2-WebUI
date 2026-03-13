# CT-1: Reasoning Model Upgrade — Design Document

**Date**: 2026-03-13
**Status**: Approved
**Builds on**: 2026-03-12-ct1-pseudo-agi-design.md

---

## Problem

CT-1's current architecture uses Qwen3.5-0.8B with thinking mode disabled. The minds produce 2-4 sentence surface-level reactions differentiated only by temperature. There is no chain-of-thought reasoning, no structured logic, and no genuine cognitive diversity. The deliberation loop simulates depth without achieving it.

## Solution

Swap to a reasoning-distilled model (Qwen3.5-0.8B-Claude-4.6-Opus-Reasoning-Distilled) and restructure the entire thinking pipeline to leverage real chain-of-thought traces.

---

## 1. Model Swap

**Model**: `Qwen3.5-0.8B-Claude-4.6-Opus-Reasoning-Distilled` (Q4_K_M GGUF)
**Source**: https://huggingface.co/Jackrong/Qwen3.5-0.8B-Claude-4.6-Opus-Reasoning-Distilled-GGUF
**Deployment**: Single llama-server, 4 parallel slots, same architecture as before.

The distilled model produces `<think>...</think>` reasoning blocks before its final answer. This is the core capability we build around.

### Config Changes

```yaml
llama_server:
  model: "F:/AI_Workstation/models/Qwen3.5-0.8B-Claude-4.6-Opus-Reasoning-Distilled-Q4_K_M.gguf"
  # Everything else unchanged
```

### Thinking Mode

- **Minds**: `enable_thinking: True` — they produce full chain-of-thought
- **Brain**: `enable_thinking: False` — stays executive, concise, decisive

---

## 2. Adaptive Complexity

The brain's `frame_problem()` now returns structured output:

```json
{
  "question": "What trade-offs exist between consistency and availability in distributed systems?",
  "complexity": "deep"
}
```

**Complexity levels and their mind prompt modifiers:**

| Level | When | Mind instruction |
|-------|------|-----------------|
| `brief` | Simple facts, arithmetic, lookups | "Think concisely. 1-2 key observations, then conclude." |
| `moderate` | Analysis, comparisons, explanations | "Think step by step. Cover the main angles before concluding." |
| `deep` | Philosophy, design, open-ended reasoning | "Think thoroughly. Explore assumptions, counterarguments, and edge cases before concluding." |

The brain determines complexity during framing. This is a natural extension — the brain already reframes the question; now it also gauges how much thinking it needs.

### Framing Prompt

```
Frame this problem for your inner minds and assess its complexity.

Question: {goal}

Respond as JSON only:
{
  "question": "reframed question in 1-2 sentences",
  "complexity": "brief|moderate|deep"
}
```

---

## 3. Thinking Trace Handling

### Parse Structure

Mind responses come back as:
```
<think>
Step 1: The question asks about X...
Step 2: Consider that Y implies Z...
Step 3: However, the counterargument is...
</think>

Therefore, the answer is A because of the reasoning in steps 1-3.
```

The system parses this into two parts:
- `reasoning`: Content inside `<think>...</think>` tags
- `conclusion`: Content after `</think>` tag

### Storage

Both parts are stored everywhere — message bus, rounds_data, journal. The reasoning trace is the most valuable data CT-1 produces for future LoRA training.

```python
{
  "round": 1,
  "responses": {
    "alpha": {
      "reasoning": "Step 1: ...\nStep 2: ...",
      "conclusion": "The answer is A because..."
    },
    "beta": { ... },
    "gamma": { ... }
  }
}
```

### Display

- **Default**: CLI shows only conclusions (clean, readable)
- **Verbose mode**: `/verbose` toggle shows full `<think>` blocks
- **Journal**: Always stores full traces

---

## 4. Evidence-Based Synthesis

The brain's `synthesize()` method changes fundamentally. Instead of answering the original question blind, it receives the distilled evidence from deliberation:

### Synthesis Prompt

```
You deliberated on: "{goal}"

Your inner voices concluded:

Mind-α: {alpha_conclusion}
Mind-β: {beta_conclusion}
Mind-γ: {gamma_conclusion}

{tension_summary}

Now give your single, definitive response. Integrate the strongest reasoning.
Speak as yourself in first person. Do not reference your inner voices.
```

Where `tension_summary` is one of:
- "All three perspectives converge. High confidence."
- "Key tension: {description}. After {N} rounds, the strongest reasoning points to..."

The brain still speaks as one entity — but now its answer is genuinely informed by three reasoning chains, not just its own single pass.

---

## 5. Updated Prompt System

### brain_system.txt (revised)

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

### mind_system.txt (revised)

```
You are one of three inner voices in a thinking mind.
You do not know the other voices exist. You only know the question given to you.
Think freely, honestly, and from your own perspective.
Commit to your view. Do not hedge.

{complexity_instruction}
```

Where `{complexity_instruction}` is set per-query based on adaptive complexity.

### Complexity Instructions

**brief**:
```
Think concisely. Identify the 1-2 most important observations and conclude directly.
```

**moderate**:
```
Think step by step. Consider the main angles of this problem before concluding.
```

**deep**:
```
Think thoroughly. Explore your assumptions, consider counterarguments, examine edge cases,
and only then draw your conclusion. Take the space you need.
```

---

## 6. Tension Detection Upgrade

With reasoning traces available, tension detection becomes more meaningful. Instead of just comparing surface conclusions, the brain can assess reasoning quality:

### Tension Detection Prompt (revised)

```
Three inner voices responded to: "{question}"

α concluded: {alpha_conclusion}
β concluded: {beta_conclusion}
γ concluded: {gamma_conclusion}

Respond as JSON only:
{
  "agreement": true/false,
  "tension_description": "brief description or empty string",
  "followup_question": "followup question or empty string",
  "confidence": 0.0-1.0,
  "strongest_voice": "alpha|beta|gamma"
}
```

The new `strongest_voice` field feeds into the reflection/journal system, providing a direct signal for which mind's reasoning style is most effective — critical data for future LoRA training.

---

## 7. Reflection Upgrade

The reflection prompt now captures reasoning quality:

### reflection_prompt.txt (revised)

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

Output ONLY a JSON object:
{
  "goal": "...",
  "complexity": "brief|moderate|deep",
  "rounds": N,
  "mind_contributions": {
    "alpha": {"useful": true/false, "reasoning_quality": "strong|moderate|weak", "summary": "..."},
    "beta": {"useful": true/false, "reasoning_quality": "strong|moderate|weak", "summary": "..."},
    "gamma": {"useful": true/false, "reasoning_quality": "strong|moderate|weak", "summary": "..."}
  },
  "outcome": "...",
  "lesson": "...",
  "complexity_correct": true/false,
  "self_score": 0.0-1.0
}
```

The new fields (`reasoning_quality`, `complexity_correct`) produce richer DPO training signal. The system learns not just what worked, but why — and whether it's calibrating complexity correctly.

---

## 8. CLI Changes

### Verbose Toggle

New `/verbose` command toggles display of reasoning traces:
```
> /verbose
[verbose mode ON — showing mind reasoning traces]

> What is consciousness?

[brain] framing... (complexity: deep)

  ── round 1 ──
  [α] <think>
       Step 1: Consciousness involves subjective experience...
       Step 2: The hard problem suggests it can't be reduced...
       </think>
       Consciousness is likely an emergent property that resists reductive explanation.
  [β] <think>
       Step 1: Define terms precisely...
       </think>
       Without a formal definition, we should distinguish phenomenal from access consciousness.
  [γ] <think>
       Step 1: What if consciousness is fundamental, not emergent?
       </think>
       Consciousness might be a fundamental feature of information processing, not an accident of complexity.

  [brain] converging... confidence 0.85 | strongest: gamma

[brain] synthesizing...

╭─ CT-1 ──────────────────────────────────────────╮
│ Consciousness appears to be...                   │
╰──────────────────────────────────────────────────╯
```

### Default (non-verbose)

```
> What is consciousness?

[brain] framing... (complexity: deep)

  ── round 1 ──
  [α] Consciousness is likely an emergent property that resists reductive explanation.
  [β] Without a formal definition, we should distinguish phenomenal from access consciousness.
  [γ] Consciousness might be a fundamental feature of information processing.

  [brain] converging... confidence 0.85

╭─ CT-1 ──────────────────────────────────────────╮
│ Consciousness appears to be...                   │
╰──────────────────────────────────────────────────╯
```

---

## 9. Data Flow Summary

```
User Input
    ↓
brain.frame_problem(goal)
    → {"question": "...", "complexity": "deep"}
    ↓
mind_α.think(question, complexity)  ─┐
mind_β.think(question, complexity)  ─┼─ parallel, enable_thinking=True
mind_γ.think(question, complexity)  ─┘
    ↓
parse_response(raw) → {reasoning: "...", conclusion: "..."}
    ↓
brain.detect_tension(question, α.conclusion, β.conclusion, γ.conclusion)
    → {agreement, tension, confidence, strongest_voice}
    ↓
[if tension: re-broadcast followup → loop back]
    ↓
brain.synthesize(goal, conclusions, tension_summary)
    → final response (evidence-based, first person)
    ↓
brain.reflect(goal, complexity, rounds, outcome)
    → {reasoning_quality per mind, complexity_correct, lesson, score}
    ↓
journal.write(reflection + full reasoning traces)
```

---

## 10. Prerequisites

1. Download the reasoning-distilled model:
   ```bash
   huggingface-cli download Jackrong/Qwen3.5-0.8B-Claude-4.6-Opus-Reasoning-Distilled-GGUF \
     Qwen3.5-0.8B-Claude-4.6-Opus-Reasoning-Distilled-Q4_K_M.gguf \
     --local-dir F:/AI_Workstation/models/
   ```

2. Verify the GGUF loads in llama-server before changing any code.

---

## 11. What This Enables

- **Real reasoning diversity**: Three genuine chains of thought, not temperature-varied parroting
- **Better LoRA signal**: Reasoning traces + quality judgments = rich DPO pairs
- **Adaptive resource use**: Brief questions don't waste 10k tokens of reasoning
- **Evidence-based synthesis**: The brain actually uses what the minds found
- **Experimental validity**: You can now measure reasoning quality, not just output text
