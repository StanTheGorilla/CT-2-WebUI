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

    async def think(self, question: str, complexity: str = "moderate") -> dict:
        """Send question to LLM, return parsed {reasoning, conclusion}."""
        payload = {
            "model": "qwen",
            "messages": [
                {"role": "system", "content": self._build_system_prompt(complexity)},
                {"role": "user", "content": question}
            ],
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

    async def close(self):
        await self.client.aclose()
