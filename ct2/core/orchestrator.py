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
from ct2.memory.plan_cache import PlanCache
from ct2.memory.session_store import SessionStore
from ct2.core.atlas import AtlasController

_CONFIG_PATH = (Path(__file__).parent.parent.parent
                / "ct2" / "server" / "model_config.yaml")


_EXT_TO_LANG = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".html": "html", ".htm": "html", ".css": "css", ".cpp": "cpp",
    ".c": "c", ".go": "go", ".rs": "rust", ".json": "json", ".sh": "bash",
}

# Maps detect_output_type() strings → canonical fence/lang name used in prompts & metadata
_OUTPUT_TYPE_TO_LANG = {
    "javascript": "javascript", "typescript": "typescript",
    "python_script": "python", "api": "python",
    "html_page": "html", "cpp": "cpp", "go": "go",
    "rust": "rust", "bash": "bash", "css": "css", "json": "json",
}

# Human-readable label per fence name (for edit prompts)
_LANG_TO_LABEL = {
    "javascript": "JavaScript", "typescript": "TypeScript",
    "python": "Python", "html": "HTML", "cpp": "C++",
    "go": "Go", "rust": "Rust", "bash": "Bash/Shell",
    "css": "CSS", "json": "JSON",
}


def _detect_lang_from_response(text: str) -> str:
    """Extract primary language from first fenced code block tag."""
    m = re.search(r'^```([\w+]+)', text, re.MULTILINE)
    if m:
        lang = m.group(1).lower()
        _ALIASES = {"py": "python", "js": "javascript", "ts": "typescript",
                    "sh": "bash", "shell": "bash", "c++": "cpp", "rs": "rust"}
        return _ALIASES.get(lang, lang)
    return "text"


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


class Orchestrator:
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

    @staticmethod
    def _extract_narrative(text: str) -> str:
        """Return the narrative/summary text from computer mode output with file blocks removed."""
        # Strategy 1: take text BEFORE the first [FILE:] marker (most common format).
        first_file = re.search(r'\[FILE:\s*[^\]]+\]|<!--\s*FILE:\s*', text)
        if first_file and first_file.start() > 20:
            before = text[:first_file.start()].strip()
            if len(before) > 30:
                return before

        # Strategy 2: strip [FILE: xxx] labels and all fenced code blocks,
        # returning whatever prose remains (handles narrative-after-files format).
        result = text
        result = re.sub(r'\[FILE:\s*[^\]]+\]\s*', '', result)
        result = re.sub(r'<!--\s*FILE:\s*.+?\s*-->\s*', '', result)
        result = re.sub(r'```[\w.\-]+[^\n]*\n.*?```', '', result, flags=re.DOTALL)
        result = re.sub(r'(?m)^COMPLETED:\s*', '', result)
        return result.strip()

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
        tools: list[dict] | None = None,
        tool_executor=None,
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

        # Infer previous file's language so the model declares its output fence.
        # Prevents accidental type changes (e.g. JS → TS) across edits.
        previous_lang = _OUTPUT_TYPE_TO_LANG.get(detect_output_type(previous_code)) if previous_code else None
        if previous_lang and previous_lang != "html":
            label = _LANG_TO_LABEL.get(previous_lang, previous_lang.upper())
            prompt = (
                f"File language: {label}\n"
                f"Wrap your entire output in ```{previous_lang} ... ``` fences.\n\n"
                f"Modify this code:\n{code_for_prompt}\n\n"
                f"Change requested: {goal}"
            )
        else:
            prompt = f"Modify this code:\n{code_for_prompt}\n\nChange requested: {goal}"

        result = await self.engine.generate(
            prompt,
            route,
            specialist_data=specialist_data,
            plan=None,
            conversation=None,
            on_token=on_token,
            is_edit=True,
            task_overrides=task_overrides,
            tools=tools,
            tool_executor=tool_executor,
        )
        draft = result["text"]
        draft_thinking = result.get("thinking", "")
        draft, draft_thinking, _finish_reason, _ = await self._continue_after_length(
            draft=draft,
            draft_thinking=draft_thinking,
            finish_reason=result.get("finish_reason"),
            goal_text=goal,
            route=route,
            continuation_context=(conversation or []) + [{"role": "user", "content": goal}],
            specialist_data=specialist_data,
            plan=None,
            task_ovr=task_overrides or {},
            emit=emit,
            on_token=on_token,
            tools=tools,
            tool_executor=tool_executor,
        )
        return draft, draft_thinking, False

    # ── Self-planning via Engine ────────────────────────────────────────

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
        skip_refinement: bool = False,
        tools: list[dict] | None = None,
        tool_executor=None,
    ) -> dict:
        """Precision-Design pipeline for new ROUTE_DESIGN generation.

        Phase 0:   Engine generates JSON spec (silent — no UI step)
        Phase 0.5: Script normalises and validates spec
        Phase 1:   Engine generates full HTML guided by the spec
        Phase 2:   Mechanical cleanup
        Phase 3:   CSS-only refinement pass
        """
        import json as _json

        # ── Phase 0: Spec generation (thinking streamed to UI) ──────
        emit("spec_generating")
        print("[design] Phase 0: generating spec")
        # Suppress content tokens during spec generation — the JSON spec
        # should not appear in the HTML preview. Only forward thinking tokens.
        def _spec_on_token(token, kind):
            if kind == "thinking":
                on_token(token, kind)
        try:
            spec = await self.engine.generate_spec(
                goal, conversation=conversation,
                task_overrides=task_ovr,
                on_token=_spec_on_token,
            )
        except (ValueError, _json.JSONDecodeError) as e:
            print(f"[design] Phase 0 failed: {e} — retrying")
            corrective = (
                f"{goal_text}\n\n"
                "Your previous output was invalid JSON. "
                "Output ONLY the JSON object with no other text."
            )
            try:
                spec = await self.engine.generate_spec(
                    corrective, conversation=conversation,
                    task_overrides=task_ovr,
                    on_token=on_token,
                )
            except (ValueError, _json.JSONDecodeError) as e2:
                print(f"[design] Phase 0 retry failed: {e2}")
                return {
                    "response": f"Design generation failed: could not produce valid spec. {e2}",
                    "thinking": "", "draft": "", "draft_thinking": "",
                    "route": "ROUTE_DESIGN", "specialist_data": None,
                    "plan": None,
                    "finish_reason": None,
                    "truncated": False,
                    "auto_continuations": 0,
                    "reflection": {
                        "goal": goal_text[:200], "complexity": "failed",
                        "lesson": "spec generation failed twice",
                        "self_score": 0.0,
                    },
                }

        # ── Phase 0.5: Normalise spec ────────────────────────────────
        spec = self._normalize_spec(spec)

        comp_ids = [c["id"] for c in spec.get("components", [])]
        if spec.get("layout_order"):
            spec["layout_order"] = [cid for cid in spec["layout_order"] if cid in comp_ids]
            for cid in comp_ids:
                if cid not in spec["layout_order"]:
                    spec["layout_order"].append(cid)
        else:
            spec["layout_order"] = comp_ids

        valid_types = {"navbar", "hero", "features", "testimonials", "cta",
                       "pricing", "contact", "footer", "gallery", "stats",
                       "team", "faq", "custom"}
        for comp in spec.get("components", []):
            if comp.get("type") not in valid_types:
                comp["type"] = "custom"

        print(f"[design] Phase 0.5: {len(spec.get('components', []))} components, "
              f"layout={spec.get('layout_order')}")
        emit("spec_validated", spec=spec)

        # ── Phase 1: Engine generates full HTML ──────────────────────
        emit("generating", editing=False)
        print("[design] Phase 1: Engine generating full page HTML")

        compact = {
            "page_title": spec.get("page_title", ""),
            "visual_style": spec.get("visual_style", ""),
            "font_pair": spec.get("font_pair", {}),
            "animation_style": spec.get("animation_style", "scroll-reveal"),
            "color_theme": spec.get("color_theme", {}),
            "layout_order": spec.get("layout_order", []),
            "components": [],
        }
        for comp in spec.get("components", []):
            c = {"id": comp["id"], "type": comp.get("type", "custom")}
            if comp.get("content"):
                c["content"] = comp["content"]
            if comp.get("style_hints"):
                c["style_hints"] = comp["style_hints"]
            if comp.get("interactions"):
                c["interactions"] = comp["interactions"]
            compact["components"].append(c)

        spec_summary = _json.dumps(compact, separators=(",", ":"))

        # Inject spec as an assistant turn — model reads it as its own prior
        # planning, not a new user instruction.
        spec_turn = {
            "role": "assistant",
            "content": (
                "I've planned the page architecture:\n\n"
                f"[PAGE SPEC]\n{spec_summary}"
            ),
        }
        gen_conversation = (conversation or []) + [
            {"role": "user", "content": goal_text},
            spec_turn,
        ]

        visual_style = spec.get("visual_style", "")
        font_pair = spec.get("font_pair", {})
        animation_style = spec.get("animation_style", "scroll-reveal")
        heading_font = font_pair.get("heading", "")
        body_font = font_pair.get("body", "")
        font_note = (
            f"Import '{heading_font}' (headings) and '{body_font}' (body) from Google Fonts. "
            if heading_font and body_font else ""
        )
        anim_note = (
            "Add CSS scroll-reveal: @keyframes fadeUp (opacity 0→1, translateY 24px→0), "
            "apply via IntersectionObserver in <script>. Stagger section entry with animation-delay. "
            if animation_style == "scroll-reveal" else
            "Add subtle fade-up entrance animations on sections. "
            if animation_style == "fade-up" else ""
        )

        gen_goal = (
            "OUTPUT ONLY HTML. Start at <!DOCTYPE html>. No text before it. No markdown fences. "
            f"Build a world-class, production-ready '{visual_style}' website following the spec above. "
            f"Include every section in layout_order. {font_note}"
            f"TYPOGRAPHY: Use the heading font for all headings (large, bold, tight letter-spacing). "
            f"Body text 17px, line-height 1.75. "
            f"HERO: Full-screen (min-h-screen), rich gradient or bold background, strong headline, clear CTA with hover effect. "
            f"SECTIONS: Generous padding (py-24 or more), never cramped. Real persuasive copy. "
            f"DEPTH: Cards with shadow-lg + hover:-translate-y-1 + hover:shadow-xl transition. "
            f"HOVER: Every button and link has smooth hover (transform + color + shadow). "
            f"{anim_note}"
            f"COLOR: Apply the color_theme cohesively — primary for CTAs, accent for highlights, background for page. "
            f"MOBILE: Mobile-first, hamburger nav on small screens. "
            f"Output only the complete HTML file — no explanations, no markdown fences."
        )

        result = await self.engine.generate(
            gen_goal, "ROUTE_DESIGN",
            conversation=gen_conversation,
            on_token=on_token,
            task_overrides=task_ovr,
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
            route="ROUTE_DESIGN",
            continuation_context=gen_conversation,
            specialist_data=None,
            plan=None,
            task_ovr=task_ovr,
            emit=emit,
            on_token=on_token,
            tools=tools,
            tool_executor=tool_executor,
        )

        # ── Phase 2: Cleanup ──────────────────────────────────────
        from ct2.core.formatter import strip_think_tags, extract_code
        draft = strip_think_tags(draft)
        draft = extract_code(draft)

        # ── Phase 2.5: Validate output is actual HTML ──
        # Small models may write prose instead of HTML. Detect and retry.
        for retry_num in range(2):
            _stripped = draft.lower().strip()
            _has_html_tags = any(tag in _stripped for tag in (
                '<!doctype', '<html', '<head', '<body', '<style',
                '<div', '<section', '<header', '<main', '<footer',
                '<nav', '<h1', '<h2', '<p ', '<p>', '<a ', '<img',
            ))
            _looks_conversational = (
                _stripped.startswith(('i ', 'let ', 'here', 'sure', 'okay',
                    'certainly', 'of course', 'below', "i'll", "i'd",
                    "i've", 'i have', 'this is', 'the following',
                    'to create', 'to build', 'to make', 'first',
                    'great', 'absolutely', 'no problem',
                ))
                or len(draft.strip()) < 200
            )
            if _has_html_tags or not _looks_conversational:
                break
            if retry_num == 0:
                emit("retrying", message="Model wrote prose instead of HTML — retrying with corrective prompt…")
                corrective = (
                    "CRITICAL: Your previous response was rejected because it contained "
                    "conversational text instead of HTML.\n\n"
                    f"Build a '{visual_style}' website. Output ONLY the complete HTML "
                    "file. Start with <!DOCTYPE html>. Do NOT write ANY text before it. "
                    "No explanations. No markdown fences."
                )
                retry_result = await self.engine.generate(
                    corrective, "ROUTE_DESIGN",
                    conversation=None,
                    on_token=on_token,
                    task_overrides=task_ovr,
                    tools=tools,
                    tool_executor=tool_executor,
                )
                draft = strip_think_tags(retry_result["text"])
                draft = extract_code(draft)
                draft_thinking = (draft_thinking or "") + "\n" + retry_result.get("thinking", "")
            else:
                print("[design] Phase 2.5: retry failed, keeping output as-is")
                emit("warning", message="The model produced conversational text instead of HTML. The output may not render correctly.")

        emit("draft", text=draft, thinking=draft_thinking)

        final_response = draft
        final_thinking = draft_thinking

        # ── Phase 3: CSS-only refinement ────────────────────────────
        # Extract just the <style> block and ask the model to polish it.
        # Much safer than full-page rewrite: HTML structure is preserved,
        # the model only handles ~2-5 KB of CSS instead of the full page.
        if not skip_refinement:
            try:
                sections = split_html_sections(draft)
                css = sections.get("style", "")
                if css and len(css.strip()) > 100:
                    emit("refining")
                    refine_ovr = {**task_ovr}
                    refine_result = await self.engine.refine_css_only(
                        css, task_overrides=refine_ovr,
                    )
                    improved_css = strip_think_tags(refine_result["text"])
                    # Strip any accidental fences the model adds
                    improved_css = re.sub(r'^```\w*\s*\n?', '', improved_css.strip())
                    improved_css = re.sub(r'\n?```\s*$', '', improved_css)
                    if improved_css and len(improved_css.strip()) > 50:
                        final_response = reassemble_html_section(draft, "style", improved_css)
                        emit("polished", code=final_response)
                        print("[design] Phase 3: CSS-only refinement applied")
                    else:
                        print("[design] Phase 3: CSS refinement output empty, keeping original")
                else:
                    print("[design] Phase 3: skipping — no meaningful CSS to refine")
            except Exception as e:
                print(f"[design] Phase 3: CSS refinement failed, keeping original: {e}")

        return {
            "response": final_response,
            "thinking": final_thinking,
            "draft": draft,
            "draft_thinking": draft_thinking,
            "route": "ROUTE_DESIGN",
            "specialist_data": _json.dumps(spec),
            "plan": None,
            "finish_reason": finish_reason,
            "truncated": finish_reason == "length",
            "auto_continuations": auto_continuations,
            "reflection": None,  # Reflection handled by caller
            "spec": spec,
            "detected_lang": "html",
            "files": [],
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

    async def compact_conversation(
        self,
        conversation: list[dict],
        fast: bool = False,
    ) -> list[dict]:
        """Compact a long conversation into an actionable summary + latest artifact.

        Returns 1-2 turns: a user-role summary and optionally the latest code
        as an assistant turn, so the model can continue editing it.

        When ``fast=True`` (or when the LLM summarizer fails), a mechanical
        summary is built locally without any model call. This guarantees the
        compaction step always finishes in milliseconds — the safety net that
        keeps the UI from hanging on slow hardware.
        """
        if not conversation:
            return []

        # Find the latest code artifact (HTML page, script, etc.)
        latest_code = ""
        for msg in reversed(conversation):
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                if not isinstance(content, str):
                    continue
                s = content.strip()
                is_bare_html = s.lower().startswith(("<!doctype", "<html"))
                is_bare_script = (
                    len(s) > 200
                    and s.startswith((
                        "import ", "from ", "def ", "class ",
                        "const ", "let ", "var ", "function ",
                    ))
                    and "```" not in s[:200]
                )
                if is_bare_html or is_bare_script:
                    latest_code = content
                    break

        def _user_text(m: dict) -> str:
            """Pull user-authored text out of a turn, handling multimodal content."""
            c = m.get("content", "")
            if isinstance(c, list):
                for part in c:
                    if isinstance(part, dict) and part.get("type") == "text":
                        c = part.get("text", "")
                        break
            return c.strip() if isinstance(c, str) else ""

        # IMMUTABLE LAYER — preserve every word the user said. The LLM summary
        # paraphrases assistant turns (lossy is fine), but the user's brief and
        # corrections are pinned verbatim so the model never drifts off the
        # original intent. This is the load-bearing fix for "after compaction
        # the AI built something completely different".
        user_turns = [t for t in (_user_text(m) for m in conversation if m.get("role") == "user") if t]
        original_brief = ""
        later_directives: list[str] = []
        if user_turns:
            # First user message = the brief. Cap at 1500 chars to bound size.
            original_brief = user_turns[0][:1500] + ("…" if len(user_turns[0]) > 1500 else "")
            # Subsequent user messages = corrections/refinements. Keep them all
            # if they fit, else last 8. Each capped at 400 chars.
            tail = user_turns[1:] if len(user_turns) <= 9 else user_turns[-8:]
            later_directives = [t[:400] + ("…" if len(t) > 400 else "") for t in tail]
        verbatim_block = ""
        if original_brief:
            verbatim_block += f"ORIGINAL REQUEST (user, verbatim):\n{original_brief}\n"
        if later_directives:
            quoted = "\n".join(f'  - "{d}"' for d in later_directives)
            verbatim_block += f"\nUSER CORRECTIONS / REFINEMENTS (verbatim, in order):\n{quoted}\n"

        def _mechanical_summary() -> str:
            """Deterministic summary without any LLM call. The user-intent
            block is added separately (verbatim) — this just describes what
            the assistant has done so far."""
            assistant_count = sum(1 for m in conversation if m.get("role") == "assistant")
            return (
                f"COMPLETED: {assistant_count} prior assistant turns ({len(conversation)} total messages elided).\n"
                "CURRENT STATE: Latest artifact preserved below if present.\n"
                "PENDING: Honor the user intent above and continue from where the latest artifact leaves off."
            )

        # Build a transcript, skipping slim placeholders and truncating large blobs
        lines = []
        for m in conversation:
            role = m.get("role", "")
            content = m.get("content", "")
            # Tool call turns: summarize each called function
            if role == "assistant" and m.get("tool_calls"):
                calls_desc = []
                for tc in m["tool_calls"]:
                    fn = tc.get("function", {})
                    name = fn.get("name", "?")
                    try:
                        import json as _json
                        args = _json.loads(fn.get("arguments", "{}"))
                        if name == "bash":
                            calls_desc.append(f"bash({args.get('command','?')[:80]})")
                        elif name == "write_file":
                            calls_desc.append(f"write_file({args.get('path','?')})")
                        elif name == "read_file":
                            calls_desc.append(f"read_file({args.get('path','?')})")
                        else:
                            calls_desc.append(name)
                    except Exception:
                        calls_desc.append(name)
                lines.append(f"ASSISTANT [tool]: {', '.join(calls_desc)}")
                continue
            # Tool result turns
            if role == "tool":
                result_preview = (str(content)[:300] + "…") if len(str(content)) > 300 else str(content)
                lines.append(f"TOOL RESULT: {result_preview}")
                continue
            if not isinstance(content, str):
                continue
            if content.strip() in ("(Previous code output omitted.)",):
                continue
            preview = (content[:500] + "…") if len(content) > 500 else content
            lines.append(f"{role.upper()}: {preview}")
        transcript = "\n\n".join(lines)

        prompt = (
            "Summarize this AI assistant conversation into a compact, actionable context block.\n"
            "The user's exact words will be preserved verbatim alongside your summary, "
            "so focus on describing what the assistant DID and the current state — "
            "do not re-paraphrase the user's requirements.\n"
            "Use exactly these section headers:\n"
            "COMPLETED: [what has been finished — include files created and commands run]\n"
            "CURRENT STATE: [the current output or working state — describe concisely]\n"
            "PENDING: [unfinished work, errors still to fix, or next steps the user mentioned]\n\n"
            "Be specific and actionable. Bullet points inside sections are fine.\n\n"
            f"CONVERSATION TO SUMMARIZE:\n{transcript}"
        )

        if fast:
            summary = _mechanical_summary()
        else:
            try:
                raw = await self.engine._call(
                    [{"role": "user", "content": prompt}],
                    max_tokens=400,
                    temperature=0.1,
                    enable_thinking=False,
                )
                summary = raw if isinstance(raw, str) else raw.get("text", "")
                summary = strip_think_tags(summary).strip()
                if not summary:
                    summary = _mechanical_summary()
            except Exception as e:
                print(f"[orch] compact_conversation LLM summary failed, using mechanical: {e}")
                summary = _mechanical_summary()

        # Compose final compacted turn: header + verbatim user intent + summary.
        # Verbatim block goes BEFORE the LLM summary so it's the first thing the
        # model attends to when reading the context.
        compacted_content = f"[CONTEXT SUMMARY — {len(conversation)} turns compacted to save memory]\n\n"
        if verbatim_block:
            compacted_content += (
                "═══ USER INTENT (preserved verbatim — treat as authoritative) ═══\n"
                f"{verbatim_block}\n"
                "═══ ASSISTANT PROGRESS (summarized) ═══\n"
            )
        compacted_content += summary

        compacted = [{"role": "user", "content": compacted_content}]

        if latest_code:
            # Truncate very large artifacts; enough for the model to edit
            if len(latest_code) > 12000:
                latest_code = latest_code[:12000] + "\n\n/* ... truncated for context ... */"
            compacted.append({"role": "assistant", "content": latest_code})

        return compacted

    @staticmethod
    def _merge_continuation(existing: str, continuation: str) -> str:
        """Append a continuation while trimming small repeated overlaps."""
        if not continuation:
            return existing
        if not existing:
            return continuation

        max_overlap = min(len(existing), len(continuation), 400)
        for size in range(max_overlap, 24, -1):
            if existing[-size:] == continuation[:size]:
                return existing + continuation[size:]

        stripped = continuation.strip()
        if stripped and stripped in existing[-2000:]:
            return existing
        return existing + continuation

    @staticmethod
    def _continuation_prompt(route: str) -> str:
        """Instruction used when a response hit the context limit mid-generation.

        Kept intentionally short — small models echo long instructions verbatim
        into the code output, corrupting the generated file.
        """
        return "Continue."

    async def _continue_after_length(
        self,
        draft: str,
        draft_thinking: str,
        finish_reason: str | None,
        goal_text: str,
        route: str,
        continuation_context: list[dict],
        specialist_data: dict | None,
        plan: dict | None,
        task_ovr: dict,
        emit,
        on_token,
        tools: list[dict] | None = None,
        tool_executor=None,
    ) -> tuple[str, str, str | None, int]:
        """Compact older history and continue when generation hit a length/context stop."""
        attempts = 0
        current_reason = finish_reason
        is_incomplete = self.engine._looks_incomplete(draft)
        if not (current_reason == "length" or is_incomplete) or not draft.strip():
            return draft, draft_thinking, current_reason, attempts

        while (current_reason == "length" or self.engine._looks_incomplete(draft)) and attempts < 3:
            attempts += 1
            emit(
                "compacting",
                message="Context limit reached — compacting older history and continuing…",
                source="generation",
                attempt=attempts,
            )

            # fast=True: mechanical truncation only — mid-generation context
            # overflow must recover in milliseconds, not minutes. The model is
            # already past its context budget; running another LLM summary call
            # would just compound the slowness.
            compacted_history = await self.compact_conversation(
                continuation_context
                or [{"role": "user", "content": goal_text}],
                fast=True,
            )
            summary_turn = (
                compacted_history[:1]
                if compacted_history
                else [{"role": "user", "content": f"[CONTEXT SUMMARY]\nCurrent request: {goal_text}"}]
            )
            continuation_conversation = [
                *summary_turn,
                {"role": "assistant", "content": draft},
            ]

            continuation_result = await self.engine.generate(
                self._continuation_prompt(route),
                route,
                specialist_data=specialist_data,
                plan=plan,
                conversation=continuation_conversation,
                on_token=on_token,
                task_overrides=task_ovr,
                tools=tools,
                tool_executor=tool_executor,
            )
            continuation_text = continuation_result.get("text", "")
            draft = self._merge_continuation(draft, continuation_text)
            cont_thinking = continuation_result.get("thinking", "")
            if cont_thinking:
                draft_thinking = (
                    f"{draft_thinking}\n\n{cont_thinking}" if draft_thinking else cont_thinking
                )
            current_reason = continuation_result.get("finish_reason")

        if attempts > 0:
            emit(
                "continued",
                message=(
                    "" if current_reason != "length"
                    else "Response still hit the context limit after continuing. The message may be incomplete."
                ),
                source="generation",
                attempt=attempts,
                truncated=(current_reason == "length"),
            )
        return draft, draft_thinking, current_reason, attempts

    async def _classify_is_question(self, message: str) -> bool:
        """Use the LLM to decide if a message is asking for information vs. requesting action.

        Works in any language — no keyword dependency. Returns True if the message
        is a pure information request (explain, describe, summarize, etc.).
        Defaults to False (action) on any error so generation is never blocked."""
        # Fast-path: clear action verbs → skip the LLM roundtrip entirely.
        _lower = message.lower().strip()
        _action_words = (
            "add ", "fix ", "make ", "change ", "update ", "remove ", "delete ",
            "create ", "build ", "write ", "refactor ", "edit ", "improve ",
            "rename ", "move ", "replace ", "implement ", "style ", "convert ",
            "generate ", "rewrite ", "include ",
        )
        if any(_lower.startswith(w) for w in _action_words):
            return False
        # Fast-path: clear question starters → also skip LLM.
        _question_starts = ("what ", "why ", "how ", "when ", "where ", "who ",
                            "which ", "explain ", "describe ", "what's ", "what is ")
        if any(_lower.startswith(w) for w in _question_starts) or _lower.endswith("?"):
            return True

        try:
            prompt = (
                f'Message: "{message}"\n\n'
                "Is the user asking for INFORMATION (explanation, description, summary) "
                "or requesting an ACTION (write, fix, add, change, create, extend)?\n"
                "Reply with one word only: information or action"
            )
            result = await self.engine._call(
                [{"role": "system", "content": "You classify user intent. Reply with one word only: information or action."},
                 {"role": "user", "content": prompt}],
                max_tokens=5,
                temperature=0.0,
                enable_thinking=False,
                conversation=None,
            )
            text = (result if isinstance(result, str) else result.get("text", "")).strip().lower()
            return "information" in text
        except Exception:
            return False  # default: treat as action, never silently break generation


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
