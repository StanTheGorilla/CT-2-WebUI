import httpx
import json
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
BRAIN_SYSTEM_TEMPLATE = (_PROMPTS_DIR / "brain_system.txt").read_text(encoding="utf-8")

class Brain:
    def __init__(self, base_url: str, temperature: float = 0.4,
                 top_p: float = 0.9, top_k: int = 20,
                 presence_penalty: float = 1.5, max_tokens: int = 1024):
        self.base_url = base_url
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.presence_penalty = presence_penalty
        self.max_tokens = max_tokens
        self.client = httpx.AsyncClient(timeout=120.0)
        self.lessons: list[str] = []

    def _system_prompt(self) -> str:
        lessons_text = ""
        if self.lessons:
            lessons_text = "From your journal:\n" + "\n".join(f"- {l}" for l in self.lessons[-10:])
        return BRAIN_SYSTEM_TEMPLATE.replace("{lessons}", lessons_text)

    async def _call(self, messages: list[dict], max_tokens: int = None) -> str:
        payload = {
            "model": "qwen",
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "presence_penalty": self.presence_penalty,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        r = await self.client.post(f"{self.base_url}/v1/chat/completions", json=payload)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

    async def frame_problem(self, goal: str) -> str:
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": f"Frame this for your inner minds in 1-2 sentences: {goal}"}
        ]
        return await self._call(messages, max_tokens=256)

    async def detect_tension(self, goal: str, alpha: str, beta: str, gamma: str) -> dict:
        prompt = f"""Three inner voices responded to: "{goal}"

α: {alpha}
β: {beta}
γ: {gamma}

Respond as JSON only:
{{
  "agreement": true,
  "tension_description": "brief description or empty string",
  "followup_question": "followup or empty string",
  "confidence": 0.85
}}"""
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": prompt}
        ]
        raw = await self._call(messages, max_tokens=256)
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            return json.loads(raw[start:end])
        except Exception:
            return {"agreement": True, "tension_description": "", "followup_question": "", "confidence": 0.6}

    async def synthesize(self, goal: str, rounds_data: list[dict]) -> str:
        # The brain answers the question as itself — clean, direct, no mind context injected.
        # The minds already informed the deliberation (framing + tension detection).
        # Now the brain speaks.
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": goal},
        ]
        return await self._call(messages, max_tokens=512)

    async def reflect(self, goal: str, rounds: int, outcome: str) -> dict:
        reflection_template = (_PROMPTS_DIR / "reflection_prompt.txt").read_text(encoding="utf-8")
        prompt = (reflection_template
                  .replace("{goal}", str(goal))
                  .replace("{rounds}", str(rounds))
                  .replace("{outcome}", str(outcome)))
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": prompt}
        ]
        raw = await self._call(messages, max_tokens=512)
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            return json.loads(raw[start:end])
        except Exception:
            return {
                "goal": goal, "rounds": rounds,
                "mind_contributions": {"alpha": {"useful": True, "summary": ""}, "beta": {"useful": True, "summary": ""}, "gamma": {"useful": True, "summary": ""}},
                "outcome": outcome, "lesson": "reflection parse failed",
                "self_score": 0.5
            }

    async def close(self):
        await self.client.aclose()
