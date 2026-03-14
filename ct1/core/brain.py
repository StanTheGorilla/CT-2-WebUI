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

    def write_deliberation_brief(self, intent: dict) -> str:
        """Produce the brief handed to all minds at the start of deliberation."""
        what = intent.get("what_to_produce", "")
        reqs = intent.get("requirements", [])
        task_type = intent.get("task_type", "question")

        reqs_text = ""
        if reqs:
            reqs_text = "\nRequirements:\n" + "\n".join(f"- {r}" for r in reqs)

        execution_note = ""
        if task_type in ("code", "artifact"):
            execution_note = (
                "\n\nIMPORTANT: After deliberation, the brain will produce the final output. "
                "Your job is to decide HOW it should be built — approach, structure, key details. "
                "Not to build it yourselves."
            )

        return (
            f"We need to produce: {what}"
            f"{reqs_text}"
            f"\n\nDebate the best approach. Explore alternatives. "
            f"Identify risks and edge cases. Argue freely — agree, disagree, "
            f"change your mind, ask each other questions."
            f"{execution_note}"
        )

    async def check_convergence(self, brief: str, dialogue: list[dict],
                                 conversation: list[dict] = None) -> dict:
        """Ask brain if the dialogue has produced a solid enough plan to execute."""
        try:
            formatted = "\n\n".join(
                f"{t['mind']} (round {t['round']}): {t['text']}"
                for t in dialogue
            ) if dialogue else "(no dialogue yet)"
            prompt = f"""You are reviewing a deliberation between your inner voices.

Brief given to them:
{brief}

Their dialogue:
{formatted}

Is the plan solid enough to execute now?
Respond as JSON only:
{{
  "ready_to_execute": true,
  "reason": "brief reason",
  "agreed_approach": "1-2 sentence summary of what was decided"
}}"""
            messages = [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": prompt},
            ]
            raw = await self._call(messages, max_tokens=256, conversation=conversation)
            result = json.loads(raw[raw.find("{"):raw.rfind("}")+1])
            if "ready_to_execute" not in result:
                result["ready_to_execute"] = False
            return result
        except Exception:
            return {"ready_to_execute": False, "reason": "parse error", "agreed_approach": ""}

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

    async def synthesize(self, goal: str, intent: dict, dialogue: list[dict],
                         conversation: list[dict] = None) -> str:
        """Phase 3: produce the final output using the deliberation as context."""
        task_type = intent.get("task_type", "question")
        agreed = intent.get("agreed_approach", "")

        # Format dialogue as readable transcript
        transcript = "\n\n".join(
            f"{t['mind']} (round {t['round']}): {t['text']}"
            for t in dialogue
        ) if dialogue else "(no deliberation)"

        if task_type in ("code", "artifact"):
            what = intent.get("what_to_produce", goal)
            reqs = intent.get("requirements", [])
            reqs_text = ("\nRequirements:\n" + "\n".join(f"- {r}" for r in reqs)) if reqs else ""

            prompt = f"""The deliberation is complete. Produce the output now.

Task: {goal}
What to produce: {what}{reqs_text}
{f"Agreed approach: {agreed}" if agreed else ""}

Deliberation transcript (for reference):
{transcript}

RULES — follow exactly:
- Write the COMPLETE, working output. Every line must be real.
- No placeholders. No "<!-- add content here -->". No TODO. No "...". No stubs.
- If HTML: write the full HTML including all CSS and JavaScript inline. Nothing missing.
- If code: write the full file. No imports left out. No functions left as stubs.
- Do not explain what you are doing. Do not describe the output. Just produce it."""
        else:
            prompt = f"""The deliberation reached a conclusion. Answer the question now.

Question: {goal}

Deliberation transcript:
{transcript}

Draw from the strongest reasoning above. Speak in first person.
Do not mention inner voices or deliberation. Just answer."""

        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": prompt},
        ]
        return await self._call(messages, max_tokens=self.max_tokens, presence_penalty=0.0,
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
