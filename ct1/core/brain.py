import httpx
import json
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
BRAIN_SYSTEM_TEMPLATE = (_PROMPTS_DIR / "brain_system.txt").read_text(encoding="utf-8")

class Brain:
    def __init__(self, base_url: str, temperature: float = 0.4,
                 top_p: float = 0.9, top_k: int = 20,
                 presence_penalty: float = 1.5, max_tokens: int = 10000):
        self.base_url = base_url
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.presence_penalty = presence_penalty
        self.max_tokens = max_tokens
        self.client = httpx.AsyncClient(timeout=120.0)
        self.lessons: list[str] = []
        self.last_session: str = ""

    def _system_prompt(self) -> str:
        lessons_text = ""
        if self.lessons:
            lessons_text = "From your journal:\n" + "\n".join(f"- {l}" for l in self.lessons[-10:])
        session_text = ""
        if self.last_session:
            session_text = f"Last session: {self.last_session}"
        return (BRAIN_SYSTEM_TEMPLATE
                .replace("{lessons}", lessons_text)
                .replace("{session_summary}", session_text))

    async def _call(self, messages: list[dict], max_tokens: int = None,
                    presence_penalty: float = None,
                    conversation: list[dict] = None) -> str:
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
            "presence_penalty": presence_penalty if presence_penalty is not None else self.presence_penalty,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        r = await self.client.post(f"{self.base_url}/v1/chat/completions", json=payload)
        if not r.is_success:
            raise httpx.HTTPStatusError(
                f"{r.status_code} from {r.url}: {r.text[:500]}",
                request=r.request, response=r,
            )
        return r.json()["choices"][0]["message"]["content"].strip()

    async def frame_problem(self, goal: str, conversation: list[dict] = None) -> dict:
        """Frame the problem and assess complexity. Returns {question, complexity}."""
        # Use a minimal system prompt here — no lessons, to prevent journal context
        # from contaminating goal interpretation in the small model.
        system = "You are a precise problem framer. Restate the user's question clearly and assess its complexity. Output only JSON."
        prompt = f"""Restate this question clearly for analysis and classify its complexity.

Question: {goal}

Respond as JSON only:
{{
  "question": "reframed question in 1-2 sentences",
  "complexity": "brief|moderate|deep"
}}"""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ]
        raw = await self._call(messages, max_tokens=256, conversation=conversation)
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            parsed = json.loads(raw[start:end])
            if parsed.get("complexity") not in ("brief", "moderate", "deep"):
                parsed["complexity"] = "moderate"
            # Reject the reframing if it's a label/placeholder rather than
            # a real question (model echoed the JSON field name, etc.)
            q = parsed.get("question", "")
            if len(q) < 20 or q.lower().startswith("reframed") or "{" in q:
                parsed["question"] = goal
            return parsed
        except Exception:
            return {"question": goal, "complexity": "moderate"}

    async def extract_intent(self, goal: str, conversation: list[dict] = None) -> dict:
        """Classify what the task requires and what must be produced.
        Returns {task_type, what_to_produce, requirements, complexity}.
        """
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
        raw = await self._call(messages, max_tokens=256, conversation=conversation)
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            parsed = json.loads(raw[start:end])
            if parsed.get("task_type") not in ("code", "artifact", "question", "analysis"):
                parsed["task_type"] = "question"
            if parsed.get("complexity") not in ("brief", "moderate", "deep"):
                parsed["complexity"] = "moderate"
            if not parsed.get("what_to_produce"):
                parsed["what_to_produce"] = goal
            return parsed
        except Exception:
            return {
                "task_type": "question",
                "what_to_produce": goal,
                "requirements": [],
                "complexity": "moderate",
            }

    async def detect_tension(self, goal: str, alpha: str, beta: str, gamma: str,
                              conversation: list[dict] = None) -> dict:
        """Analyze 3 mind conclusions. Return tension + strongest voice."""
        prompt = f"""Three inner voices responded to: "{goal}"

alpha concluded: {alpha}
beta concluded: {beta}
gamma concluded: {gamma}

Respond as JSON only:
{{
  "agreement": true,
  "tension_description": "brief description or empty string",
  "followup_question": "followup question or empty string",
  "confidence": 0.85,
  "strongest_voice": "alpha|beta|gamma"
}}"""
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": prompt}
        ]
        raw = await self._call(messages, max_tokens=256, conversation=conversation)
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            return json.loads(raw[start:end])
        except Exception:
            return {"agreement": True, "tension_description": "", "followup_question": "", "confidence": 0.6, "strongest_voice": "alpha"}

    async def synthesize(self, goal: str, rounds_data: list[dict],
                         tension_summary: str = "", conversation: list[dict] = None) -> str:
        """Produce final response using mind conclusions as evidence."""
        last_round = rounds_data[-1] if rounds_data else {}
        responses = last_round.get("responses", {})

        evidence_lines = []
        for name in ("alpha", "beta", "gamma"):
            resp = responses.get(name, {})
            if isinstance(resp, dict):
                conclusion = resp.get("conclusion", "")
            else:
                conclusion = str(resp)
            # Truncate per-mind evidence; full code is extracted separately below
            if len(conclusion) > 800:
                conclusion = conclusion[:800] + "…"
            evidence_lines.append(f"Mind-{name}: {conclusion}")

        evidence = "\n".join(evidence_lines)

        # If any mind produced a code block, surface the best one directly
        # rather than asking the brain to re-generate it from scratch.
        code_block = self._extract_best_code(
            [responses.get(n, {}) for n in ("alpha", "beta", "gamma")]
        )

        if code_block:
            # One of the minds already produced real code — surface it directly.
            # Don't ask the brain to regenerate; just wrap with a one-liner.
            return f"Here is the result:\n\n```\n{code_block}\n```"

        prompt = f"""You deliberated on: "{goal}"

Your inner voices concluded:

{evidence}

{tension_summary}

Now give your single, definitive response. Follow these rules exactly:
- If the task asks for code, HTML, CSS, JavaScript, or any file: write the COMPLETE file. Every line must be real, working code. No placeholders.
- BANNED: comments like <!-- ... -->, # ..., or // ... used as substitutes for actual code. If CSS belongs somewhere, write the CSS. If JavaScript belongs somewhere, write the JavaScript.
- BANNED: phrases like "add your code here", "insert styles here", "TODO", "...", or any stub.
- If the task asks a question: answer it directly.
- Do not mention your inner voices or deliberation process."""

        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": prompt}
        ]
        # presence_penalty=0 for synthesis: code/HTML requires reusing tokens freely
        return await self._call(messages, max_tokens=4096, presence_penalty=0.0,
                                conversation=conversation)

    @staticmethod
    def _extract_best_code(mind_responses: list) -> str:
        """Return the longest fenced code block found across mind conclusions."""
        import re
        best = ""
        for resp in mind_responses:
            if not isinstance(resp, dict):
                continue
            text = resp.get("conclusion", "") or resp.get("reasoning", "")
            blocks = re.findall(r"```[^\n]*\n(.*?)```", text, re.DOTALL)
            for block in blocks:
                if len(block) > len(best):
                    best = block
        return best

    async def reflect(self, goal: str, complexity: str, rounds: int, outcome: str,
                      conversation: list[dict] = None) -> dict:
        """Write structured journal reflection."""
        reflection_template = (_PROMPTS_DIR / "reflection_prompt.txt").read_text(encoding="utf-8")
        # Truncate outcome to avoid context overflow when embedding in prompt
        outcome_truncated = outcome[:2000] + "…" if len(outcome) > 2000 else outcome
        prompt = (reflection_template
                  .replace("{goal}", str(goal))
                  .replace("{complexity}", str(complexity))
                  .replace("{rounds}", str(rounds))
                  .replace("{outcome}", outcome_truncated))
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": prompt}
        ]
        raw = await self._call(messages, max_tokens=512, conversation=conversation)
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            return json.loads(raw[start:end])
        except Exception:
            return {
                "goal": goal, "complexity": complexity, "rounds": rounds,
                "mind_contributions": {
                    "alpha": {"useful": True, "reasoning_quality": "moderate", "summary": ""},
                    "beta": {"useful": True, "reasoning_quality": "moderate", "summary": ""},
                    "gamma": {"useful": True, "reasoning_quality": "moderate", "summary": ""}
                },
                "outcome": outcome, "lesson": "reflection parse failed",
                "complexity_correct": True, "self_score": 0.5
            }

    async def summarize_session(self, conversation: list[dict]) -> str | None:
        """Produce a 2-3 sentence summary of the session for cross-session memory."""
        if not conversation:
            return None
        lines = []
        for msg in conversation:
            if msg["role"] == "user":
                lines.append(f"- {msg['content'][:200]}")
                if len(lines) >= 20:
                    break
        transcript = "\n".join(lines)
        prompt = f"""Summarize this conversation session in 2-3 sentences. Focus on the topics discussed and any conclusions reached. Be specific.

User messages:
{transcript}

Summary:"""
        messages = [
            {"role": "system", "content": "You are a concise summarizer. Output only the summary, no preamble."},
            {"role": "user", "content": prompt},
        ]
        try:
            return await self._call(messages, max_tokens=128)
        except Exception:
            return None

    async def close(self):
        await self.client.aclose()
