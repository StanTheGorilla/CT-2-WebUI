import re
import httpx
import json
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
BRAIN_SYSTEM_TEMPLATE = (_PROMPTS_DIR / "brain_system.txt").read_text(encoding="utf-8")

_CODE_KEYWORDS = {
    "html", "css", "javascript", "js", "website", "web page", "webpage",
    "script", "program", "function", "code", "app", "application",
    "component", "api", "endpoint", "server", "database", "sql",
    "python", "react", "svelte", "vue", "angular", "node",
}

# For code generation: no commentary, just code.
_CODE_SYSTEM = (
    "You are a code generator. Output ONLY complete, working code. "
    "No explanations. No markdown fences. No commentary before or after. "
    "For HTML: output a COMPLETE document starting with <!DOCTYPE html> "
    "and ending with </html>. Include <html>, <head> with <meta charset> "
    "and <meta viewport>, <title>, all CSS in <style>, <body> with content, "
    "all JS in <script> before </body>. Every tag must be closed."
)


class Brain:
    def __init__(self, base_url: str, temperature: float = 0.4,
                 top_p: float = 0.9, top_k: int = 20,
                 presence_penalty: float = 1.5, max_tokens: int = 100000):
        self.base_url = base_url
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.presence_penalty = presence_penalty
        self.max_tokens = max_tokens
        self.client = httpx.AsyncClient(timeout=600.0)
        self.lessons: list[str] = []
        self.last_session: str = ""

    def _system_prompt(self) -> str:
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
                    enable_thinking: bool = False):
        """Call the LLM. Returns str when thinking disabled, dict when enabled."""
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
                f"{r.status_code} from {r.url}: {r.text[:500]}",
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

    # ── Intent extraction ────────────────────────────────────────────

    async def extract_intent(self, goal: str,
                             conversation: list[dict] = None) -> dict:
        system = "You are a precise task classifier. Output only valid JSON."
        prompt = f"""Analyze this task and classify it.

Task: {goal}

Respond as JSON only:
{{
  "task_type": "code" | "artifact" | "question" | "analysis",
  "what_to_produce": "one sentence describing the exact output expected",
  "requirements": ["key requirement 1", "key requirement 2"],
  "complexity": "brief" | "moderate" | "deep"
}}

Use "code" for any task asking for code, HTML, CSS, scripts, programs.
Use "artifact" for documents, designs, structured outputs.
Use "question" for factual or conceptual questions.
Use "analysis" for evaluation, comparison, review tasks."""

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        raw = await self._call(messages, max_tokens=512,
                               conversation=conversation)
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            parsed = json.loads(raw[start:end])
            if parsed.get("task_type") not in (
                "code", "artifact", "question", "analysis"
            ):
                parsed["task_type"] = "question"
            if parsed.get("complexity") not in ("brief", "moderate", "deep"):
                parsed["complexity"] = "moderate"
            if not parsed.get("what_to_produce"):
                parsed["what_to_produce"] = goal

            # Keyword override for code tasks the model misclassified
            if parsed["task_type"] != "code":
                goal_lower = goal.lower()
                if any(kw in goal_lower for kw in _CODE_KEYWORDS):
                    parsed["task_type"] = "code"

            return parsed
        except Exception:
            goal_lower = goal.lower()
            default_type = ("code" if any(kw in goal_lower
                            for kw in _CODE_KEYWORDS) else "question")
            return {
                "task_type": default_type,
                "what_to_produce": goal,
                "requirements": [],
                "complexity": "moderate",
            }

    # ── Code / answer generation ─────────────────────────────────────

    async def generate(self, goal: str, intent: dict, briefs: list[dict],
                       conversation: list[dict] = None) -> dict:
        """Generate output using design briefs from minds.
        Returns {"text": str, "thinking": str}.
        """
        task_type = intent.get("task_type", "question")
        is_code = task_type in ("code", "artifact")

        brief_text = "\n".join(
            f"- {b['name']}: {b['text']}" for b in briefs if b["text"]
        )

        if is_code:
            what = intent.get("what_to_produce", goal)
            reqs = intent.get("requirements", [])
            reqs_text = ("\nRequirements:\n" + "\n".join(
                f"- {r}" for r in reqs
            )) if reqs else ""

            prompt = f"""Task: {goal}
Output: {what}{reqs_text}

Design inputs prepared for you:
{brief_text}

Use the design inputs above (colors, sections, fonts) in your code.
Write the COMPLETE HTML document from <!DOCTYPE html> to </html>.
All CSS inside <style> in <head>. All JS inside <script> before </body>.
Include <meta charset="UTF-8"> and <meta name="viewport"> in <head>.
No placeholders. No TODO. No stubs. Only real, working code."""

            system = _CODE_SYSTEM
            raw = await self._call(
                [{"role": "system", "content": system},
                 {"role": "user", "content": prompt}],
                max_tokens=self.max_tokens,
                presence_penalty=0.0,
                conversation=conversation,
                enable_thinking=False,
            )
            return {"text": self._clean_code_output(raw), "thinking": ""}

        else:
            prompt = f"""Question: {goal}

Three perspectives:
{brief_text}

Synthesize these into a clear, comprehensive answer.
Speak in first person. Do not reference the perspectives."""

            result = await self._call(
                [{"role": "system", "content": self._system_prompt()},
                 {"role": "user", "content": prompt}],
                max_tokens=self.max_tokens,
                presence_penalty=0.0,
                conversation=conversation,
                enable_thinking=True,
            )
            return result

    # ── Fix pass (only when validation finds issues) ─────────────────

    async def fix(self, goal: str, intent: dict, draft: str,
                  issues: list[str],
                  conversation: list[dict] = None) -> dict:
        """Fix specific structural issues found by validation.
        Returns {"text": str, "thinking": str}.
        """
        issue_text = "\n".join(f"- {issue}" for issue in issues)
        max_draft = 12000
        draft_for_prompt = draft[:max_draft] if len(draft) > max_draft else draft

        prompt = f"""This code has structural issues that MUST be fixed:
{issue_text}

Current code:
{draft_for_prompt}

Fix ALL listed issues. Output the COMPLETE fixed code.
Start with <!DOCTYPE html>, end with </html>.
Include all original content, styling, and functionality.
Only code — no explanations."""

        raw = await self._call(
            [{"role": "system", "content": _CODE_SYSTEM},
             {"role": "user", "content": prompt}],
            max_tokens=self.max_tokens,
            presence_penalty=0.0,
            conversation=conversation,
            enable_thinking=False,
        )
        return {"text": self._clean_code_output(raw), "thinking": ""}

    # ── Programmatic HTML validation ─────────────────────────────────

    @staticmethod
    def validate_html(html: str) -> list[str]:
        """Check HTML for structural completeness. Returns list of issues."""
        issues = []
        h = html.lower()

        if '<!doctype html>' not in h:
            issues.append("Missing <!DOCTYPE html> declaration")
        if '<html' not in h:
            issues.append("Missing <html> tag")
        if '<head' not in h:
            issues.append("Missing <head> section")
        if '<body' not in h:
            issues.append("Missing <body> section")
        if '</html>' not in h:
            issues.append("Missing closing </html> tag")
        if 'viewport' not in h:
            issues.append("Missing viewport meta tag for responsiveness")
        if '<title' not in h:
            issues.append("Missing <title> tag")
        if '<style' not in h and 'stylesheet' not in h:
            issues.append("No CSS styling found")
        if len(html.strip()) < 200:
            issues.append("Output too short — likely incomplete generation")

        return issues

    # ── Code output cleaning ─────────────────────────────────────────

    @staticmethod
    def _clean_code_output(text: str) -> str:
        """Extract clean code from brain output."""
        # Step 1: extract from markdown code fences
        fence = re.search(
            r'```(?:html|css|js|javascript)?\s*\n(.*?)```', text, re.DOTALL
        )
        if fence:
            text = fence.group(1).strip()

        # Step 2: find start of HTML
        for marker in ("<!DOCTYPE", "<!doctype", "<html", "<HTML"):
            idx = text.find(marker)
            if idx > 0:
                text = text[idx:]
                break
        else:
            for marker in ("<!--", "<link", "<meta", "<style", "<head"):
                idx = text.find(marker)
                if idx > 0:
                    text = text[idx:]
                    break

        # Step 3: strip trailing commentary after </html>
        for end_tag in ("</html>", "</HTML>"):
            idx = text.find(end_tag)
            if idx != -1:
                text = text[:idx + len(end_tag)]
                break

        # Step 4: wrap fragments in complete document structure
        text_lower = text.lower().strip()
        if (text_lower
                and not text_lower.startswith("<!doctype")
                and not text_lower.startswith("<html")):
            if any(tag in text_lower for tag in
                   ("<style", "<div", "<section", "<link", "<!--")):
                style = re.search(
                    r'(<style[\s\S]*?</style>)', text, re.IGNORECASE
                )
                script = re.search(
                    r'(<script[\s\S]*?</script>)', text, re.IGNORECASE
                )
                links = re.findall(r'(<link[^>]*>)', text, re.IGNORECASE)

                body = text
                if style:
                    body = body.replace(style.group(1), '')
                if script:
                    body = body.replace(script.group(1), '')
                for link in links:
                    body = body.replace(link, '')
                body = body.strip()

                head_parts = "\n".join(links)
                if style:
                    head_parts += "\n" + style.group(1)

                script_part = script.group(1) if script else ""

                text = (
                    '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
                    '    <meta charset="UTF-8">\n'
                    '    <meta name="viewport" content="width=device-width, '
                    'initial-scale=1.0">\n'
                    f'    <title>CT-1 Output</title>\n{head_parts}\n'
                    f'</head>\n<body>\n{body}\n{script_part}\n'
                    '</body>\n</html>'
                )

        return text.strip()

    # ── Reflection ───────────────────────────────────────────────────

    async def reflect(self, goal: str, complexity: str, phases: int,
                      outcome: str,
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
                  .replace("{rounds}", str(phases))
                  .replace("{outcome}", outcome_for_prompt))
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": prompt},
        ]
        raw = await self._call(messages, max_tokens=512,
                               conversation=conversation)
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            return json.loads(raw[start:end])
        except Exception:
            return {
                "goal": goal, "complexity": complexity, "rounds": phases,
                "mind_contributions": {
                    "alpha": {"useful": True, "reasoning_quality": "moderate",
                              "summary": ""},
                    "beta": {"useful": True, "reasoning_quality": "moderate",
                             "summary": ""},
                    "gamma": {"useful": True, "reasoning_quality": "moderate",
                              "summary": ""},
                },
                "outcome": outcome, "lesson": "reflection parse failed",
                "complexity_correct": True, "self_score": 0.5,
            }

    async def summarize_session(self, conversation: list[dict]) -> str | None:
        if not conversation:
            return None
        lines = []
        for msg in conversation:
            if msg["role"] == "user":
                lines.append(f"- {msg['content'][:200]}")
                if len(lines) >= 20:
                    break
        transcript = "\n".join(lines)
        prompt = (
            "Summarize this conversation session in 2-3 sentences. "
            "Focus on the topics discussed and any conclusions reached.\n\n"
            f"User messages:\n{transcript}\n\nSummary:"
        )
        messages = [
            {"role": "system", "content":
             "You are a concise summarizer. Output only the summary."},
            {"role": "user", "content": prompt},
        ]
        try:
            return await self._call(messages, max_tokens=128)
        except Exception:
            return None

    async def close(self):
        await self.client.aclose()
