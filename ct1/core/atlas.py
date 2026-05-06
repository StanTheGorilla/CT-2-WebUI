"""CT-2 Atlas Controller: Adaptive compute allocation and multi-candidate selection.

Wraps the Orchestrator._pipeline() to:
  1. Estimate task difficulty from 4 signals
  2. Allocate a compute budget (k candidates, thinking tier)
  3. Generate diverse candidates via perturbation
  4. Score and select the best candidate
  5. Optionally repair failures via iterative refinement (PR-CoT)
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# ── Dataclasses ──────────────────────────────────────────────────────

@dataclass
class AtlasConfig:
    """Frontend-provided Atlas settings."""
    enabled: bool = False
    effort_mode: str = "auto"          # "auto" | "manual"
    effort_level: int = 3              # 1-5 (manual mode slider)
    self_verification: bool = True
    multi_perspective: bool = True
    iterative_refinement: bool = True

    @classmethod
    def from_dict(cls, d: dict | None) -> "AtlasConfig":
        if not d:
            return cls()
        return cls(
            enabled=d.get("enabled", False),
            effort_mode=d.get("effort_mode", "auto"),
            effort_level=d.get("effort_level", 3),
            self_verification=d.get("self_verification", True),
            multi_perspective=d.get("multi_perspective", True),
            iterative_refinement=d.get("iterative_refinement", True),
        )


@dataclass
class ComputeBudget:
    """Computed resource allocation for a single Atlas run."""
    k: int = 1                         # Number of candidates to generate
    thinking_tier: str = "standard"    # nothink | light | standard | hard | extreme
    thinking_tokens: int = 2048        # Token budget for thinking
    difficulty: float = 0.5            # Estimated difficulty 0.0-1.0


# ── Difficulty estimation ────────────────────────────────────────────

_COMPLEXITY_KEYWORDS = {
    "implement", "algorithm", "optimize", "architecture", "database",
    "concurrent", "distributed", "recursive", "dynamic programming",
    "authentication", "encryption", "security", "real-time", "streaming",
    "websocket", "microservice", "pipeline", "transform", "compile",
    "parser", "interpreter", "scheduler", "cache", "index", "migration",
    "deploy", "integration", "api", "framework", "protocol", "state machine",
    "neural", "gradient", "inference", "training", "embedding",
}


def _estimate_difficulty(
    message: str,
    conversation: list[dict],
    cache_hit: float,
    pattern_match: float,
) -> float:
    """Heuristic difficulty score 0.0-1.0 from 4 signals.

    D = 0.30 * (1 - cache_hit)
      + 0.25 * (1 - pattern_match)
      + 0.20 * complexity
      + 0.25 * conversation_depth
    """
    # Signal 1: cache_hit — how similar to cached components (0.0 = no match)
    cache_signal = 1.0 - min(max(cache_hit, 0.0), 1.0)

    # Signal 2: pattern_match — how well journal lessons match (0.0 = no match)
    pattern_signal = 1.0 - min(max(pattern_match, 0.0), 1.0)

    # Signal 3: complexity — keyword density + length
    lower = message.lower()
    keyword_hits = sum(1 for kw in _COMPLEXITY_KEYWORDS if kw in lower)
    keyword_density = min(keyword_hits / 5.0, 1.0)  # saturates at 5 hits
    length_factor = min(len(message) / 2000.0, 1.0)  # saturates at 2000 chars
    complexity = 0.6 * keyword_density + 0.4 * length_factor

    # Signal 4: conversation_depth — edit chain depth
    user_turns = sum(1 for m in conversation if m.get("role") == "user")
    depth = min(user_turns / 8.0, 1.0)  # saturates at 8 turns

    difficulty = (
        0.30 * cache_signal
        + 0.25 * pattern_signal
        + 0.20 * complexity
        + 0.25 * depth
    )
    return round(min(max(difficulty, 0.0), 1.0), 3)


# ── Budget selectors ────────────────────────────────────────────────

def _select_k(difficulty: float) -> int:
    """Map difficulty to candidate count."""
    if difficulty < 0.2:
        return 1
    elif difficulty < 0.4:
        return 1
    elif difficulty < 0.6:
        return 2
    elif difficulty < 0.8:
        return 3
    else:
        return 5


_THINKING_TIERS = [
    (0.1, "nothink",   0),
    (0.3, "light",     1024),
    (0.5, "standard",  2048),
    (0.7, "hard",      4096),
    (1.1, "extreme",   8192),  # 1.1 so difficulty=1.0 lands here
]


def _select_thinking_tier(difficulty: float) -> tuple[str, int]:
    """Map difficulty to (tier_name, thinking_token_budget)."""
    for threshold, name, tokens in _THINKING_TIERS:
        if difficulty < threshold:
            return name, tokens
    return "extreme", 8192


def compute_budget(
    config: AtlasConfig,
    message: str,
    conversation: list[dict],
    cache_hit: float,
    pattern_match: float,
) -> ComputeBudget:
    """Compute resource budget based on auto or manual mode."""
    if config.effort_mode == "manual":
        # Manual: map effort_level 1-5 to fixed budgets
        level = max(1, min(config.effort_level, 5))
        k_map = {1: 1, 2: 1, 3: 2, 4: 3, 5: 5}
        tier_map = {
            1: ("nothink", 0),
            2: ("light", 1024),
            3: ("standard", 2048),
            4: ("hard", 4096),
            5: ("extreme", 8192),
        }
        tier_name, tier_tokens = tier_map[level]
        return ComputeBudget(
            k=k_map[level],
            thinking_tier=tier_name,
            thinking_tokens=tier_tokens,
            difficulty=level / 5.0,
        )

    # Auto mode: estimate difficulty from signals
    difficulty = _estimate_difficulty(message, conversation, cache_hit, pattern_match)
    k = _select_k(difficulty)
    tier_name, tier_tokens = _select_thinking_tier(difficulty)

    return ComputeBudget(
        k=k,
        thinking_tier=tier_name,
        thinking_tokens=tier_tokens,
        difficulty=difficulty,
    )


# ── Diversity sampling perturbations ─────────────────────────────────

_CODE_PERTURBATIONS = [
    (
        "You are a senior software architect reviewing this from a systems perspective.",
        "Focus on correctness and completeness above all else.",
        "Use a methodical, step-by-step approach.",
    ),
    (
        "You are a performance engineer optimizing for speed and efficiency.",
        "Prioritize clean, maintainable code structure.",
        "Prototype the core logic first, then layer on presentation.",
    ),
    (
        "You are a pragmatic lead developer shipping production code.",
        "Optimize for minimal complexity while meeting all requirements.",
        "Start with the hardest constraint and build outward.",
    ),
    (
        "You are a security-conscious engineer ensuring robustness.",
        "Focus on edge cases, input validation, and defensive coding.",
        "Use a methodical, step-by-step approach.",
    ),
]

_DESIGN_PERTURBATIONS = [
    (
        "You are a brand designer who creates distinctive visual identities.",
        "Emphasize a bold, unique aesthetic that stands out from generic templates.",
        "Start with one signature visual detail and build the entire design around it.",
    ),
    (
        "You are a typographer and layout specialist.",
        "Prioritize rhythm, hierarchy, and whitespace over decoration.",
        "Begin with the content structure and let the typography drive the visual feel.",
    ),
    (
        "You are a creative director at a top design studio.",
        "Emphasize visual storytelling — every section should guide the visitor's eye.",
        "Design the hero first as the emotional anchor, then flow naturally downward.",
    ),
    (
        "You are a conversion-focused product designer.",
        "Every element should serve clarity and persuasion. Remove visual noise.",
        "Start from the CTA and work backwards — what must the visitor see and feel before clicking?",
    ),
]


def get_perturbation(index: int, route: str = "") -> str:
    """Get a combined perturbation string for candidate `index`.
    Index 0 returns empty string (baseline). Route-aware: design routes
    get design-specific perspectives, code routes get code perspectives."""
    if index == 0:
        return ""
    pool = _DESIGN_PERTURBATIONS if route == "ROUTE_DESIGN" else _CODE_PERTURBATIONS
    slot = (index - 1) % len(pool)
    role, instruction, style = pool[slot]
    return f"{role}\n{instruction}\n{style}"


# ── Prompt templates ─────────────────────────────────────────────────

CONSTRAINT_EXTRACTION_PROMPT = textwrap.dedent("""\
    Analyze this request and extract all explicit and implicit constraints.
    Return a JSON object with:
    - "constraints": list of constraint strings
    - "success_criteria": list of testable criteria
    - "edge_cases": list of potential edge cases

    Request: {goal}
""")

PLAN_FROM_CONSTRAINTS_PROMPT = textwrap.dedent("""\
    Given these constraints, create an implementation plan.
    Return a JSON object with:
    - "steps": list of implementation step strings
    - "priority_order": list of step indices in priority order
    - "risk_areas": list of areas that could fail

    Constraints:
    {constraints}
""")

SELF_TEST_PROMPT = textwrap.dedent("""\
    Generate test cases for this {route} output.
    The code should satisfy this goal: {goal}

    Return a JSON object with:
    - "tests": list of objects with "name", "input", "expected", "assertion_type"
    - "visual_checks": list of strings (for design routes)

    Code to test:
    {code}
""")

DESIGN_TEST_PROMPT = textwrap.dedent("""\
    Evaluate this HTML/CSS design output against the original goal.
    Score each criterion 0.0-1.0.

    Return a JSON object with:
    - "structure_score": float (correct HTML structure, semantic tags)
    - "style_score": float (visual quality, consistent styling)
    - "content_score": float (real content, no lorem ipsum, matches goal)
    - "responsive_score": float (mobile-friendly, breakpoints)
    - "overall": float (weighted average)
    - "issues": list of specific problems found

    Goal: {goal}
    Output:
    {code}
""")

FAILURE_ANALYSIS_PROMPT = textwrap.dedent("""\
    Analyze why this code fails to meet its goal.
    Categorize the failure and provide diagnosis.

    Return a JSON object with:
    - "category": one of "logic_error", "missing_feature", "structural", "style", "incomplete"
    - "diagnosis": detailed explanation of the root cause
    - "affected_areas": list of specific code sections affected
    - "fix_strategy": recommended approach to fix

    Goal: {goal}
    Route: {route}
    Code:
    {code}
""")

PRCOT_CODE_PROMPT = textwrap.dedent("""\
    You are repairing code that failed verification.
    Apply Plan-Refine Chain of Thought:

    1. PLAN: Review the failure analysis and plan your fix
    2. REFINE: Apply the fix while preserving all working functionality
    3. VERIFY: Check your fix addresses the root cause

    Failure analysis:
    {analysis}

    Original goal: {goal}
    Original code:
    {code}

    Output the complete fixed code. No explanations. No markdown fences for HTML.
""")

PRCOT_DESIGN_PROMPT = textwrap.dedent("""\
    You are repairing a design output that failed verification.
    Apply Plan-Refine Chain of Thought:

    1. PLAN: Review the failure analysis and plan your fix
    2. REFINE: Fix the design while preserving all working elements
    3. VERIFY: Ensure the fix addresses visual/structural issues

    Failure analysis:
    {analysis}

    Original goal: {goal}
    Original code:
    {code}

    Output the complete fixed HTML. From <!DOCTYPE html> to </html>.
""")

CONSTRAINT_REFINEMENT_PROMPT = textwrap.dedent("""\
    A previous attempt failed with this analysis:
    Category: {failure_category}
    Diagnosis: {diagnosis}

    Refine the constraints to prevent this failure.
    Return a JSON object with:
    - "refined_constraints": list of updated constraint strings
    - "additional_instructions": string with specific guidance to prevent the failure

    Original goal: {goal}
""")


# ── Atlas Controller ─────────────────────────────────────────────────

class AtlasController:
    """Orchestrates multi-candidate generation with adaptive compute."""

    def __init__(self, orchestrator):
        self.orch = orchestrator

    async def run(
        self,
        goal,
        conversation: list[dict],
        atlas_settings: dict | None,
        on_event: Callable | None = None,
        mode_override: str | None = None,
        skip_refinement: bool = False,
    ) -> dict:
        """Main Atlas entry point. Generates multiple candidates, selects best,
        and optionally repairs failures."""

        config = AtlasConfig.from_dict(atlas_settings)
        goal_text = _extract_goal_text(goal)

        def emit(event: str, **data):
            if on_event:
                on_event(event, **data)

        # ── Gather signals for difficulty estimation ──
        cache_hit = await self._check_cache_similarity(goal_text)
        pattern_match = self._check_journal_patterns(goal_text)

        # ── Compute budget ──
        budget = compute_budget(
            config, goal_text, conversation, cache_hit, pattern_match,
        )

        emit("atlas_started",
             difficulty=budget.difficulty,
             k=budget.k,
             effort_tier=budget.thinking_tier)

        # ── Generate k candidates ──
        # Candidate 0 (baseline) streams tokens to the UI normally.
        # Candidates 1+ run silently — only atlas-level events reach the frontend.
        # Allowlist: only these atlas-level events pass through for silent candidates.
        # Everything else (pipeline phases, tokens, thinking) is suppressed.
        _ATLAS_EVENTS = {
            "atlas_started", "atlas_testing", "atlas_repair", "atlas_repair_result",
            "candidate_start", "candidate_scored", "candidate_selected",
            "atlas_test_error", "warning", "error",
        }

        def _silent_event(event: str, **data):
            """Only pass atlas-level events; suppress all pipeline events."""
            if event in _ATLAS_EVENTS and on_event:
                on_event(event, **data)

        # Determine route for route-aware perturbations
        _MODE_ROUTES = {"design": "ROUTE_DESIGN", "code": "ROUTE_CODE",
                        "chat": "ROUTE_DIRECT", "computer": "ROUTE_COMPUTER"}
        detected_route = _MODE_ROUTES.get(mode_override or "", "")
        if not detected_route:
            detected_route = self.orch._deterministic_route(goal_text)

        candidates: list[dict] = []
        scores: list[float] = []

        for i in range(budget.k):
            perturbation = get_perturbation(i, route=detected_route) if config.multi_perspective else ""

            # Prepend perturbation to goal text
            if perturbation:
                if isinstance(goal, list):
                    perturbed_goal = _prepend_to_goal(goal, perturbation)
                else:
                    perturbed_goal = f"[APPROACH]\n{perturbation}\n[/APPROACH]\n\n{goal}"
            else:
                perturbed_goal = goal

            emit("candidate_start", index=i, total=budget.k)

            # Candidate 0 streams live; candidates 1+ run silently
            pipeline_event = on_event if i == 0 else _silent_event

            try:
                result = await self.orch._pipeline(
                    perturbed_goal,
                    on_event=pipeline_event,
                    conversation=conversation,
                    mode_override=mode_override,
                    skip_refinement=skip_refinement,
                )
            except Exception as e:
                candidates.append(None)
                scores.append(0.0)
                emit("candidate_scored", index=i, score=0.0,
                     tests_passed=None, tests_total=None)
                continue

            # ── Score candidate ──
            score = 0.5  # default
            route = result.get("route", "")

            # Self-verification: skip for design routes — 4B models can't
            # reliably score HTML quality via JSON.  Use reflection score only.
            run_self_test = (
                config.self_verification
                and route != "ROUTE_DESIGN"
            )

            if run_self_test:
                try:
                    test_score = await self._run_self_tests(
                        goal_text, result.get("response", ""), route, emit,
                    )
                    score = test_score
                except Exception:
                    pass

            # Use reflection score (always available from _pipeline)
            reflection = result.get("reflection")
            if reflection and isinstance(reflection, dict):
                refl_score = reflection.get("self_score", 0.5)
                if run_self_test:
                    # Blend: 60% test, 40% reflection
                    score = 0.6 * score + 0.4 * refl_score
                else:
                    score = refl_score

            candidates.append(result)
            scores.append(score)

            emit("candidate_scored", index=i, score=score,
                 tests_passed=None, tests_total=None)

            # Early stop: if score is high enough and we have at least 1 candidate
            if score >= 0.9 and len(candidates) >= 1:
                emit("candidate_selected", index=i, reason="high_confidence")
                break

        valid_candidates = [(i, c, s) for i, (c, s) in enumerate(zip(candidates, scores)) if c is not None]
        if not valid_candidates:
            # All candidates failed — fall back to single pipeline call
            return await self.orch._pipeline(
                goal,
                on_event=on_event,
                conversation=conversation,
                mode_override=mode_override,
                skip_refinement=skip_refinement,
            )

        # ── Select best candidate ──
        best_idx, best_result, best_score = max(valid_candidates, key=lambda x: x[2])

        emit("candidate_selected", index=best_idx, reason="best_score")

        # ── Iterative refinement if all candidates scored weak ──
        # Gate: only attempt repair when there's enough context for a full
        # rewrite (>= 32K) and the score is genuinely bad.  On small models
        # the self-evaluation is unreliable and the repair prompt easily
        # exceeds available context, producing truncated garbage that
        # replaces the good original.
        ctx = getattr(self.orch.engine, "context_size", 16384)
        can_repair = (
            config.iterative_refinement
            and best_score < 0.5          # only repair genuinely bad output
            and budget.k > 1
            and ctx >= 32768              # need room for code + repair prompt
            and detected_route != "ROUTE_DESIGN"  # design rewrites always blow context
        )

        if can_repair:
            emit("atlas_repair", iteration=0, strategy="refinement",
                 failure_type="low_score")
            refined = await self._refinement_loop(
                config, goal, goal_text, best_result,
                conversation, mode_override, skip_refinement, emit,
            )
            if refined is not None:
                best_result = refined
                emit("atlas_repair_result", passed=True, score=0.0)

        return best_result

    # ── Self-test generation and execution ───────────────────────────

    async def _run_self_tests(
        self,
        goal: str,
        code: str,
        route: str,
        emit: Callable,
    ) -> float:
        """Generate test cases and execute them. Returns score 0.0-1.0."""
        if not code or len(code) < 20:
            return 0.0

        is_design = route in ("ROUTE_DESIGN",)
        prompt_template = DESIGN_TEST_PROMPT if is_design else SELF_TEST_PROMPT

        ctx = getattr(self.orch.engine, "context_size", 16384)
        code_budget = min(len(code), max(ctx // 4, 1500))

        prompt = prompt_template.format(
            goal=goal[:500],
            code=code[:code_budget],
            route=route,
        )

        messages = [
            {"role": "system", "content": "You are a code testing expert. Return valid JSON only."},
            {"role": "user", "content": prompt},
        ]

        try:
            raw = await self.orch.engine._call(
                messages,
                max_tokens=1024,
                enable_thinking=False,
            )
            if isinstance(raw, dict):
                raw = raw.get("text", "")

            parsed = self._parse_json_from_response(raw)
            if parsed is None:
                return 0.5

            if is_design:
                # Design test: use overall score directly
                return float(parsed.get("overall", 0.5))

            # Code test: try to execute
            tests = parsed.get("tests", [])
            if not tests:
                return 0.5

            if route in ("ROUTE_CODE", "ROUTE_COMPUTER"):
                passed = await self._execute_code_tests(code, tests)
                return passed
            else:
                # Non-executable: count how many tests have reasonable assertions
                return 0.6  # partial credit for having generated tests

        except Exception as e:
            emit("atlas_test_error", error=str(e))
            return 0.5

    async def _execute_code_tests(
        self,
        code: str,
        tests: list[dict],
    ) -> float:
        """Run code against generated tests via subprocess.
        Returns fraction of tests passed (0.0-1.0)."""
        # Extract code from markdown fences if present
        clean_code = _extract_code_block(code)
        if not clean_code:
            return 0.0

        passed = 0
        total = len(tests)
        if total == 0:
            return 0.5

        for test in tests[:5]:  # cap at 5 tests
            test_input = test.get("input", "")
            expected = test.get("expected", "")

            # Build test script
            test_script = f"""{clean_code}

# --- Atlas test ---
try:
    result = {test_input}
    expected = {repr(expected)}
    if str(result).strip() == str(expected).strip():
        print("PASS")
    else:
        print(f"FAIL: got {{result}}, expected {{expected}}")
except Exception as e:
    print(f"ERROR: {{e}}")
"""
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".py", delete=False, encoding="utf-8"
                ) as f:
                    f.write(test_script)
                    f.flush()
                    tmp_path = f.name

                result = subprocess.run(
                    ["python", tmp_path],
                    capture_output=True,
                    text=True, encoding="utf-8", errors="replace",
                    timeout=10,
                )
                if "PASS" in result.stdout:
                    passed += 1

            except (subprocess.TimeoutExpired, Exception):
                pass
            finally:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass

        return passed / total

    # ── Iterative refinement loop ────────────────────────────────────

    async def _refinement_loop(
        self,
        config: AtlasConfig,
        goal,
        goal_text: str,
        best_result: dict,
        conversation: list[dict],
        mode_override: str | None,
        skip_refinement: bool,
        emit: Callable,
    ) -> dict | None:
        """Single iteration: failure analysis -> PR-CoT repair -> test."""
        current = best_result
        route = current.get("route", "ROUTE_CODE")

        for iteration in range(1):
            emit("atlas_repair", iteration=iteration + 1,
                 strategy="analysis", failure_type="unknown")

            code = current.get("response", "")

            # Step 1: Failure analysis
            analysis = await self._analyze_failure(goal_text, code, route)
            if analysis is None:
                break

            category = analysis.get("category", "unknown")
            diagnosis = analysis.get("diagnosis", "")

            emit("atlas_repair", iteration=iteration + 1,
                 strategy="pr_cot", failure_type=category)

            # Step 2: PR-CoT repair
            repaired_code = await self._prcot_repair(
                goal_text, code, route, analysis,
            )
            if not repaired_code:
                break

            # Step 3: Test the repair
            repair_score = 0.5
            if config.self_verification:
                try:
                    repair_score = await self._run_self_tests(
                        goal_text, repaired_code, route, emit,
                    )
                except Exception:
                    pass

            emit("atlas_repair_result",
                 passed=repair_score >= 0.7,
                 score=repair_score)

            # Update current result with repaired code
            current = {
                **current,
                "response": repaired_code,
                "atlas_repaired": True,
                "atlas_repair_iteration": iteration,
                "atlas_repair_score": repair_score,
            }

            # Good enough — stop refining
            if repair_score >= 0.7:
                self._store_lesson(goal_text, category, diagnosis)
                return current

            # Step 4: Constraint refinement for next iteration
            refined_constraints = await self._refine_constraints(
                goal_text, category, diagnosis,
            )
            if refined_constraints:
                additional = refined_constraints.get("additional_instructions", "")
                if additional:
                    goal_text = f"{goal_text}\n\n[REFINED CONSTRAINTS]\n{additional}"

        # Store lesson even if repair didn't fully succeed
        if analysis:
            self._store_lesson(
                goal_text,
                analysis.get("category", "unknown"),
                analysis.get("diagnosis", "refinement incomplete"),
            )

        return current

    # ── Failure analysis ─────────────────────────────────────────────

    async def _analyze_failure(
        self,
        goal: str,
        code: str,
        route: str,
    ) -> dict | None:
        """Categorize failure via engine._call."""
        ctx = getattr(self.orch.engine, "context_size", 16384)
        code_budget = min(len(code), max(ctx // 4, 1500))

        prompt = FAILURE_ANALYSIS_PROMPT.format(
            goal=goal[:500],
            route=route,
            code=code[:code_budget],
        )

        messages = [
            {"role": "system", "content": "You are a failure analysis expert. Return valid JSON only."},
            {"role": "user", "content": prompt},
        ]

        try:
            raw = await self.orch.engine._call(
                messages,
                max_tokens=1024,
                enable_thinking=False,
            )
            if isinstance(raw, dict):
                raw = raw.get("text", "")
            return self._parse_json_from_response(raw)
        except Exception:
            return None

    # ── PR-CoT repair ────────────────────────────────────────────────

    async def _prcot_repair(
        self,
        goal: str,
        code: str,
        route: str,
        analysis: dict,
    ) -> str | None:
        """Multi-perspective repair via engine._call."""
        is_design = route in ("ROUTE_DESIGN",)
        template = PRCOT_DESIGN_PROMPT if is_design else PRCOT_CODE_PROMPT

        # Budget code size to fit in context alongside output
        ctx = getattr(self.orch.engine, "context_size", 16384)
        code_budget = min(len(code), max(ctx // 3, 2000))

        prompt = template.format(
            goal=goal[:500],
            code=code[:code_budget],
            analysis=json.dumps(analysis, indent=2)[:800],
        )

        messages = [
            {"role": "system", "content": "You are an expert code repair specialist."},
            {"role": "user", "content": prompt},
        ]

        try:
            raw = await self.orch.engine._call(
                messages,
                max_tokens=4096,
                enable_thinking=True,
            )
            if isinstance(raw, dict):
                text = raw.get("text", "")
            else:
                text = raw

            if not text or len(text) < 20:
                return None

            # For design routes, extract HTML if wrapped in fences
            if is_design:
                extracted = _extract_code_block(text)
                return extracted if extracted else text
            return text

        except Exception:
            return None

    # ── Constraint refinement ────────────────────────────────────────

    async def _refine_constraints(
        self,
        goal: str,
        failure_category: str,
        diagnosis: str,
    ) -> dict | None:
        """Generate refined constraints after a failure."""
        prompt = CONSTRAINT_REFINEMENT_PROMPT.format(
            goal=goal[:500],
            failure_category=failure_category,
            diagnosis=diagnosis[:500],
        )

        messages = [
            {"role": "system", "content": "You are a requirements refinement expert. Return valid JSON only."},
            {"role": "user", "content": prompt},
        ]

        try:
            raw = await self.orch.engine._call(
                messages,
                max_tokens=1024,
                enable_thinking=False,
            )
            if isinstance(raw, dict):
                raw = raw.get("text", "")
            return self._parse_json_from_response(raw)
        except Exception:
            return None

    # ── Cache and journal queries ────────────────────────────────────

    async def _check_cache_similarity(self, goal: str) -> float:
        """Query component cache for similarity. Returns 0.0-1.0."""
        if not self.orch.component_cache:
            return 0.0

        try:
            from ct1.memory.component_cache import ComponentCache
            keywords = ComponentCache.extract_tags(goal, None)
            if not keywords:
                return 0.0
            results = await self.orch.component_cache.search_similar(keywords, limit=1)
            if results:
                return float(results[0].get("score", 0.0))
            return 0.0
        except Exception:
            return 0.0

    def _check_journal_patterns(self, goal: str) -> float:
        """Journal has been replaced by PlanCache. Always returns 0.0."""
        return 0.0

    def _store_lesson(self, goal: str, failure_type: str, analysis: str) -> None:
        """Journal has been replaced by PlanCache. No-op."""
        pass

    # ── Utilities ────────────────────────────────────────────────────

    @staticmethod
    def _parse_json_from_response(text: str) -> dict | None:
        """Extract JSON from LLM output, handling markdown fences."""
        if not text:
            return None

        # Try direct parse first
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Strip markdown JSON fences
        fence_match = re.search(
            r'```(?:json)?\s*\n?(.*?)\n?\s*```',
            text,
            re.DOTALL,
        )
        if fence_match:
            try:
                return json.loads(fence_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Find first { ... } block
        start = text.find("{")
        if start != -1:
            # Find matching closing brace
            depth = 0
            for i in range(start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except json.JSONDecodeError:
                            break

        return None


# ── Module-level helpers ─────────────────────────────────────────────

def _extract_goal_text(goal) -> str:
    """Extract plain text from goal (may be string or multimodal content array)."""
    if isinstance(goal, str):
        return goal
    if isinstance(goal, list):
        return " ".join(
            p.get("text", "") for p in goal if p.get("type") == "text"
        )
    return str(goal)


def _prepend_to_goal(goal, prefix: str):
    """Prepend text to a multimodal goal array."""
    if isinstance(goal, str):
        return f"[APPROACH]\n{prefix}\n[/APPROACH]\n\n{goal}"
    if isinstance(goal, list):
        # Clone and prepend to first text part
        new_goal = []
        prepended = False
        for part in goal:
            part_copy = dict(part)
            if not prepended and part_copy.get("type") == "text":
                part_copy["text"] = f"[APPROACH]\n{prefix}\n[/APPROACH]\n\n{part_copy['text']}"
                prepended = True
            new_goal.append(part_copy)
        if not prepended:
            # No text part found; insert one at the start
            new_goal.insert(0, {
                "type": "text",
                "text": f"[APPROACH]\n{prefix}\n[/APPROACH]",
            })
        return new_goal
    return goal


def _extract_code_block(text: str) -> str | None:
    """Extract code from markdown fences. Returns None if no fences found."""
    # Try fenced code block
    match = re.search(
        r'```(?:\w+)?\s*\n(.*?)\n\s*```',
        text,
        re.DOTALL,
    )
    if match:
        return match.group(1).strip()

    # If text looks like raw code (starts with common patterns), return as-is
    stripped = text.strip()
    if stripped.startswith(("<!DOCTYPE", "<!doctype", "<html", "import ", "def ", "class ", "from ")):
        return stripped

    return stripped if len(stripped) > 50 else None
