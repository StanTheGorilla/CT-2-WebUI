"""CT-2 Engine: The unified model interface and code generator.

Operates in two modes:
  - ROUTER: Classifies intent → ROUTE_DESIGN | ROUTE_CODE | ROUTE_DIRECT
  - GENERATOR: Produces full code/answers
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

_GENERATOR_CODE_SYSTEM = (
    "You are CT-2, an expert developer. Output ONLY code. No explanations. No markdown fences.\n\n"
    "HTML: complete <!DOCTYPE html> to </html>. Every tag closed. CSS in <style>, JS in <script>.\n"
    "Python: complete .py with imports, functions, main block.\n"
    "No placeholders. No TODOs. No '...' skips. Complete code only.\n\n"

    "THINKING PROCESS — before writing ANY code, reason through these in your thinking:\n"
    "1. What exactly is being asked? Restate the core requirement.\n"
    "2. What language/approach fits best?\n"
    "3. Key data structures and algorithms needed\n"
    "4. Edge cases to handle\n"
    "5. Outline the structure: imports, functions, main logic\n"
    "Then write the complete code.\n"
)

_GENERATOR_DESIGN_SYSTEM = (
    "You are CT-2, an elite web designer who creates stunning, production-quality websites.\n"
    "Output ONLY a single complete HTML file. No explanations. No markdown fences.\n"
    "From <!DOCTYPE html> to </html>.\n\n"

    "TOOLING:\n"
    "- Include Tailwind CSS via CDN in <head>:\n"
    '  <script src="https://cdn.tailwindcss.com"></script>\n'
    "- Use Tailwind utility classes for ALL layout, spacing, typography, and color.\n"
    "- Custom CSS in <style> ONLY for: animations, gradients, custom properties, fonts.\n"
    "- JS in <script> at end of body.\n\n"

    "DESIGN MANDATE — every website you build MUST have all of these:\n\n"

    "1. COLORS: Use Tailwind color utilities (bg-slate-900, text-amber-500, etc).\n"
    "   For custom brand colors, define in a <script> block with tailwind.config.\n"
    "   Pick a cohesive palette that matches the project's mood.\n"
    "   If [REQUIREMENTS] are provided, follow their color/mood/theme guidance.\n\n"

    "2. TYPOGRAPHY: Import Google Fonts in <head> with &display=swap.\n"
    "   Headings: text-4xl md:text-6xl font-bold tracking-tight leading-tight.\n"
    "   Body: text-base md:text-lg leading-relaxed.\n"
    "   Use font-[] for custom fonts.\n\n"

    "3. HERO: min-h-screen or min-h-[90vh]. flex items-center justify-center.\n"
    "   Gradient or image background. One clear headline, subtext, CTA.\n\n"

    "4. LAYOUT: max-w-7xl mx-auto px-6. py-20 md:py-28 for sections.\n"
    "   grid grid-cols-1 md:grid-cols-3 gap-8 for card layouts.\n\n"

    "5. DEPTH: shadow-lg hover:shadow-xl on cards.\n"
    "   border border-black/5 (light) or border-white/10 (dark).\n"
    "   rounded-2xl cards, rounded-xl buttons.\n\n"

    "6. MOTION: transition-all duration-300 ease-out on interactive elements.\n"
    "   hover:-translate-y-1 hover:shadow-xl on cards.\n"
    "   IntersectionObserver scroll-triggered animations in <script>.\n\n"

    "7. RESPONSIVE: Mobile-first. sm: md: lg: breakpoints.\n"
    "   Stack on mobile, grid on desktop. Fluid text with text-base md:text-lg.\n\n"

    "8. CONTENT: Write real, compelling copy. Never lorem ipsum.\n"
    "   Persuasive headlines. Concrete descriptions. Clear CTAs.\n\n"

    "9. SEMANTIC HTML: <header>, <nav>, <main>, <section>, <footer>.\n"
    "   Accessible: focus:ring-2 focus:ring-offset-2, alt text on images.\n\n"

    "10. COMPLETENESS: Every section fully styled. No gaps. No unstyled elements.\n"
    "    The page must look finished and polished in a browser.\n\n"

    "OUTPUT SAFETY — violations here produce blank/broken pages:\n"
    "- ALWAYS set bg and text color on <body> (e.g. class=\"bg-white text-gray-900\").\n"
    "- All text must be visible on its background. Dark bg = light text. Light bg = dark text.\n"
    "- Content must render WITHOUT JavaScript. Put real text in HTML, not injected via JS.\n"
    "- Hero must have visible foreground text, not just a background gradient.\n"
    "- Never rely on a single color for both background and text.\n\n"

    "THINKING PROCESS — before writing ANY HTML, reason through these in your thinking:\n"
    "1. What is this project? Who is the audience and what mood fits?\n"
    "2. Color palette: pick 4-5 specific Tailwind colors (e.g. slate-900, amber-500)\n"
    "3. Typography: choose heading + body Google Fonts\n"
    "4. Sections: list every section you will build, in order\n"
    "5. Layout approach for each section (grid, flex, centered, split)\n"
    "6. One unique design detail that makes this site memorable\n"
    "Then write the complete HTML.\n"
)

_GENERATOR_EDIT_SYSTEM = (
    "You are CT-2, an expert developer.\n"
    "The user wants to MODIFY code from a previous response.\n\n"
    "RULES:\n"
    "1. Apply ONLY the requested changes. Do NOT change anything else.\n"
    "2. Output the COMPLETE modified code — not just the changed parts.\n"
    "3. For HTML: output the full document from <!DOCTYPE html> to </html>.\n"
    "4. For Python: output the full script with all imports and functions.\n"
    "5. No explanations. No markdown fences. No diffs. Just the code.\n"
    "6. Preserve all existing functionality, styles, and structure unless the user explicitly asked to change them.\n"
    "7. Write COMPLETE code. No placeholders. No TODOs. No '...' skips."
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

_GENERATOR_COMPUTER_SYSTEM = (
    "You write complete project files. Output ONLY code using these markers:\n\n"
    "[FILE: filename.ext]\n"
    "complete code here\n\n"
    "[RUN: command to test]\n\n"
    "RULES:\n"
    "- Every file starts with [FILE: path] on its own line\n"
    "- No markdown fences. No explanations. Just [FILE:] and code.\n"
    "- NEVER use input()/scanf()/readline() — code runs non-interactively\n"
    "- Use hardcoded test values instead of user input\n"
    "- Always end with [RUN: ...] to test the code\n"
    "- Default to Python if language unclear\n\n"
    "THINKING PROCESS — before writing ANY code, reason through these in your thinking:\n"
    "1. What files are needed and what does each one do?\n"
    "2. Key functions, classes, and data flow between files\n"
    "3. How should the code be tested?\n"
    "Then write the complete project files.\n\n"

    "EXAMPLE:\n"
    "User: 'create a calculator'\n"
    "[FILE: calculator.py]\n"
    "def add(a, b): return a + b\n"
    "def sub(a, b): return a - b\n"
    "def mul(a, b): return a * b\n"
    "def div(a, b): return a / b if b else None\n"
    "print(add(10,3), sub(10,3), mul(10,3), div(10,3))\n"
    "[RUN: python calculator.py]\n"
)

_GENERATOR_TEXT_SYSTEM = (
    "You are CT-2, a knowledgeable conversational assistant.\n"
    "Answer the user directly. Adapt your length and format to the request:\n"
    "- Short questions get short answers.\n"
    "- Essays, explanations, and detailed requests get full, thorough responses.\n"
    "- Technical questions: include code examples when helpful.\n"
    "- Math/logic: show step-by-step reasoning.\n\n"
    "Use headings and bullet points for structure when the answer is long.\n"
    "Never fabricate facts. Say 'I'm not sure' when uncertain.\n"
    "Do not repeat yourself. Do not self-correct in circles — state the answer once, correctly.\n"
)

_GENERATOR_DISCUSS_SYSTEM = (
    "You are CT-2, an expert developer.\n"
    "The user is asking about code you generated previously.\n"
    "Answer their question clearly and concisely. "
    "Reference specific parts of the code when relevant.\n"
    "Do NOT output modified code unless the user explicitly asks for changes."
)

_LENGTH_GUIDE = {
    "simple": "Target: 80-150 lines of code.",
    "moderate": "Target: 150-350 lines of code.",
    "complex": "Target: 350-600 lines of code.",
}


class Engine:
    def __init__(self, base_url: str, temperature: float = 0.6,
                 top_p: float = 0.9, top_k: int = 40,
                 presence_penalty: float = 1.0, frequency_penalty: float = 0.0,
                 max_tokens: int = 100000,
                 thinking_budget: int = -1,
                 vision_supported: bool = False):
        self.base_url = base_url
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.presence_penalty = presence_penalty
        self.frequency_penalty = frequency_penalty
        self.max_tokens = max_tokens
        self.thinking_budget = thinking_budget
        self.vision_supported = vision_supported
        self.client = httpx.AsyncClient(timeout=600.0)
        self.lessons: list[str] = []
        self.last_session: str = ""

    def _sanitize_messages(self, messages: list[dict]) -> list[dict]:
        """Strip image content from messages if vision is not supported."""
        if self.vision_supported:
            return messages
        sanitized = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [p.get("text", "") for p in content
                              if p.get("type") == "text"]
                sanitized.append({
                    **msg,
                    "content": " ".join(text_parts) or "(image attachment — vision not available)",
                })
            else:
                sanitized.append(msg)
        return sanitized

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
                    temperature: float = None,
                    top_p: float = None,
                    conversation: list[dict] = None,
                    enable_thinking: bool = True,
                    thinking_budget: int = None):
        """Call the engine. Thinking enabled by default."""
        if conversation:
            system = messages[:1]
            rest = messages[1:]
            messages = system + conversation + rest

        messages = self._sanitize_messages(messages)

        chat_kwargs = {"enable_thinking": enable_thinking}
        budget = thinking_budget if thinking_budget is not None else self.thinking_budget
        if enable_thinking and budget > 0:
            chat_kwargs["thinking_budget"] = budget

        payload = {
            "model": "qwen",
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "top_p": top_p if top_p is not None else self.top_p,
            "top_k": self.top_k,
            "presence_penalty": (presence_penalty if presence_penalty is not None
                                 else self.presence_penalty),
            "frequency_penalty": self.frequency_penalty,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": False,
            "chat_template_kwargs": chat_kwargs,
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


    # ── Streaming call ────────────────────────────────────────────────

    @staticmethod
    def _detect_repetition(text: str, window: int = 40) -> bool:
        """Detect if the model is stuck in a repetition loop.

        Catches three patterns:
        1. Exact chunk repetition (same 40 chars 3+ times)
        2. Line repetition (same line 4+ times in last 30 lines)
        3. Paragraph repetition (similar paragraphs keep appearing)
        """
        if len(text) < 500:
            return False
        from collections import Counter

        tail = text[-window * 4:]

        # 1. Exact chunk repetition
        pattern = tail[-window:]
        if tail.count(pattern) >= 3:
            return True

        # 2. Line-level repetition
        # Filter out short structural lines (}, },, ], );, etc.)
        # which naturally repeat in nested code and are NOT repetition loops
        lines = tail.split('\n')[-30:]
        non_empty = [l.strip() for l in lines
                     if l.strip() and len(l.strip()) > 5]
        if len(non_empty) >= 4:
            counts = Counter(non_empty)
            if counts.most_common(1)[0][1] >= 4:
                return True

        # 3. Paragraph/sentence repetition — catch the "That's fine. Timeout
        #    maybe due to..." pattern where sentences repeat with tiny variations
        if len(text) > 800:
            # Split into sentences, normalize whitespace, check for repeats
            last_chunk = text[-2000:]
            sentences = [s.strip() for s in last_chunk.replace('\n', ' ').split('.')
                         if len(s.strip()) > 20]
            if len(sentences) >= 6:
                # Normalize: lowercase, collapse spaces
                normed = [' '.join(s.lower().split()) for s in sentences]
                counts = Counter(normed)
                most_common_count = counts.most_common(1)[0][1]
                if most_common_count >= 4:
                    return True
                # Check for near-duplicates (same first 30 chars)
                prefixes = Counter(s[:30] for s in normed if len(s) >= 30)
                if prefixes and prefixes.most_common(1)[0][1] >= 5:
                    return True

        return False

    async def _call_stream(self, messages: list[dict], on_token=None,
                           max_tokens: int = None,
                           presence_penalty: float = None,
                           temperature: float = None,
                           top_p: float = None,
                           conversation: list[dict] = None,
                           enable_thinking: bool = True,
                           thinking_budget: int = None):
        """Streaming call with token-by-token callback."""
        if conversation:
            system = messages[:1]
            rest = messages[1:]
            messages = system + conversation + rest

        messages = self._sanitize_messages(messages)

        chat_kwargs = {"enable_thinking": enable_thinking}
        budget = thinking_budget if thinking_budget is not None else self.thinking_budget
        if enable_thinking and budget > 0:
            chat_kwargs["thinking_budget"] = budget

        payload = {
            "model": "qwen",
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "top_p": top_p if top_p is not None else self.top_p,
            "top_k": self.top_k,
            "presence_penalty": (presence_penalty if presence_penalty is not None
                                 else self.presence_penalty),
            "frequency_penalty": self.frequency_penalty,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": True,
            "chat_template_kwargs": chat_kwargs,
        }

        text = ""
        thinking = ""
        content_token_count = 0
        thinking_token_count = 0

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
                        # Check content for repetition every 150 tokens
                        content_token_count += 1
                        if content_token_count >= 150:
                            content_token_count = 0
                            if self._detect_repetition(text):
                                text = self._trim_repetition(text)
                                break
                    if reason:
                        thinking += reason
                        if on_token:
                            on_token(reason, "thinking")
                        # Check thinking for repetition every 200 tokens
                        thinking_token_count += 1
                        if thinking_token_count >= 200:
                            thinking_token_count = 0
                            if self._detect_repetition(thinking):
                                thinking = self._trim_repetition(thinking)
                                break
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

        return {"text": text.strip(), "thinking": thinking.strip()}

    @staticmethod
    def _trim_repetition(text: str) -> str:
        """Find where repetition started and cut it off."""
        # HTML end markers
        for end_marker in ("</html>", "</body>", "</script>", "</style>",
                           "</section>", "</div>", "</footer>"):
            idx = text.rfind(end_marker)
            if idx != -1:
                return text[:idx + len(end_marker)]
        # Python/JS end markers — find last complete function or block
        for end_marker in ("\nif __name__", "\ndef ", "\nclass ",
                           "\nfunction ", "\nmodule.exports",
                           "\nint main(", "\nreturn 0;"):
            idx = text.rfind(end_marker)
            if idx != -1:
                # Find end of this block
                nl = text.find("\n\n", idx + len(end_marker))
                if nl != -1:
                    return text[:nl]
        # Fallback: cut at the last newline before the repetition zone
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

    # ── Task planning (model writes its own checklist) ──────────────

    _TASK_PLAN_SYSTEM = (
        "Write a short numbered task list for building this project.\n"
        "RULES:\n"
        "- Each task is ONE short line, max 10 words\n"
        "- Be specific: include key details (colors, names, layout)\n"
        "- 5-8 tasks maximum\n"
        "- No explanations, no paragraphs\n\n"
        "EXAMPLE:\n"
        "1. Hero: dark bg, white text, name SV//EN, CTA button\n"
        "2. Menu: 3-col grid, dish cards with prices\n"
        "3. Footer: contact info, social links, dark bg\n"
        "4. Smooth scroll, hover effects, transitions\n"
        "5. Responsive: stack on mobile, grid on desktop\n"
    )

    async def plan_tasks(self, goal_text: str, specialist_data: dict = None,
                         task_overrides: dict = None) -> list[str]:
        """Engine writes its own project-specific task list.

        Returns a list of concrete task strings, or empty list on failure.
        """
        ovr = task_overrides or {}
        context = ""
        if specialist_data:
            context = self._format_specialist_context(specialist_data)

        messages = [
            {"role": "system", "content": self._TASK_PLAN_SYSTEM},
            {"role": "user", "content": f"{goal_text}{context}"},
        ]

        try:
            result = await self._call(
                messages, max_tokens=384,
                temperature=ovr.get("temperature", 0.4),
                top_p=ovr.get("top_p", 0.9),
                enable_thinking=False,
            )
            text = result if isinstance(result, str) else result.get("text", "")
            # Parse numbered lines: "1. ...", "2. ...", etc.
            import re
            tasks = []
            for line in text.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                # Strip leading number + dot/paren/dash
                cleaned = re.sub(r'^[\d\-\*]+[\.\)\:]?\s*', '', line).strip()
                if cleaned and len(cleaned) > 5:
                    # Hard truncate to ~80 chars at word boundary
                    if len(cleaned) > 80:
                        cut = cleaned[:80].rfind(' ')
                        cleaned = cleaned[:cut] if cut > 40 else cleaned[:80]
                    tasks.append(cleaned)
            return tasks[:8]
        except Exception as e:
            print(f"[director] task planning failed: {e}")
            return []

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
                       code_context: str = None,
                       task_overrides: dict = None,
                       task_list: list[str] = None) -> dict:
        """Generate the full response. Returns {"text": str, "thinking": str}.

        plan: structured task breakdown from Specialist.plan().
        on_token: if provided, streams tokens via callback(token, kind).
        is_edit: if True, uses edit-aware prompting to modify previous code.
        """
        is_code = route in ("ROUTE_DESIGN", "ROUTE_CODE", "ROUTE_COMPUTER")
        is_direct = route == "ROUTE_DIRECT"
        is_computer = route == "ROUTE_COMPUTER"
        # Unpack per-task overrides (e.g. Nemotron uses different temp per route)
        ovr = task_overrides or {}
        ovr_temp = ovr.get("temperature")
        ovr_top_p = ovr.get("top_p")
        ovr_pp = ovr.get("presence_penalty")
        ovr_thinking = ovr.get("enable_thinking")
        ovr_budget = ovr.get("thinking_budget")

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
                    max_tokens=8192,
                    presence_penalty=0.0,
                    temperature=ovr_temp,
                    top_p=ovr_top_p,
                    conversation=conversation,
                    enable_thinking=ovr_thinking if ovr_thinking is not None else False,
                    thinking_budget=ovr_budget,
                )
            return await self._call(
                messages, max_tokens=8192,
                temperature=ovr_temp,
                top_p=ovr_top_p,
                conversation=conversation,
                enable_thinking=ovr_thinking if ovr_thinking is not None else False,
                thinking_budget=ovr_budget,
            )

        # For complex Python/scripts: use the micro-fill loop instead
        if (plan and not is_direct and not is_edit
                and plan.get("output_type") in ("python_script", "api")
                and plan.get("complexity") == "complex"
                and len(plan.get("components", [])) >= 4):
            return await self._generate_micro(
                goal_text, plan, conversation=conversation, on_token=on_token
            )

        # Build prompt — format specialist data as readable text, not JSON
        specialist_ctx = self._format_specialist_context(specialist_data)
        plan_ctx = self._build_plan_context(plan) if plan else ""

        # Output length guidance based on complexity
        complexity = plan.get("complexity", "moderate") if plan else "moderate"
        length_ctx = "\n" + _LENGTH_GUIDE.get(complexity, "") if plan else ""

        # Format task list as inline checklist the model sees while generating
        task_ctx = ""
        if task_list:
            items = "\n".join(f"  □ {t}" for t in task_list)
            task_ctx = (
                f"\n\n[YOUR TASK LIST — complete ALL of these]\n{items}\n"
                "Verify every task is done before finishing."
            )

        is_design = route == "ROUTE_DESIGN"

        if is_edit and is_code:
            prompt = f"Modify the code from the previous response:\n{goal_text}"
            system = _GENERATOR_EDIT_SYSTEM
        elif is_computer:
            prompt = self._build_user_content(goal, f"{plan_ctx}{specialist_ctx}{task_ctx}{length_ctx}")
            system = _GENERATOR_COMPUTER_SYSTEM
        elif is_design:
            prompt = self._build_user_content(goal, f"{specialist_ctx}{task_ctx}")
            system = _GENERATOR_DESIGN_SYSTEM
        elif is_code:
            prompt = self._build_user_content(goal, f"{plan_ctx}{specialist_ctx}{task_ctx}{length_ctx}")
            system = _GENERATOR_CODE_SYSTEM
        elif is_direct:
            prompt = self._build_user_content(goal, f"{specialist_ctx}{task_ctx}")
            system = _GENERATOR_TEXT_SYSTEM
        else:
            prompt = self._build_user_content(goal, f"{plan_ctx}{specialist_ctx}{task_ctx}{length_ctx}")
            system = self._personality_prompt()

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

        # Resolve enable_thinking: override > route default > True
        thinking = (ovr_thinking if ovr_thinking is not None
                    else True)

        # Resolve presence_penalty: override > route default > instance default
        pp = ovr_pp if ovr_pp is not None else self.presence_penalty

        if on_token:
            return await self._call_stream(
                messages,
                on_token=on_token,
                max_tokens=self.max_tokens if not is_direct else 16384,
                presence_penalty=pp,
                temperature=ovr_temp,
                top_p=ovr_top_p,
                conversation=conversation,
                enable_thinking=thinking,
                thinking_budget=ovr_budget,
            )

        return await self._call(
            messages,
            max_tokens=self.max_tokens if not is_direct else 16384,
            presence_penalty=pp,
            temperature=ovr_temp,
            top_p=ovr_top_p,
            conversation=conversation,
            enable_thinking=thinking,
            thinking_budget=ovr_budget,
        )

    # ── Precision-Design: Spec generation (Phase 0) ─────────────────────

    _SPEC_GENERATOR_SYSTEM = (
        "You are a website architecture planner. You receive a user's website request "
        "and output a structured JSON specification. You output ONLY valid JSON — "
        "no text before or after it, no markdown fences, no explanation.\n\n"

        "Your JSON must conform to this exact structure:\n"
        "{\n"
        '  "page_title": "string",\n'
        '  "color_theme": {\n'
        '    "primary": "tailwind-color-shade",\n'
        '    "secondary": "tailwind-color-shade",\n'
        '    "accent": "tailwind-color-shade",\n'
        '    "background": "tailwind-color-shade",\n'
        '    "text": "tailwind-color-shade"\n'
        "  },\n"
        '  "layout_order": ["component-id-1", "component-id-2", ...],\n'
        '  "components": [\n'
        "    {\n"
        '      "id": "kebab-case-id",\n'
        '      "type": "one of: navbar|hero|features|testimonials|cta|pricing|contact|footer|gallery|stats|team|faq|custom",\n'
        '      "required_elements": [\n'
        '        {"tag": "html-tag", "identifier": "id-or-class-name", "text": "optional exact text"}\n'
        "      ],\n"
        '      "content": {\n'
        '        "heading": "Actual headline text",\n'
        '        "subheading": "Actual subtitle text",\n'
        '        "body": "Actual body text if needed",\n'
        '        "items": [{"title": "...", "description": "..."}],\n'
        '        "cta_text": "Button label",\n'
        '        "cta_href": "#section-id"\n'
        "      },\n"
        '      "style_hints": "Tailwind utility class suggestions, must include responsive breakpoints",\n'
        '      "interactions": ["optional array of: hamburger-toggle|smooth-scroll|accordion|form-validation|dark-mode-toggle|carousel|modal|scroll-reveal"]\n'
        "    }\n"
        "  ]\n"
        "}\n\n"

        "Rules:\n"
        "- Every component id must appear in layout_order and vice versa.\n"
        "- Content fields must contain real, relevant text for the user's domain — never \"Lorem ipsum.\"\n"
        "- Color theme values must be valid Tailwind color classes (e.g., \"blue-600\", \"gray-50\").\n"
        "- required_elements must list every critical UI element needed for validation.\n"
        "- style_hints must mention mobile-first responsive design.\n"
        "- interactions is OPTIONAL. Only include it when a component genuinely needs client-side behavior "
        "(e.g., a navbar needs hamburger-toggle, an FAQ needs accordion). "
        "Do NOT add interactions to components that work fine as static HTML. "
        "An empty array or omitting the field entirely means no JS for that component.\n\n"

        'Example — User prompt: "Landing page for a coffee shop called Bean & Brew"\n\n'
        "{\n"
        '  "page_title": "Bean & Brew — Craft Coffee",\n'
        '  "color_theme": {\n'
        '    "primary": "amber-800",\n'
        '    "secondary": "stone-100",\n'
        '    "accent": "amber-500",\n'
        '    "background": "stone-50",\n'
        '    "text": "stone-900"\n'
        "  },\n"
        '  "layout_order": ["navbar", "hero", "menu-highlights", "about", "footer"],\n'
        '  "components": [\n'
        "    {\n"
        '      "id": "navbar",\n'
        '      "type": "navbar",\n'
        '      "required_elements": [\n'
        '        {"tag": "nav", "identifier": "navbar"},\n'
        '        {"tag": "a", "identifier": "logo-link", "text": "Bean & Brew"},\n'
        '        {"tag": "button", "identifier": "mobile-menu-toggle"}\n'
        "      ],\n"
        '      "content": {\n'
        '        "items": [\n'
        '          {"title": "Menu", "description": "#menu-highlights"},\n'
        '          {"title": "About", "description": "#about"},\n'
        '          {"title": "Visit Us", "description": "#footer"}\n'
        "        ]\n"
        "      },\n"
        '      "style_hints": "sticky top-0, dark bg, responsive with hamburger on mobile (md:hidden / md:flex)",\n'
        '      "interactions": ["hamburger-toggle", "smooth-scroll"]\n'
        "    },\n"
        "    {\n"
        '      "id": "hero",\n'
        '      "type": "hero",\n'
        '      "required_elements": [\n'
        '        {"tag": "section", "identifier": "hero"},\n'
        '        {"tag": "h1", "identifier": "hero-heading"},\n'
        '        {"tag": "a", "identifier": "hero-cta"}\n'
        "      ],\n"
        '      "content": {\n'
        '        "heading": "Coffee worth waking up for",\n'
        '        "subheading": "Single-origin roasts, brewed fresh every morning in the heart of downtown.",\n'
        '        "cta_text": "See Our Menu",\n'
        '        "cta_href": "#menu-highlights"\n'
        "      },\n"
        '      "style_hints": "full-width, centered text, py-24 md:py-32, large heading text-4xl md:text-6xl"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )

    async def generate_spec(
        self, goal, conversation: list[dict] = None,
        task_overrides: dict = None,
    ) -> dict:
        """Phase 0: Generate JSON spec from user prompt.

        The Engine produces a structured JSON specification describing
        the page architecture. This spec drives all downstream generation.

        Returns parsed JSON dict. Raises ValueError if output is not valid JSON.
        """
        import json as _json

        ovr = task_overrides or {}
        goal_text = goal if isinstance(goal, str) else " ".join(
            p.get("text", "") for p in goal if p.get("type") == "text"
        )

        messages = [
            {"role": "system", "content": self._SPEC_GENERATOR_SYSTEM},
            {"role": "user", "content": goal_text},
        ]

        result = await self._call(
            messages,
            max_tokens=4096,
            temperature=ovr.get("temperature", 0.35),
            top_p=ovr.get("top_p", 0.9),
            conversation=conversation,
            enable_thinking=True,
            thinking_budget=ovr.get("thinking_budget"),
        )

        # Extract text from result
        text = result if isinstance(result, str) else result.get("text", "")

        # Strip think tags and markdown fences
        import re
        text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
        if "```" in text:
            lines = [l for l in text.split("\n") if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        # Extract JSON object
        start = text.find("{")
        end = text.rfind("}") + 1
        if start < 0 or end <= start:
            raise ValueError(f"No JSON object found in Engine output: {text[:300]!r}")

        return _json.loads(text[start:end])

    # ── Self-refinement pass (design mode) ─────────────────────────────

    _REFINE_SYSTEM = (
        "You are a senior web designer reviewing a website you just built.\n"
        "Your job: rewrite it to be significantly better. Output ONLY the complete improved HTML.\n"
        "No explanations. No markdown fences. From <!DOCTYPE html> to </html>.\n\n"
        "REVIEW CHECKLIST — fix ALL of these:\n"
        "- SPACING: Unify padding/margin. No cramped sections. Generous whitespace.\n"
        "- TYPOGRAPHY: Consistent hierarchy. Headings properly sized. Body readable.\n"
        "- COLORS: Cohesive palette. No clashing colors. Proper contrast ratios.\n"
        "- HOVER STATES: Every interactive element needs hover feedback.\n"
        "- CONSISTENCY: Same border-radius, shadow style, spacing scale throughout.\n"
        "- POLISH: Smooth transitions. Proper focus states. No rough edges.\n"
        "- MOBILE: Verify responsive breakpoints work. Stack properly on small screens.\n\n"
        "Keep the same content, structure, and overall design direction.\n"
        "Make it noticeably more polished and professional.\n"
    )

    _REFINE_TARGETED_SYSTEM = (
        "You are a senior web designer reviewing a website you just built.\n"
        "Your job: fix the SPECIFIC issues listed below. Output ONLY the complete improved HTML.\n"
        "No explanations. No markdown fences. From <!DOCTYPE html> to </html>.\n\n"
        "Keep everything that already works. Only fix what is listed.\n"
    )

    async def refine_design(self, html: str, on_token=None,
                            task_overrides: dict = None,
                            missing_items: list[str] = None) -> dict:
        """Self-refinement: model reviews and improves its own output.

        Pass 2 of design mode — the model receives its complete HTML output
        and rewrites it with unified spacing, consistent styles, hover states,
        and polish. Returns {"text": str, "thinking": str}.
        """
        ovr = task_overrides or {}

        # Use targeted prompt if specific issues are known
        if missing_items:
            issue_list = "\n".join(f"- {item}" for item in missing_items)
            system = (
                self._REFINE_TARGETED_SYSTEM
                + f"MISSING / BROKEN — fix these:\n{issue_list}\n"
            )
        else:
            system = self._REFINE_SYSTEM

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Here is the website to improve:\n\n{html}"},
        ]

        if on_token:
            return await self._call_stream(
                messages,
                on_token=on_token,
                max_tokens=self.max_tokens,
                temperature=ovr.get("temperature", 0.4),
                top_p=ovr.get("top_p", 0.9),
                enable_thinking=True,
                thinking_budget=ovr.get("thinking_budget"),
            )

        return await self._call(
            messages,
            max_tokens=self.max_tokens,
            temperature=ovr.get("temperature", 0.4),
            top_p=ovr.get("top_p", 0.9),
            enable_thinking=True,
            thinking_budget=ovr.get("thinking_budget"),
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

    # ── HTML Scaffold + Fill loop ────────────────────────────────────

    async def _generate_html_scaffold(self, goal: str, plan: dict,
                                       specialist_data: dict = None,
                                       conversation: list[dict] = None,
                                       on_token=None,
                                       task_overrides: dict = None) -> dict:
        """Two-phase HTML generation: structure first, then style + content.

        Phase A: Generate HTML skeleton (structure + class names, minimal inline content)
        Phase B: Generate full CSS targeting those classes + fill body content

        This decouples structural decisions from visual ones, letting
        the 4B model focus on one concern at a time.
        """
        components = plan.get("components", []) if plan else []
        ovr = task_overrides or {}
        ovr_budget = ovr.get("thinking_budget")

        # Build specialist context
        specialist_ctx = self._format_specialist_context(specialist_data)
        plan_ctx = self._build_plan_context(plan) if plan else ""

        # Length guidance
        complexity = plan.get("complexity", "moderate") if plan else "moderate"
        length_guide = _LENGTH_GUIDE.get(complexity, "Target: 200-400 lines total.")

        # ── Phase A: HTML structure skeleton ─────────────────────────
        skel_prompt = (
            f"Task: {goal}\n{plan_ctx}{specialist_ctx}\n\n"
            f"Write the COMPLETE HTML from <!DOCTYPE html> to </html>.\n"
            f"Real, compelling content — never lorem ipsum. Write persuasive copy.\n"
            f"Descriptive, semantic class names.\n"
            f"Include <head> with Google Fonts link (for fonts in DESIGN SPEC), meta viewport, title.\n"
            f"Include EMPTY <style></style> — CSS will be added separately.\n"
            f"Include <script> with IntersectionObserver scroll-triggered fade-in animations.\n"
            f"No markdown fences. {length_guide}\n"
        )

        if on_token:
            on_token("[Phase 1: Building HTML structure...]\n", "thinking")

        # Route Phase A tokens to thinking stream only (content comes at end)
        def _skel_token(token, kind):
            if on_token:
                on_token(token, "thinking")

        skel_result = await self._call_stream(
            [{"role": "system", "content": _GENERATOR_CODE_SYSTEM},
             {"role": "user", "content": skel_prompt}],
            on_token=_skel_token,
            max_tokens=self.max_tokens,
            temperature=0.45,  # Moderate temp for structure + creative copy
            conversation=conversation,
            enable_thinking=True,
            thinking_budget=ovr_budget,
        )
        skeleton = skel_result["text"]
        skel_thinking = skel_result.get("thinking", "")

        # ── Phase B: CSS targeting the skeleton's classes ────────────
        # Extract just the body for context (model sees what classes exist)
        import re as _re
        body_match = _re.search(r'<body[^>]*>(.*?)</body>', skeleton,
                                _re.DOTALL | _re.IGNORECASE)
        body_preview = body_match.group(1)[:4000] if body_match else skeleton[:4000]

        css_prompt = (
            f"Task: {goal}\n{specialist_ctx}\n\n"
            f"HTML BODY (target these classes):\n{body_preview}\n\n"
            f"Write ALL CSS rules for this page. Output ONLY CSS — no HTML tags, no fences.\n\n"
            f"REQUIRED:\n"
            f"- :root with ALL color variables from the DESIGN SPEC above\n"
            f"- Typography: font-family, font-size with clamp(), letter-spacing, line-height\n"
            f"- Layered box-shadows on cards/buttons (subtle + medium layers)\n"
            f"- Transitions (0.3s cubic-bezier) + hover transforms (translateY, shadow lift)\n"
            f"- Hero section: full viewport, gradient background, centered content\n"
            f"- Responsive: @media (max-width: 768px) — stack grids, reduce padding\n"
            f"- Scroll animations: .fade-in-up with @keyframes\n"
            f"- Every section, every element must have complete styling — no unstyled gaps.\n"
        )

        if on_token:
            on_token("\n[Phase 2: Writing CSS...]\n", "thinking")

        css_result = await self._call(
            [{"role": "system", "content": (
                "You are a CSS expert. Output ONLY CSS rules. No HTML tags. "
                "No <style> wrappers. No markdown fences. No explanations. Just CSS."
            )},
             {"role": "user", "content": css_prompt}],
            max_tokens=self.max_tokens,
            temperature=0.5,  # Slightly higher for creative styling
            enable_thinking=False,
        )
        css_text = css_result if isinstance(css_result, str) else css_result.get("text", "")
        # Strip any fences or tags the model might add
        css_text = css_text.strip()
        if css_text.startswith("```"):
            lines = css_text.split("\n")
            css_text = "\n".join(l for l in lines if not l.startswith("```"))
        css_text = _re.sub(r'</?style[^>]*>', '', css_text)

        # ── Assemble: inject CSS into skeleton's empty <style> ──────
        style_match = _re.search(r'<style[^>]*></style>', skeleton,
                                  _re.IGNORECASE)
        if style_match:
            assembled = (skeleton[:style_match.start()]
                         + f"<style>\n{css_text}\n</style>"
                         + skeleton[style_match.end():])
        else:
            # Fallback: inject before </head>
            head_end = skeleton.find('</head>')
            if head_end != -1:
                assembled = (skeleton[:head_end]
                             + f"\n<style>\n{css_text}\n</style>\n"
                             + skeleton[head_end:])
            else:
                assembled = skeleton

        # Stream the final assembled output to the client
        if on_token:
            # Clear previous streaming and send the assembled version
            on_token(assembled, "content")

        return {"text": assembled, "thinking": skel_thinking}

    @staticmethod
    def _format_specialist_context(data: dict = None) -> str:
        """Format decomposition data as concise requirements context."""
        if not data:
            return ""
        route = data.get("_route", "")
        parts = ["\n\n[REQUIREMENTS]"]

        if route == "ROUTE_DESIGN":
            if data.get("project_type"):
                parts.append(f"Project: {data['project_type']}")
            if data.get("audience"):
                parts.append(f"Audience: {data['audience']}")
            if data.get("mood"):
                mood = data["mood"] if isinstance(data["mood"], list) else [data["mood"]]
                parts.append(f"Mood: {', '.join(mood)}")
            if data.get("theme"):
                parts.append(f"Theme: {data['theme']}")
            if data.get("sections"):
                parts.append(f"Sections: {' → '.join(data['sections'])}")
            if data.get("color_hints"):
                hints = [h for h in data["color_hints"] if h]
                if hints:
                    parts.append(f"Colors: {', '.join(hints)}")
            if data.get("special"):
                special = [s for s in data["special"] if s]
                if special:
                    parts.append(f"Special: {', '.join(special)}")

        elif route == "ROUTE_CODE":
            if data.get("language"):
                parts.append(f"Language: {data['language']}")
            if data.get("type"):
                parts.append(f"Type: {data['type']}")
            if data.get("requirements"):
                parts.append("Must do:")
                for r in data["requirements"]:
                    parts.append(f"  - {r}")
            if data.get("edge_cases"):
                cases = data["edge_cases"] if isinstance(data["edge_cases"], list) else [data["edge_cases"]]
                parts.append(f"Edge cases: {', '.join(cases)}")
            if data.get("output_format"):
                parts.append(f"Output: {data['output_format']}")

        elif route == "ROUTE_COMPUTER":
            if data.get("language"):
                parts.append(f"Language: {data['language']}")
            if data.get("framework") and data["framework"] != "none":
                parts.append(f"Framework: {data['framework']}")
            if data.get("files"):
                parts.append(f"Files: {', '.join(data['files'])}")
            if data.get("requirements"):
                parts.append("Must do:")
                for r in data["requirements"]:
                    parts.append(f"  - {r}")
            if data.get("run_command"):
                parts.append(f"Run: {data['run_command']}")

        elif route == "ROUTE_DIRECT":
            if data.get("topic"):
                parts.append(f"Topic: {data['topic']}")
            if data.get("answer_type"):
                parts.append(f"Answer type: {data['answer_type']}")
            if data.get("depth"):
                parts.append(f"Depth: {data['depth']}")
            if data.get("key_points"):
                points = [p for p in data["key_points"] if p]
                if points:
                    parts.append("Address:")
                    for p in points:
                        parts.append(f"  - {p}")

        if len(parts) <= 1:
            return ""
        return "\n".join(parts)

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
