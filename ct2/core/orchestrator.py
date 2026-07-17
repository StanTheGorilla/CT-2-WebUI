"""CT-2 Orchestrator: Single-engine pipeline with deterministic routing.

6-phase pipeline:
  1. ROUTE    — Deterministic keyword classifier (no AI — instant, predictable)
  2. PLAN     — Engine self-planning for code routes (lightweight JSON plan)
  3. GENERATE — Engine produces full response (with plan context injected)
  4. VALIDATE — Output-type-aware validation (HTML structural / Python AST / JS braces)
  5. FORMAT   — Deterministic Python cleanup
"""
import yaml
from pathlib import Path
from ct2.core.engine import Engine
from ct2.prompts.manager import _get_prompt_manager as _pm
from ct2.server.launcher import load_raw_config, resolve_config
import re
from ct2.core.formatter import (
    clean_response, validate_output, validate_file,
    split_html_sections, reassemble_html_section,
    strip_think_tags, extract_code,
    detect_broken_sections, detect_output_type, detect_output_type_from_fence,
    polish_html_css, check_completeness,
    enforce_file_markers, fix_html_structure,
)
from ct2.core.pipeline_util import (
    _EXT_TO_LANG, _OUTPUT_TYPE_TO_LANG, _LANG_TO_LABEL,
    _detect_lang_from_response,
)
from ct2.memory.plan_cache import PlanCache
from ct2.memory.session_store import SessionStore
from ct2.core.atlas import AtlasController

_CONFIG_PATH = (Path(__file__).parent.parent.parent
                / "ct2" / "server" / "model_config.yaml")


# ── Mode registry singleton (loaded once at startup) ─────────────
from ct2.modes.registry import ModeRegistry as _ModeRegistry

_mode_registry: _ModeRegistry | None = None


def _get_mode_registry() -> _ModeRegistry:
    """Lazy-load the mode registry (avoids import-time filesystem access)."""
    global _mode_registry
    if _mode_registry is None:
        _mode_registry = _ModeRegistry()
    return _mode_registry


def _extract_text(goal) -> str:
    """Extract plain text from goal (may be string or multimodal content array)."""
    if isinstance(goal, str):
        return goal
    if isinstance(goal, list):
        return " ".join(
            p.get("text", "") for p in goal if p.get("type") == "text"
        )
    return str(goal)


def _strip_file_context(text: str) -> str:
    """Strip inlined file/context blocks, keeping only the user's own message.
    Used for routing/classification so file content doesn't pollute intent detection."""
    text = re.sub(r'\[WORKSPACE FILES[^\]]*\].*?\n\n(?=\S)', '', text, count=1, flags=re.DOTALL)
    text = re.sub(
        r'\[FETCHED CONTENT FROM:[^\]]*\].*?\[END FETCHED CONTENT\]\s*',
        '', text, flags=re.DOTALL,
    )
    text = re.sub(
        r'\[CONTEXT FILE:[^\]]*\].*?\[END CONTEXT FILE\]\s*',
        '', text, flags=re.DOTALL,
    )
    return re.sub(r'\[(?:Workspace )?[Ff]ile: [^\]]+\]\n.*?\n\n', '', text, flags=re.DOTALL).strip()


# ── Conversation mode detection keywords ──────────────────────────
# Used by _detect_conversation_mode() to distinguish edits from questions
# when there's existing code in the conversation.



_EDIT_INTENT = {
    # Explicit edit verbs
    "change", "modify", "update", "edit", "fix", "add", "remove",
    "replace", "swap", "move", "resize", "make it", "make the",
    "adjust", "tweak", "set the", "turn the", "switch",
    "rename", "recolor", "restyle", "redesign", "redo",
    "bigger", "smaller", "wider", "narrower", "taller", "shorter",
    "darker", "lighter", "brighter", "bolder",
    "add a", "add the", "put a", "put the", "insert",
    "delete", "drop", "hide", "show",
    "rewrite", "refactor", "optimise", "optimize", "improve", "extend",
    # Implicit edit: describing problems / desired state
    "should be", "needs to be", "supposed to",
    "is off", "is wrong", "is broken", "is missing",
    "is not", "isn't", "doesn't look",
    "too big", "too small", "too dark", "too light",
    "too far", "too close", "too high", "too low",
    "too wide", "too narrow", "too thick", "too thin",
    "not centered", "not aligned", "not right",
    "off to the", "off center",
    # Positional / layout directions
    "to the left", "to the right", "to the center",
    "in the middle", "at the top", "at the bottom",
    "center it", "align it",
    "like the other", "like other", "same as the",
    # Visual state complaints
    "doesn't match", "don't match", "looks wrong",
    "can't see", "hard to read", "too close to",
    "overlapping", "cut off", "overflowing",
}


_SOLO_PLAN_SYSTEM = _pm().get("solo_plan")


_EXTERNAL_CFG_DEFAULTS = {
    "llama_server": {"port": 8080, "context_size": 32768},
    "models": {"director": {
        "temperature": 0.6, "top_p": 0.9, "top_k": 40,
        "presence_penalty": 1.0, "frequency_penalty": 0.0,
        "repeat_penalty": 1.10,
        "max_tokens": -1, "thinking_budget": -1,
        "vision_supported": False, "enable_thinking": False,
    }},
    "_task_overrides": {},
    "_preset_info": {},
    "plan_cache": {"path": "ct2/data/plan_cache.db"},
    "sessions": {"path": "ct2/data/sessions"},
}


from ct2.core.edit_pipeline import EditPipelineMixin
from ct2.core.design_pipeline import DesignPipelineMixin
from ct2.core.conversation_ops import ConversationOpsMixin


class Orchestrator(EditPipelineMixin, DesignPipelineMixin, ConversationOpsMixin):
    def __init__(self, config_path: str = None, component_cache=None,
                 context_size_override: int = None,
                 external_base_url: str | None = None,
                 external_model_name: str = ""):
        if config_path is None:
            config_path = str(_CONFIG_PATH)

        raw_cfg = load_raw_config(config_path)
        try:
            cfg = resolve_config(raw_cfg, config_path,
                                 context_size_override=context_size_override)
        except Exception as e:
            if not external_base_url:
                raise
            print(f"[orch] Config resolve failed ({e}), using defaults for external backend")
            cfg = _EXTERNAL_CFG_DEFAULTS

        if external_base_url:
            director_url = external_base_url
            is_external = True
        else:
            director_url = f"http://localhost:{cfg['llama_server']['port']}"
            is_external = False

        dc = cfg["models"]["director"]

        self.engine = Engine(
            base_url=director_url,
            temperature=dc["temperature"],
            top_p=dc["top_p"],
            top_k=dc["top_k"],
            presence_penalty=dc["presence_penalty"],
            frequency_penalty=dc.get("frequency_penalty", 0),
            repeat_penalty=dc.get("repeat_penalty", 1.05),
            max_tokens=dc.get("max_tokens", 100000),
            thinking_budget=dc.get("thinking_budget", -1),
            vision_supported=dc.get("vision_supported", False),
            context_size=cfg["llama_server"]["context_size"],
            model_name=external_model_name,
            is_external=is_external,
        )

        # Per-task parameter overrides (e.g. Nemotron optimized per route)
        self.task_overrides = cfg.get("_task_overrides", {})

        # Detect model tier for adaptive pipeline depth
        from ct2.core.tier import detect_tier
        preset_info = cfg.get("_preset_info", {})
        model_file = preset_info.get("model_file", "")
        explicit_tier = preset_info.get("tier")
        self.tier = detect_tier(model_file, explicit_tier)
        self.engine.tier = self.tier  # used for tier-aware prompt selection
        self.context_size = cfg["llama_server"]["context_size"]
        print(f"[orch] Model tier: {self.tier} (model: {model_file})")

        self.plan_cache = PlanCache(
            cfg.get("plan_cache", {}).get("path", "ct2/data/plan_cache.db")
        )
        self.plan_cache_fast = cfg.get("plan_cache", {}).get("enable_fast_path", False)
        self.verbose = False

        # No more lesson injection — plan cache handles acceleration
        self.engine.lessons = []
        self.component_cache = component_cache

        # Load last session for continuity
        self.session_store = SessionStore(
            cfg.get("sessions", {}).get("path", "ct2/data/sessions")
        )
        last_session = self.session_store.read_latest()
        self.engine.last_session = last_session or ""
        self.atlas = AtlasController(self)

    # ── Deterministic pre-routing (runs BEFORE AI routing) ──────────

    @classmethod
    def _deterministic_route(cls, msg: str) -> str:
        """Deterministic routing via keyword/regex. Delegates to ModeRegistry.

        Priority order is defined in ct2/modes/*.yaml (sorted by priority field).
        """
        return _get_mode_registry().resolve(msg).route_id

    # ── Main pipeline ────────────────────────────────────────────────

    @staticmethod
    def _slim_conversation(conversation: list[dict]) -> list[dict]:
        """Strip large bare code files from assistant turns to prevent style bleeding.

        Only strips responses that are actual code file outputs (raw HTML pages,
        Python scripts, etc.) — NOT markdown chat responses that contain code blocks.
        Markdown responses start with prose text; code files start with <!DOCTYPE,
        import, def, etc. This distinction prevents the model from losing context
        of its own previous chat answers.
        """
        slim = []
        for msg in conversation:
            if msg["role"] == "assistant":
                content = msg.get("content", "")
                if isinstance(content, str):
                    stripped = content.strip()
                    # Only slim bare code file outputs, not markdown chat responses.
                    # Markdown always starts with prose; code files start with
                    # language-specific syntax and have no markdown fences.
                    is_bare_html = stripped.lower().startswith(
                        ("<!doctype", "<html")
                    )
                    is_bare_script = (
                        len(stripped) > 800
                        and stripped.startswith((
                            "import ", "from ", "#!/",
                            "def ", "class ",
                            "const ", "let ", "var ", "function ", "//",
                        ))
                        and "```" not in stripped[:400]
                    )
                    if is_bare_html or is_bare_script:
                        slim.append({
                            "role": "assistant",
                            "content": "(Previous code output omitted.)",
                        })
                    else:
                        slim.append(msg)
                else:
                    slim.append(msg)
            else:
                slim.append(msg)
        return slim

    @classmethod
    def _detect_conversation_mode(cls, goal_text: str,
                                   conversation: list[dict]) -> tuple[str, str]:
        """Detect conversation mode based on code context + user intent.
        Returns (mode, previous_code) where mode is 'edit', 'question', or 'new'.
        """
        if not conversation:
            return "new", ""

        # Find the last assistant message
        previous_code = ""
        has_code = False
        for msg in reversed(conversation):
            if msg["role"] == "assistant":
                content = msg.get("content", "")
                if not isinstance(content, str):
                    break
                stripped = content.strip()
                is_html = (stripped.startswith("<!DOCTYPE")
                           or stripped.startswith("<html")
                           or stripped.startswith("<!doctype"))
                is_python = ("def " in content and "import " in content
                             and len(content) > 500)
                is_js = ("function " in content and len(content) > 500)
                if is_html or is_python or is_js:
                    has_code = True
                    previous_code = content
                break

        if not has_code:
            return "new", ""

        # Code exists — check for clear edit intent via keywords (fast path).
        # "Is this a question?" is handled separately via LLM in think().
        gl = goal_text.lower().strip()
        if any(kw in gl for kw in _EDIT_INTENT):
            return "edit", previous_code

        # Ambiguous — caller will use LLM to distinguish question vs. new request
        return "new", previous_code

    def _get_task_overrides(self, route: str, goal_text: str) -> dict:
        """Select per-task parameter overrides based on route and content.

        Mode YAML provides defaults; model_config.yaml overrides win if present.
        """
        # Reasoning keywords → reasoning-specific overrides (model_config only)
        lower = goal_text.lower()
        if any(kw in lower for kw in self._REASONING_KEYWORDS):
            if self.task_overrides.get("reasoning"):
                return self.task_overrides["reasoning"]

        # Map route to override key used in model_config
        route_map = {
            "ROUTE_CODE": "code",
            "ROUTE_DESIGN": "design",
            "ROUTE_DIRECT": "direct",
            "ROUTE_COMPUTER": "computer",
        }
        key = route_map.get(route, "direct")

        # Start with mode YAML defaults, then apply model_config overrides on top
        mode_defaults: dict = {}
        for m in _get_mode_registry().get_all():
            if m.route_id == route:
                mode_defaults = dict(m.task_overrides)
                break

        model_overrides = self.task_overrides.get(key, {})
        return {**mode_defaults, **model_overrides}

    # ── Multi-file parsing (Computer Mode) ──────────────────────────

    async def _solo_plan(self, goal: str, route: str) -> dict | None:
        """Lightweight self-planning via Engine.
        Uses the engine with thinking disabled for speed."""
        try:
            import json
            raw = await self.engine._call(
                [{"role": "system", "content": _SOLO_PLAN_SYSTEM},
                 {"role": "user", "content": goal}],
                max_tokens=512,
                enable_thinking=False,
            )
            text = raw if isinstance(raw, str) else raw.get("text", "")
            text = strip_think_tags(text)
            # Extract JSON
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                plan = json.loads(text[start:end])
                # Validate and normalize
                valid_types = ("html_page", "python_script", "javascript",
                               "typescript", "cpp", "go", "rust", "shell",
                               "sql", "api", "other")
                if plan.get("output_type") not in valid_types:
                    default = "html_page" if route == "ROUTE_DESIGN" else "other"
                    plan["output_type"] = default
                if not isinstance(plan.get("components"), list):
                    plan["components"] = []
                plan["components"] = plan["components"][:5]
                return plan
        except Exception as e:
            print(f"[orch] solo plan failed: {e}")
        return None

    # Mode override → route mapping
    _MODE_ROUTE_MAP = {
        "design": "ROUTE_DESIGN",
        "code": "ROUTE_CODE",
        "chat": "ROUTE_DIRECT",
        "computer": "ROUTE_COMPUTER",
    }

    # ── Precision-Design pipeline ─────────────────────────────────────


    async def _pipeline(self, goal, on_event=None,
                        conversation: list[dict] = None,
                        mode_override: str | None = None,
                        skip_refinement: bool = False,
                        tools: list[dict] | None = None,
                        tool_executor=None) -> dict:
        if conversation is None:
            conversation = []

        # Extract text for routing/planning (multimodal-safe)
        goal_text = _extract_text(goal)
        # Strip inlined file content for intent detection / routing
        user_message = _strip_file_context(goal_text)

        # Handle images when vision not supported
        has_images = (isinstance(goal, list) and
                      any(p.get("type") == "image_url" for p in goal))
        no_vision = has_images and not self.engine.vision_supported
        if no_vision:
            if on_event:
                on_event("warning", message="Image attached but vision is not available with current model. The image will be ignored.")

        def emit(event: str, **data):
            if on_event:
                on_event(event, **data)

        # Detect conversation mode (edit / new) via fast keyword check.
        # "question" detection is now done by LLM below — no keywords.
        mode, previous_code = self._detect_conversation_mode(user_message, conversation)
        is_edit = mode == "edit"

        # For "new" mode, strip full code from conversation history.
        # A 4B/16K model gets confused by prior HTML/code in context,
        # mixing styles and content from previous turns into new output.
        if mode == "new" and conversation:
            conversation = self._slim_conversation(conversation)

        # ── Phase 1: ROUTE ────────────────────────────────────────────
        emit("routing")
        forced_route = self._MODE_ROUTE_MAP.get(mode_override or "")

        # ── Fast-path plan cache check ────────────────────
        # Currently disabled for quality assurance — the plan cache still
        # records entries for the Learn tab, but does not alter the pipeline.
        # Set plan_cache.enable_fast_path: true in model_config.yaml to enable.
        plan_hint = None
        _fast_path = False
        if (self.plan_cache_fast and not forced_route and not is_edit):
            plan_hint = self.plan_cache.lookup(user_message)
            if plan_hint and plan_hint.get("confidence", 0) >= 0.6:
                print(f"[plan-cache] HIT — {plan_hint.get('task_type', 'direct')} "
                      f"(confidence: {plan_hint.get('confidence', 0):.02f})")
                _cached_type = plan_hint.get("task_type", "direct")
                if _cached_type == "code":
                    forced_route = "ROUTE_CODE"
                elif _cached_type == "design":
                    forced_route = "ROUTE_DESIGN"
                else:
                    forced_route = "ROUTE_DIRECT"
                _fast_path = True
                print(f"[plan-cache] fast-path → {forced_route}")
            else:
                plan_hint = None

        # LLM-based question detection: when there's existing code and the
        # message isn't a clear edit, ask the model if it's an info request.
        # This works in any language — no keyword dependency.
        is_question = False
        if previous_code and not is_edit:
            is_question = await self._classify_is_question(user_message)
            if is_question:
                mode = "question"

        if forced_route:
            # User explicitly selected a mode — skip AI routing
            if is_edit:
                route = forced_route if forced_route != "ROUTE_DIRECT" else "ROUTE_CODE"
            elif is_question and forced_route != "ROUTE_DESIGN":
                # Pure info question in code mode → text answer, not a code file.
                # Design mode: let it fall through — "add a section?" is still a design task.
                route = "ROUTE_DIRECT"
            else:
                route = forced_route
            print(f"[mode-override] → {route} (user selected '{mode_override}')")
        elif no_vision and not is_edit:
            route = "ROUTE_DIRECT"
        elif is_edit:
            route = "ROUTE_CODE"
        elif is_question:
            route = "ROUTE_DIRECT"
        else:
            route = self._deterministic_route(user_message)
            print(f"[route] → {route} (deterministic)")
        emit("routed", route=route)

        is_code = route in ("ROUTE_DESIGN", "ROUTE_CODE", "ROUTE_COMPUTER")

        # Resolve per-task parameter overrides for this route
        task_ovr = self._get_task_overrides(route, user_message)

        # ── ROUTE_DESIGN: Precision-Design pipeline ──
        if route == "ROUTE_DESIGN":
            def on_token(token, kind):
                emit("token", text=token, kind=kind)

            if is_question or is_edit:
                # Questions and edits fall through to the regular pipeline below.
                # Edits use _generate_edit → _section_edit (section-based HTML editing).
                pass
            else:
                result = await self._design_pipeline(
                    goal, goal_text, conversation,
                    emit, on_token, task_ovr,
                    skip_refinement=skip_refinement,
                    tools=tools,
                    tool_executor=tool_executor,
                )
                # Write to plan cache so future design tasks skip deliberation
                if result.get("reflection") is None:
                    self.plan_cache.add(
                        goal_text,
                        output_type="html",
                        task_type="design",
                        complexity="moderate",
                        score=0.7,
                    )
                    result["reflection"] = None
                return result

        # ── Phase 2: PLAN (tier-aware) ──
        plan = None
        if not _fast_path:  # Skip AI planning on cached fast-path
            is_complex = len(user_message) > 80 or any(
                kw in user_message.lower()
                for kw in ("step by step", "multiple", "project", "full", "complete",
                           "detailed", "comprehensive", "with tests")
            )

            if self.tier == "large" and is_code and not is_edit:
                # Large tier: always plan for code tasks
                plan = await self._solo_plan(user_message, route)
                if plan:
                    emit("planned", plan=plan)
            elif self.tier == "medium" and is_code and not is_edit and is_complex:
                # Medium tier: plan only for complex requests
                plan = await self._solo_plan(user_message, route)
                if plan:
                    emit("planned", plan=plan)
        # Small tier: no planning call (inline in system prompt)

        # ── Phase 3: specialist_data (always None — specialist removed) ──
        specialist_data = None

        task_list = []

        # ── Phase 3.6: Inject cached references into director (#4) ────
        cache_ctx = ""
        if (self.component_cache and is_code and not is_edit
                and route != "ROUTE_COMPUTER"):
            try:
                from ct2.memory.component_cache import ComponentCache
                kw = ComponentCache.extract_tags(user_message, specialist_data)
                refs = await self.component_cache.search_similar(kw, limit=2)
                if refs:
                    snippets = []
                    for r in refs:
                        snippet = r["html_snippet"][:2000]
                        snippets.append(
                            f"[REFERENCE — approved {r['category']} "
                            f"(score {r['score']:.0%})]\n{snippet}"
                        )
                    cache_ctx = "\n\n".join(snippets)
            except Exception as e:
                print(f"[orch] cache reference inject error: {e}")

        # ── Phase 4: GENERATE (streamed) ──────────────────────────────
        emit("generating", editing=is_edit)

        def on_token(token, kind):
            emit("token", text=token, kind=kind)

        used_section_edit = False
        finish_reason = None
        auto_continuations = 0

        if is_edit and is_code:
            draft, draft_thinking, used_section_edit = await self._generate_edit(
                user_message, route, previous_code, on_token, emit,
                specialist_data=specialist_data,
                conversation=conversation,
                task_overrides=task_ovr,
                tools=tools,
                tool_executor=tool_executor,
            )
            # Push patched code to streamingText so preview shows it immediately
            emit("token", text=draft, kind="content")
        else:
            # Single-pass generation — no scaffold, no fragmentation
            actual_goal = goal
            if cache_ctx:
                if isinstance(actual_goal, str):
                    actual_goal = f"{cache_ctx}\n\n{actual_goal}"
                elif isinstance(actual_goal, list):
                    for part in actual_goal:
                        if part.get("type") == "text":
                            part["text"] = f"{cache_ctx}\n\n{part['text']}"
                            break

            result = await self.engine.generate(
                actual_goal, route,
                specialist_data=specialist_data,
                plan=plan,
                conversation=conversation,
                on_token=on_token,
                code_context=previous_code if is_question else None,
                task_overrides=task_ovr,
                task_list=task_list if task_list else None,
                tools=tools,
                tool_executor=tool_executor,
            )
            draft = result["text"]
            draft_thinking = result.get("thinking", "")
            finish_reason = result.get("finish_reason")
            draft, draft_thinking, finish_reason, auto_continuations = await self._continue_after_length(
                draft=draft,
                draft_thinking=draft_thinking,
                finish_reason=finish_reason,
                goal_text=goal_text,
                route=route,
                continuation_context=(conversation or []) + [{"role": "user", "content": goal_text}],
                specialist_data=specialist_data,
                plan=plan,
                task_ovr=task_ovr,
                emit=emit,
                on_token=on_token,
                tools=tools,
                tool_executor=tool_executor,
            )

        emit("draft", text=draft, thinking=draft_thinking)

        final_response = draft
        final_thinking = draft_thinking

        # ── Phase 4.1: CHECKLIST (completeness verification) ────────
        checklist = []
        missing_items = []
        if not is_edit and not is_question:
            clean_for_check = strip_think_tags(draft)
            clean_for_check = extract_code(clean_for_check)

            if task_list:
                # Verify against model's OWN task list — much more accurate
                lower = clean_for_check.lower()
                for task in task_list:
                    # Extract key terms (5+ chars) from the task
                    words = [w for w in re.findall(r'[a-zA-Z]{5,}', task.lower())
                             if w not in {"should", "create", "build", "every",
                                          "include", "using", "about", "their",
                                          "which", "these", "those", "based"}]
                    if words:
                        matches = sum(1 for w in words if w in lower)
                        done = matches >= max(1, len(words) // 3)
                    else:
                        done = True
                    checklist.append({"item": task, "done": done})
            if checklist:
                emit("checklist", items=checklist)
                missing_items = [c["item"] for c in checklist if not c["done"]]
                if missing_items:
                    print(f"[orch] checklist: {len(missing_items)} items missing: {missing_items}")
                else:
                    print(f"[orch] checklist: all {len(checklist)} items present")

        # (Phase 4.25 refinement for ROUTE_DESIGN now runs inside _design_pipeline)

        # ── Phase 4.5: POLISH (deterministic CSS, no AI) ─────────────
        # Skip for ROUTE_DESIGN — the self-refinement pass already handles polish
        polish_output_type = plan.get("output_type", "html_page") if plan else "html_page"
        if (is_code and not is_edit and route not in ("ROUTE_COMPUTER", "ROUTE_DESIGN")
                and polish_output_type == "html_page"):
            emit("polishing")
            polished = polish_html_css(final_response)
            if polished != final_response:
                final_response = polished
                emit("polished", code=final_response)

        # ── Phase 5: VALIDATE ─────────────────────────────────────────
        # ROUTE_COMPUTER skips static validation — the AI already ran and tested
        # the code via tool calls; the static validator produces false positives that
        # trigger an unnecessary fix pass and break working code.
        fence_type = None  # resolved from model's fence tag; may stay None for edits/direct
        if is_code and not is_edit and route != "ROUTE_COMPUTER":
            # Non-computer code: resolve output type for validation + download.
            # Priority: model's fence language tag > plan > content heuristics.
            # The fence tag (```python, ```typescript …) is the model's own
            # declaration and is always more accurate than post-hoc detection.
            raw_for_fence = strip_think_tags(final_response)
            fence_type = detect_output_type_from_fence(raw_for_fence)
            if fence_type:
                output_type = fence_type
            else:
                output_type = plan.get("output_type", "other") if plan else "other"
                if output_type in ("other", "html_page"):
                    detected = detect_output_type(draft)
                    if detected != "other":
                        output_type = detected

            # Extract code from markdown fences before validating.
            # Models often wrap output in explanation text + ```lang ... ``` fences.
            # Running ast.parse / HTML checks on raw markdown causes spurious errors.
            _validate_target = extract_code(strip_think_tags(final_response))

            # HTML: fix missing boilerplate deterministically (no AI)
            if output_type in ("html_page", "other") and detect_output_type(_validate_target) == "html_page":
                final_response = fix_html_structure(final_response)

            # Programmatic validation — informational only for ROUTE_CODE.
            # No LLM fix cycle: the model rarely fixes syntax errors correctly and
            # the UI gets stuck in a permanent "validation failed" state.
            issues = validate_output(_validate_target, output_type)

            if route == "ROUTE_CODE":
                # Soft validation: always resolve, never trigger a fix cycle.
                emit("validated", issues=issues,
                     review={"pass": True, "critical_issues": [],
                             "fix_instructions": ""})
            elif issues:
                emit("validating", issues=issues,
                     review={"pass": False, "critical_issues": issues,
                             "fix_instructions": ""})
                emit("fixing")

                fix_prompt = (
                    f"Fix ALL these issues in the code:\n"
                    + "\n".join(f"- {i}" for i in issues)
                    + f"\n\nOriginal code:\n{_validate_target}"
                )

                def on_fix_token(token, kind):
                    emit("token", text=token, kind=kind)

                fix_ovr = {**task_ovr}
                if "thinking_budget" in fix_ovr:
                    fix_ovr["thinking_budget"] = min(fix_ovr["thinking_budget"], 2048)
                fix_result = await self.engine.generate(
                    fix_prompt, route,
                    specialist_data=specialist_data,
                    plan=None,
                    conversation=conversation,
                    on_token=on_fix_token,
                    task_overrides=fix_ovr,
                    tools=tools,
                    tool_executor=tool_executor,
                )
                final_response = fix_result["text"]
                final_thinking = fix_result.get("thinking", "")
            else:
                emit("validated", issues=[],
                     review={"pass": True, "critical_issues": [],
                             "fix_instructions": ""})
        elif is_edit:
            emit("validated", issues=[], review={"pass": True,
                 "critical_issues": [], "fix_instructions": ""})

        # ── Phase 5.5: SELF-REVIEW (large tier only) ──
        if self.tier == "large" and is_code and not is_edit and not is_question:
            emit("validating")
            review = await self._self_review(
                final_response, user_message, route, task_ovr
            )
            if review and not review.get("pass", True):
                emit("fixing")
                fix_prompt = (
                    f"Fix these issues:\n"
                    + "\n".join(f"- {i}" for i in review.get("issues", [])[:5])
                    + f"\n\n{review.get('fix_instructions', '')}"
                    + f"\n\nOriginal code:\n{final_response}"
                )
                fix_result = await self.engine.generate(
                    fix_prompt, route,
                    on_token=on_token,
                    task_overrides=task_ovr,
                    tools=tools,
                    tool_executor=tool_executor,
                )
                fixed = strip_think_tags(fix_result["text"])
                fixed = extract_code(fixed) or fixed
                if len(fixed) > 50:
                    final_response = fixed
                    final_thinking = fix_result.get("thinking", "")
                    print(f"[orch] self-review fix applied")

        # ── Phase 6: FORMAT ──────────────────────────────────────────
        # Capture fence language from raw draft BEFORE Phase 6 strips fences.
        # This is the authoritative source for new code. Edit prompts tell the model
        # to output bare code (no fences), so _draft_fence_lang will be None for edits.
        _draft_fence_lang = None
        if route == "ROUTE_CODE":
            _raw_for_lang = strip_think_tags(draft)
            _draft_fence_lang = _detect_lang_from_response(_raw_for_lang)
            if _draft_fence_lang == "text":
                _draft_fence_lang = None

        # For ROUTE_CODE: capture explanation text the model wrote before the code fence.
        # Phase 6 clean_response() will strip it — grab it now.
        explanation_text = ""
        if route == "ROUTE_CODE" and not is_edit:
            _stripped = strip_think_tags(final_response)
            _fence = re.search(r'```', _stripped)
            if _fence and _fence.start() > 20:
                explanation_text = _stripped[:_fence.start()].strip()

        if route == "ROUTE_COMPUTER":
            # Computer mode: only strip thinking tags — _parse_multi_file
            # handles code extraction per-file (extract_code here would
            # destroy [FILE:] markers)
            final_response = strip_think_tags(final_response)
        elif used_section_edit:
            final_response = strip_think_tags(final_response)
        else:
            # Auto-detect output type for correct cleanup
            output_type = plan.get("output_type", "other") if plan else "other"
            final_response = clean_response(
                final_response, is_code=is_code, output_type=output_type
            )

            # For ROUTE_CODE: propagate the resolved output_type to plan so the
            # frontend shows the right file extension/badge.
            # Use fence type (already computed above) if available, otherwise detect.
            if route == "ROUTE_CODE":
                actual_type = (fence_type
                               or detect_output_type(final_response)
                               or "other")
                if plan is None:
                    plan = {"output_type": actual_type,
                            "components": [], "complexity": "simple"}
                else:
                    plan["output_type"] = actual_type

        # Enforce file markers for computer mode
        final_response = enforce_file_markers(final_response, route)

        # ── Phase 6.5: AUTO-RETRY broken sections (max 2 attempts) ──
        # Only runs for HTML output — non-HTML code has no sections to retry.
        # Skip for computer mode — multi-file output doesn't use HTML section structure.
        _retry_output_type = plan.get("output_type", "other") if plan else "other"
        if (is_code and not is_edit and route not in ("ROUTE_COMPUTER", "ROUTE_CODE")
                and _retry_output_type in ("html_page", "other")):
            for retry_num in range(2):
                broken = detect_broken_sections(final_response)
                if not broken:
                    break
                emit("retrying", message=f"Retrying broken sections: {', '.join(broken)} (attempt {retry_num + 1})")
                sections = split_html_sections(final_response)
                if not sections:
                    break
                try:
                    for section_name in broken:
                        if section_name not in sections:
                            continue
                        def retry_token(token, kind):
                            if kind == "thinking":
                                emit("token", text=token, kind=kind)
                        retry_result = await self.engine.generate_section_edit(
                            f"Regenerate the {section_name} section completely. The current {section_name} is empty or broken. Original request: {goal_text}",
                            section_name, sections, on_token=retry_token,
                        )
                        new_content = strip_think_tags(retry_result["text"])
                        new_content = extract_code(new_content)
                        if new_content and len(new_content) > 20:
                            final_response = reassemble_html_section(
                                final_response, section_name, new_content,
                            )
                            sections[section_name] = new_content
                except Exception as e:
                    print(f"[orch] retry error: {e}")
                    break

        # ── Reflection (code routes only — skip for direct text) ─────
        if is_code and route != "ROUTE_COMPUTER":
            complexity = plan.get("complexity", "moderate") if plan else "moderate"
        # ── Plan cache write (all routes) ─────────────────────────
        # After every successful generation, write to the plan cache so
        # future similar tasks skip deliberation.
        if not is_edit:
            if is_code and route != "ROUTE_COMPUTER":
                _complexity = plan.get("complexity", "moderate") if plan else "moderate"
            else:
                _complexity = "brief"
            _task_type = "design" if route == "ROUTE_DESIGN" else ("code" if is_code else "direct")
            _out_type = plan.get("output_type", "") if plan else ""
            self.plan_cache.add(
                goal_text,
                output_type=_out_type,
                task_type=_task_type,
                complexity=_complexity,
                score=0.7,
            )
        reflection = None

        # ── Build metadata: detected_lang + files ─────────────────────
        if route == "ROUTE_DESIGN":
            _detected_lang = "html"
            _files: list[dict] = []
        elif route == "ROUTE_CODE":
            _resolved_type = plan.get("output_type", "other") if plan else "other"
            # Priority: 1) fence tag in raw draft (before Phase 6 stripped it)
            #           2) plan output_type (set from fence in Phase 5 for new code)
            #           3) fence scan on draft again (redundant but cheap)
            #           4) original file language for edits (preserve type across edits)
            #           5) "javascript" fallback (ROUTE_CODE is always code, never text)
            _detected_lang = (
                _draft_fence_lang
                or _OUTPUT_TYPE_TO_LANG.get(_resolved_type)
                or _detect_lang_from_response(draft)
            )
            if is_edit and previous_code and not _detected_lang:
                _detected_lang = _OUTPUT_TYPE_TO_LANG.get(detect_output_type(previous_code))
            if not _detected_lang:
                _detected_lang = "javascript"  # ROUTE_CODE always produces code, never plain text
            _files = []
        elif route == "ROUTE_COMPUTER":
            _parsed = self._parse_multi_file(final_response)
            _files = [
                {
                    "path": f["path"],
                    "lang": _EXT_TO_LANG.get(
                        "." + f["path"].rsplit(".", 1)[-1].lower()
                        if "." in f["path"] else "",
                        "text",
                    ),
                }
                for f in _parsed
            ]
            _detected_lang = "multi" if _parsed else "text"
            if _parsed:
                explanation_text = Orchestrator._extract_narrative(final_response)
        else:  # ROUTE_DIRECT
            _detected_lang = "text"
            _files = []

        return {
            "response": final_response,
            "thinking": final_thinking,
            "draft": draft,
            "draft_thinking": draft_thinking,
            "route": route,
            "specialist_data": specialist_data,
            "plan": plan,
            "finish_reason": finish_reason,
            "truncated": finish_reason == "length",
            "auto_continuations": auto_continuations,
            "reflection": reflection,
            "tier": self.tier,
            "detected_lang": _detected_lang,
            "files": _files,
            "explanation": explanation_text,
        }

    async def think(self, goal, on_event=None,
                    conversation: list[dict] = None,
                    mode_override: str | None = None,
                    skip_refinement: bool = False,
                    atlas_settings: dict | None = None,
                    tools: list[dict] | None = None,
                    tool_executor=None) -> dict:
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
            tools=tools,
            tool_executor=tool_executor,
        )

    async def clear_kv_cache(self) -> bool:
        """Clear the llama-server KV cache to reclaim VRAM between conversations.

        Call this after a conversation completes (on 'done' event) to prevent
        VRAM fragmentation across long sessions. Safe no-op on older server builds.
        Returns True if cleared, False if unsupported or server unreachable.
        """
        return await self.engine.clear_kv_cache()

    async def reset_engine_client(self) -> None:
        """Delegate to Engine.reset_client() to flush stale TCP connections.

        Call this after llama-server restarts or model swaps.
        """
        await self.engine.reset_client()

    async def close(self):
        await self.engine.close()
        self.plan_cache.close()
