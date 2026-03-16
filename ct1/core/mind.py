import re
import httpx


_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+')


def _truncate_sentences(text: str, max_sentences: int = 4) -> str:
    """Hard-limit text to max_sentences. 0.8B models can't self-limit."""
    lines = text.strip().splitlines()
    cleaned = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        line = re.sub(r'^[-*•]\s+', '', line)
        line = re.sub(r'^\d+\.\s+', '', line)
        if line:
            cleaned.append(line)
    text = ' '.join(cleaned)
    sentences = _SENTENCE_RE.split(text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if len(sentences) <= max_sentences:
        return text
    return ' '.join(sentences[:max_sentences])


class Mind:
    """Thin executor for 0.8B mind models.

    These models are too small for reasoning or critique. They excel at
    simple, structured tasks: fill-in-the-blank, listing, extraction.
    The orchestrator constructs the prompts; the mind just executes.
    """

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
        self.client = httpx.AsyncClient(timeout=120.0)

    async def execute(self, system: str, user: str,
                      max_tokens: int = 0,
                      truncate_sentences: int = 0,
                      conversation: list[dict] = None) -> str:
        """Execute a task with explicit system/user prompts.

        Args:
            system: System prompt (keep very short for 0.8B).
            user: User prompt (structured fill-in-the-blank works best).
            max_tokens: Override default (0 = use self.max_tokens).
            truncate_sentences: If >0, hard-limit to N sentences.
            conversation: Optional prior conversation for context.
        """
        messages = [{"role": "system", "content": system}]
        if conversation:
            messages.extend(conversation)
        messages.append({"role": "user", "content": user})

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
        r = await self.client.post(
            f"{self.base_url}/v1/chat/completions", json=payload
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"].strip()

        if truncate_sentences > 0:
            return _truncate_sentences(raw, truncate_sentences)
        return raw

    async def close(self):
        await self.client.aclose()
