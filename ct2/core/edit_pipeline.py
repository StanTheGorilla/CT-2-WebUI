"""Extracted from Orchestrator — see ct2/core/orchestrator.py."""
import re

from ct2.core.formatter import (
    detect_output_type, extract_code, reassemble_html_section,
    split_html_sections, strip_think_tags,
)
from ct2.core.pipeline_util import _EXT_TO_LANG, _LANG_TO_LABEL, _OUTPUT_TYPE_TO_LANG


class EditPipelineMixin:
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
                content = EditPipelineMixin._strip_run_markers(content)
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
        cleaned = EditPipelineMixin._strip_run_markers(text)
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

