import re

from ct1.core.engine import Engine


class Mind(Engine):
    """Compatibility wrapper for the older Mind test surface."""

    def __init__(self, name: str, base_url: str, temperature: float = 0.9, **kwargs):
        super().__init__(base_url=base_url, temperature=temperature, **kwargs)
        self.name = name

    @staticmethod
    def _strip_think_tags(text: str) -> str:
        return re.sub(r"<think>[\s\S]*?</think>", "", text).strip()

    def _system_prompt(self) -> str:
        return (
            f"You are {self.name}, a deliberate specialist. "
            "Respond with concise plain text."
        )

    async def think(
        self,
        goal: str,
        conversation: list[dict] | None = None,
        prior_voices: str | None = None,
    ) -> str:
        prompt = goal
        if prior_voices:
            prompt = f"Prior voices:\n{prior_voices}\n\nCurrent task:\n{goal}"
        result = await self._call(
            [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": prompt},
            ],
            conversation=conversation,
            enable_thinking=False,
        )
        return self._strip_think_tags(result)

    async def converse(
        self,
        brief: str,
        dialogue: list[dict],
        conversation: list[dict] | None = None,
    ) -> str:
        dialogue_text = "\n".join(
            f"- {turn.get('mind', 'mind')}: {turn.get('text', '')}" for turn in dialogue
        )
        prompt = (
            f"Brief:\n{brief}\n\n"
            f"Prior dialogue:\n{dialogue_text or '- none'}\n\n"
            "Respond with your next contribution."
        )
        result = await self._call(
            [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": prompt},
            ],
            conversation=conversation,
            enable_thinking=False,
        )
        return self._strip_think_tags(result)
