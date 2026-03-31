# Atlas Mode Integration — Design Document

**Date**: 2026-03-29
**Status**: Approved
**Source**: [ATLAS V3](https://github.com/itigges22/ATLAS) — Adaptive Test-time Learning and Autonomous Specialization

## Overview

Beta setting that wraps CT-2's existing pipeline in Atlas's test-time compute infrastructure. When enabled, the system generates multiple candidates with diverse prompting strategies, selects the best via ground-truth testing + self-evaluation, and iteratively repairs failures using multi-perspective analysis. When disabled, zero overhead — pipeline unchanged.

## Design Decisions

- **Auto-adaptive + manual override**: Difficulty estimation auto-selects candidate count (k). Users can override with a manual effort slider (1-5).
- **Tiered execution**: Single-file code validated via subprocess. Multi-file projects use existing computer mode sandbox.
- **Hybrid selection**: Test pass/fail is primary signal. Self-evaluation (Engine.reflect) is tiebreaker and fallback for non-executable outputs (design, chat).
- **Wrapper architecture**: Atlas controller calls `_pipeline()` multiple times with different parameters. Existing pipeline internals untouched.
- **New file `ct1/core/atlas.py`**: All Atlas logic isolated. Clean separation.

## Settings & Toggle

### Preferences Store (frontend)

```typescript
interface AtlasPreferences {
  atlasMode: boolean;              // Master toggle (default: false)
  atlasEffortMode: 'auto' | 'manual';  // Auto-adaptive vs manual
  atlasEffortLevel: number;        // 1-5 (manual mode only)
  atlasSelfVerification: boolean;  // Self-test generation + execution
  atlasMultiPerspective: boolean;  // PR-CoT 4-angle repair
  atlasIterativeRefinement: boolean; // Refinement loop
}
```

All stored in localStorage `ct2-preferences`. Sent to backend as part of WebSocket message payload.

### Settings UI

Atlas section in settings page with:
- Master toggle: "Atlas Mode (Beta)"
- Effort level: Auto (recommended) / Manual slider 1-5
- Sub-toggles: Self-Verification, Multi-Perspective Review, Iterative Refinement
- Collapsible, only expanded when master toggle is ON

## Backend Architecture

### Atlas Controller (`ct1/core/atlas.py`)

```
User message + atlas_settings
    │
    ▼
┌─ Difficulty Estimation ──────────────────────┐
│  D(x) = 0.30*(1-cache) + 0.25*(1-pattern)   │
│        + 0.20*complexity + 0.25*conv_depth   │
│  All heuristic, no AI call                   │
└──────────────────────────────────────────────┘
    │
    ▼
┌─ Compute Budget ─────────────────────────────┐
│  D(x) → k (candidate count)                  │
│  D(x) → thinking tier (nothink..extreme)     │
│  Manual override replaces auto values         │
└──────────────────────────────────────────────┘
    │
    ▼
┌─ Candidate Generation Loop ──────────────────┐
│  For i in range(k):                          │
│    1. Select perturbation (DivSampling)      │
│    2. Extract constraints (PlanSearch)        │
│    3. Generate via _pipeline() with mods     │
│    4. Score candidate (tests or reflection)  │
│    5. If confident → early stop (ReASC)      │
└──────────────────────────────────────────────┘
    │
    ▼
┌─ Selection ──────────────────────────────────┐
│  Best candidate by: test pass > score > first│
└──────────────────────────────────────────────┘
    │
    ▼ (only if ALL candidates failed)
┌─ Refinement Loop (max 2 iterations) ─────────┐
│  1. Self-test generation (once)              │
│  2. Failure analysis (categorize)            │
│  3. PR-CoT repair (4-perspective fix)        │
│  4. If repair passes → return                │
│  5. Constraint refinement → PlanSearch again │
│  6. Test new candidate                       │
│  7. If passes → return                       │
│  After max: return best-scoring candidate    │
└──────────────────────────────────────────────┘
```

### Integration Point

In `orchestrator.py`, the entry to `_pipeline()` checks `atlas_mode`:

```python
if atlas_settings and atlas_settings.get("atlasMode"):
    result = await self.atlas.run(message, conversation, atlas_settings, on_event)
else:
    result = await self._pipeline(message, conversation, on_event)
```

The Atlas controller holds a reference to the Orchestrator and calls `_pipeline()` internally.

## Phase 1: Constraint-Driven Generation

### PlanSearch

1. **Constraint extraction**: Single LLM call extracts N constraint sets from user request (N = k)
2. **Plan per constraint set**: One plan call per constraint set
3. **Code per plan**: One generation call per plan (via `_pipeline()`)

Route-specific:
- **ROUTE_CODE / ROUTE_COMPUTER**: Full PlanSearch (constraints → plans → candidates)
- **ROUTE_DESIGN**: Constraints become design variations (color approaches, layout strategies, interaction patterns)
- **ROUTE_DIRECT**: PlanSearch skipped — uses DivSampling only

### DivSampling (Prompt Perturbations)

12 perturbations across 3 categories:

| Category | Variants |
|----------|----------|
| Role | systems_engineer, designer, pragmatist, perfectionist |
| Instruction | step_by_step, edge_case_first, constraint_driven, user_empathy |
| Style | minimal, comprehensive, optimize_iteratively, structured |

One perturbation from each category selected per candidate. Prepended to system prompt.

### BudgetForcing (Adaptive Thinking)

| Tier | Tokens | D(x) Range |
|------|--------|------------|
| nothink | 0 | 0.0–0.1 |
| light | 1024 | 0.1–0.3 |
| standard | 2048 | 0.3–0.5 |
| hard | 4096 | 0.5–0.7 |
| extreme | 8192+ | 0.7–1.0 |

Replaces static `thinking_budget` from task_overrides when Atlas is active.

## Phase 2: Adaptive Compute Allocation

### Confidence Router

```python
D(x) = 0.30 * (1 - cache_hit)       # component cache similarity
     + 0.25 * (1 - pattern_match)    # journal lesson match
     + 0.20 * complexity              # keyword/length heuristic
     + 0.25 * conversation_depth      # edit chain depth
```

### Blend-ASC (K Selection)

| D(x) | k (auto) |
|-------|----------|
| 0.0–0.2 | 1 |
| 0.2–0.4 | 1 |
| 0.4–0.6 | 2 |
| 0.6–0.8 | 3 |
| 0.8–1.0 | 4-5 |

### ReASC (Early Stopping)

- Code: all self-tests pass → stop
- Design: self-eval > 0.9 → stop
- Chat: always k=1 unless manual override

## Phase 3: Self-Verified Iterative Refinement

Triggers only when all Phase 1 candidates fail.

### Self-Test Generation

Model generates test cases from problem statement alone:
- Code routes → unit tests (assert-based)
- Computer routes → integration tests (CLI I/O)
- Design routes → structural checklist ("has nav", "is responsive")

Generated once, reused across all candidates and refinement iterations.

### Failure Analysis

Six categories: `wrong_algorithm`, `implementation_bug`, `edge_case_miss`, `timeout`, `format_error`, `incomplete`. Single LLM call with failing code + test output.

### PR-CoT Repair

Four-perspective analysis in one prompt:

**Code routes:**
1. Logical consistency — loop bounds, conditionals, off-by-one
2. Information completeness — missing cases, unhandled ranges
3. Unstated assumptions — hardcoded values, implicit constraints
4. Alternative approaches — different algorithm/data structure

**Design routes:**
1. Visual hierarchy — layout scannability, CTA prominence
2. Completeness — missing sections, broken responsive breakpoints
3. Consistency — color/typography/spacing coherence
4. Accessibility — contrast, semantic HTML, keyboard nav

### Constraint Refinement

After failure analysis, generate new constraint sets addressing the specific failure. `wrong_algorithm` → algorithmic constraints. `edge_case_miss` → explicit edge case enumeration. Fed back into PlanSearch.

### Refinement Loop

```
Max 2 iterations:
  → Failure analysis
  → PR-CoT repair attempt
  → If passes: return
  → Constraint refinement → PlanSearch → test
  → If passes: return
After max: return best-scoring candidate
```

## Metacognitive Learning

### Failure Pattern Storage

On successful refinement, store lesson in journal system:

```json
{
  "type": "atlas_lesson",
  "problem_type": "sortable data table",
  "failure_category": "edge_case_miss",
  "compensating_constraint": "Always handle zero-length input arrays",
  "repair_strategy": "pr_cot",
  "confidence": 1.0
}
```

### Confidence Decay (Ebbinghaus)

- Creation: confidence = 1.0
- On cache hit (lesson helped): refresh to 1.0
- Daily decay: confidence *= 0.95
- Below 0.3: deprioritized, eventually pruned

### Feedback Loop

Stored lessons feed into:
1. Confidence Router's `pattern_match` signal
2. PlanSearch's constraint extraction prompt (compensating constraints injected)

## Frontend Changes

### New WebSocket Events

| Event | Data |
|-------|------|
| `atlas_started` | `{ k, difficulty, effort_tier }` |
| `candidate_start` | `{ index, total, perturbation }` |
| `candidate_scored` | `{ index, score, test_results }` |
| `candidate_selected` | `{ index, reason }` |
| `atlas_testing` | `{ test_count }` |
| `atlas_tests_ready` | `{ tests }` |
| `atlas_repair` | `{ iteration, strategy, failure_type }` |
| `atlas_repair_result` | `{ passed, score }` |

### Chat Store Additions

```typescript
atlasActive: boolean;
atlasCandidates: {
  index: number;
  score: number | null;
  testsPassed: number | null;
  testsTotal: number | null;
  status: 'pending' | 'generating' | 'scored' | 'selected' | 'failed';
}[];
atlasPhase: 'estimating' | 'generating' | 'testing' | 'selecting' | 'repairing' | null;
atlasEffort: { k: number; difficulty: number; tier: string } | null;
```

### New Component: AtlasProgress.svelte

Collapsible progress panel showing:
- Current Atlas phase
- Candidate list with status indicators
- Effort level and difficulty score
- Refinement iteration progress (when active)

### Settings Page Addition

Atlas section with master toggle, effort mode selector, and sub-toggles. Collapsed when master toggle is OFF.

## Files

| Action | File | Changes |
|--------|------|---------|
| New | `ct1/core/atlas.py` | Atlas controller, all pipeline logic |
| New | `ct1/web/src/lib/components/AtlasProgress.svelte` | Progress visualization |
| Modify | `ct1/core/orchestrator.py` | Atlas entry point, import + conditional |
| Modify | `ct1/web/src/lib/stores/preferences.ts` | Atlas preference fields |
| Modify | `ct1/web/src/lib/stores/chat.ts` | Atlas state fields + event handlers |
| Modify | `ct1/web/src/routes/settings/+page.svelte` | Atlas settings UI |
| Modify | `ct1/web/src/routes/+page.svelte` | AtlasProgress component integration |
| Modify | `ct1/server/api.py` | Pass atlas_settings through WebSocket |
