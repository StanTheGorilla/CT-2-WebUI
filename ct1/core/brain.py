import httpx
import json
from pathlib import Path
from ct1.core.response_parser import parse_thinking_response

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
BRAIN_SYSTEM_TEMPLATE = (_PROMPTS_DIR / "brain_system.txt").read_text(encoding="utf-8")

class Brain:
    def __init__(self, base_url: str, temperature: float = 0.4,
                 top_p: float = 0.9, top_k: int = 20,
                 presence_penalty: float = 1.5, max_tokens: int = 10000,
                 enable_thinking: bool = True):
        self.base_url = base_url
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.presence_penalty = presence_penalty
        self.max_tokens = max_tokens
        self.enable_thinking = enable_thinking
        self.client = httpx.AsyncClient(timeout=600.0)
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
                    conversation: list[dict] = None,
                    thinking: bool = None) -> str:
        """Call the LLM. thinking=None uses self.enable_thinking, or override per call."""
        use_thinking = thinking if thinking is not None else self.enable_thinking
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
            "chat_template_kwargs": {"enable_thinking": use_thinking},
        }
        r = await self.client.post(f"{self.base_url}/v1/chat/completions", json=payload)
        if not r.is_success:
            raise httpx.HTTPStatusError(
                f"{r.status_code} from {r.url}: {r.text[:500]}",
                request=r.request, response=r,
            )
        raw = r.json()["choices"][0]["message"]["content"].strip()
        if use_thinking:
            parsed = parse_thinking_response(raw)
            self._last_thinking = parsed.get("reasoning", "")
            return parsed.get("conclusion", raw)
        self._last_thinking = ""
        return raw

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
        raw = await self._call(messages, max_tokens=256, conversation=conversation, thinking=False)
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

        if task_type in ("code", "artifact"):
            return (
                f"We need to design: {what}"
                f"{reqs_text}"
                f"\n\nDiscuss the design — what layout, what colors, what fonts, "
                f"what sections the page should have, what makes it feel premium. "
                f"Debate the choices."
            )

        return (
            f"We need to answer: {what}"
            f"{reqs_text}"
            f"\n\nDiscuss different angles and approaches. "
            f"What are the key considerations? What could go wrong?"
        )

    async def assess_deliberation(self, brief: str, dialogue: list[dict],
                                   conversation: list[dict] = None) -> dict:
        """Brain actively reviews the deliberation and speaks into the conversation.

        Returns {text: visible assessment, should_stop: bool, summary: str}.
        The 'text' field goes into the dialogue so minds can see it.
        """
        try:
            # Only show recent dialogue to avoid overwhelming the model
            recent = dialogue[-6:] if len(dialogue) > 6 else dialogue
            formatted = "\n".join(
                f"{t['mind']}: {t['text']}"
                for t in recent
            )
            prompt = f"""You are the brain moderating a discussion between alpha, beta, and gamma.

Topic: {brief}

Recent discussion:
{formatted}

Review the conversation. In 2-4 sentences:
1. Summarize what was decided so far
2. Call out anything that sounds wrong or made up (hallucinations)
3. Say whether we should STOP discussing and start building, or CONTINUE because something important is missing

End your response with exactly one of these lines:
VERDICT: STOP - [one-line summary of the agreed approach]
VERDICT: CONTINUE - [what still needs to be discussed]"""
            messages = [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": prompt},
            ]
            raw = await self._call(messages, max_tokens=300, conversation=conversation, thinking=False)

            should_stop = "VERDICT: STOP" in raw
            summary = ""
            if "VERDICT: STOP" in raw:
                summary = raw.split("VERDICT: STOP")[-1].strip().lstrip("- ")
            elif "VERDICT: CONTINUE" in raw:
                summary = raw.split("VERDICT: CONTINUE")[-1].strip().lstrip("- ")

            return {"text": raw, "should_stop": should_stop, "summary": summary}
        except Exception:
            return {"text": "I can't assess the discussion right now. Let's continue.",
                    "should_stop": False, "summary": ""}

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
        result = await self._call(messages, max_tokens=self.max_tokens, presence_penalty=0.0,
                                  conversation=conversation)
        return {"text": result, "thinking": self._last_thinking}

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
        raw = await self._call(messages, max_tokens=512, conversation=conversation, thinking=False)
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
            return await self._call(messages, max_tokens=128, thinking=False)
        except Exception:
            return None

    async def close(self):
        await self.client.aclose()
