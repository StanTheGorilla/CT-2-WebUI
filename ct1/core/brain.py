import json

from ct1.core.engine import Engine, _repair_json


class Brain(Engine):
    """Compatibility wrapper for the older Brain test surface."""

    def __init__(self, base_url: str, **kwargs):
        super().__init__(base_url=base_url, **kwargs)

    @staticmethod
    def _text(result) -> str:
        return result if isinstance(result, str) else result.get("text", "")

    @staticmethod
    def _parse_json(text: str, fallback: dict) -> dict:
        if not text:
            return fallback
        try:
            return json.loads(text)
        except Exception:
            try:
                return json.loads(_repair_json(text))
            except Exception:
                return fallback

    async def extract_intent(self, goal: str) -> dict:
        messages = [
            {
                "role": "system",
                "content": (
                    "Return strict JSON with keys task_type, what_to_produce, "
                    "requirements, complexity."
                ),
            },
            {"role": "user", "content": goal},
        ]
        result = await self._call(messages, max_tokens=256, enable_thinking=False)
        fallback = {
            "task_type": "question" if "?" in goal else "code",
            "what_to_produce": goal,
            "requirements": [],
            "complexity": "deep" if "?" in goal else "moderate",
        }
        return self._parse_json(self._text(result), fallback)

    def write_deliberation_brief(self, intent: dict) -> str:
        requirements = intent.get("requirements") or []
        requirement_lines = "\n".join(f"- {item}" for item in requirements)
        if requirement_lines:
            requirement_lines = f"\nRequirements:\n{requirement_lines}"
        return (
            f"Task type: {intent.get('task_type', 'unknown')}\n"
            f"What to produce: {intent.get('what_to_produce', '')}"
            f"{requirement_lines}\n"
            f"Complexity: {intent.get('complexity', 'moderate')}"
        ).strip()

    async def check_convergence(self, goal: str, dialogue: list[dict]) -> dict:
        transcript = "\n".join(
            f"- {turn.get('mind', 'mind')}: {turn.get('text', '')}" for turn in dialogue
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "Return strict JSON with keys ready_to_execute, reason, "
                    "agreed_approach."
                ),
            },
            {
                "role": "user",
                "content": f"Goal: {goal}\n\nDialogue:\n{transcript or '(none)'}",
            },
        ]
        result = await self._call(messages, max_tokens=256, enable_thinking=False)
        fallback = {
            "ready_to_execute": False,
            "reason": "Could not determine convergence.",
            "agreed_approach": "",
        }
        return self._parse_json(self._text(result), fallback)

    async def synthesize(self, goal: str, intent: dict, dialogue: list[dict]) -> str:
        dialogue_text = "\n".join(
            f"- {turn.get('mind', 'mind')}: {turn.get('text', '')}" for turn in dialogue
        )
        requirements = "\n".join(f"- {item}" for item in (intent.get("requirements") or []))
        rules = ""
        if intent.get("task_type") == "code":
            rules = (
                "\nRules:\n"
                "- Produce a complete result.\n"
                "- No placeholders.\n"
                "- No TODOs or stubs.\n"
            )

        messages = [
            {
                "role": "system",
                "content": "Synthesize the final answer from the agreed approach.",
            },
            {
                "role": "user",
                "content": (
                    f"Goal: {goal}\n"
                    f"What to produce: {intent.get('what_to_produce', '')}\n"
                    f"Requirements:\n{requirements or '- none'}\n"
                    f"Dialogue:\n{dialogue_text or '- none'}"
                    f"{rules}"
                ),
            },
        ]
        result = await self._call(messages, enable_thinking=False)
        return self._text(result)
