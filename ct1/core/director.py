"""CT-2 Director: The 4B orchestrator and sole code generator.

Operates in two modes:
  - ROUTER: Classifies intent → ROUTE_DESIGN | ROUTE_CODE | ROUTE_DIRECT
  - GENERATOR: Produces full code/answers using specialist data
"""
import httpx
import json
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
BRAIN_SYSTEM_TEMPLATE = (_PROMPTS_DIR / "brain_system.txt").read_text(
    encoding="utf-8"
)

_DESIGN_TOOLKIT_PATH = _PROMPTS_DIR / "design_toolkit.txt"
_DESIGN_TOOLKIT = (
    _DESIGN_TOOLKIT_PATH.read_text(encoding="utf-8")
    if _DESIGN_TOOLKIT_PATH.exists() else ""
)

_ROUTER_SYSTEM = (
    "You are the CT-2 Routing Engine. Read the user request and categorize it.\n"
    "You may ONLY output one of the following exact strings:\n"
    '- "ROUTE_DESIGN" (If the user asks for UI/UX, styling, or layouts)\n'
    '- "ROUTE_CODE" (If the user asks for complex application logic or algorithms)\n'
    '- "ROUTE_DIRECT" (If it is a simple question or FAQ requiring no planning)\n'
    "Output nothing else."
)

_GENERATOR_CODE_SYSTEM = (
    "You are the CT-2 Director, an expert developer.\n"
    "Output ONLY complete, working code. No explanations. No markdown fences.\n"
    "For HTML: output a COMPLETE document starting with <!DOCTYPE html> "
    "and ending with </html>. Include <html>, <head> with <meta charset> "
    "and <meta viewport>, <title>, all CSS in <style>, <body> with content, "
    "all JS in <script> before </body>. Every tag must be closed.\n"
    "Think through your solution carefully, then output the final code."
    + (f"\n\nMANDATORY CSS RULES — apply ALL of these:\n{_DESIGN_TOOLKIT}"
       if _DESIGN_TOOLKIT else "")
)

_GENERATOR_EDIT_SYSTEM = (
    "You are the CT-2 Director, an expert developer.\n"
    "The user wants to MODIFY code from a previous response.\n"
    "Apply the requested changes to the existing code. "
    "Output the COMPLETE modified code — not just the changed parts.\n"
    "No explanations. No markdown fences. No diffs.\n"
    "For HTML: output the full document from <!DOCTYPE html> to </html>.\n"
    "Keep everything that the user didn't ask to change exactly as it was."
)

_GENERATOR_SECTION_EDIT_SYSTEM = (
    "You are editing a specific section of an HTML document.\n"
    "Output ONLY the inner content of that section — no wrapping tags.\n"
    "No markdown fences. No explanations. No commentary.\n"
    "If editing <style>: output only the CSS rules.\n"
    "If editing <body>: output only the HTML elements (no <script>).\n"
    "If editing <script>: output only the JavaScript code.\n"
    "If editing <head>: output only the meta/title/link tags (no <style>).\n"
    "Keep everything the user didn't ask to change exactly as it was."
)

_GENERATOR_PATCH_SYSTEM = (
    "You are a code editor. Make ONLY the specific changes requested.\n"
    "Output one or more SEARCH/REPLACE blocks. Nothing else.\n\n"
    "Format:\n"
    "<<<SEARCH\n"
    "exact lines from the original code\n"
    "===\n"
    "replacement lines\n"
    ">>>\n\n"
    "Rules:\n"
    "- SEARCH text must match the original code EXACTLY (whitespace matters)\n"
    "- Include 1-2 surrounding lines for context so the match is unique\n"
    "- Only change what the user asked for. Do NOT rewrite other code.\n"
    "- For insertions: use surrounding lines as SEARCH, add new lines in REPLACE\n"
    "- You may use multiple blocks if the change touches multiple places\n"
    "- No markdown fences. No explanations. Only SEARCH/REPLACE blocks."
)

_GENERATOR_TEXT_SYSTEM = (
    "You are the CT-2 Director, an expert assistant.\n"
    "Respond to the user's request comprehensively.\n"
    "If Specialist Data is provided, adhere to its constraints.\n"
    "Think through your solution carefully, then output the final response."
)

_GENERATOR_DISCUSS_SYSTEM = (
    "You are the CT-2 Director, an expert developer.\n"
    "The user is asking about code you generated previously.\n"
    "Answer their question clearly and concisely. "
    "Reference specific parts of the code when relevant.\n"
    "Do NOT output modified code unless the user explicitly asks for changes."
)

_CODE_KEYWORDS = {
    "html", "css", "javascript", "js", "website", "web page", "webpage",
    "script", "program", "function", "code", "app", "application",
    "component", "api", "endpoint", "server", "database", "sql",
    "python", "react", "svelte", "vue", "angular", "node",
}


class Director:
    def __init__(self, base_url: str, temperature: float = 0.6,
                 top_p: float = 0.9, top_k: int = 40,
                 presence_penalty: float = 1.0, max_tokens: int = 100000):
        self.base_url = base_url
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.presence_penalty = presence_penalty
        self.max_tokens = max_tokens
        self.client = httpx.AsyncClient(timeout=600.0)
        self.lessons: list[str] = []
        self.last_session: str = ""

    def _personality_prompt(self) -> str:
        lessons_text = ""
        if self.lessons:
            lessons_text = "From your journal:\n" + "\n".join(
                f"- {l}" for l in self.lessons[-10:]
            )
        session_text = ""
        if self.last_session:
            session_text = f"Last session: {self.last_session}"
        return (BRAIN_SYSTEM_TEMPLATE
                .replace("{lessons}", lessons_text)
                .replace("{session_summary}", session_text))

    async def _call(self, messages: list[dict], max_tokens: int = None,
                    presence_penalty: float = None,
                    conversation: list[dict] = None,
                    enable_thinking: bool = True):
        """Call the 4B Director. Thinking enabled by default."""
        if conversation:
            system = messages[:1]
            rest = messages[1:]
            messages = system + conversation + rest

        payload = {
            "model": "qwen",
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "presence_penalty": (presence_penalty if presence_penalty is not None
                                 else self.presence_penalty),
            "max_tokens": max_tokens or self.max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
        }

        r = await self.client.post(
            f"{self.base_url}/v1/chat/completions", json=payload
        )
        if not r.is_success:
            raise httpx.HTTPStatusError(
                f"{r.status_code}: {r.text[:500]}",
                request=r.request, response=r,
            )

        if enable_thinking:
            msg = r.json()["choices"][0]["message"]
            content = msg.get("content", "").strip()
            reasoning = msg.get("reasoning_content", "").strip()
            text = content if content else reasoning
            thinking = reasoning if content else ""
            return {"text": text, "thinking": thinking}

        return r.json()["choices"][0]["message"]["content"].strip()

    # ── Router mode ──────────────────────────────────────────────────

    async def route(self, goal: str,
                    conversation: list[dict] = None) -> str:
        """Classify the request. Returns ROUTE_DESIGN | ROUTE_CODE | ROUTE_DIRECT."""
        messages = [
            {"role": "system", "content": _ROUTER_SYSTEM},
            {"role": "user", "content": goal},
        ]
        raw = await self._call(
            messages, max_tokens=32,
            conversation=conversation,
            enable_thinking=False,
        )
        raw_upper = raw.upper().strip().strip('"')

        if "DESIGN" in raw_upper:
            return "ROUTE_DESIGN"
        if "CODE" in raw_upper:
            return "ROUTE_CODE"

        # Keyword fallback
        goal_lower = goal.lower()
        if any(kw in goal_lower for kw in _CODE_KEYWORDS):
            return "ROUTE_CODE"

        return "ROUTE_DIRECT"

    # ── Streaming call ────────────────────────────────────────────────

    @staticmethod
    def _detect_repetition(text: str, window: int = 20) -> bool:
        """Detect if the last chunk is stuck in a repetition loop."""
        if len(text) < window * 3:
            return False
        tail = text[-window * 3:]
        # Check if the last `window` chars repeat in the preceding text
        pattern = tail[-window:]
        count = tail.count(pattern)
        return count >= 3

    async def _call_stream(self, messages: list[dict], on_token=None,
                           max_tokens: int = None,
                           presence_penalty: float = None,
                           conversation: list[dict] = None,
                           enable_thinking: bool = True):
        """Streaming call with token-by-token callback."""
        if conversation:
            system = messages[:1]
            rest = messages[1:]
            messages = system + conversation + rest

        payload = {
            "model": "qwen",
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "presence_penalty": (presence_penalty if presence_penalty is not None
                                 else self.presence_penalty),
            "max_tokens": max_tokens or self.max_tokens,
            "stream": True,
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
        }

        text = ""
        thinking = ""
        rep_check_counter = 0

        async with self.client.stream(
            "POST", f"{self.base_url}/v1/chat/completions", json=payload
        ) as response:
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {})
                    token = delta.get("content", "")
                    reason = delta.get("reasoning_content", "")
                    if token:
                        text += token
                        if on_token:
                            on_token(token, "content")
                        # Check for repetition every 50 tokens
                        rep_check_counter += 1
                        if rep_check_counter >= 50:
                            rep_check_counter = 0
                            if self._detect_repetition(text):
                                # Trim the repeated garbage
                                text = self._trim_repetition(text)
                                break
                    if reason:
                        thinking += reason
                        if on_token:
                            on_token(reason, "thinking")
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

        return {"text": text.strip(), "thinking": thinking.strip()}

    @staticmethod
    def _trim_repetition(text: str) -> str:
        """Find where repetition started and cut it off."""
        # Look for the last valid HTML-like content before the loop
        for end_marker in ("</html>", "</body>", "</script>", "</style>",
                           "</section>", "</div>", "</footer>"):
            idx = text.rfind(end_marker)
            if idx != -1:
                return text[:idx + len(end_marker)]
        # Fallback: just cut at the last newline before the repetition zone
        cut = len(text) - 200
        nl = text.rfind("\n", 0, cut)
        if nl > 0:
            return text[:nl]
        return text[:cut]

    # ── Prompt building ───────────────────────────────────────────────

    @staticmethod
    def _build_plan_context(plan: dict) -> str:
        """Turn a plan into an explicit generation directive."""
        components = plan.get("components", [])
        if not components:
            return ""
        output_type = plan.get("output_type", "other")

        if output_type == "html_page":
            lines = ["Build ALL of the following sections/components:"]
            for c in components:
                lines.append(f"  {c['id']}. {c['name']}: {c['description']}")
            lines.append("Include every component listed above in the output.")
        else:
            lines = ["Implement ALL of the following functions/components:"]
            for c in components:
                lines.append(f"  {c['id']}. {c['name']}: {c['description']}")
            lines.append(
                "Write the complete script. Every function listed above must be implemented."
            )

        return "\n" + "\n".join(lines)

    # ── Generator mode ───────────────────────────────────────────────

    @staticmethod
    def _build_user_content(goal, suffix: str = ""):
        """Build user message content, preserving multimodal parts if present."""
        if isinstance(goal, list):
            # Multimodal: append suffix to the text part, keep image parts
            parts = []
            for p in goal:
                if p.get("type") == "text":
                    parts.append({"type": "text", "text": p["text"] + suffix})
                else:
                    parts.append(p)
            return parts
        return f"{goal}{suffix}"

    async def generate(self, goal, route: str,
                       specialist_data: dict = None,
                       plan: dict = None,
                       conversation: list[dict] = None,
                       on_token=None,
                       is_edit: bool = False,
                       code_context: str = None) -> dict:
        """Generate the full response. Returns {"text": str, "thinking": str}.

        plan: structured task breakdown from Specialist.plan().
        on_token: if provided, streams tokens via callback(token, kind).
        is_edit: if True, uses edit-aware prompting to modify previous code.
        """
        is_code = route in ("ROUTE_DESIGN", "ROUTE_CODE")
        is_direct = route == "ROUTE_DIRECT"

        goal_text = goal if isinstance(goal, str) else " ".join(
            p.get("text", "") for p in goal if p.get("type") == "text"
        )

        # "Question about code" mode — answer about previously generated code
        if code_context and is_direct:
            truncated = self._truncate_context(code_context, 6000)
            prompt = (
                f"[Previously generated code for reference]\n{truncated}\n\n"
                f"User question: {goal_text}"
            )
            system = _GENERATOR_DISCUSS_SYSTEM
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ]
            if on_token:
                return await self._call_stream(
                    messages, on_token=on_token,
                    max_tokens=2048,
                    presence_penalty=0.0,
                    conversation=conversation,
                    enable_thinking=False,
                )
            return await self._call(
                messages, max_tokens=2048,
                conversation=conversation,
                enable_thinking=False,
            )

        # For complex Python/scripts: use the micro-fill loop instead
        if (plan and not is_direct and not is_edit
                and plan.get("output_type") in ("python_script", "api")
                and plan.get("complexity") == "complex"
                and len(plan.get("components", [])) >= 4):
            return await self._generate_micro(
                goal_text, plan, conversation=conversation, on_token=on_token
            )

        # Build prompt
        specialist_ctx = ""
        if specialist_data:
            specialist_ctx = (
                "\n\n[DESIGN SPEC] "
                + json.dumps(specialist_data, separators=(",", ":"))
            )
        plan_ctx = self._build_plan_context(plan) if plan else ""

        if is_edit and is_code:
            prompt = f"Modify the code from the previous response:\n{goal_text}"
            system = _GENERATOR_EDIT_SYSTEM
        elif is_code:
            prompt = self._build_user_content(goal, f"{plan_ctx}{specialist_ctx}")
            system = _GENERATOR_CODE_SYSTEM
        elif is_direct:
            prompt = self._build_user_content(goal)
            system = _GENERATOR_TEXT_SYSTEM
        else:
            prompt = self._build_user_content(goal, f"{plan_ctx}{specialist_ctx}")
            system = self._personality_prompt()

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

        if on_token:
            return await self._call_stream(
                messages,
                on_token=on_token,
                max_tokens=self.max_tokens if not is_direct else 2048,
                presence_penalty=self.presence_penalty if not is_direct else 0.0,
                conversation=conversation,
                enable_thinking=not is_direct,
            )

        return await self._call(
            messages,
            max_tokens=self.max_tokens if not is_direct else 2048,
            conversation=conversation,
            enable_thinking=not is_direct,
        )

    # ── Section-level edit ──────────────────────────────────────────────

    async def generate_patch_edit(
        self, goal: str, code: str, on_token=None,
    ) -> dict:
        """Ask the director to output SEARCH/REPLACE patches instead of full code.

        Returns {"text": str, "thinking": str} where text contains patch blocks.
        """
        # Truncate code for context window — keep start + end
        if len(code) > 8000:
            code_for_prompt = (
                code[:5000]
                + "\n\n/* ... middle section ... */\n\n"
                + code[-3000:]
            )
        else:
            code_for_prompt = code

        prompt = (
            f"Original code:\n{code_for_prompt}\n\n"
            f"Change requested: {goal}"
        )

        messages = [
            {"role": "system", "content": _GENERATOR_PATCH_SYSTEM},
            {"role": "user", "content": prompt},
        ]

        if on_token:
            return await self._call_stream(
                messages, on_token=on_token,
                max_tokens=4096,
                presence_penalty=0.0,
                enable_thinking=True,
            )

        return await self._call(
            messages, max_tokens=4096,
            enable_thinking=True,
        )

    @staticmethod
    def _truncate_context(text: str, max_chars: int) -> str:
        """Truncate text keeping start and end for context."""
        if len(text) <= max_chars:
            return text
        half = max_chars // 2
        return text[:half] + "\n/* ... */\n" + text[-half:]

    async def generate_section_edit(
        self, goal: str, section: str,
        sections: dict[str, str],
        on_token=None,
    ) -> dict:
        """Regenerate a single HTML section. Returns {"text": str, "thinking": str}.

        section: which section to edit ('style', 'body', 'script', 'head')
        sections: dict of all section contents for read-only context
        """
        section_content = sections.get(section, "")

        # Build compact context from other sections (truncated to fit context window)
        context_parts = []
        for name, content in sections.items():
            if name == section:
                continue
            # Truncate large sections — director only needs a sketch for context
            truncated = self._truncate_context(content, 1500)
            context_parts.append(f"<{name}>\n{truncated}\n</{name}>")
        context = "\n\n".join(context_parts)

        prompt = (
            f"[CONTEXT — other sections for reference, do NOT output these]\n"
            f"{context}\n\n"
            f"[SECTION TO EDIT — <{section}>]\n"
            f"{section_content}\n\n"
            f"User request: {goal}\n\n"
            f"Output ONLY the modified <{section}> inner content. "
            f"No wrapping <{section}> tags. No <!DOCTYPE>. No other sections."
        )

        messages = [
            {"role": "system", "content": _GENERATOR_SECTION_EDIT_SYSTEM},
            {"role": "user", "content": prompt},
        ]

        if on_token:
            return await self._call_stream(
                messages, on_token=on_token,
                max_tokens=self.max_tokens,
                presence_penalty=self.presence_penalty,
                enable_thinking=True,
            )

        return await self._call(
            messages, max_tokens=self.max_tokens,
            enable_thinking=True,
        )

    # ── Polish pass ─────────────────────────────────────────────────

    async def polish_css(self, css: str) -> dict:
        """Improve CSS quality with design polish rules.

        Returns {"text": str} — thinking disabled to keep output clean.
        """
        polish_prompt_path = _PROMPTS_DIR / "polish_system.txt"
        system = polish_prompt_path.read_text(encoding="utf-8")

        # Truncate if CSS is huge
        if len(css) > 6000:
            css_for_prompt = css[:4000] + "\n/* ... */\n" + css[-2000:]
        else:
            css_for_prompt = css

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Improve this CSS:\n\n{css_for_prompt}"},
        ]

        raw = await self._call(
            messages, max_tokens=self.max_tokens,
            enable_thinking=False,
        )
        # _call with enable_thinking=False returns a plain string
        text = raw if isinstance(raw, str) else raw.get("text", "")
        return {"text": text}

    # ── Micro-fill loop (complex Python/scripts) ─────────────────────

    async def _generate_micro(self, goal: str, plan: dict,
                               conversation: list[dict] = None,
                               on_token=None) -> dict:
        """Skeleton + targeted fill for complex Python/script generation.

        1. Generate a hollow skeleton with # TODO: {id} markers.
        2. For each component, fill in just that function in a focused call.
        3. Assemble and return the complete script.
        """
        components = plan.get("components", [])

        # ── Step 1: generate skeleton ────────────────────────────────
        skel_prompt = (
            f"Task: {goal}\n\n"
            f"Write a Python script skeleton. "
            f"Define the imports and all function signatures, "
            f"but leave each function body as exactly: "
            f"# TODO: {{id}}  (no other code inside).\n\n"
            f"Functions to define:\n"
            + "\n".join(
                f"  def {c['name'].lower().replace(' ', '_')}(): "
                f"# TODO: {c['id']}"
                for c in components
            )
            + "\n\nOutput ONLY the skeleton. No explanations."
        )

        if on_token:
            on_token("[Building skeleton...]\n", "thinking")

        skel_result = await self._call(
            [{"role": "system", "content": _GENERATOR_CODE_SYSTEM},
             {"role": "user", "content": skel_prompt}],
            max_tokens=2048,
            enable_thinking=False,
        )
        skeleton = skel_result if isinstance(skel_result, str) else skel_result.get("text", "")

        # ── Step 2: fill each TODO ────────────────────────────────────
        assembled = skeleton
        total_thinking = f"[Skeleton built: {len(skeleton)} chars]\n"

        for c in components:
            todo_marker = f"# TODO: {c['id']}"
            if todo_marker not in assembled:
                continue  # skeleton didn't include this one, skip

            if on_token:
                on_token(f"[Filling: {c['name']}]\n", "thinking")

            fill_prompt = (
                f"Task: {goal}\n\n"
                f"Here is the script skeleton:\n{assembled}\n\n"
                f"Fill in ONLY the function marked `{todo_marker}`.\n"
                f"Component: {c['name']} — {c['description']}\n"
                f"Return ONLY the replacement code for that function body. "
                f"No explanations. No other functions."
            )

            fill_result = await self._call(
                [{"role": "system", "content": _GENERATOR_CODE_SYSTEM},
                 {"role": "user", "content": fill_prompt}],
                max_tokens=1024,
                enable_thinking=False,
            )
            fill_text = (fill_result if isinstance(fill_result, str)
                         else fill_result.get("text", ""))

            # Extract just the function body lines (strip fences/preamble)
            fill_text = fill_text.strip()
            if fill_text.startswith("```"):
                lines = fill_text.split("\n")
                lines = [l for l in lines
                         if not l.startswith("```") and not l.startswith("```")]
                fill_text = "\n".join(lines).strip()

            # Replace the TODO marker with the filled body
            assembled = assembled.replace(todo_marker, fill_text, 1)
            total_thinking += f"[{c['name']}: {len(fill_text)} chars]\n"

        if on_token:
            on_token(assembled, "content")

        return {"text": assembled, "thinking": total_thinking}

    # ── Reflection (reused from brain) ───────────────────────────────

    async def reflect(self, goal: str, complexity: str, outcome: str,
                      conversation: list[dict] = None) -> dict:
        reflection_template = (
            _PROMPTS_DIR / "reflection_prompt.txt"
        ).read_text(encoding="utf-8")
        if len(outcome) > 500:
            outcome_for_prompt = (
                f"[Generated {len(outcome)} characters of output]"
            )
        else:
            outcome_for_prompt = outcome
        prompt = (reflection_template
                  .replace("{goal}", str(goal))
                  .replace("{complexity}", str(complexity))
                  .replace("{rounds}", "2")
                  .replace("{outcome}", outcome_for_prompt))
        messages = [
            {"role": "system", "content": self._personality_prompt()},
            {"role": "user", "content": prompt},
        ]
        raw = await self._call(
            messages, max_tokens=512,
            conversation=conversation,
            enable_thinking=False,
        )
        if isinstance(raw, dict):
            raw = raw.get("text", "")
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            return json.loads(raw[start:end])
        except Exception:
            return {
                "goal": goal, "complexity": complexity,
                "lesson": "reflection parse failed",
                "self_score": 0.5,
            }

    async def summarize_session(self, conversation: list[dict]) -> str | None:
        if not conversation:
            return None
        lines = [f"- {m['content'][:200]}"
                 for m in conversation if m["role"] == "user"][:20]
        prompt = (
            "Summarize this conversation in 2-3 sentences.\n\n"
            f"User messages:\n" + "\n".join(lines) + "\n\nSummary:"
        )
        messages = [
            {"role": "system", "content": "Concise summarizer. Output only the summary."},
            {"role": "user", "content": prompt},
        ]
        try:
            return await self._call(
                messages, max_tokens=128, enable_thinking=False
            )
        except Exception:
            return None

    async def close(self):
        await self.client.aclose()
