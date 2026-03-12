import httpx
from pathlib import Path

MIND_SYSTEM = Path("ct1/prompts/mind_system.txt").read_text(encoding="utf-8")

class Mind:
    def __init__(self, name: str, base_url: str, temperature: float,
                 top_p: float = 1.0, top_k: int = 40,
                 presence_penalty: float = 1.5, max_tokens: int = 512):
        self.name = name
        self.base_url = base_url
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.presence_penalty = presence_penalty
        self.max_tokens = max_tokens
        self.client = httpx.AsyncClient(timeout=60.0)

    async def think(self, question: str) -> str:
        payload = {
            "model": "qwen",
            "messages": [
                {"role": "system", "content": MIND_SYSTEM},
                {"role": "user", "content": question}
            ],
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "presence_penalty": self.presence_penalty,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        r = await self.client.post(f"{self.base_url}/v1/chat/completions", json=payload)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

    async def close(self):
        await self.client.aclose()
