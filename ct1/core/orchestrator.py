"""CT-2 Orchestrator: Sequential Supervisor-Worker pipeline.

6-phase pipeline:
  1. ROUTE    — Specialist classifies intent (ROUTE_DESIGN | ROUTE_CODE | ROUTE_DIRECT)
  2. PLAN     — Specialist produces a structured task breakdown (code routes only)
  3. CONSULT  — Specialist provides design data (ROUTE_DESIGN only)
  4. GENERATE — Director produces full response (with plan context injected)
  5. VALIDATE — Output-type-aware validation (HTML structural / Python AST / JS braces)
  6. FORMAT   — Deterministic Python cleanup
"""
import yaml
from pathlib import Path
from ct1.core.director import Director
from ct1.core.specialist import Specialist
import re
from ct1.core.formatter import (
    clean_response, validate_output,
    split_html_sections, reassemble_html_section,
    strip_think_tags, extract_code,
)
from ct1.memory.journal import Journal
from ct1.memory.journal_reader import JournalReader
from ct1.memory.session_store import SessionStore

_CONFIG_PATH = (Path(__file__).parent.parent.parent
                / "ct1" / "server" / "model_config.yaml")


def _extract_text(goal) -> str:
    """Extract plain text from goal (may be string or multimodal content array)."""
    if isinstance(goal, str):
        return goal
    if isinstance(goal, list):
        return " ".join(
            p.get("text", "") for p in goal if p.get("type") == "text"
        )
    return str(goal)


_EDIT_INTENT = {
    "change", "modify", "update", "edit", "fix", "add", "remove",
    "replace", "swap", "move", "resize", "make it", "make the",
    "adjust", "tweak", "set the", "turn the", "switch",
    "rename", "recolor", "restyle", "redesign", "redo",
    "bigger", "smaller", "wider", "narrower", "taller", "shorter",
    "darker", "lighter", "brighter", "bolder",
    "add a", "add the", "put a", "put the", "insert",
    "delete", "drop", "hide", "show",
}

_QUESTION_STARTS = (
    "what", "why", "how", "explain", "describe", "tell me",
    "is there", "is this", "is it", "are there", "can you explain",
    "which", "where", "when", "who", "does", "do you",
    "could you explain", "what's", "what is", "how does",
    "how do", "how is", "how are", "can i", "should",
)


class Orchestrator:
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = str(_CONFIG_PATH)

        cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        director_url = f"http://localhost:{cfg['llama_server']['port']}"
        specialist_url = f"http://localhost:{cfg['llama_server_specialist']['port']}"
        dc = cfg["models"]["director"]
        sc = cfg["models"]["specialist"]

        self.director = Director(
            base_url=director_url,
            temperature=dc["temperature"],
            top_p=dc["top_p"],
            top_k=dc["top_k"],
            presence_penalty=dc["presence_penalty"],
            max_tokens=dc["max_tokens"],
            vision_supported=dc.get("vision_supported", False),
        )

        self.specialist = Specialist(
            base_url=specialist_url,
            temperature=sc["temperature"],
            top_p=sc["top_p"],
            top_k=sc["top_k"],
            max_tokens=sc["max_tokens"],
            enable_thinking=sc.get("enable_thinking", False),
        )

        self.journal = Journal(cfg["journal"]["path"])
        self.journal_reader = JournalReader(cfg["journal"]["path"])
        self.verbose = False

        # Load lessons into Director personality
        lessons = self.journal_reader.get_recent_lessons(
            cfg["journal"]["lessons_on_startup"]
        )
        self.director.lessons = lessons

        # Load last session for continuity
        self.session_store = SessionStore(
            cfg.get("sessions", {}).get("path", "ct1/data/sessions")
        )
        last_session = self.session_store.read_latest()
        self.director.last_session = last_session or ""

    # ── Main pipeline ────────────────────────────────────────────────

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

        # Code exists — check user intent
        gl = goal_text.lower().strip()

        # Question detection (check first — questions take priority)
        if gl.startswith(_QUESTION_STARTS) or gl.endswith("?"):
            return "question", previous_code

        # Edit intent detection
        if any(kw in gl for kw in _EDIT_INTENT):
            return "edit", previous_code

        # Ambiguous — default to new (let specialist route normally)
        return "new", ""

    @staticmethod
    def _parse_patches(text: str) -> list[tuple[str, str]]:
        """Parse SEARCH/REPLACE blocks from model output."""
        text = strip_think_tags(text)
        text = extract_code(text)
        patches = []
        # Match <<<SEARCH ... === ... >>>
        for m in re.finditer(
            r'<<<\s*SEARCH\s*\n(.*?)\n===\n(.*?)\n>>>',
            text, re.DOTALL,
        ):
            search = m.group(1)
            replace = m.group(2)
            if search.strip():  # ignore empty search blocks
                patches.append((search, replace))
        return patches

    @staticmethod
    def _apply_patches(
        code: str, patches: list[tuple[str, str]],
    ) -> tuple[str, int]:
        """Apply search/replace patches to code. Returns (result, applied_count)."""
        result = code
        applied = 0
        for search, replace in patches:
            if search in result:
                result = result.replace(search, replace, 1)
                applied += 1
            else:
                # Try with normalized whitespace (tabs vs spaces, trailing ws)
                search_norm = re.sub(r'[ \t]+', ' ', search.strip())
                # Search through code with normalized whitespace
                lines = result.split('\n')
                found = False
                for i in range(len(lines)):
                    # Try matching a window of lines
                    search_lines = search.strip().split('\n')
                    if i + len(search_lines) > len(lines):
                        continue
                    window = '\n'.join(lines[i:i + len(search_lines)])
                    window_norm = re.sub(r'[ \t]+', ' ', window.strip())
                    if window_norm == search_norm:
                        # Found fuzzy match — replace the window
                        before = '\n'.join(lines[:i])
                        after = '\n'.join(lines[i + len(search_lines):])
                        result = before + '\n' + replace + '\n' + after
                        applied += 1
                        found = True
                        break
                if not found:
                    pass  # skip unapplicable patch
        return result, applied

    _FIX_KEYWORDS = {
        "fix", "broken", "error", "bug", "blank", "empty", "crash",
        "not working", "doesn't work", "won't load", "white screen",
        "not showing", "doesn't show", "missing", "incomplete",
    }

    @classmethod
    def _is_fix_request(cls, goal: str) -> bool:
        """Detect if this is a fix/debug request (needs full regen, not patches)."""
        g = goal.lower()
        return any(kw in g for kw in cls._FIX_KEYWORDS)

    async def _generate_edit(
        self, goal: str, route: str, previous_code: str,
        on_token, emit,
        specialist_data=None, conversation=None,
    ) -> tuple[str, str, bool]:
        """Handle edit-mode generation. Returns (draft, thinking, used_patch).

        Fix requests: skip patches, go straight to full regeneration.
        Patch edit: model outputs SEARCH/REPLACE blocks (not streamed to user).
        Fallback: full regeneration if patches fail.
        """
        # ── Fix/debug requests skip patch mode entirely ──────────────
        if self._is_fix_request(goal):
            on_token("[Fixing — full regeneration...]\n", "thinking")
            # Fall through to full regen below
            patches = []
            patch_thinking = ""
        else:
            # ── Try patch-based edit ─────────────────────────────────
            def thinking_only(token, kind):
                if kind == "thinking":
                    on_token(token, kind)

            on_token("[Applying edit...]\n", "thinking")

            patch_result = await self.director.generate_patch_edit(
                goal, previous_code, on_token=thinking_only,
            )
            patch_text = patch_result["text"]
            patch_thinking = patch_result.get("thinking", "")

            patches = self._parse_patches(patch_text)
            if patches:
                patched_code, applied = self._apply_patches(
                    previous_code, patches,
                )
                if applied > 0:
                    on_token(
                        f"[Applied {applied} change{'s' if applied > 1 else ''}"
                        f" — {len(patches)} total]\n", "thinking",
                    )
                    return patched_code, patch_thinking, True

        # ── Fallback: full regeneration with edit prompt ─────────────
        on_token("[Regenerating with changes...]\n", "thinking")

        if len(previous_code) > 6000:
            code_for_prompt = (
                previous_code[:4000]
                + "\n\n/* ... middle section unchanged ... */\n\n"
                + previous_code[-2000:]
            )
        else:
            code_for_prompt = previous_code

        result = await self.director.generate(
            f"Modify this code:\n{code_for_prompt}\n\nChange requested: {goal}",
            route,
            specialist_data=specialist_data,
            plan=None,
            conversation=None,
            on_token=on_token,
            is_edit=True,
        )
        return result["text"], result.get("thinking", ""), False

    async def _pipeline(self, goal, on_event=None,
                        conversation: list[dict] = None) -> dict:
        if conversation is None:
            conversation = []

        # Extract text for routing/planning (multimodal-safe)
        goal_text = _extract_text(goal)

        # Warn if images attached but vision not supported
        has_images = (isinstance(goal, list) and
                      any(p.get("type") == "image_url" for p in goal))
        if has_images and not self.director.vision_supported:
            if on_event:
                on_event("warning", message="Image attached but vision is not available with current model. The image will be ignored.")

        def emit(event: str, **data):
            if on_event:
                on_event(event, **data)

        # Detect conversation mode (edit / question / new)
        mode, previous_code = self._detect_conversation_mode(goal_text, conversation)
        is_edit = mode == "edit"

        # ── Phase 1: ROUTE ────────────────────────────────────
        if is_edit:
            route = "ROUTE_CODE"
            emit("routing")
            emit("routed", route=route)
        elif mode == "question":
            route = "ROUTE_DIRECT"
            emit("routing")
            emit("routed", route=route)
        else:
            emit("routing")
            route = await self.specialist.route(goal_text, conversation=conversation)
            emit("routed", route=route)

        is_code = route in ("ROUTE_DESIGN", "ROUTE_CODE")

        # ── Phase 2: PLAN (code routes only, skip for edits) ────────
        plan = None
        if is_code and not is_edit:
            plan = await self.specialist.plan(goal_text, route)
            emit("planned", plan=plan)

        # ── Phase 3: CONSULT (ROUTE_DESIGN only, skip for edits) ──
        specialist_data = None
        if route == "ROUTE_DESIGN" and not is_edit:
            emit("consulting")
            specialist_data = await self.specialist.consult(
                goal_text, conversation=conversation,
            )
            emit("consulted", data=specialist_data)

        # ── Phase 4: GENERATE (streamed) ──────────────────────────────
        emit("generating", editing=is_edit)

        def on_token(token, kind):
            emit("token", text=token, kind=kind)

        used_section_edit = False

        if is_edit and is_code:
            draft, draft_thinking, used_section_edit = await self._generate_edit(
                goal_text, route, previous_code, on_token, emit,
                specialist_data=specialist_data,
                conversation=conversation,
            )
            # Push patched code to streamingText so preview shows it immediately
            emit("token", text=draft, kind="content")
        else:
            result = await self.director.generate(
                goal, route,
                specialist_data=specialist_data,
                plan=plan,
                conversation=conversation,
                on_token=on_token,
                code_context=previous_code if mode == "question" else None,
            )
            draft = result["text"]
            draft_thinking = result.get("thinking", "")

        emit("draft", text=draft, thinking=draft_thinking)

        final_response = draft
        final_thinking = draft_thinking

        # ── Phase 4.5: POLISH (CSS refinement for HTML, skip edits) ──────
        polish_output_type = plan.get("output_type", "html_page") if plan else "html_page"
        if is_code and not is_edit and polish_output_type == "html_page":
            sections = split_html_sections(draft)
            css = sections.get("style", "")
            if css and len(css) > 50:
                emit("polishing")

                # Don't stream tokens — polish reasoning isn't useful to the user
                polish_result = await self.director.polish_css(css)
                polished_css = strip_think_tags(polish_result["text"])
                polished_css = extract_code(polished_css)

                if len(polished_css) > 50:
                    final_response = reassemble_html_section(
                        draft, "style", polished_css,
                    )
                    emit("polished", code=final_response)

        # ── Phase 5: VALIDATE (skip for edits — base was already valid) ──
        if is_code and not is_edit:
            output_type = plan.get("output_type", "html_page") if plan else "html_page"

            # Programmatic validation (real syntax check, no AI)
            issues = validate_output(draft, output_type)

            # Specialist review only if programmatic check found issues
            # (2B model hallucinates missing tags on truncated code)
            review_result = {"pass": True, "critical_issues": [], "fix_instructions": ""}
            if issues and output_type in ("html_page", "other"):
                review_result = await self.specialist.review(
                    goal_text, draft, conversation=conversation
                )

            all_issues = list(issues)
            if not review_result["pass"]:
                all_issues.extend(review_result.get("critical_issues", []))

            if all_issues:
                emit("validating", issues=all_issues, review=review_result)
                emit("fixing")

                fix_prompt = (
                    f"Fix ALL these issues in the code:\n"
                    + "\n".join(f"- {i}" for i in all_issues)
                    + (f"\n\n{review_result['fix_instructions']}"
                       if review_result.get("fix_instructions") else "")
                    + f"\n\nOriginal code:\n{draft}"
                )

                def on_fix_token(token, kind):
                    emit("token", text=token, kind=kind)

                fix_result = await self.director.generate(
                    fix_prompt, route,
                    specialist_data=specialist_data,
                    plan=None,  # don't re-plan for fix pass
                    conversation=conversation,
                    on_token=on_fix_token,
                )
                final_response = fix_result["text"]
                final_thinking = fix_result.get("thinking", "")
            else:
                emit("validated", issues=[], review=review_result)
        elif is_edit:
            emit("validated", issues=[], review={"pass": True,
                 "critical_issues": [], "fix_instructions": ""})

        # ── Phase 6: FORMAT ──────────────────────────────────────────
        if used_section_edit:
            # Section edits are already assembled — only strip think tags
            final_response = strip_think_tags(final_response)
        else:
            output_type = plan.get("output_type", "html_page") if plan else "html_page"
            final_response = clean_response(
                final_response, is_code=is_code, output_type=output_type
            )

        # ── Reflection ───────────────────────────────────────────────
        complexity = plan.get("complexity", "moderate") if plan else "moderate"
        reflection = await self.director.reflect(
            goal_text, complexity, final_response,
            conversation=conversation,
        )
        self.journal.write(reflection)

        return {
            "response": final_response,
            "thinking": final_thinking,
            "draft": draft,
            "draft_thinking": draft_thinking,
            "route": route,
            "specialist_data": specialist_data,
            "plan": plan,
            "reflection": reflection,
        }

    async def think(self, goal, on_event=None,
                    conversation: list[dict] = None) -> dict:
        return await self._pipeline(
            goal, on_event=on_event, conversation=conversation or []
        )

    async def close(self):
        await self.director.close()
        await self.specialist.close()
