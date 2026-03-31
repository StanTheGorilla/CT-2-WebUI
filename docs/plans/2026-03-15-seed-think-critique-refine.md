# Seed → Think → Critique → Refine Pipeline

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the broken round-based deliberation with a 4-phase pipeline that maximizes output quality using the 2B brain for deep reasoning and 0.8B minds for parallel seeding + critique.

**Architecture:** Minds generate 3 independent seed approaches in parallel (Phase 1). Brain reads all seeds with thinking enabled and generates a first draft (Phase 2). Minds critique the draft in parallel (Phase 3). Brain reads critiques and produces polished final output (Phase 4).

**Tech Stack:** Python/FastAPI backend, SvelteKit 5 frontend, llama-server (Qwen3.5-2B brain, Qwen3.5-0.8B minds x3)

---

### Task 1: Update model_config.yaml

**Files:**
- Modify: `ct1/server/model_config.yaml`

**Step 1: Update deliberation config**

Replace the deliberation section with new token budgets:

```yaml
deliberation:
  seed_max_tokens: 512
  critique_max_tokens: 512
  brain_synthesis_max_tokens: 100000
  brain_refine_max_tokens: 100000
```

Remove `max_rounds`, `alpha_max_tokens`, `beta_max_tokens`, `gamma_max_tokens` — they no longer exist.

---

### Task 2: Rewrite brain.py — add thinking support + new methods

**Files:**
- Modify: `ct1/core/brain.py`

**Step 1: Add `enable_thinking` parameter to `_call()`**

The brain's `_call()` currently hardcodes `enable_thinking: False`. Add parameter to override per-call. When thinking is enabled, parse `reasoning_content` and `content` from the response. Return a dict `{"text": str, "thinking": str}` instead of just a string when thinking is enabled.

```python
async def _call(self, messages: list[dict], max_tokens: int = None,
                presence_penalty: float = None,
                conversation: list[dict] = None,
                enable_thinking: bool = False) -> str | dict:
    # ... existing conversation injection ...
    payload = {
        # ... existing fields ...
        "chat_template_kwargs": {"enable_thinking": enable_thinking},
    }
    r = await self.client.post(f"{self.base_url}/v1/chat/completions", json=payload)
    # ... existing error handling ...

    if enable_thinking:
        msg = r.json()["choices"][0]["message"]
        content = msg.get("content", "").strip()
        reasoning = msg.get("reasoning_content", "").strip()
        text = content if content else reasoning
        return {"text": text, "thinking": reasoning if content else ""}

    return r.json()["choices"][0]["message"]["content"].strip()
```

**Step 2: Rewrite `synthesize()` to take full dialogue + use thinking**

Change signature: `synthesize(goal, intent, dialogue, conversation)` — takes ALL mind turns, not just gamma resolutions. Enable thinking so the brain reasons about the seeds.

```python
async def synthesize(self, goal: str, intent: dict, seeds: list[dict],
                     conversation: list[dict] = None) -> dict:
    """Phase 2: read all seed approaches, think deeply, generate first draft.
    Returns {"text": str, "thinking": str}.
    """
    task_type = intent.get("task_type", "question")

    # Format seeds as diverse perspectives
    seed_text = "\n".join(
        f"- {s['name']}: {s['text']}" for s in seeds
    )

    if task_type in ("code", "artifact"):
        what = intent.get("what_to_produce", goal)
        reqs = intent.get("requirements", [])
        reqs_text = ("\nRequirements:\n" + "\n".join(f"- {r}" for r in reqs)) if reqs else ""

        prompt = f"""Task: {goal}
What to produce: {what}{reqs_text}

Three approaches were proposed:
{seed_text}

Think about which ideas are strongest. Then write the COMPLETE output.
Every line must be real code. No placeholders. No TODO. No stubs.
If HTML: full HTML with all CSS and JS inline.
Start output with <!DOCTYPE html> or the first line of code."""
    else:
        prompt = f"""Question: {goal}

Three perspectives were offered:
{seed_text}

Think about which perspectives are strongest and most insightful.
Then answer directly. Speak in first person. Do not mention the perspectives."""

    messages = [
        {"role": "system", "content": self._system_prompt()},
        {"role": "user", "content": prompt},
    ]
    result = await self._call(messages, max_tokens=self.max_tokens,
                              presence_penalty=0.0,
                              conversation=conversation,
                              enable_thinking=True)

    # Strip preamble for code tasks
    if task_type in ("code", "artifact") and isinstance(result, dict):
        result["text"] = self._strip_code_preamble(result["text"])

    return result
```

**Step 3: Add `refine()` method**

New method that takes the draft + critiques and produces the polished final output.

```python
async def refine(self, goal: str, intent: dict, draft: str,
                 critiques: list[dict],
                 conversation: list[dict] = None) -> dict:
    """Phase 4: read critiques of the draft, think about them, produce polished output.
    Returns {"text": str, "thinking": str}.
    """
    task_type = intent.get("task_type", "question")

    critique_text = "\n".join(
        f"- {c['name']}: {c['text']}" for c in critiques
    )

    # For code, truncate draft to avoid context overflow
    draft_for_prompt = draft[:3000] if len(draft) > 3000 else draft

    if task_type in ("code", "artifact"):
        prompt = f"""You wrote this draft:
{draft_for_prompt}

Reviewers found these issues:
{critique_text}

Fix the valid issues. Ignore invalid criticism. Output the COMPLETE improved version.
Every line must be real code. No placeholders. No TODO.
Start with <!DOCTYPE html> or the first line of code."""
    else:
        prompt = f"""You wrote this draft:
{draft_for_prompt}

Feedback received:
{critique_text}

Incorporate valid feedback and produce the improved final answer.
Speak in first person. Do not mention feedback or reviewers."""

    messages = [
        {"role": "system", "content": self._system_prompt()},
        {"role": "user", "content": prompt},
    ]
    result = await self._call(messages, max_tokens=self.max_tokens,
                              presence_penalty=0.0,
                              conversation=conversation,
                              enable_thinking=True)

    if task_type in ("code", "artifact") and isinstance(result, dict):
        result["text"] = self._strip_code_preamble(result["text"])

    return result
```

**Step 4: Remove `write_round_brief()` — no longer needed**

Delete the method entirely. The round-based brief system is gone.

**Step 5: Keep `extract_intent()` but simplify**

Remove `rounds` and `round_topics` from extract_intent since they're no longer used. Keep task_type, what_to_produce, requirements, complexity.

Update the prompt to remove rounds/topics fields. Keep keyword override. Keep all fallbacks.

**Step 6: Keep `_strip_code_preamble()`, `reflect()`, `summarize_session()` as-is**

These don't change.

---

### Task 3: Rewrite mind.py — add seed() and critique()

**Files:**
- Modify: `ct1/core/mind.py`

**Step 1: Add `seed()` method**

Simple method: give the mind the task, get a short approach back. No thinking (wastes tokens on 0.8B). Truncate to 6 sentences.

```python
async def seed(self, goal: str, what_to_produce: str,
               requirements: list[str] = None,
               conversation: list[dict] = None,
               max_tokens: int = 512) -> str:
    """Generate a seed approach for the task. Returns plain text."""
    reqs = ""
    if requirements:
        reqs = "\nRequirements: " + ", ".join(requirements)

    user_content = f"Goal: {what_to_produce}{reqs}\n\nPropose your approach in a few sentences. Be specific about structure, style, and key decisions."

    messages = [
        {"role": "system", "content": self._build_system_prompt()},
        {"role": "user", "content": user_content},
    ]
    if conversation:
        messages = [messages[0]] + conversation + messages[1:]

    payload = {
        "model": "qwen",
        "messages": messages,
        "temperature": self.temperature,
        "top_p": self.top_p,
        "top_k": self.top_k,
        "presence_penalty": self.presence_penalty,
        "max_tokens": max_tokens,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    r = await self.client.post(f"{self.base_url}/v1/chat/completions", json=payload)
    r.raise_for_status()
    raw = r.json()["choices"][0]["message"]["content"].strip()
    return _truncate_sentences(raw, max_sentences=6)
```

**Step 2: Add `critique()` method**

Each mind gets a SPECIFIC critique role. Truncate to 4 sentences.

```python
async def critique(self, draft: str, role_prompt: str,
                   conversation: list[dict] = None,
                   max_tokens: int = 512) -> str:
    """Critique the brain's draft from a specific angle. Returns plain text."""
    # Truncate draft for 0.8B context
    draft_preview = draft[:2000] if len(draft) > 2000 else draft

    user_content = f"{role_prompt}\n\nDraft to review:\n{draft_preview}"

    messages = [
        {"role": "system", "content": "You are a reviewer. Be specific and concise. 2-4 sentences max."},
        {"role": "user", "content": user_content},
    ]
    if conversation:
        messages = [messages[0]] + conversation + messages[1:]

    payload = {
        "model": "qwen",
        "messages": messages,
        "temperature": self.temperature,
        "top_p": self.top_p,
        "top_k": self.top_k,
        "presence_penalty": self.presence_penalty,
        "max_tokens": max_tokens,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    r = await self.client.post(f"{self.base_url}/v1/chat/completions", json=payload)
    r.raise_for_status()
    raw = r.json()["choices"][0]["message"]["content"].strip()
    return _truncate_sentences(raw, max_sentences=4)
```

**Step 3: Remove `converse()` method — no longer needed**

Delete it. The round-based conversation system is gone.

**Step 4: Keep `think()`, `_extract_response()`, `_truncate_sentences()`**

The `think()` method stays (used elsewhere). `_extract_response()` stays (utility). `_truncate_sentences()` stays (used by seed/critique).

**Step 5: Update mind system prompt for seeds**

The mind prompt no longer needs round-specific rules. Update `mind_system.txt`:

```
You are {name}, one of three inner voices. {role}

RULES:
1. NEVER write code, HTML, CSS, or implementation. You are PLANNING, not building.
2. Keep it short and specific. No essays. No bullet lists. No numbered lists.
3. Focus on concrete decisions: what structure, what colors, what approach.

{complexity_instruction}
```

Update `MIND_ROLES` for the seed context:

```python
MIND_ROLES = {
    "alpha": "You are the creative one. Propose bold, specific ideas.",
    "beta": "You are the pragmatist. Focus on what works and what's feasible.",
    "gamma": "You are the perfectionist. Focus on quality, polish, and details.",
}
```

---

### Task 4: Rewrite orchestrator.py — new 4-phase pipeline

**Files:**
- Modify: `ct1/core/orchestrator.py`

**Step 1: Update __init__ for new config fields**

```python
dc = cfg["deliberation"]
self.seed_max_tokens = dc.get("seed_max_tokens", 512)
self.critique_max_tokens = dc.get("critique_max_tokens", 512)
```

Remove: `self.max_rounds`, `self.alpha_max_tokens`, `self.beta_max_tokens`, `self.gamma_max_tokens`.

Remove import of `TOPIC_MENUS` from brain.

**Step 2: Rewrite `_deliberate()` with 4-phase pipeline**

```python
async def _deliberate(self, goal, on_event=None, conversation=None):
    if conversation is None:
        conversation = []

    def emit(event, **data):
        if on_event:
            on_event(event, **data)

    self.bus.clear()

    # ── Phase 1: Intent ───────────────────────────────────────────────
    emit("framing")
    intent = await self.brain.extract_intent(goal, conversation=conversation)
    complexity = intent.get("complexity", "moderate")
    emit("framed",
         text=intent.get("what_to_produce", goal),
         task_type=intent.get("task_type", "question"),
         requirements=intent.get("requirements", []),
         complexity=complexity)

    # ── Phase 2: Parallel Seeding (all 3 minds simultaneously) ──────
    emit("seeding")
    what = intent.get("what_to_produce", goal)
    reqs = intent.get("requirements", [])

    seed_results = await asyncio.gather(
        self.minds["alpha"].seed(goal, what, reqs, conversation, self.seed_max_tokens),
        self.minds["beta"].seed(goal, what, reqs, conversation, self.seed_max_tokens),
        self.minds["gamma"].seed(goal, what, reqs, conversation, self.seed_max_tokens),
    )

    seeds = []
    for name, text in zip(["alpha", "beta", "gamma"], seed_results):
        seeds.append({"name": name, "text": text})
        emit("seed", name=name, text=text)

    # ── Phase 3: Brain Synthesis with deep thinking ─────────────────
    emit("synthesizing")
    synthesis = await self.brain.synthesize(
        goal, intent, seeds, conversation=conversation
    )
    draft = synthesis["text"]
    brain_thinking = synthesis.get("thinking", "")
    emit("draft", text=draft, thinking=brain_thinking)

    # ── Phase 4: Parallel Critique (all 3 minds simultaneously) ─────
    emit("critiquing")
    critique_prompts = {
        "alpha": "What's missing? What important features or sections are absent?",
        "beta": "What's broken or wrong? Find bugs, errors, or design flaws.",
        "gamma": "Score 1-10. What's the single biggest improvement that would raise the score?",
    }

    critique_results = await asyncio.gather(
        self.minds["alpha"].critique(draft, critique_prompts["alpha"], conversation, self.critique_max_tokens),
        self.minds["beta"].critique(draft, critique_prompts["beta"], conversation, self.critique_max_tokens),
        self.minds["gamma"].critique(draft, critique_prompts["gamma"], conversation, self.critique_max_tokens),
    )

    critiques = []
    for name, text in zip(["alpha", "beta", "gamma"], critique_results):
        critiques.append({"name": name, "text": text})
        emit("critique", name=name, text=text)

    # ── Phase 5: Brain Refinement with thinking ─────────────────────
    emit("refining")
    refinement = await self.brain.refine(
        goal, intent, draft, critiques, conversation=conversation
    )
    final_response = refinement["text"]
    refine_thinking = refinement.get("thinking", "")

    # Reflection
    reflection = await self.brain.reflect(
        goal, complexity, 4, final_response, conversation=conversation
    )
    reflection["_seeds"] = seeds
    reflection["_critiques"] = critiques
    self.journal.write(reflection)

    return {
        "response": final_response,
        "thinking": refine_thinking,
        "draft": draft,
        "draft_thinking": brain_thinking,
        "rounds": 4,
        "complexity": complexity,
        "reflection": reflection,
        "seeds": seeds,
        "critiques": critiques,
    }
```

---

### Task 5: Update api.py — pass new fields in done event

**Files:**
- Modify: `ct1/server/api.py`

**Step 1: Update the `done` event in `run_think()`**

```python
async def run_think():
    result = await _orch.think(
        goal, on_event=on_event, conversation=conversation
    )
    queue.put_nowait({
        "event": "done",
        "response": result["response"],
        "thinking": result.get("thinking", ""),
        "draft": result.get("draft", ""),
        "draft_thinking": result.get("draft_thinking", ""),
        "rounds": result.get("rounds", 0),
        "complexity": result["complexity"],
        "reflection": result.get("reflection", {}),
    })
```

---

### Task 6: Update chat.ts — new phases and events

**Files:**
- Modify: `ct1/web/src/lib/stores/chat.ts`

**Step 1: Update MindTurn interface — replace `round` with `phase`**

```typescript
export interface MindTurn {
    name: string;
    phase: 'seed' | 'critique';
    text: string;
}
```

**Step 2: Update ChatState — new phases, add draft**

```typescript
interface ChatState {
    conversation: Turn[];
    events: Record<string, any>[];
    dialogue: MindTurn[];  // seeds + critiques
    intent: Intent | null;
    reflection: Reflection | null;
    response: string;
    thinking: string;        // brain thinking from refinement
    draft: string;           // brain's first draft
    draftThinking: string;   // brain thinking from synthesis
    phase: 'idle' | 'framing' | 'seeding' | 'synthesizing' | 'critiquing' | 'refining' | 'done';
}
```

Add `draft: ''` and `draftThinking: ''` to `initial`. Remove `currentRound` and `roundTopics`.

**Step 3: Update handleEvent switch**

```typescript
case 'seeding':
    s.phase = 'seeding';
    break;
case 'seed':
    s.dialogue = [...s.dialogue, {
        name: data.name,
        phase: 'seed',
        text: data.text,
    }];
    break;
case 'synthesizing':
    s.phase = 'synthesizing';
    break;
case 'draft':
    s.draft = data.text;
    s.draftThinking = data.thinking || '';
    break;
case 'critiquing':
    s.phase = 'critiquing';
    break;
case 'critique':
    s.dialogue = [...s.dialogue, {
        name: data.name,
        phase: 'critique',
        text: data.text,
    }];
    break;
case 'refining':
    s.phase = 'refining';
    break;
case 'done':
    s.phase = 'done';
    s.response = data.response;
    s.thinking = data.thinking || '';
    if (!s.draft) s.draft = data.draft || '';
    if (!s.draftThinking) s.draftThinking = data.draft_thinking || '';
    s.reflection = data.reflection;
    s.conversation = [
        ...s.conversation,
        { role: 'assistant', content: data.response },
    ];
    break;
```

Remove: `round_start`, `mind_turn`, `converging`, `tension` cases.

**Step 4: Update sendThink reset**

Add `draft: ''`, `draftThinking: ''`. Remove `currentRound`, `roundTopics`.

---

### Task 7: Rewrite +page.svelte — new phase indicators

**Files:**
- Modify: `ct1/web/src/routes/+page.svelte`

**Step 1: Replace deliberation status messages**

Replace the old round-based status indicators with phase-based ones:

```svelte
{#if $chat.phase === 'seeding'}
    <div class="status"><span class="pulse mind"></span> Exploring approaches...</div>
{/if}

{#if $chat.dialogue.filter(d => d.phase === 'seed').length > 0}
    <DeliberationPanel
        dialogue={$chat.dialogue.filter(d => d.phase === 'seed')}
        phase={$chat.phase}
        label="Seed Approaches"
    />
{/if}

{#if $chat.phase === 'synthesizing'}
    <div class="status"><span class="pulse brain"></span> Brain generating first draft...</div>
{/if}

{#if $chat.draft && $chat.phase !== 'done'}
    <ResponsePanel response={$chat.draft} thinking={$chat.draftThinking} label="First Draft" />
{/if}

{#if $chat.phase === 'critiquing'}
    <div class="status"><span class="pulse mind"></span> Reviewing draft...</div>
{/if}

{#if $chat.dialogue.filter(d => d.phase === 'critique').length > 0}
    <DeliberationPanel
        dialogue={$chat.dialogue.filter(d => d.phase === 'critique')}
        phase={$chat.phase}
        label="Critiques"
    />
{/if}

{#if $chat.phase === 'refining'}
    <div class="status"><span class="pulse brain"></span> Polishing final version...</div>
{/if}
```

Remove: old `deliberating` status, `currentRound`, `roundTopics` references.

---

### Task 8: Simplify DeliberationPanel.svelte — remove round logic

**Files:**
- Modify: `ct1/web/src/lib/components/DeliberationPanel.svelte`

**Step 1: Replace round grouping with simple list**

Remove `roundTopics` prop, `currentRound` prop. Add `label` prop.

The panel now just shows a list of MindTurns with a header label ("Seed Approaches" or "Critiques"). No round grouping. No brain-card logic. No split view (seeds/critiques don't need it).

```svelte
<script lang="ts">
    import type { MindTurn as MindTurnType } from '$lib/stores/chat';
    import MindTurn from './MindTurn.svelte';

    let { dialogue, phase, label = 'Deliberation' }:
        { dialogue: MindTurnType[]; phase: string; label?: string } = $props();

    let collapsed = $state(false);
</script>

<div class="panel">
    <div class="panel-header">
        <button class="title-btn" onclick={() => collapsed = !collapsed}>
            <span class="title">{label}</span>
            <span class="turn-count">{dialogue.length} turns</span>
            <span class="chevron">{collapsed ? '+' : '\u2212'}</span>
        </button>
    </div>
    {#if !collapsed}
        <div class="panel-body">
            {#each dialogue as turn}
                <MindTurn name={turn.name} text={turn.text} />
            {/each}
            {#if phase === 'seeding' || phase === 'critiquing'}
                <div class="thinking"><span class="pulse"></span> thinking...</div>
            {/if}
        </div>
    {/if}
</div>
```

---

### Task 9: Update MindTurn.svelte — remove thinking toggle (minds no longer think)

**Files:**
- Modify: `ct1/web/src/lib/components/MindTurn.svelte`

**Step 1: Simplify — remove thinking**

Minds no longer have thinking (disabled for 0.8B). Remove the thinking prop, toggle button, and thinking-body div. Keep it clean.

---

### Task 10: Update ResponsePanel.svelte — add label prop

**Files:**
- Modify: `ct1/web/src/lib/components/ResponsePanel.svelte`

**Step 1: Add optional `label` prop**

Default "CT-1", but allow "First Draft" for the draft display.

```svelte
let { response, thinking = '', label = 'CT-1' }:
    { response: string; thinking?: string; label?: string } = $props();
```

Use `{label}` instead of hardcoded "CT-1" in the header.

---

### Task 11: Update mind_system.txt prompt

**Files:**
- Modify: `ct1/prompts/mind_system.txt`

**Step 1: Update for seed context**

```
You are {name}, one of three inner voices. {role}

RULES:
1. NEVER write code, HTML, CSS, or implementation. You are PLANNING, not building.
2. Keep it short and specific. No essays. No bullet lists.
3. Focus on concrete decisions: what structure, what colors, what approach.

{complexity_instruction}
```

---

### Task 12: Build frontend and verify

**Step 1:** Run `npm run build` in `ct1/web/`

**Step 2:** Start from worktree directory:
```bash
cd F:\AI_Workstation\ct\.worktrees\web-ui
python ct1.py --start-server
```

**Step 3:** Verify port 8080 shows `Qwen3.5-2B` model

**Step 4:** In another terminal:
```bash
cd F:\AI_Workstation\ct\.worktrees\web-ui
uvicorn ct1.server.api:app --port 3001
```

**Step 5:** Open browser, test with a code task like "make a landing page for a coffee shop"

**Verify:**
- Seeds appear in parallel (~30s)
- Brain draft appears with thinking toggle (~1-2 min)
- Critiques appear in parallel (~30s)
- Final polished response appears (~1-2 min)
- Total time: 3-5 minutes
