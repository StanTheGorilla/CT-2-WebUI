"""CT-2 Orchestrator: Sequential Supervisor-Worker pipeline.

6-phase pipeline:
  1. ROUTE    — Deterministic keyword classifier (no AI — instant, predictable)
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
from ct1.server.launcher import load_raw_config, resolve_config
import re
from ct1.core.formatter import (
    clean_response, validate_output,
    split_html_sections, reassemble_html_section,
    strip_think_tags, extract_code,
    detect_broken_sections,
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


def _strip_file_context(text: str) -> str:
    """Strip inlined [File: ...] blocks, keeping only the user's own message.
    Used for routing/classification so file content doesn't pollute intent detection."""
    return re.sub(r'\[File: [^\]]+\]\n.*?\n\n', '', text, flags=re.DOTALL).strip()


# ── Conversation mode detection keywords ──────────────────────────
# Used by _detect_conversation_mode() to distinguish edits from questions
# when there's existing code in the conversation. NOT used for routing
# (routing is handled by the Specialist AI).

_QUESTION_STARTS = (
    "what is", "what are", "what does", "what was", "what do",
    "explain", "describe", "tell me", "can you explain",
    "could you explain", "how does", "how do", "how is",
    "how can i", "how would", "how to",
    "why is", "why does", "why do", "why are",
    "who is", "who are", "where is", "where are",
    "when is", "when does", "what's", "where's",
    "is there", "is this", "is it", "are there", "are these",
    "does this", "does it", "do they", "do these",
    "which", "summarize", "summary", "show me",
)


def _is_question(msg: str) -> bool:
    """Detect if a message is purely asking for information.
    Used by _detect_conversation_mode() — NOT for routing."""
    lower = msg.lower().strip()
    if lower.startswith(_QUESTION_STARTS):
        return True
    if lower.endswith("?"):
        return True
    return False


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


class Orchestrator:
    def __init__(self, config_path: str = None, component_cache=None):
        if config_path is None:
            config_path = str(_CONFIG_PATH)

        raw_cfg = load_raw_config(config_path)
        cfg = resolve_config(raw_cfg, config_path)

        director_url = f"http://localhost:{cfg['llama_server']['port']}"
        dc = cfg["models"]["director"]

        self.director = Director(
            base_url=director_url,
            temperature=dc["temperature"],
            top_p=dc["top_p"],
            top_k=dc["top_k"],
            presence_penalty=dc["presence_penalty"],
            frequency_penalty=dc.get("frequency_penalty", 0),
            max_tokens=dc["max_tokens"],
            thinking_budget=dc.get("thinking_budget", -1),
            vision_supported=dc.get("vision_supported", False),
        )

        # Specialist is optional (solo presets don't have one)
        if "llama_server_specialist" in cfg:
            specialist_url = f"http://localhost:{cfg['llama_server_specialist']['port']}"
            sc = cfg["models"]["specialist"]
            self.specialist = Specialist(
                base_url=specialist_url,
                temperature=sc["temperature"],
                top_p=sc["top_p"],
                top_k=sc["top_k"],
                max_tokens=sc["max_tokens"],
                enable_thinking=sc.get("enable_thinking", False),
            )
        else:
            self.specialist = None

        # Per-task parameter overrides (e.g. Nemotron optimized per route)
        self.task_overrides = cfg.get("_task_overrides", {})

        self.journal = Journal(cfg["journal"]["path"])
        self.journal_reader = JournalReader(cfg["journal"]["path"])
        self.verbose = False

        # Load lessons into Director personality
        lessons = self.journal_reader.get_recent_lessons(
            cfg["journal"]["lessons_on_startup"]
        )
        self.director.lessons = lessons
        self.component_cache = component_cache

        # Load last session for continuity
        self.session_store = SessionStore(
            cfg.get("sessions", {}).get("path", "ct1/data/sessions")
        )
        last_session = self.session_store.read_latest()
        self.director.last_session = last_session or ""

    # ── Deterministic pre-routing (runs BEFORE AI routing) ──────────

    _DIRECT_SIGNALS = {
        "analyze", "analyse", "analyzing", "analysis",
        "evaluate", "evaluating", "evaluation",
        "advising", "advise", "advice",
        "recommend", "assess", "assessing",
        "compare", "contrast", "discuss",
        "maximize", "minimize", "optimize",
        "probability", "trade-off", "tradeoff",
        "pros and cons", "constraint",
        "scenario", "decompos",
        "think through", "reason about",
        "what would", "how would you", "what should",
        "advantages", "disadvantages",
        "calculate", "solve", "prove", "derive",
    }

    _BUILD_PHRASES = {
        "build", "create", "make me", "make a", "make an",
        "generate a", "generate an", "generate me",
        "write me", "write a", "write an",
        "code a", "code me", "implement a", "implement an",
        "develop a", "develop an", "scaffold",
        "build me", "create me", "give me a", "give me an",
        "set up a", "set up an",
    }

    @classmethod
    def _pre_route(cls, msg: str) -> str | None:
        """Deterministic pre-routing for obvious non-build requests.

        Catches clear DIRECT cases before the 2B specialist, which
        misroutes long analytical text containing words like
        'algorithm', 'design', 'function' as CODE.

        Returns route string or None to defer to AI/keyword routing.
        """
        lower = msg.lower().strip()

        # 1. Questions → always DIRECT
        if _is_question(lower):
            return "ROUTE_DIRECT"

        has_build = any(p in lower for p in cls._BUILD_PHRASES)

        # 2. Reasoning/analysis signals without build intent → DIRECT
        if any(s in lower for s in cls._DIRECT_SIGNALS) and not has_build:
            return "ROUTE_DIRECT"

        # 3. Long text (>300 chars) without build intent → DIRECT
        #    Real build requests are concise; long text is reasoning/scenarios
        if len(lower) > 300 and not has_build:
            return "ROUTE_DIRECT"

        # 4. Ambiguous — defer to AI/keyword routing
        return None

    # ── Solo-mode keyword router ─────────────────────────────────────

    _SOLO_DESIGN_KW = {
        "website", "web page", "webpage", "landing page", "portfolio",
        "homepage", "home page", "dashboard", "web app", "web site",
        "web design", "ui design", "ux design",
    }
    _SOLO_CODE_KW = {
        "script", "program", "function", "algorithm", "api", "endpoint",
        "server", "database", "sql", "python", "react", "svelte", "vue",
        "angular", "node", "component",
    }
    # Action verbs that turn a keyword match into a build request
    _SOLO_BUILD_VERBS = {
        "build", "create", "make", "generate", "design", "develop",
        "write", "code", "implement", "set up", "scaffold",
    }

    @classmethod
    def _keyword_route(cls, msg: str) -> str:
        """Keyword-based route for solo mode (no specialist available)."""
        lower = msg.lower().strip()

        # Questions are always DIRECT, even if they mention "website"
        if _is_question(lower):
            return "ROUTE_DIRECT"

        has_design_kw = any(kw in lower for kw in cls._SOLO_DESIGN_KW)
        has_code_kw = any(kw in lower for kw in cls._SOLO_CODE_KW)
        has_build_verb = any(v in lower for v in cls._SOLO_BUILD_VERBS)

        if has_design_kw and has_build_verb:
            return "ROUTE_DESIGN"
        if has_design_kw:
            # Even without explicit verb — "landing page for coffee shop" is a build request
            return "ROUTE_DESIGN"
        if has_code_kw and has_build_verb:
            return "ROUTE_CODE"
        if has_code_kw:
            return "ROUTE_CODE"
        return "ROUTE_DIRECT"

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
        if _is_question(gl):
            return "question", previous_code

        # Edit intent detection
        if any(kw in gl for kw in _EDIT_INTENT):
            return "edit", previous_code

        # Ambiguous — default to new (normal routing)
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

    # ── Reasoning detection for task overrides ──────────────────────
    _REASONING_KEYWORDS = {
        "solve", "calculate", "compute", "prove", "derive", "reason",
        "math", "equation", "formula", "theorem", "logic",
        "step by step", "step-by-step", "think through",
        "plan", "strategy", "outline", "break down", "breakdown",
    }

    def _get_task_overrides(self, route: str, goal_text: str) -> dict:
        """Select per-task parameter overrides based on route and content."""
        if not self.task_overrides:
            return {}

        # Check for reasoning keywords (math, planning, logic)
        lower = goal_text.lower()
        if any(kw in lower for kw in self._REASONING_KEYWORDS):
            if "reasoning" in self.task_overrides:
                return self.task_overrides["reasoning"]

        # Map route to override key
        route_map = {
            "ROUTE_CODE": "code",
            "ROUTE_DESIGN": "design",
            "ROUTE_DIRECT": "direct",
            "ROUTE_COMPUTER": "computer",
        }
        key = route_map.get(route, "direct")
        return self.task_overrides.get(key, {})

    # ── Multi-file parsing (Computer Mode) ──────────────────────────

    @staticmethod
    def _parse_run_commands(text: str) -> list[str]:
        """Parse <!-- RUN: command --> markers from model output."""
        matches = re.findall(r'\[RUN:\s*(.+?)\]', text)
        if not matches:
            matches = re.findall(r'<!--\s*RUN:\s*(.+?)\s*-->', text)
        return matches

    @staticmethod
    def _strip_run_markers(text: str) -> str:
        """Remove <!-- RUN: ... --> markers from text."""
        text = re.sub(r'\[RUN:\s*.+?\]\s*', '', text)
        text = re.sub(r'<!--\s*RUN:\s*.+?\s*-->\s*', '', text)
        return text.strip()

    @staticmethod
    def _parse_multi_file(text: str) -> list[dict]:
        """Parse model output for multi-file markers.

        Supports markers like:
            <!-- FILE: path/to/file.ext -->
            ```filename.ext
            (content in fenced code blocks with filename)

        Returns list of {path, content} dicts. If no markers found,
        returns a single entry with the whole output as index.html.
        """
        files = []

        # Pattern 1: <!-- FILE: path --> ... <!-- FILE: path2 -->
        parts = re.split(r'\[FILE:\s*(.+?)\]', text)
        if len(parts) <= 2:
            parts = re.split(r'<!--\s*FILE:\s*(.+?)\s*-->', text)
        if len(parts) > 2:
            # parts = [preamble, filename1, content1, filename2, content2, ...]
            for i in range(1, len(parts), 2):
                filename = parts[i].strip()
                content = parts[i + 1].strip() if i + 1 < len(parts) else ""
                content = Orchestrator._strip_run_markers(content)
                content = strip_think_tags(content)
                content = extract_code(content)
                if content:
                    files.append({"path": filename, "content": content})
            return files

        # Pattern 2: ```filename.ext ... ```
        for m in re.finditer(
            r'```(\S+\.\w+)\s*\n(.*?)```', text, re.DOTALL
        ):
            filename = m.group(1).strip()
            content = m.group(2).strip()
            if content and '/' not in filename[:1]:  # skip language labels like ```html
                files.append({"path": filename, "content": content})

        if files:
            return files

        # No multi-file markers — return as single file
        cleaned = Orchestrator._strip_run_markers(text)
        cleaned = strip_think_tags(cleaned)
        cleaned = extract_code(cleaned)
        if cleaned:
            ext = "html"
            lower = cleaned.strip().lower()
            if lower.startswith(("import ", "from ", "def ", "class ",
                                 "#!", "#!/")):
                ext = "py"
            elif lower.startswith(("const ", "let ", "var ", "function ",
                                   "import {", "import '")):
                ext = "js"
            elif lower.startswith(("{", "[")):
                ext = "json"
            files.append({"path": f"index.{ext}", "content": cleaned})
        return files

    # ── Section-based editing ────────────────────────────────────────

    @staticmethod
    def _identify_edit_sections(goal: str) -> list[str]:
        """Determine which HTML sections an edit request affects (keyword-based)."""
        lower = goal.lower()
        sections = []
        style_kw = {
            "color", "background", "font", "size", "style", "css",
            "border", "margin", "padding", "width", "height",
            "darker", "lighter", "bigger", "smaller", "gradient",
            "shadow", "round", "spacing", "align", "layout",
            "theme", "opacity", "responsive",
            "design", "look", "aesthetic", "palette",
        }
        body_kw = {
            "add", "remove", "section", "text", "content", "heading",
            "paragraph", "image", "link", "button", "nav", "footer",
            "header", "card", "list", "table", "form", "title",
            "menu", "sidebar", "hero", "banner", "icon", "logo",
        }
        script_kw = {
            "click", "event", "handler", "toggle",
            "function", "script", "interactive", "scroll", "timer",
            "modal", "dropdown", "animate", "animation",
        }
        head_kw = {"meta", "favicon", "seo", "description", "og:"}
        if any(kw in lower for kw in style_kw):
            sections.append("style")
        if any(kw in lower for kw in body_kw):
            sections.append("body")
        if any(kw in lower for kw in script_kw):
            sections.append("script")
        if any(kw in lower for kw in head_kw):
            sections.append("head")
        return sections or ["style", "body"]

    async def _section_edit(
        self, goal: str, html: str, sections: dict,
        on_token, emit,
    ) -> tuple[str, str, bool]:
        """Section-based HTML editing — only regenerates affected sections.

        Preserves all unchanged sections exactly. The 4B model only needs
        to output one small section at a time instead of the whole document.
        """
        affected = self._identify_edit_sections(goal)
        # Edit in logical order: body (structure) → style → script → head
        ordered = [s for s in ("body", "style", "script", "head")
                   if s in affected and s in sections]

        on_token(f"[Editing: {', '.join(ordered)}]\n", "thinking")

        result_html = html
        all_thinking = ""

        for section_name in ordered:
            # Only forward thinking tokens, not content (we assemble at the end)
            def thinking_only(token, kind):
                if kind == "thinking":
                    on_token(token, kind)

            edit_result = await self.director.generate_section_edit(
                goal, section_name, sections, on_token=thinking_only,
            )

            new_content = strip_think_tags(edit_result["text"])
            new_content = extract_code(new_content)

            if new_content and len(new_content) > 10:
                result_html = reassemble_html_section(
                    result_html, section_name, new_content,
                )
                # Update sections dict so next section sees updated context
                sections[section_name] = new_content
                on_token(f"[Updated {section_name}]\n", "thinking")

            if edit_result.get("thinking"):
                all_thinking += edit_result["thinking"] + "\n"

        return result_html, all_thinking, True

    async def _generate_edit(
        self, goal: str, route: str, previous_code: str,
        on_token, emit,
        specialist_data=None, conversation=None,
        task_overrides=None,
    ) -> tuple[str, str, bool]:
        """Handle edit-mode generation. Returns (draft, thinking, used_section_edit).

        For HTML: section-based editing — only regenerates affected sections
        (style/body/script/head) while preserving everything else exactly.
        For other code: full regeneration with edit context.
        """
        stripped = previous_code.strip().lower()
        is_html = (stripped.startswith("<!doctype") or stripped.startswith("<html"))

        # HTML: use section-based editing for reliability
        if is_html:
            sections = split_html_sections(previous_code)
            if sections:
                return await self._section_edit(
                    goal, previous_code, sections, on_token, emit,
                )

        # Non-HTML or failed to split: full regeneration
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
            task_overrides=task_overrides,
        )
        return result["text"], result.get("thinking", ""), False

    # Mode override → route mapping
    _MODE_ROUTE_MAP = {
        "design": "ROUTE_DESIGN",
        "code": "ROUTE_CODE",
        "chat": "ROUTE_DIRECT",
        "computer": "ROUTE_COMPUTER",
    }

    async def _pipeline(self, goal, on_event=None,
                        conversation: list[dict] = None,
                        mode_override: str | None = None) -> dict:
        if conversation is None:
            conversation = []

        # Extract text for routing/planning (multimodal-safe)
        goal_text = _extract_text(goal)
        # Strip inlined file content for intent detection / routing
        user_message = _strip_file_context(goal_text)

        # Handle images when vision not supported
        has_images = (isinstance(goal, list) and
                      any(p.get("type") == "image_url" for p in goal))
        no_vision = has_images and not self.director.vision_supported
        if no_vision:
            if on_event:
                on_event("warning", message="Image attached but vision is not available with current model. The image will be ignored.")

        def emit(event: str, **data):
            if on_event:
                on_event(event, **data)

        # Detect conversation mode (edit / question / new)
        mode, previous_code = self._detect_conversation_mode(user_message, conversation)
        is_edit = mode == "edit"

        # ── Phase 1: ROUTE (AI via Specialist, with deterministic fast-paths) ──
        emit("routing")
        forced_route = self._MODE_ROUTE_MAP.get(mode_override or "")
        if forced_route:
            # User explicitly selected a mode — skip AI routing
            if is_edit:
                route = forced_route if forced_route != "ROUTE_DIRECT" else "ROUTE_CODE"
            elif mode == "question" and forced_route == "ROUTE_DIRECT":
                route = "ROUTE_DIRECT"
            else:
                route = forced_route
            print(f"[mode-override] → {route} (user selected '{mode_override}')")
        elif no_vision and not is_edit:
            route = "ROUTE_DIRECT"
        elif is_edit:
            route = "ROUTE_CODE"
        elif mode == "question":
            route = "ROUTE_DIRECT"
        else:
            route = self._pre_route(user_message)
            if route:
                print(f"[pre-route] → {route} (deterministic)")
            elif self.specialist:
                route = await self.specialist.route(user_message)
            else:
                route = self._keyword_route(user_message)
        emit("routed", route=route)

        is_code = route in ("ROUTE_DESIGN", "ROUTE_CODE", "ROUTE_COMPUTER")

        # Resolve per-task parameter overrides for this route
        task_ovr = self._get_task_overrides(route, user_message)

        # ── Phase 2: PLAN (code routes only, skip for edits, needs specialist) ──
        plan = None
        if is_code and not is_edit and self.specialist and route != "ROUTE_COMPUTER":
            plan = await self.specialist.plan(user_message, route)
            emit("planned", plan=plan)

        # ── Phase 3: CONSULT (ROUTE_DESIGN only, skip for edits, needs specialist) ──
        specialist_data = None
        if route == "ROUTE_DESIGN" and not is_edit and self.specialist:
            emit("consulting")
            # Fetch cached references for the specialist
            references = []
            if self.component_cache:
                try:
                    from ct1.memory.component_cache import ComponentCache
                    keywords = ComponentCache.extract_tags(user_message)
                    refs = await self.component_cache.search_similar(keywords, limit=2)
                    for r in refs:
                        references.append({
                            "category": r["category"],
                            "tags": r["tags"],
                            "score": r["score"],
                            "snippet": r["html_snippet"][:500],
                        })
                except Exception as e:
                    print(f"[orch] cache search error: {e}")
            specialist_data = await self.specialist.consult(
                user_message, conversation=conversation,
                references=references if references else None,
            )
            emit("consulted", data=specialist_data)

        # ── Phase 4: GENERATE (streamed) ──────────────────────────────
        emit("generating", editing=is_edit)

        def on_token(token, kind):
            emit("token", text=token, kind=kind)

        used_section_edit = False

        if is_edit and is_code:
            draft, draft_thinking, used_section_edit = await self._generate_edit(
                user_message, route, previous_code, on_token, emit,
                specialist_data=specialist_data,
                conversation=conversation,
                task_overrides=task_ovr,
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
                task_overrides=task_ovr,
            )
            draft = result["text"]
            draft_thinking = result.get("thinking", "")

        emit("draft", text=draft, thinking=draft_thinking)

        final_response = draft
        final_thinking = draft_thinking

        # ── Phase 4.5: POLISH (CSS refinement for HTML, skip edits) ──────
        polish_output_type = plan.get("output_type", "html_page") if plan else "html_page"
        if is_code and not is_edit and route != "ROUTE_COMPUTER" and polish_output_type == "html_page":
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
        if is_code and not is_edit and route != "ROUTE_COMPUTER":
            output_type = plan.get("output_type", "html_page") if plan else "html_page"

            # Programmatic validation (real syntax check, no AI)
            issues = validate_output(draft, output_type)

            # Specialist review only if programmatic check found issues
            # and specialist is available (solo mode skips this)
            review_result = {"pass": True, "critical_issues": [], "fix_instructions": ""}
            if issues and output_type in ("html_page", "other") and self.specialist:
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
                    task_overrides=task_ovr,
                )
                final_response = fix_result["text"]
                final_thinking = fix_result.get("thinking", "")
            else:
                emit("validated", issues=[], review=review_result)
        elif is_edit:
            emit("validated", issues=[], review={"pass": True,
                 "critical_issues": [], "fix_instructions": ""})

        # ── Phase 6: FORMAT ──────────────────────────────────────────
        if route == "ROUTE_COMPUTER":
            # Computer mode: only strip thinking, preserve FILE/RUN markers
            final_response = strip_think_tags(final_response)
        elif used_section_edit:
            final_response = strip_think_tags(final_response)
        else:
            output_type = plan.get("output_type", "html_page") if plan else "html_page"
            final_response = clean_response(
                final_response, is_code=is_code, output_type=output_type
            )

        # ── Phase 6.5: AUTO-RETRY broken sections (max 2 attempts) ──
        # Skip for computer mode — multi-file output doesn't use HTML section structure
        if is_code and not is_edit and route != "ROUTE_COMPUTER":
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
                        retry_result = await self.director.generate_section_edit(
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
            reflection = await self.director.reflect(
                goal_text, complexity, final_response,
                conversation=conversation,
            )
            self.journal.write(reflection)

            # Auto-cache high-scoring outputs
            if (self.component_cache
                    and reflection.get("self_score", 0) >= 0.85
                    and not is_edit):
                try:
                    from ct1.memory.component_cache import ComponentCache
                    tags = ComponentCache.extract_tags(goal_text, specialist_data)
                    category = ComponentCache.categorize(goal_text, plan)
                    await self.component_cache.save_component(
                        category, tags, final_response,
                        reflection["self_score"], goal_text[:200],
                    )
                except Exception as e:
                    print(f"[orch] cache save error: {e}")
        else:
            reflection = {
                "goal": goal_text[:200], "complexity": "brief",
                "lesson": "", "self_score": 0.0,
            }

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
                    conversation: list[dict] = None,
                    mode_override: str | None = None) -> dict:
        return await self._pipeline(
            goal, on_event=on_event, conversation=conversation or [],
            mode_override=mode_override,
        )

    async def close(self):
        await self.director.close()
        if self.specialist:
            await self.specialist.close()
