# Atlas Mode Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a beta "Atlas Mode" toggle that wraps CT-2's pipeline in Atlas's test-time compute infrastructure — multi-candidate generation, adaptive compute allocation, self-verification, and iterative repair.

**Architecture:** Atlas controller (`ct1/core/atlas.py`) wraps the existing `Orchestrator._pipeline()`. When atlas_mode is on, the controller estimates difficulty, generates k candidates with diverse prompting, selects the best via test execution + self-evaluation, and repairs failures via multi-perspective analysis. When off, zero code path changes.

**Tech Stack:** Python (backend), SvelteKit/TypeScript (frontend), existing llama-server LLM API, existing Journal/ComponentCache storage.

---

### Task 1: Add Atlas preferences to frontend store

**Files:**
- Modify: `ct1/web/src/lib/stores/preferences.ts:1-61`

**Step 1: Add Atlas fields to Preferences interface and defaults**

```typescript
interface Preferences {
    theme: Theme;
    showThinking: boolean;
    designRefinement: boolean;
    // Atlas Mode (beta)
    atlasMode: boolean;
    atlasEffortMode: 'auto' | 'manual';
    atlasEffortLevel: number;
    atlasSelfVerification: boolean;
    atlasMultiPerspective: boolean;
    atlasIterativeRefinement: boolean;
}

const defaults: Preferences = {
    theme: 'light',
    showThinking: false,
    designRefinement: true,
    // Atlas defaults
    atlasMode: false,
    atlasEffortMode: 'auto',
    atlasEffortLevel: 3,
    atlasSelfVerification: true,
    atlasMultiPerspective: true,
    atlasIterativeRefinement: true,
};
```

**Step 2: Verify the store loads correctly**

Run: `cd ct1/web && npm run check`
Expected: PASS, no type errors

**Step 3: Commit**

```bash
git add ct1/web/src/lib/stores/preferences.ts
git commit -m "feat(atlas): add Atlas preferences to frontend store"
```

---

### Task 2: Add Atlas state to chat store

**Files:**
- Modify: `ct1/web/src/lib/stores/chat.ts:93-171`

**Step 1: Add Atlas types and state fields**

Add after the `ModeOverride` type (line 91):

```typescript
export interface AtlasCandidate {
    index: number;
    score: number | null;
    testsPassed: number | null;
    testsTotal: number | null;
    status: 'pending' | 'generating' | 'scored' | 'selected' | 'failed';
}

export interface AtlasEffort {
    k: number;
    difficulty: number;
    tier: string;
}
```

Add to `ChatState` interface (after `fetchedContent` field, line 135):

```typescript
    // Atlas state
    atlasActive: boolean;
    atlasCandidates: AtlasCandidate[];
    atlasPhase: 'estimating' | 'generating' | 'testing' | 'selecting' | 'repairing' | null;
    atlasEffort: AtlasEffort | null;
```

Add to `initial` object (after `fetchedContent` default, line 170):

```typescript
    atlasActive: false,
    atlasCandidates: [],
    atlasPhase: null,
    atlasEffort: null,
```

**Step 2: Add Atlas event handlers to `handleEvent`**

Add new cases before the `case 'warning':` line (before line 399):

```typescript
            // ── Atlas pipeline events ──
            case 'atlas_started':
                s.atlasActive = true;
                s.atlasPhase = 'estimating';
                s.atlasEffort = {
                    k: data.k,
                    difficulty: data.difficulty,
                    tier: data.effort_tier,
                };
                s.atlasCandidates = Array.from({ length: data.k }, (_, i) => ({
                    index: i,
                    score: null,
                    testsPassed: null,
                    testsTotal: null,
                    status: 'pending' as const,
                }));
                break;
            case 'candidate_start':
                s.atlasPhase = 'generating';
                if (s.atlasCandidates[data.index]) {
                    s.atlasCandidates = s.atlasCandidates.map((c, i) =>
                        i === data.index ? { ...c, status: 'generating' } : c
                    );
                }
                s.streamingText = '';
                s.streamingThinking = '';
                s.tokenCount = 0;
                s.genStartTime = 0;
                break;
            case 'candidate_scored':
                if (s.atlasCandidates[data.index]) {
                    s.atlasCandidates = s.atlasCandidates.map((c, i) =>
                        i === data.index ? {
                            ...c,
                            score: data.score,
                            testsPassed: data.tests_passed ?? null,
                            testsTotal: data.tests_total ?? null,
                            status: 'scored',
                        } : c
                    );
                }
                break;
            case 'candidate_selected':
                s.atlasPhase = 'selecting';
                if (s.atlasCandidates[data.index]) {
                    s.atlasCandidates = s.atlasCandidates.map((c, i) =>
                        i === data.index ? { ...c, status: 'selected' } : c
                    );
                }
                break;
            case 'atlas_testing':
                s.atlasPhase = 'testing';
                break;
            case 'atlas_repair':
                s.atlasPhase = 'repairing';
                break;
            case 'atlas_repair_result':
                // Repair done — if passed, phase transitions via candidate_selected
                break;
```

**Step 3: Reset Atlas state in `sendThink`**

In the `chat.update` call inside `sendThink` (around line 619), add resets:

```typescript
        s.atlasActive = false;
        s.atlasCandidates = [];
        s.atlasPhase = null;
        s.atlasEffort = null;
```

**Step 4: Send Atlas settings over WebSocket**

In `sendThink`, modify the `ws?.send` call (line 697) to include atlas settings:

```typescript
    const prefs = get(preferences);
    const atlasSettings = prefs.atlasMode ? {
        atlasMode: true,
        effortMode: prefs.atlasEffortMode,
        effortLevel: prefs.atlasEffortLevel,
        selfVerification: prefs.atlasSelfVerification,
        multiPerspective: prefs.atlasMultiPerspective,
        iterativeRefinement: prefs.atlasIterativeRefinement,
    } : null;

    ws?.send({
        type: 'think',
        goal: goalContent,
        conversation: backendConv,
        conversation_id: convId,
        position: conv.length,
        ...(mode !== 'auto' ? { mode_override: mode } : {}),
        ...(wsId ? { workspace_id: wsId } : {}),
        ...(!prefs.designRefinement ? { skip_refinement: true } : {}),
        ...(atlasSettings ? { atlas: atlasSettings } : {}),
    });
```

**Step 5: Type check**

Run: `cd ct1/web && npm run check`
Expected: PASS

**Step 6: Commit**

```bash
git add ct1/web/src/lib/stores/chat.ts
git commit -m "feat(atlas): add Atlas state and event handlers to chat store"
```

---

### Task 3: Add Atlas settings UI to settings page

**Files:**
- Modify: `ct1/web/src/routes/settings/+page.svelte:227-245`

**Step 1: Add Atlas section after the existing Pipeline section**

Insert after the closing `</section>` of the Pipeline section (after line 245) and before the Server Status section:

```svelte
    <!-- ─── Atlas Mode (Beta) ─── -->
    <section class="section">
        <h2 class="section-title">Atlas Mode <span class="beta-badge">Beta</span></h2>
        <label class="toggle-row">
            <span class="toggle-label">
                <span class="toggle-name">Enable Atlas Mode</span>
                <span class="toggle-desc">Adaptive test-time compute: generates multiple candidates, selects the best, repairs failures automatically.</span>
            </span>
            <button
                class="toggle-switch"
                class:on={$preferences.atlasMode}
                onclick={() => preferences.update(p => ({ ...p, atlasMode: !p.atlasMode }))}
                role="switch"
                aria-checked={$preferences.atlasMode}
            >
                <span class="toggle-knob"></span>
            </button>
        </label>

        {#if $preferences.atlasMode}
            <div class="atlas-settings">
                <!-- Effort Mode -->
                <div class="atlas-row">
                    <span class="atlas-label">Effort Level</span>
                    <div class="atlas-control">
                        <select
                            class="atlas-select"
                            value={$preferences.atlasEffortMode}
                            onchange={(e) => preferences.update(p => ({ ...p, atlasEffortMode: e.currentTarget.value as 'auto' | 'manual' }))}
                        >
                            <option value="auto">Auto (recommended)</option>
                            <option value="manual">Manual</option>
                        </select>
                    </div>
                </div>

                {#if $preferences.atlasEffortMode === 'manual'}
                    <div class="atlas-row">
                        <span class="atlas-label">Candidates (k)</span>
                        <div class="slider-container">
                            <input type="range"
                                min={1}
                                max={5}
                                step={1}
                                value={$preferences.atlasEffortLevel}
                                oninput={(e) => preferences.update(p => ({ ...p, atlasEffortLevel: parseInt(e.currentTarget.value) }))}
                            />
                            <span class="slider-value">{$preferences.atlasEffortLevel}</span>
                        </div>
                    </div>
                {/if}

                <!-- Sub-toggles -->
                <label class="toggle-row sub-toggle">
                    <span class="toggle-label">
                        <span class="toggle-name">Self-Verification</span>
                        <span class="toggle-desc">Generate tests and verify code outputs in sandbox.</span>
                    </span>
                    <button
                        class="toggle-switch"
                        class:on={$preferences.atlasSelfVerification}
                        onclick={() => preferences.update(p => ({ ...p, atlasSelfVerification: !p.atlasSelfVerification }))}
                        role="switch"
                        aria-checked={$preferences.atlasSelfVerification}
                    >
                        <span class="toggle-knob"></span>
                    </button>
                </label>

                <label class="toggle-row sub-toggle">
                    <span class="toggle-label">
                        <span class="toggle-name">Multi-Perspective Review</span>
                        <span class="toggle-desc">Analyze outputs from 4 angles: logic, completeness, assumptions, alternatives.</span>
                    </span>
                    <button
                        class="toggle-switch"
                        class:on={$preferences.atlasMultiPerspective}
                        onclick={() => preferences.update(p => ({ ...p, atlasMultiPerspective: !p.atlasMultiPerspective }))}
                        role="switch"
                        aria-checked={$preferences.atlasMultiPerspective}
                    >
                        <span class="toggle-knob"></span>
                    </button>
                </label>

                <label class="toggle-row sub-toggle">
                    <span class="toggle-label">
                        <span class="toggle-name">Iterative Refinement</span>
                        <span class="toggle-desc">Retry failing outputs with failure analysis and targeted repair.</span>
                    </span>
                    <button
                        class="toggle-switch"
                        class:on={$preferences.atlasIterativeRefinement}
                        onclick={() => preferences.update(p => ({ ...p, atlasIterativeRefinement: !p.atlasIterativeRefinement }))}
                        role="switch"
                        aria-checked={$preferences.atlasIterativeRefinement}
                    >
                        <span class="toggle-knob"></span>
                    </button>
                </label>
            </div>
        {/if}
    </section>
```

**Step 2: Add Atlas CSS styles**

Add before the closing `</style>` tag:

```css
    /* ── Atlas Mode ── */
    .beta-badge {
        font-size: 10px;
        font-weight: 600;
        color: var(--text-muted);
        background: rgba(210, 153, 34, 0.12);
        border: 1px solid rgba(210, 153, 34, 0.25);
        padding: 1px 6px;
        border-radius: var(--radius-pill);
        vertical-align: middle;
        margin-left: 6px;
        text-transform: none;
        letter-spacing: 0;
    }
    .atlas-settings {
        display: flex;
        flex-direction: column;
        gap: 6px;
        margin-top: 8px;
    }
    .atlas-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        padding: 10px 18px;
        background: var(--bubble);
        border: var(--bubble-border);
        border-radius: var(--radius);
        box-shadow: var(--shadow-xs);
    }
    .atlas-label {
        font-size: 13px;
        font-weight: 550;
        color: var(--text);
    }
    .atlas-control {
        flex-shrink: 0;
    }
    .atlas-select {
        font-family: inherit;
        font-size: 12.5px;
        color: var(--text);
        background: var(--bg);
        border: 1px solid var(--border);
        border-radius: var(--radius-sm);
        padding: 4px 10px;
        cursor: pointer;
        outline: none;
    }
    .atlas-select:focus {
        border-color: var(--text-muted);
    }
    .sub-toggle {
        padding: 10px 18px;
    }
    .sub-toggle .toggle-name {
        font-size: 13px;
    }
    .sub-toggle .toggle-desc {
        font-size: 11.5px;
    }
```

**Step 3: Type check**

Run: `cd ct1/web && npm run check`
Expected: PASS

**Step 4: Commit**

```bash
git add ct1/web/src/routes/settings/+page.svelte
git commit -m "feat(atlas): add Atlas Mode settings UI with toggles and effort slider"
```

---

### Task 4: Create Atlas controller — difficulty estimation and compute budget

**Files:**
- Create: `ct1/core/atlas.py`

**Step 1: Write the Atlas controller with difficulty estimation and K selection**

```python
"""Atlas Mode: Adaptive test-time compute pipeline for CT-2.

Wraps the Orchestrator's _pipeline() to generate multiple candidates,
select the best via testing + self-evaluation, and repair failures
via multi-perspective analysis.

When disabled, this module is never imported — zero overhead.
"""
import asyncio
import re
import time
import json
from dataclasses import dataclass, field

# ── Difficulty estimation signals ────────────────────────────────

_COMPLEXITY_KEYWORDS = {
    # High-complexity signals (weight 1.0 each, max ~5)
    "algorithm", "optimize", "efficient", "performance", "concurrent",
    "recursive", "dynamic programming", "binary search", "graph",
    "tree", "sort", "hash", "cache", "async", "parallel",
    "authentication", "database", "api", "websocket", "encryption",
    "responsive", "animated", "accessible", "interactive", "realtime",
}

_SIMPLE_SIGNALS = {
    "hello", "hi", "thanks", "explain", "what is", "define",
    "list", "show", "print", "log",
}


@dataclass
class AtlasConfig:
    """Atlas settings from frontend preferences."""
    enabled: bool = False
    effort_mode: str = "auto"       # "auto" or "manual"
    effort_level: int = 3           # 1-5 (manual mode)
    self_verification: bool = True
    multi_perspective: bool = True
    iterative_refinement: bool = True


@dataclass
class ComputeBudget:
    """Computed resource allocation for a request."""
    k: int = 1                      # Number of candidates
    thinking_tier: str = "standard" # nothink, light, standard, hard, extreme
    thinking_tokens: int = 2048     # Token budget for thinking
    difficulty: float = 0.0         # 0.0-1.0 difficulty score


# ── Thinking tier mapping ────────────────────────────────────────

_THINKING_TIERS = {
    "nothink":  0,
    "light":    1024,
    "standard": 2048,
    "hard":     4096,
    "extreme":  8192,
}

# ── K selection table (auto mode) ────────────────────────────────

_K_TABLE = [
    (0.2, 1),   # trivial
    (0.4, 1),   # low
    (0.6, 2),   # medium
    (0.8, 3),   # hard
    (1.0, 5),   # extreme
]


def _estimate_difficulty(
    message: str,
    conversation: list[dict],
    cache_hit: float = 0.0,
    pattern_match: float = 0.0,
) -> float:
    """Estimate request difficulty from heuristic signals. Returns 0.0-1.0.

    Four signals:
      - cache_hit: 0.0 (no match) to 1.0 (exact match) from component cache
      - pattern_match: 0.0 (novel) to 1.0 (seen before) from journal lessons
      - complexity: keyword density + length heuristic
      - conversation_depth: deeper edit chains are harder
    """
    lower = message.lower()

    # Complexity signal: keyword hits + length
    hits = sum(1 for kw in _COMPLEXITY_KEYWORDS if kw in lower)
    simple_hits = sum(1 for kw in _SIMPLE_SIGNALS if kw in lower)
    length_factor = min(len(message) / 1000, 1.0)  # long prompts tend harder
    complexity = min((hits * 0.15 + length_factor * 0.3 - simple_hits * 0.1), 1.0)
    complexity = max(complexity, 0.0)

    # Conversation depth signal
    depth = len([t for t in conversation if t.get("role") == "user"])
    depth_signal = min(depth / 8, 1.0)  # caps at 8 turns

    # Weighted sum
    d = (0.30 * (1.0 - cache_hit)
         + 0.25 * (1.0 - pattern_match)
         + 0.20 * complexity
         + 0.25 * depth_signal)

    return round(min(max(d, 0.0), 1.0), 3)


def _select_k(difficulty: float) -> int:
    """Map difficulty to candidate count."""
    for threshold, k in _K_TABLE:
        if difficulty <= threshold:
            return k
    return 5


def _select_thinking_tier(difficulty: float) -> tuple[str, int]:
    """Map difficulty to thinking tier and token budget."""
    if difficulty < 0.1:
        tier = "nothink"
    elif difficulty < 0.3:
        tier = "light"
    elif difficulty < 0.5:
        tier = "standard"
    elif difficulty < 0.7:
        tier = "hard"
    else:
        tier = "extreme"
    return tier, _THINKING_TIERS[tier]


def compute_budget(
    config: AtlasConfig,
    message: str,
    conversation: list[dict],
    cache_hit: float = 0.0,
    pattern_match: float = 0.0,
) -> ComputeBudget:
    """Determine compute allocation for a request."""
    difficulty = _estimate_difficulty(message, conversation, cache_hit, pattern_match)

    if config.effort_mode == "manual":
        k = config.effort_level
    else:
        k = _select_k(difficulty)

    tier, tokens = _select_thinking_tier(difficulty)

    return ComputeBudget(
        k=k,
        thinking_tier=tier,
        thinking_tokens=tokens,
        difficulty=difficulty,
    )


# ── DivSampling: Prompt perturbations ───────────────────────────

_ROLE_PERTURBATIONS = [
    "You are a senior systems engineer focused on correctness, edge cases, and production-readiness.",
    "You are a pragmatic developer who prioritizes simplicity, readability, and maintainability.",
    "You are a perfectionist architect who designs for scalability, elegance, and optimal performance.",
    "You are a creative designer who balances aesthetics with functionality and user delight.",
]

_INSTRUCTION_PERTURBATIONS = [
    "Think step-by-step. Break the problem into subproblems before writing code.",
    "Start by identifying edge cases and failure modes. Handle those first, then build the happy path.",
    "Focus on constraints: what are the hard requirements? Satisfy those precisely.",
    "Think from the user's perspective. What would they expect? Design the interface first, then implement.",
]

_STYLE_PERTURBATIONS = [
    "Prefer minimal, clean solutions. Remove anything unnecessary.",
    "Be comprehensive. Cover all cases. Include thorough error handling.",
    "Optimize iteratively: write a working solution first, then improve performance.",
    "Use structured patterns: clear separation of concerns, named constants, explicit types.",
]


def get_perturbation(candidate_index: int) -> str:
    """Select a prompt perturbation for candidate N.
    Cycles through one from each category."""
    role = _ROLE_PERTURBATIONS[candidate_index % len(_ROLE_PERTURBATIONS)]
    instruction = _INSTRUCTION_PERTURBATIONS[candidate_index % len(_INSTRUCTION_PERTURBATIONS)]
    style = _STYLE_PERTURBATIONS[candidate_index % len(_STYLE_PERTURBATIONS)]
    return f"{role}\n{instruction}\n{style}"


# ── PlanSearch: Constraint extraction ────────────────────────────

CONSTRAINT_EXTRACTION_PROMPT = (
    "Read this problem carefully. Identify {n} distinct CONSTRAINT SETS.\n"
    "Each constraint set is a different angle or priority for solving this problem.\n"
    "For each set, list 3-5 specific constraints that a solution must satisfy.\n\n"
    "Output JSON array of constraint sets:\n"
    "```json\n"
    '[{{"focus": "description", "constraints": ["c1", "c2", "c3"]}}]\n'
    "```\n\n"
    "Problem:\n{problem}"
)

PLAN_FROM_CONSTRAINTS_PROMPT = (
    "Based on these constraints, design a solution plan.\n\n"
    "Constraints:\n{constraints}\n\n"
    "Original problem:\n{problem}\n\n"
    "Output a step-by-step plan (3-6 steps). Be specific about data structures, "
    "algorithms, and patterns you'll use. Keep it concise."
)


# ── Self-Test Generation ─────────────────────────────────────────

SELF_TEST_PROMPT = (
    "Given this problem, generate {n} test cases to verify a solution's correctness.\n\n"
    "Problem:\n{problem}\n\n"
    "For each test case, provide:\n"
    "- Input (as it would be passed to the solution)\n"
    "- Expected output\n"
    "- Brief rationale (what edge case or scenario this covers)\n\n"
    "Output JSON array:\n"
    "```json\n"
    '[{{"input": "...", "expected": "...", "rationale": "..."}}]\n'
    "```"
)

DESIGN_TEST_PROMPT = (
    "Given this design request, generate a checklist of {n} structural/quality checks.\n\n"
    "Request:\n{problem}\n\n"
    "For each check:\n"
    "- What to verify (e.g., 'has navigation bar', 'is responsive at 768px')\n"
    "- How to verify it (look for specific HTML elements, CSS properties, etc.)\n\n"
    "Output JSON array:\n"
    "```json\n"
    '[{{"check": "...", "how": "..."}}]\n'
    "```"
)


# ── Failure Analysis ─────────────────────────────────────────────

FAILURE_ANALYSIS_PROMPT = (
    "Analyze why this code failed. Categorize the failure.\n\n"
    "Problem:\n{problem}\n\n"
    "Code:\n```\n{code}\n```\n\n"
    "Test output / error:\n{error}\n\n"
    "Categorize as ONE of:\n"
    "- wrong_algorithm: correct structure but fundamentally wrong approach\n"
    "- implementation_bug: right approach, but has a bug (off-by-one, typo, wrong operator)\n"
    "- edge_case_miss: works for basic cases, fails on edge cases\n"
    "- timeout: too slow, needs better algorithm or optimization\n"
    "- format_error: wrong output format (missing newline, wrong delimiter)\n"
    "- incomplete: missing required sections or features\n\n"
    "Output JSON:\n"
    "```json\n"
    '{{"category": "...", "diagnosis": "brief explanation", "fix_hint": "what to change"}}\n'
    "```"
)


# ── PR-CoT Repair ────────────────────────────────────────────────

PRCOT_CODE_PROMPT = (
    "Analyze this failing code from 4 perspectives, then fix it.\n\n"
    "Problem:\n{problem}\n\n"
    "Failing code:\n```\n{code}\n```\n\n"
    "Error:\n{error}\n\n"
    "Analyze from these perspectives:\n"
    "1. LOGICAL CONSISTENCY: Check loop bounds, conditionals, off-by-one errors\n"
    "2. INFORMATION COMPLETENESS: Are there missing cases or unhandled input ranges?\n"
    "3. UNSTATED ASSUMPTIONS: Any hardcoded values or implicit constraints?\n"
    "4. ALTERNATIVE APPROACHES: Would a different algorithm/data structure work better?\n\n"
    "After analysis, output the COMPLETE corrected code."
)

PRCOT_DESIGN_PROMPT = (
    "Review this HTML/CSS from 4 design perspectives, then improve it.\n\n"
    "Original request:\n{problem}\n\n"
    "Current code:\n```html\n{code}\n```\n\n"
    "Issues found:\n{error}\n\n"
    "Analyze from these perspectives:\n"
    "1. VISUAL HIERARCHY: Is the layout scannable? Do CTAs stand out?\n"
    "2. COMPLETENESS: Any missing sections? Broken responsive breakpoints?\n"
    "3. CONSISTENCY: Color, typography, spacing coherence throughout?\n"
    "4. ACCESSIBILITY: Contrast ratios, semantic HTML, keyboard navigation?\n\n"
    "After analysis, output the COMPLETE improved HTML."
)


# ── Constraint Refinement ────────────────────────────────────────

CONSTRAINT_REFINEMENT_PROMPT = (
    "Previous solution attempts failed. Generate refined constraints.\n\n"
    "Problem:\n{problem}\n\n"
    "Failure type: {failure_category}\n"
    "Diagnosis: {diagnosis}\n\n"
    "Generate a refined constraint set that specifically addresses this failure.\n"
    "Output JSON:\n"
    "```json\n"
    '{{"focus": "addressing {failure_category}", "constraints": ["c1", "c2", "c3"]}}\n'
    "```"
)


# ── Atlas Controller ─────────────────────────────────────────────

class AtlasController:
    """Orchestrates multi-candidate generation with test-time compute."""

    def __init__(self, orchestrator):
        """Hold a reference to the parent Orchestrator."""
        self.orch = orchestrator

    async def run(
        self,
        goal,
        conversation: list[dict],
        atlas_settings: dict,
        on_event=None,
        mode_override: str | None = None,
        skip_refinement: bool = False,
    ) -> dict:
        """Main Atlas entry point. Returns same dict shape as _pipeline()."""
        config = AtlasConfig(
            enabled=atlas_settings.get("atlasMode", False),
            effort_mode=atlas_settings.get("effortMode", "auto"),
            effort_level=atlas_settings.get("effortLevel", 3),
            self_verification=atlas_settings.get("selfVerification", True),
            multi_perspective=atlas_settings.get("multiPerspective", True),
            iterative_refinement=atlas_settings.get("iterativeRefinement", True),
        )

        goal_text = goal if isinstance(goal, str) else " ".join(
            p.get("text", "") for p in goal if isinstance(p, dict) and p.get("type") == "text"
        )

        def emit(event: str, **data):
            if on_event:
                on_event(event, **data)

        # ── Difficulty estimation ──
        cache_hit = await self._check_cache_similarity(goal_text)
        pattern_match = self._check_journal_patterns(goal_text)
        budget = compute_budget(config, goal_text, conversation, cache_hit, pattern_match)

        emit("atlas_started", k=budget.k, difficulty=budget.difficulty,
             effort_tier=budget.thinking_tier)

        # ── Phase 1: Generate k candidates ──
        candidates = []
        best_candidate = None
        best_score = -1.0

        for i in range(budget.k):
            emit("candidate_start", index=i, total=budget.k,
                 perturbation=f"candidate_{i+1}")

            # Apply perturbation to system prompt
            perturbation = get_perturbation(i) if budget.k > 1 else None

            # Generate candidate via existing pipeline
            try:
                result = await self.orch._pipeline(
                    goal, on_event=on_event, conversation=conversation,
                    mode_override=mode_override,
                    skip_refinement=skip_refinement,
                    _atlas_perturbation=perturbation,
                    _atlas_thinking_budget=budget.thinking_tokens if budget.thinking_tier != "nothink" else 0,
                )
            except Exception as e:
                print(f"[atlas] candidate {i} failed: {e}")
                emit("candidate_scored", index=i, score=0.0)
                candidates.append({"result": None, "score": 0.0, "tests_passed": 0})
                continue

            # ── Score candidate ──
            score = 0.5  # default
            tests_passed = None
            tests_total = None

            route = result.get("route", "")

            # Self-verification for code routes
            if (config.self_verification
                    and route in ("ROUTE_CODE", "ROUTE_COMPUTER")
                    and result.get("response")):
                test_result = await self._run_self_tests(
                    goal_text, result["response"], route, emit)
                if test_result is not None:
                    tests_passed = test_result["passed"]
                    tests_total = test_result["total"]
                    score = tests_passed / tests_total if tests_total > 0 else 0.0

            # Self-evaluation fallback (design, chat, or when no tests)
            if tests_passed is None and result.get("response"):
                try:
                    reflection = await self.orch.engine.reflect(
                        goal_text, "atlas", result["response"][:500], conversation)
                    score = reflection.get("self_score", 0.5)
                except Exception:
                    score = 0.5

            candidates.append({
                "result": result,
                "score": score,
                "tests_passed": tests_passed or 0,
                "tests_total": tests_total or 0,
            })

            emit("candidate_scored", index=i, score=round(score, 3),
                 tests_passed=tests_passed, tests_total=tests_total)

            # ── ReASC: Early stopping ──
            if score > best_score:
                best_score = score
                best_candidate = i

            # Stop early if confident
            if (tests_passed is not None and tests_total
                    and tests_passed == tests_total):
                emit("candidate_selected", index=i, reason="all_tests_passed")
                return candidates[i]["result"]
            if score >= 0.9:
                emit("candidate_selected", index=i, reason="high_confidence")
                return candidates[i]["result"]

        # ── Phase 2: Select best candidate ──
        if best_candidate is not None and candidates[best_candidate]["result"]:
            # Check if best is good enough
            if best_score >= 0.7 or not config.iterative_refinement:
                emit("candidate_selected", index=best_candidate,
                     reason="best_score")
                return candidates[best_candidate]["result"]

        # ── Phase 3: Refinement loop (only if all candidates weak) ──
        if config.iterative_refinement and best_candidate is not None:
            best_result = candidates[best_candidate]["result"]
            if best_result:
                repaired = await self._refinement_loop(
                    config, goal, goal_text, best_result,
                    conversation, mode_override, skip_refinement, emit)
                if repaired:
                    return repaired

        # Return best we have
        if best_candidate is not None and candidates[best_candidate]["result"]:
            emit("candidate_selected", index=best_candidate,
                 reason="best_available")
            return candidates[best_candidate]["result"]

        # Fallback: run pipeline without Atlas
        return await self.orch._pipeline(
            goal, on_event=on_event, conversation=conversation,
            mode_override=mode_override, skip_refinement=skip_refinement)

    async def _run_self_tests(self, goal: str, code: str, route: str,
                              emit) -> dict | None:
        """Generate and run self-tests against candidate code.
        Returns {"passed": int, "total": int} or None if testing not applicable."""
        emit("atlas_testing", test_count=5)

        # Generate test cases
        prompt = SELF_TEST_PROMPT.format(problem=goal[:2000], n=5)
        try:
            test_result = await self.orch.engine._call(
                [{"role": "system", "content": "You are a test engineer. Output only JSON."},
                 {"role": "user", "content": prompt}],
                enable_thinking=False,
            )
            tests = self._parse_json_from_response(test_result.get("text", ""))
            if not tests or not isinstance(tests, list):
                return None
        except Exception as e:
            print(f"[atlas] self-test generation failed: {e}")
            return None

        emit("atlas_tests_ready", tests=len(tests))

        # For code routes, try to execute tests
        if route == "ROUTE_CODE":
            return await self._execute_code_tests(code, tests)

        # For computer route, would use workspace — simplified here
        return None

    async def _execute_code_tests(self, code: str, tests: list[dict]) -> dict:
        """Execute code against test cases via subprocess.
        Returns {"passed": int, "total": int}."""
        import subprocess
        import tempfile
        import os

        passed = 0
        total = len(tests)

        # Extract raw code from markdown fences
        clean_code = code
        if "```" in code:
            blocks = re.findall(r"```(?:\w+)?\n(.*?)```", code, re.DOTALL)
            if blocks:
                clean_code = blocks[0]

        for test in tests:
            test_input = test.get("input", "")
            expected = str(test.get("expected", "")).strip()
            if not expected:
                total -= 1
                continue

            # Create test script that runs the code with test input
            test_script = f"{clean_code}\n\n# Auto-test\nprint({test_input})"

            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".py", delete=False, encoding="utf-8"
                ) as f:
                    f.write(test_script)
                    tmp_path = f.name

                proc = subprocess.run(
                    ["python", tmp_path],
                    capture_output=True, text=True, timeout=10,
                )
                actual = proc.stdout.strip()
                if actual == expected:
                    passed += 1
            except Exception:
                pass
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        return {"passed": passed, "total": max(total, 1)}

    async def _refinement_loop(
        self, config: AtlasConfig, goal, goal_text: str,
        best_result: dict, conversation: list[dict],
        mode_override, skip_refinement, emit,
    ) -> dict | None:
        """Phase 3: Analyze failure, attempt PR-CoT repair, then constrained retry.
        Returns repaired result or None."""
        route = best_result.get("route", "")
        code = best_result.get("response", "")
        max_iterations = 2

        for iteration in range(max_iterations):
            # ── Failure analysis ──
            emit("atlas_repair", iteration=iteration + 1,
                 strategy="analysis", failure_type="unknown")

            analysis = await self._analyze_failure(goal_text, code, route)
            failure_type = analysis.get("category", "implementation_bug") if analysis else "implementation_bug"

            emit("atlas_repair", iteration=iteration + 1,
                 strategy="pr_cot", failure_type=failure_type)

            # ── PR-CoT repair ──
            if config.multi_perspective:
                repaired_code = await self._prcot_repair(
                    goal_text, code, route, analysis)
                if repaired_code:
                    # Score the repair
                    repair_result = dict(best_result)
                    repair_result["response"] = repaired_code

                    if config.self_verification and route in ("ROUTE_CODE", "ROUTE_COMPUTER"):
                        test_result = await self._run_self_tests(
                            goal_text, repaired_code, route, emit)
                        if test_result and test_result["passed"] == test_result["total"]:
                            emit("atlas_repair_result", passed=True,
                                 score=1.0)
                            # Store lesson
                            self._store_lesson(goal_text, failure_type, analysis)
                            return repair_result

                    # Self-eval for non-code or when tests not definitive
                    try:
                        reflection = await self.orch.engine.reflect(
                            goal_text, "atlas_repair", repaired_code[:500], conversation)
                        repair_score = reflection.get("self_score", 0.5)
                        if repair_score >= 0.8:
                            emit("atlas_repair_result", passed=True,
                                 score=repair_score)
                            self._store_lesson(goal_text, failure_type, analysis)
                            repair_result["reflection"] = reflection
                            return repair_result
                    except Exception:
                        pass

            emit("atlas_repair_result", passed=False, score=0.0)

            # ── Constraint refinement + retry ──
            if config.iterative_refinement and iteration < max_iterations - 1:
                refined = await self._refine_constraints(
                    goal_text, failure_type,
                    analysis.get("diagnosis", "") if analysis else "")
                if refined:
                    # Retry with refined constraints as context
                    refined_goal = (
                        f"IMPORTANT CONSTRAINTS (from previous failure analysis):\n"
                        f"{json.dumps(refined, indent=2)}\n\n"
                        f"Original request:\n{goal_text}"
                    )
                    try:
                        retry_result = await self.orch._pipeline(
                            refined_goal if isinstance(goal, str) else goal,
                            on_event=on_event if iteration == max_iterations - 1 else None,
                            conversation=conversation,
                            mode_override=mode_override,
                            skip_refinement=skip_refinement,
                        )
                        code = retry_result.get("response", "")
                        best_result = retry_result
                    except Exception:
                        pass

        return None

    async def _analyze_failure(self, goal: str, code: str, route: str) -> dict | None:
        """Categorize why a candidate failed."""
        prompt = FAILURE_ANALYSIS_PROMPT.format(
            problem=goal[:1500],
            code=code[:3000],
            error="Low confidence score / potential issues detected",
        )
        try:
            result = await self.orch.engine._call(
                [{"role": "system", "content": "You are a code analyst. Output only JSON."},
                 {"role": "user", "content": prompt}],
                enable_thinking=False,
            )
            return self._parse_json_from_response(result.get("text", ""))
        except Exception:
            return None

    async def _prcot_repair(self, goal: str, code: str, route: str,
                            analysis: dict | None) -> str | None:
        """Multi-perspective repair. Returns corrected code or None."""
        error_desc = ""
        if analysis:
            error_desc = f"Category: {analysis.get('category', 'unknown')}\n"
            error_desc += f"Diagnosis: {analysis.get('diagnosis', '')}\n"
            error_desc += f"Hint: {analysis.get('fix_hint', '')}"

        if route == "ROUTE_DESIGN":
            prompt = PRCOT_DESIGN_PROMPT.format(
                problem=goal[:1500], code=code[:6000], error=error_desc)
        else:
            prompt = PRCOT_CODE_PROMPT.format(
                problem=goal[:1500], code=code[:4000], error=error_desc)

        try:
            result = await self.orch.engine._call(
                [{"role": "system", "content": "You are an expert debugger and code reviewer."},
                 {"role": "user", "content": prompt}],
                enable_thinking=True,
            )
            text = result.get("text", "").strip()
            if text and len(text) > 50:
                return text
        except Exception:
            pass
        return None

    async def _refine_constraints(self, goal: str, failure_category: str,
                                  diagnosis: str) -> dict | None:
        """Generate refined constraints addressing the failure."""
        prompt = CONSTRAINT_REFINEMENT_PROMPT.format(
            problem=goal[:1500],
            failure_category=failure_category,
            diagnosis=diagnosis,
        )
        try:
            result = await self.orch.engine._call(
                [{"role": "system", "content": "Output only JSON."},
                 {"role": "user", "content": prompt}],
                enable_thinking=False,
            )
            return self._parse_json_from_response(result.get("text", ""))
        except Exception:
            return None

    async def _check_cache_similarity(self, goal: str) -> float:
        """Check component cache for similar past outputs. Returns 0.0-1.0."""
        if not hasattr(self.orch, 'component_cache') or not self.orch.component_cache:
            return 0.0
        try:
            keywords = [w for w in goal.lower().split() if len(w) > 3][:5]
            results = await self.orch.component_cache.search_similar(keywords, limit=1)
            return 0.8 if results else 0.0
        except Exception:
            return 0.0

    def _check_journal_patterns(self, goal: str) -> float:
        """Check journal for matching lessons. Returns 0.0-1.0."""
        try:
            reader = self.orch.journal_reader
            lessons = reader.get_recent_lessons(20)
            lower = goal.lower()
            matches = sum(1 for l in lessons if any(
                w in lower for w in l.lower().split() if len(w) > 4))
            return min(matches / 5.0, 1.0)
        except Exception:
            return 0.0

    def _store_lesson(self, goal: str, failure_type: str,
                      analysis: dict | None):
        """Store a metacognitive lesson in the journal."""
        try:
            self.orch.journal.write({
                "type": "atlas_lesson",
                "problem_summary": goal[:200],
                "failure_category": failure_type,
                "diagnosis": analysis.get("diagnosis", "") if analysis else "",
                "fix_hint": analysis.get("fix_hint", "") if analysis else "",
                "confidence": 1.0,
            })
        except Exception as e:
            print(f"[atlas] lesson store failed: {e}")

    @staticmethod
    def _parse_json_from_response(text: str):
        """Extract JSON from an LLM response (may be in markdown fences)."""
        text = text.strip()
        # Try direct parse
        try:
            return json.loads(text)
        except Exception:
            pass
        # Try extracting from markdown fences
        if "```" in text:
            match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1).strip())
                except Exception:
                    pass
        # Try finding first [ or { to end
        for start_char, end_char in [("[", "]"), ("{", "}")]:
            start = text.find(start_char)
            end = text.rfind(end_char)
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end + 1])
                except Exception:
                    pass
        return None
```

**Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('ct1/core/atlas.py').read()); print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add ct1/core/atlas.py
git commit -m "feat(atlas): create Atlas controller with difficulty estimation, DivSampling, PlanSearch, self-tests, PR-CoT repair, and refinement loop"
```

---

### Task 5: Integrate Atlas controller into Orchestrator

**Files:**
- Modify: `ct1/core/orchestrator.py:1-12` (imports)
- Modify: `ct1/core/orchestrator.py:1032-1035` (_pipeline signature)
- Modify: `ct1/core/orchestrator.py:1520-1528` (think method)

**Step 1: Add Atlas import and initialization**

After the existing imports (around line 27), add:

```python
from ct1.core.atlas import AtlasController
```

Find the `__init__` method of `Orchestrator` and add at the end:

```python
        self.atlas = AtlasController(self)
```

**Step 2: Add atlas parameters to `_pipeline` signature**

Modify the `_pipeline` method signature (line 1032) to accept atlas parameters:

```python
    async def _pipeline(self, goal, on_event=None,
                        conversation: list[dict] = None,
                        mode_override: str | None = None,
                        skip_refinement: bool = False,
                        _atlas_perturbation: str | None = None,
                        _atlas_thinking_budget: int | None = None) -> dict:
```

Then in the GENERATE phase, when calling `self.engine.generate()`, pass the perturbation as a prefix to the goal if present. Find where `self.engine.generate(` is called and wrap the goal:

```python
        # Apply Atlas perturbation if present
        generation_goal = goal
        if _atlas_perturbation:
            goal_text_for_gen = _extract_text(goal)
            generation_goal = f"[APPROACH]\n{_atlas_perturbation}\n[/APPROACH]\n\n{goal_text_for_gen}"
```

**Step 3: Modify `think()` to route through Atlas**

Replace the `think` method (lines 1520-1528):

```python
    async def think(self, goal, on_event=None,
                    conversation: list[dict] = None,
                    mode_override: str | None = None,
                    skip_refinement: bool = False,
                    atlas_settings: dict | None = None) -> dict:
        if atlas_settings and atlas_settings.get("atlasMode"):
            return await self.atlas.run(
                goal, conversation=conversation or [],
                atlas_settings=atlas_settings,
                on_event=on_event,
                mode_override=mode_override,
                skip_refinement=skip_refinement,
            )
        return await self._pipeline(
            goal, on_event=on_event, conversation=conversation or [],
            mode_override=mode_override,
            skip_refinement=skip_refinement,
        )
```

**Step 4: Verify syntax**

Run: `python -c "import ast; ast.parse(open('ct1/core/orchestrator.py').read()); print('OK')"`
Expected: `OK`

**Step 5: Commit**

```bash
git add ct1/core/orchestrator.py
git commit -m "feat(atlas): integrate Atlas controller into Orchestrator.think()"
```

---

### Task 6: Pass Atlas settings through API WebSocket

**Files:**
- Modify: `ct1/server/api.py:336-340` (run_think function)

**Step 1: Extract atlas settings from WebSocket message**

In `run_think()` (around line 336), where `mode_override` and `skip_refinement` are extracted from `msg`, add:

```python
                    atlas_settings = msg.get("atlas")
```

**Step 2: Pass to _orch.think()**

Modify the `_orch.think()` call (line 417) to include atlas_settings:

```python
                    result = await _orch.think(
                        actual_goal, on_event=on_event, conversation=conversation,
                        mode_override=mode_override,
                        skip_refinement=skip_refinement,
                        atlas_settings=atlas_settings,
                    )
```

**Step 3: Verify syntax**

Run: `python -c "import ast; ast.parse(open('ct1/server/api.py').read()); print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add ct1/server/api.py
git commit -m "feat(atlas): pass Atlas settings from WebSocket to Orchestrator"
```

---

### Task 7: Create AtlasProgress frontend component

**Files:**
- Create: `ct1/web/src/lib/components/AtlasProgress.svelte`

**Step 1: Write the component**

```svelte
<script lang="ts">
    import { chat } from '$lib/stores/chat';
    import type { AtlasCandidate, AtlasEffort } from '$lib/stores/chat';

    let expanded = $state(false);

    let active = $derived($chat.atlasActive);
    let phase = $derived($chat.atlasPhase);
    let candidates = $derived($chat.atlasCandidates);
    let effort = $derived($chat.atlasEffort);

    function phaseLabel(p: string | null): string {
        switch (p) {
            case 'estimating': return 'Estimating difficulty';
            case 'generating': return 'Generating candidates';
            case 'testing': return 'Running self-tests';
            case 'selecting': return 'Selecting best';
            case 'repairing': return 'Repairing failures';
            default: return 'Atlas';
        }
    }

    function statusIcon(status: string): string {
        switch (status) {
            case 'selected': return '\u2713';
            case 'scored': return '\u2022';
            case 'generating': return '\u25CB';
            case 'failed': return '\u2717';
            default: return '\u25CB';
        }
    }

    function tierLabel(tier: string): string {
        return tier.charAt(0).toUpperCase() + tier.slice(1);
    }
</script>

{#if active}
    <div class="atlas-progress">
        <button class="atlas-header" onclick={() => expanded = !expanded}>
            <span class="atlas-spinner"></span>
            <span class="atlas-phase">{phaseLabel(phase)}</span>
            {#if effort}
                <span class="atlas-meta">
                    k={effort.k} &middot; D={effort.difficulty.toFixed(2)} &middot; {tierLabel(effort.tier)}
                </span>
            {/if}
            <span class="atlas-chevron" class:open={expanded}></span>
        </button>

        {#if expanded && candidates.length > 0}
            <div class="atlas-candidates">
                {#each candidates as c, i}
                    <div class="atlas-candidate" class:active={c.status === 'generating'} class:selected={c.status === 'selected'}>
                        <span class="candidate-icon" class:done={c.status === 'scored' || c.status === 'selected'} class:fail={c.status === 'failed'}>
                            {statusIcon(c.status)}
                        </span>
                        <span class="candidate-label">Candidate {i + 1}</span>
                        {#if c.score !== null}
                            <span class="candidate-score">{(c.score * 100).toFixed(0)}%</span>
                        {/if}
                        {#if c.testsPassed !== null && c.testsTotal !== null}
                            <span class="candidate-tests">{c.testsPassed}/{c.testsTotal} tests</span>
                        {/if}
                    </div>
                {/each}
            </div>
        {/if}
    </div>
{/if}

<style>
    .atlas-progress {
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius-sm);
        background: var(--bubble);
        margin-bottom: 8px;
        overflow: hidden;
    }
    .atlas-header {
        display: flex;
        align-items: center;
        gap: 8px;
        width: 100%;
        padding: 8px 12px;
        background: none;
        border: none;
        cursor: pointer;
        font-family: inherit;
        font-size: 12.5px;
        color: var(--text-secondary);
        text-align: left;
    }
    .atlas-header:hover {
        background: var(--accent-subtle);
    }
    .atlas-spinner {
        width: 12px;
        height: 12px;
        border: 2px solid var(--border);
        border-top-color: var(--text-secondary);
        border-radius: 50%;
        animation: atlas-spin 0.7s linear infinite;
        flex-shrink: 0;
    }
    @keyframes atlas-spin { to { transform: rotate(360deg); } }

    .atlas-phase {
        font-weight: 600;
        color: var(--text);
    }
    .atlas-meta {
        font-family: var(--font-mono);
        font-size: 11px;
        color: var(--text-muted);
        margin-left: auto;
    }
    .atlas-chevron {
        width: 0;
        height: 0;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid var(--text-muted);
        transition: transform 0.15s;
        flex-shrink: 0;
    }
    .atlas-chevron.open {
        transform: rotate(180deg);
    }

    .atlas-candidates {
        padding: 4px 12px 8px;
        display: flex;
        flex-direction: column;
        gap: 4px;
    }
    .atlas-candidate {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 4px 8px;
        border-radius: var(--radius-sm);
        font-size: 12px;
        color: var(--text-secondary);
    }
    .atlas-candidate.active {
        background: var(--accent-subtle);
    }
    .atlas-candidate.selected {
        background: rgba(46, 160, 67, 0.08);
    }
    .candidate-icon {
        font-size: 11px;
        color: var(--text-muted);
        width: 14px;
        text-align: center;
    }
    .candidate-icon.done { color: var(--text-secondary); }
    .candidate-icon.fail { color: var(--error); }
    .candidate-label {
        font-weight: 500;
    }
    .candidate-score {
        font-family: var(--font-mono);
        font-size: 11px;
        font-weight: 600;
        color: var(--text);
        margin-left: auto;
    }
    .candidate-tests {
        font-family: var(--font-mono);
        font-size: 11px;
        color: var(--text-muted);
    }
</style>
```

**Step 2: Type check**

Run: `cd ct1/web && npm run check`
Expected: PASS

**Step 3: Commit**

```bash
git add ct1/web/src/lib/components/AtlasProgress.svelte
git commit -m "feat(atlas): create AtlasProgress component for candidate tracking UI"
```

---

### Task 8: Integrate AtlasProgress into main page

**Files:**
- Modify: `ct1/web/src/routes/+page.svelte`

**Step 1: Import and place AtlasProgress**

Add import at the top of the script section:

```typescript
import AtlasProgress from '$lib/components/AtlasProgress.svelte';
```

Place `<AtlasProgress />` in the template, just above the phase/status indicator area (wherever the "Generating..." / "Routing..." status text is shown). The exact location depends on the +page.svelte structure — find the phase indicator section and add `<AtlasProgress />` directly above it.

**Step 2: Type check**

Run: `cd ct1/web && npm run check`
Expected: PASS

**Step 3: Commit**

```bash
git add ct1/web/src/routes/+page.svelte
git commit -m "feat(atlas): integrate AtlasProgress component into main chat page"
```

---

### Task 9: End-to-end verification

**Step 1: Verify Python backend loads**

Run: `python -c "from ct1.core.atlas import AtlasController, compute_budget, AtlasConfig; print('Atlas module OK')"`
Expected: `Atlas module OK`

**Step 2: Verify orchestrator imports atlas**

Run: `python -c "from ct1.core.orchestrator import Orchestrator; print('Orchestrator OK')"`
Expected: `Orchestrator OK`

**Step 3: Verify frontend type checks**

Run: `cd ct1/web && npm run check`
Expected: PASS

**Step 4: Commit all remaining changes**

If any files were missed:
```bash
git add -A
git commit -m "feat(atlas): complete Atlas Mode beta integration"
```
