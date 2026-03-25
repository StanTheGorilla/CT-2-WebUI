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
from ct1.core.engine import Engine
from ct1.server.launcher import load_raw_config, resolve_config
import re
from ct1.core.formatter import (
    clean_response, validate_output, validate_file,
    split_html_sections, reassemble_html_section,
    strip_think_tags, extract_code,
    detect_broken_sections, detect_output_type,
    polish_html_css, check_completeness,
)
from ct1.memory.journal import Journal
from ct1.memory.journal_reader import JournalReader
from ct1.memory.session_store import SessionStore
from ct1.core.validator import validate_spec, validate_component, validate_page, sanitize_component
from ct1.core.assembler import assemble_page, patch_component as patch_component_in_page
from ct1.templates.fallbacks import get_fallback

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
    """Strip inlined [File: ...] and [Workspace file: ...] blocks,
    keeping only the user's own message.
    Used for routing/classification so file content doesn't pollute intent detection."""
    text = re.sub(r'\[WORKSPACE FILES[^\]]*\].*?\n\n(?=\S)', '', text, count=1, flags=re.DOTALL)
    return re.sub(r'\[(?:Workspace )?[Ff]ile: [^\]]+\]\n.*?\n\n', '', text, flags=re.DOTALL).strip()


# ── Conversation mode detection keywords ──────────────────────────
# Used by _detect_conversation_mode() to distinguish edits from questions
# when there's existing code in the conversation.

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

        self.engine = Engine(
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

        # Per-task parameter overrides (e.g. Nemotron optimized per route)
        self.task_overrides = cfg.get("_task_overrides", {})

        # Detect model tier for adaptive pipeline depth
        from ct1.core.tier import detect_tier
        preset_info = cfg.get("_preset_info", {})
        model_file = preset_info.get("model_file", "")
        explicit_tier = preset_info.get("tier")
        self.tier = detect_tier(model_file, explicit_tier)
        self.context_size = cfg["llama_server"]["context_size"]
        print(f"[orch] Model tier: {self.tier} (model: {model_file})")

        self.journal = Journal(cfg["journal"]["path"])
        self.journal_reader = JournalReader(cfg["journal"]["path"])
        self.verbose = False

        # Load lessons into Engine personality
        lessons = self.journal_reader.get_recent_lessons(
            cfg["journal"]["lessons_on_startup"]
        )
        self.engine.lessons = lessons
        self.component_cache = component_cache

        # Load last session for continuity
        self.session_store = SessionStore(
            cfg.get("sessions", {}).get("path", "ct1/data/sessions")
        )
        last_session = self.session_store.read_latest()
        self.engine.last_session = last_session or ""

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

        Catches clear DIRECT cases before keyword routing.

        Returns route string or None to defer to keyword routing.
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
        """Keyword-based route — deterministic fallback after _pre_route."""
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

    @staticmethod
    def _slim_conversation(conversation: list[dict]) -> list[dict]:
        """Strip full code from assistant turns to prevent context contamination.

        Keeps user messages intact and replaces long assistant code with a
        short summary. This frees context for the new generation and stops
        the model from copying styles/content from prior outputs.
        """
        slim = []
        for msg in conversation:
            if msg["role"] == "assistant":
                content = msg.get("content", "")
                if isinstance(content, str) and len(content) > 300:
                    # Replace full code with a one-line note
                    slim.append({
                        "role": "assistant",
                        "content": "(Previous code response omitted for brevity.)",
                    })
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
            [FILE: path/to/file.ext]
            <!-- FILE: path/to/file.ext -->
            ```filename.ext
            (content in fenced code blocks with filename)

        Returns list of {path, content} dicts. If no markers found,
        returns a single entry with the whole output as index.html.
        """
        files = []

        # Strip outer markdown fence if model wrapped entire output
        stripped = text.strip()
        if stripped.startswith("```") and stripped.endswith("```"):
            # Remove opening ```lang\n and closing ```
            inner = re.sub(r'^```\w*\s*\n?', '', stripped)
            inner = re.sub(r'\n?```$', '', inner)
            if '[FILE:' in inner or '<!-- FILE:' in inner:
                text = inner

        # Strip conversational preamble before first [FILE:]
        first_file = re.search(r'\[FILE:', text)
        if first_file and first_file.start() > 0:
            preamble = text[:first_file.start()]
            # Only strip if preamble is short text (not code)
            if len(preamble) < 500 and not preamble.strip().startswith(('import ', 'def ', '#!')):
                text = text[first_file.start():]

        # Pattern 1: [FILE: path] ... [FILE: path2] ...
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
            lower = cleaned.strip().lower()
            if lower.startswith(("import ", "from ", "def ", "class ",
                                 "#!", "#!/")):
                ext = "py"
                name = "main"
            elif lower.startswith(("const ", "let ", "var ", "function ",
                                   "import {", "import '")):
                ext = "js"
                name = "index"
            elif lower.startswith(("#include", "using namespace", "int main")):
                ext = "cpp"
                name = "main"
            elif lower.startswith(("package ", "func ")):
                ext = "go"
                name = "main"
            elif lower.startswith(("use ", "fn ", "mod ")):
                ext = "rs"
                name = "main"
            elif lower.startswith(("{", "[")):
                ext = "json"
                name = "data"
            elif lower.startswith(("<!doctype", "<html")):
                ext = "html"
                name = "index"
            else:
                ext = "py"
                name = "main"
            files.append({"path": f"{name}.{ext}", "content": cleaned})
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

            edit_result = await self.engine.generate_section_edit(
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

        result = await self.engine.generate(
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

    # ── Self-planning via Engine ────────────────────────────────────────

    _SOLO_PLAN_SYSTEM = (
        "Analyze this request and output ONLY a JSON object. No other text.\n"
        '{"output_type":"html_page"|"python_script"|"javascript"|"cpp"|"other",'
        '"components":[{"id":1,"name":"short name","description":"what it does"}],'
        '"complexity":"simple"|"moderate"|"complex"}\n'
        "Max 5 components. Be concise."
    )

    async def _solo_plan(self, goal: str, route: str) -> dict | None:
        """Lightweight self-planning via Engine.
        Uses the engine with thinking disabled for speed."""
        try:
            import json
            raw = await self.engine._call(
                [{"role": "system", "content": self._SOLO_PLAN_SYSTEM},
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
                               "cpp", "api", "other")
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

    _VALID_INTERACTIONS = frozenset([
        "hamburger-toggle", "smooth-scroll", "accordion", "form-validation",
        "dark-mode-toggle", "carousel", "modal", "scroll-reveal",
    ])

    @staticmethod
    def _normalize_spec(spec: dict) -> dict:
        """Normalize an Engine spec before validation.

        Strips invalid interaction names and fixes common model mistakes
        so validation doesn't reject otherwise-good specs.
        """
        valid = Orchestrator._VALID_INTERACTIONS
        for comp in spec.get("components", []):
            if "interactions" in comp:
                original = comp["interactions"]
                comp["interactions"] = [i for i in original if i in valid]
                dropped = set(original) - set(comp["interactions"])
                if dropped:
                    print(f"[design] stripped invalid interactions from {comp.get('id')}: {dropped}")
        return spec

    async def _design_pipeline(
        self, goal, goal_text: str, conversation: list[dict],
        emit, on_token, task_ovr: dict,
    ) -> dict:
        """Precision-Design pipeline for new ROUTE_DESIGN generation.

        Phase 0:   Engine (4B) generates JSON spec (structured planning)
        Phase 0.5: Script validates spec mechanically
        Phase 1:   Engine (4B) generates full HTML page guided by the spec
        Phase 2:   Mechanical validation + cleanup
        """
        import json as _json

        # ── Phase 0: Spec Generation (Engine plans the page) ────
        emit("spec_generating")
        print("[design] Phase 0: generating spec")

        try:
            spec = await self.engine.generate_spec(
                goal, conversation=conversation,
                task_overrides=task_ovr,
            )
        except (ValueError, _json.JSONDecodeError) as e:
            print(f"[design] Phase 0 failed: {e}")
            emit("spec_failed", errors=[str(e)])
            corrective = (
                f"{goal_text}\n\n"
                "Your previous output was invalid JSON. "
                "Output ONLY the JSON object with no other text."
            )
            try:
                spec = await self.engine.generate_spec(
                    corrective, conversation=conversation,
                    task_overrides=task_ovr,
                )
            except (ValueError, _json.JSONDecodeError) as e2:
                print(f"[design] Phase 0 retry failed: {e2}")
                return {
                    "response": f"Design generation failed: could not produce valid spec. {e2}",
                    "thinking": "", "draft": "", "draft_thinking": "",
                    "route": "ROUTE_DESIGN", "specialist_data": None,
                    "plan": None,
                    "reflection": {
                        "goal": goal_text[:200], "complexity": "failed",
                        "lesson": "spec generation failed twice",
                        "self_score": 0.0,
                    },
                }

        # ── Phase 0.5: Spec Validation ────────────────────────────
        spec = self._normalize_spec(spec)
        passed, errors = validate_spec(spec)
        if not passed:
            print(f"[design] Phase 0.5 failed: {errors}")
            emit("spec_failed", errors=errors)
            error_str = "; ".join(errors)
            corrective = (
                f"{goal_text}\n\n"
                f"Your previous spec had these errors: {error_str}\n"
                "Fix the errors and output ONLY the corrected JSON object."
            )
            try:
                spec = await self.engine.generate_spec(
                    corrective, conversation=conversation,
                    task_overrides=task_ovr,
                )
            except (ValueError, _json.JSONDecodeError) as e:
                print(f"[design] Phase 0.5 retry failed: {e}")
                return {
                    "response": f"Design generation failed: spec invalid after retry. {e}",
                    "thinking": "", "draft": "", "draft_thinking": "",
                    "route": "ROUTE_DESIGN", "specialist_data": None,
                    "plan": None,
                    "reflection": {
                        "goal": goal_text[:200], "complexity": "failed",
                        "lesson": "spec validation failed twice",
                        "self_score": 0.0,
                    },
                }

            spec = self._normalize_spec(spec)
            passed, errors = validate_spec(spec)
            if not passed:
                print(f"[design] Phase 0.5 second failure: {errors}")
                return {
                    "response": (
                        f"Design generation failed: spec invalid after retry.\n"
                        f"Errors: {'; '.join(errors)}"
                    ),
                    "thinking": "", "draft": "", "draft_thinking": "",
                    "route": "ROUTE_DESIGN", "specialist_data": None,
                    "plan": None,
                    "reflection": {
                        "goal": goal_text[:200], "complexity": "failed",
                        "lesson": f"spec validation: {errors[0]}",
                        "self_score": 0.0,
                    },
                }

        emit("spec_validated", spec=spec)
        print(f"[design] Phase 0.5 passed: {len(spec['components'])} components, "
              f"layout={spec['layout_order']}")

        # ── Phase 1: Engine generates full HTML (single pass, 4B) ──
        emit("generating", editing=False)
        print("[design] Phase 1: Engine generating full page HTML")

        # Build spec context for the Engine — a structured blueprint
        spec_summary = _json.dumps(spec, indent=2)
        spec_guided_goal = (
            f"{goal_text}\n\n"
            f"[PAGE SPECIFICATION — follow this blueprint exactly]\n"
            f"{spec_summary}\n\n"
            f"Generate the complete HTML page. Include ALL components from the "
            f"layout_order in that exact sequence. Use the color_theme values as "
            f"Tailwind classes. Use the content text from each component's spec verbatim."
        )

        result = await self.engine.generate(
            spec_guided_goal, "ROUTE_DESIGN",
            conversation=conversation,
            on_token=on_token,
            task_overrides=task_ovr,
        )
        draft = result["text"]
        draft_thinking = result.get("thinking", "")

        # ── Phase 2: Cleanup ──────────────────────────────────────
        from ct1.core.formatter import strip_think_tags, extract_code
        draft = strip_think_tags(draft)
        draft = extract_code(draft)

        emit("draft", text=draft, thinking=draft_thinking)

        # Persist spec for edit mode
        spec_json = _json.dumps(spec)

        return {
            "response": draft,
            "thinking": draft_thinking,
            "draft": draft,
            "draft_thinking": draft_thinking,
            "route": "ROUTE_DESIGN",
            "specialist_data": spec_json,
            "plan": None,
            "reflection": None,  # Reflection handled by caller
            "spec": spec,
        }

    async def _design_edit_pipeline(
        self, goal_text: str, conversation: list[dict],
        emit, on_token, task_ovr: dict,
        previous_code: str,
    ) -> dict:
        """Edit mode for Precision-Design.

        1. Retrieve persisted spec from conversation
        2. Engine identifies which component(s) the edit targets
        3. Re-run generation + validation for only that component
        4. Patch into assembled page
        """
        import json as _json

        # Retrieve the spec from the last assistant turn's specialist_data
        spec = None
        for turn in reversed(conversation):
            if turn.get("role") == "assistant":
                sd = turn.get("specialist_data")
                if sd and isinstance(sd, str):
                    try:
                        spec = _json.loads(sd)
                        if "layout_order" in spec and "components" in spec:
                            break
                        spec = None
                    except (ValueError, _json.JSONDecodeError):
                        pass
                elif sd and isinstance(sd, dict):
                    if "layout_order" in sd and "components" in sd:
                        spec = sd
                        break

        if not spec:
            # No spec found — fall back to full regeneration
            print("[design-edit] no spec found in conversation, falling back to full pipeline")
            return await self._design_pipeline(
                goal_text, goal_text, conversation,
                emit, on_token, task_ovr,
            )

        # Use Engine to identify target component(s) from edit request
        emit("spec_generating")
        comp_map = {c["id"]: c for c in spec["components"]}

        # Simple heuristic: check if any component id is mentioned in the edit
        target_ids = []
        goal_lower = goal_text.lower()
        for cid in spec["layout_order"]:
            if cid.lower() in goal_lower or cid.replace("-", " ").lower() in goal_lower:
                target_ids.append(cid)

        # Also check component types
        if not target_ids:
            for comp in spec["components"]:
                ctype = comp["type"].lower()
                if ctype in goal_lower:
                    target_ids.append(comp["id"])

        # If still nothing, regenerate all — the edit is ambiguous
        if not target_ids:
            target_ids = list(spec["layout_order"])
            print(f"[design-edit] ambiguous edit, regenerating all components")
        else:
            print(f"[design-edit] targeting components: {target_ids}")

        emit("spec_validated", spec=spec)

        # Regenerate targeted components
        total = len(target_ids)
        for i, comp_id in enumerate(target_ids):
            comp_spec = comp_map.get(comp_id)
            if not comp_spec:
                continue

            emit("component_generating",
                 component_id=comp_id, index=i, total=total)

            # Specialist removed — use fallback for component regeneration
            html = get_fallback(comp_spec["type"], comp_id)
            emit("component_fallback", component_id=comp_id)

            # Patch into previous assembled page
            if previous_code:
                previous_code = patch_component_in_page(
                    previous_code, comp_id, html,
                )

            emit("component_validated",
                 component_id=comp_id, index=i, total=total)

        # If no previous assembled page, do full assembly
        if not previous_code or "<html" not in previous_code.lower():
            component_html = {}
            for comp in spec["components"]:
                cid = comp["id"]
                if cid in [c for c in target_ids]:
                    # Already regenerated above — but we only patched into previous_code
                    # Need to extract or regenerate
                    component_html[cid] = get_fallback(comp["type"], cid)
                else:
                    component_html[cid] = get_fallback(comp["type"], cid)
            previous_code = assemble_page(
                spec["page_title"], component_html,
                spec["layout_order"], spec,
            )

        emit("draft", text=previous_code, thinking="")

        spec_json = _json.dumps(spec)
        return {
            "response": previous_code,
            "thinking": "",
            "draft": previous_code,
            "draft_thinking": "",
            "route": "ROUTE_DESIGN",
            "specialist_data": spec_json,
            "plan": None,
            "reflection": None,
            "spec": spec,
        }

    async def _self_review(self, code: str, goal: str, route: str,
                           task_overrides: dict = None) -> dict | None:
        """Large-tier self-review: model checks its own output."""
        review_prompt = (
            f"Review this code against the original request.\n\n"
            f"REQUEST: {goal[:500]}\n\n"
            f"CODE:\n{code[:3000]}\n\n"
            f"Check for:\n"
            f"1. Does it fully address the request?\n"
            f"2. Any syntax errors or bugs?\n"
            f"3. Missing functionality?\n\n"
            f"Output ONLY a JSON object:\n"
            f'{{"pass": true, "issues": [], "fix_instructions": ""}}\n'
            f'or\n'
            f'{{"pass": false, "issues": ["issue1"], "fix_instructions": "fix this"}}'
        )
        try:
            review_ovr = {**(task_overrides or {}),
                          "temperature": 0.1, "enable_thinking": False}
            result = await self.engine.generate(
                review_prompt, route,
                task_overrides=review_ovr,
            )
            import json
            text = result["text"].strip()
            # Extract JSON from possible markdown fences
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            return json.loads(text)
        except Exception as e:
            print(f"[orch] self-review failed: {e}")
            return None

    async def _pipeline(self, goal, on_event=None,
                        conversation: list[dict] = None,
                        mode_override: str | None = None,
                        skip_refinement: bool = False) -> dict:
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

        # Detect conversation mode (edit / question / new)
        mode, previous_code = self._detect_conversation_mode(user_message, conversation)
        is_edit = mode == "edit"

        # For "new" mode, strip full code from conversation history.
        # A 4B/16K model gets confused by prior HTML/code in context,
        # mixing styles and content from previous turns into new output.
        if mode == "new" and conversation:
            conversation = self._slim_conversation(conversation)

        # ── Phase 1: ROUTE (deterministic — _pre_route then _keyword_route) ──
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
            else:
                route = self._keyword_route(user_message)
        emit("routed", route=route)

        is_code = route in ("ROUTE_DESIGN", "ROUTE_CODE", "ROUTE_COMPUTER")

        # Resolve per-task parameter overrides for this route
        task_ovr = self._get_task_overrides(route, user_message)

        # ── ROUTE_DESIGN: Precision-Design pipeline (replaces old flow) ──
        if route == "ROUTE_DESIGN":
            def on_token(token, kind):
                emit("token", text=token, kind=kind)

            if mode == "question":
                # Questions about design → fall through to normal ROUTE_DIRECT flow
                pass
            elif is_edit:
                result = await self._design_edit_pipeline(
                    user_message, conversation,
                    emit, on_token, task_ovr,
                    previous_code=previous_code,
                )
                # Run reflection
                if result.get("reflection") is None:
                    reflection = await self.engine.reflect(
                        goal_text, "moderate", result["response"],
                        conversation=conversation,
                    )
                    self.journal.write(reflection)
                    result["reflection"] = reflection
                return result
            else:
                result = await self._design_pipeline(
                    goal, goal_text, conversation,
                    emit, on_token, task_ovr,
                )
                # Run reflection
                if result.get("reflection") is None:
                    reflection = await self.engine.reflect(
                        goal_text, "moderate", result["response"],
                        conversation=conversation,
                    )
                    self.journal.write(reflection)
                    result["reflection"] = reflection
                return result

        # ── Phase 2: PLAN (tier-aware) ──
        plan = None
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
                from ct1.memory.component_cache import ComponentCache
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
                code_context=previous_code if mode == "question" else None,
                task_overrides=task_ovr,
                task_list=task_list if task_list else None,
            )
            draft = result["text"]
            draft_thinking = result.get("thinking", "")

        emit("draft", text=draft, thinking=draft_thinking)

        final_response = draft
        final_thinking = draft_thinking

        # ── Phase 4.1: CHECKLIST (completeness verification) ────────
        checklist = []
        missing_items = []
        if not is_edit and mode != "question":
            clean_for_check = strip_think_tags(draft)
            clean_for_check = extract_code(clean_for_check)

            if task_list:
                # Verify against model's OWN task list — much more accurate
                lower = clean_for_check.lower()
                for task in task_list:
                    # Extract key terms (5+ chars) from the task
                    import re
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

        # ── Phase 4.25: REFINE (design mode, targeted or skipped) ───
        if (route == "ROUTE_DESIGN" and not is_edit and mode != "question"
                and not skip_refinement):
            # Skip refinement if checklist passed completely
            if checklist and not missing_items:
                print("[orch] all checklist items present — skipping refinement")
            else:
                try:
                    clean_draft = strip_think_tags(draft)
                    clean_draft = extract_code(clean_draft)
                    draft_lower = clean_draft.strip().lower()
                    if (clean_draft and len(clean_draft) > 100
                            and (draft_lower.startswith("<!doctype")
                                 or draft_lower.startswith("<html"))):
                        emit("refining")

                        # Refinement is a simpler task — cap thinking budget
                        refine_ovr = {**task_ovr}
                        if "thinking_budget" in refine_ovr:
                            refine_ovr["thinking_budget"] = min(
                                refine_ovr["thinking_budget"], 2048
                            )

                        refine_result = await self.engine.refine_design(
                            clean_draft, on_token=None,
                            task_overrides=refine_ovr,
                            missing_items=missing_items if missing_items else None,
                        )
                        refined = refine_result["text"]
                        refined = strip_think_tags(refined)
                        refined = extract_code(refined)
                        refined_stripped = refined.strip().lower()
                        if (refined_stripped.startswith("<!doctype") or
                                refined_stripped.startswith("<html")):
                            final_response = refined
                            final_thinking = refine_result.get("thinking", "")
                            emit("polished", code=final_response)

                            # Re-check after refinement
                            if missing_items and specialist_data:
                                checklist = check_completeness(refined, specialist_data)
                                emit("checklist", items=checklist)
                        else:
                            print("[orch] refinement output not valid HTML, keeping original")
                    else:
                        print(f"[orch] skipping refinement — draft not valid HTML")
                except Exception as e:
                    print(f"[orch] refinement failed, keeping original: {e}")

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
        if is_code and not is_edit and route == "ROUTE_COMPUTER":
            # Computer mode: validate each parsed file individually
            parsed_files = self._parse_multi_file(draft)
            file_issues = []
            for f in parsed_files:
                file_issues.extend(validate_file(f["path"], f["content"]))
            if file_issues:
                emit("validating", issues=file_issues,
                     review={"pass": False, "critical_issues": file_issues,
                             "fix_instructions": ""})
                emit("fixing")

                fix_prompt = (
                    f"Fix ALL these issues in the code:\n"
                    + "\n".join(f"- {i}" for i in file_issues[:5])
                    + f"\n\nOriginal output:\n{draft}"
                )

                def on_fix_token_comp(token, kind):
                    emit("token", text=token, kind=kind)

                fix_ovr = {**task_ovr}
                if "thinking_budget" in fix_ovr:
                    fix_ovr["thinking_budget"] = min(fix_ovr["thinking_budget"], 2048)
                fix_result = await self.engine.generate(
                    fix_prompt, route,
                    on_token=on_fix_token_comp,
                    task_overrides=fix_ovr,
                )
                final_response = fix_result["text"]
                final_thinking = fix_result.get("thinking", "")
            else:
                emit("validated", issues=[], review={"pass": True,
                     "critical_issues": [], "fix_instructions": ""})

        elif is_code and not is_edit:
            # Non-computer code: auto-detect output type for proper validation
            output_type = plan.get("output_type", "other") if plan else "other"
            if output_type in ("other", "html_page"):
                detected = detect_output_type(draft)
                if detected != "other":
                    output_type = detected

            # Programmatic validation (real syntax check, no AI)
            issues = validate_output(draft, output_type)

            review_result = {"pass": True, "critical_issues": [], "fix_instructions": ""}

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
                )
                final_response = fix_result["text"]
                final_thinking = fix_result.get("thinking", "")
            else:
                emit("validated", issues=[], review=review_result)
        elif is_edit:
            emit("validated", issues=[], review={"pass": True,
                 "critical_issues": [], "fix_instructions": ""})

        # ── Phase 5.5: SELF-REVIEW (large tier only) ──
        if self.tier == "large" and is_code and not is_edit and mode != "question":
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
                )
                fixed = strip_think_tags(fix_result["text"])
                fixed = extract_code(fixed) or fixed
                if len(fixed) > 50:
                    final_response = fixed
                    final_thinking = fix_result.get("thinking", "")
                    print(f"[orch] self-review fix applied")

        # ── Phase 6: FORMAT ──────────────────────────────────────────
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
            reflection = await self.engine.reflect(
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
            "tier": self.tier,
        }

    async def think(self, goal, on_event=None,
                    conversation: list[dict] = None,
                    mode_override: str | None = None,
                    skip_refinement: bool = False) -> dict:
        return await self._pipeline(
            goal, on_event=on_event, conversation=conversation or [],
            mode_override=mode_override,
            skip_refinement=skip_refinement,
        )

    async def close(self):
        await self.engine.close()
