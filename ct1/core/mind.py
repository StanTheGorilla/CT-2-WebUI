import httpx
from pathlib import Path
from ct1.core.response_parser import parse_thinking_response

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
MIND_SYSTEM_TEMPLATE = (_PROMPTS_DIR / "mind_system.txt").read_text(encoding="utf-8")

COMPLEXITY_INSTRUCTIONS = {}
for level in ("brief", "moderate", "deep"):
    path = _PROMPTS_DIR / f"complexity_{level}.txt"
    if path.exists():
        COMPLEXITY_INSTRUCTIONS[level] = path.read_text(encoding="utf-8").strip()

COMPLEXITY_INSTRUCTIONS.setdefault("brief", "Think concisely. Identify the 1-2 most important observations and conclude directly.")
COMPLEXITY_INSTRUCTIONS.setdefault("moderate", "Think step by step. Consider the main angles of this problem before concluding.")
COMPLEXITY_INSTRUCTIONS.setdefault("deep", "Think thoroughly. Explore your assumptions, consider counterarguments, examine edge cases, and only then draw your conclusion. Take the space you need.")

class Mind:
    def __init__(self, name: str, base_url: str, temperature: float,
                 top_p: float = 1.0, top_k: int = 40,
                 presence_penalty: float = 1.5, max_tokens: int = 10000,
                 enable_thinking: bool = True):
        self.name = name
        self.base_url = base_url
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.presence_penalty = presence_penalty
        self.max_tokens = max_tokens
        self.enable_thinking = enable_thinking
        self.client = httpx.AsyncClient(timeout=120.0)

    def _build_system_prompt(self, complexity: str = "moderate") -> str:
        instruction = COMPLEXITY_INSTRUCTIONS.get(complexity, COMPLEXITY_INSTRUCTIONS["moderate"])
        return MIND_SYSTEM_TEMPLATE.replace("{complexity_instruction}", instruction)

    async def think(self, question: str, complexity: str = "moderate",
                    conversation: list[dict] = None,
                    prior_voices: str = "") -> dict:
        """Send question to LLM, return parsed {reasoning, conclusion}.

        prior_voices: text showing what the other minds said so far this round,
                      so this mind can respond to them directly.
        """
        if prior_voices:
            user_content = f"{prior_voices}\n\n---\n\nNow respond with your own view on: {question}"
        else:
            user_content = question

        messages = [
            {"role": "system", "content": self._build_system_prompt(complexity)},
        ]
        if conversation:
            messages.extend(conversation)
        messages.append({"role": "user", "content": user_content})

        payload = {
            "model": "qwen",
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "presence_penalty": self.presence_penalty,
            "max_tokens": self.max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": self.enable_thinking},
        }
        r = await self.client.post(f"{self.base_url}/v1/chat/completions", json=payload)
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"].strip()
        return parse_thinking_response(raw)

    async def converse(self, brief: str, dialogue: list[dict],
                       conversation: list[dict] = None) -> str:
        """Contribute one turn to the free-form deliberation dialogue.

        brief: what the minds are deliberating about (from brain.write_deliberation_brief)
        dialogue: all prior turns [{mind, round, text}, ...]
        Returns a plain string — the mind's contribution.
        """
        if dialogue:
            turns_text = "\n\n".join(
                f"{t['mind']}: {t['text']}"
                for t in dialogue
            )
            user_content = (
                f"{brief}\n\n"
                f"Conversation so far:\n{turns_text}\n\n"
                f"You are {self.name}. Continue the conversation. "
                f"Be direct and specific. Engage with what was said."
            )
        else:
            user_content = (
                f"{brief}\n\n"
                f"You are {self.name}. You go first. Think freely."
            )

        messages = [{"role": "system", "content": self._build_system_prompt("moderate")}]
        if conversation:
            messages.extend(conversation)
        messages.append({"role": "user", "content": user_content})

        payload = {
            "model": "qwen",
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "presence_penalty": self.presence_penalty,
            "max_tokens": self.max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": self.enable_thinking},
        }
        r = await self.client.post(f"{self.base_url}/v1/chat/completions", json=payload)
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"].strip()
        parsed = parse_thinking_response(raw)
        # Return just the conclusion text (thinking block stripped)
        return parsed.get("conclusion", raw)

    async def close(self):
        await self.client.aclose()
