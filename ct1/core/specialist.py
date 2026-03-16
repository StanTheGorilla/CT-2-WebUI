"""CT-2 Specialist: The 2B consultant and reviewer.

Strict JSON-only output. Thinking DISABLED. Temperature 0.1.
Two modes:
  - CONSULTANT: Returns palette/typography/rationale JSON for design tasks
  - REVIEWER: Returns pass/fail with critical issues for generated code
"""
import httpx
import json

_CONSULTANT_SYSTEM = (
    "You are the CT-2 Design Specialist. "
    "Return ONLY a valid JSON object with these exact keys:\n"
    '{\n'
    '  "palette": {"background": "#hex", "text": "#hex", "accent": "#hex", '
    '"secondary": "#hex", "border": "#hex"},\n'
    '  "typography": {"heading_font": "font name", "body_font": "font name", '
    '"style_direction": "e.g. clean minimal dark, warm rustic organic, etc."},\n'
    '  "sections": ["section1", "section2", "section3", "section4", '
    '"section5", "section6"],\n'
    '  "rationale": "one sentence"\n'
    "}\n"
    "Output ONLY the JSON. No markdown. No explanation."
)

_REVIEWER_SYSTEM = (
    "You are the CT-2 Code Reviewer. Evaluate the HTML/CSS/JS output.\n"
    "Return ONLY a valid JSON object with these exact keys:\n"
    '{\n'
    '  "pass": true or false,\n'
    '  "critical_issues": ["issue1", "issue2"],\n'
    '  "fix_instructions": "specific instructions if pass is false, '
    'empty string if pass is true"\n'
    "}\n"
    "Only flag CRITICAL structural issues (missing tags, broken layout, "
    "no CSS, broken JS). Ignore minor style preferences.\n"
    "Output ONLY the JSON. No markdown. No explanation."
)

_ROUTER_SYSTEM = (
    "You are the CT-2 Routing Engine. Read the user request and categorize it.\n"
    "You may ONLY output one of the following exact strings:\n"
    '- "ROUTE_DESIGN" (If the user asks for UI/UX, styling, or layouts)\n'
    '- "ROUTE_CODE" (If the user asks for complex application logic or algorithms)\n'
    '- "ROUTE_DIRECT" (If it is a simple question or FAQ requiring no planning)\n'
    "Output nothing else."
)

_PLANNER_SYSTEM = (
    "You are the CT-2 Product Manager. Analyze the request and produce a build plan.\n"
    "Return ONLY a valid JSON object:\n"
    '{\n'
    '  "output_type": "html_page" | "python_script" | "javascript" | "api" | "other",\n'
    '  "components": [\n'
    '    {"id": 1, "name": "short name", "description": "what this component does"}\n'
    '  ],\n'
    '  "complexity": "simple" | "moderate" | "complex"\n'
    "}\n"
    "Max 6 components. Be specific and concise.\n"
    "simple = 1-2 components. moderate = 3-4. complex = 5-6.\n"
    "Output ONLY the JSON. No markdown. No explanation."
)

_CODE_KEYWORDS = {
    "html", "css", "javascript", "js", "website", "web page", "webpage",
    "script", "program", "function", "code", "app", "application",
    "component", "api", "endpoint", "server", "database", "sql",
    "python", "react", "svelte", "vue", "angular", "node",
}

_MAX_JSON_RETRIES = 2


class Specialist:
    def __init__(self, base_url: str, temperature: float = 0.1,
                 top_p: float = 0.9, top_k: int = 10,
                 max_tokens: int = 1024):
        self.base_url = base_url
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.max_tokens = max_tokens
        self.client = httpx.AsyncClient(timeout=120.0)

    async def _call(self, messages: list[dict], max_tokens: int = None) -> str:
        """Simple non-JSON call for routing."""
        payload = {
            "model": "qwen",
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        r = await self.client.post(
            f"{self.base_url}/v1/chat/completions", json=payload
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """Remove all <think>...</think> blocks. Qwen3 leaks them even with
        enable_thinking=False when grammar-forcing (response_format) is active."""
        import re
        # Remove all think blocks (greedy variant handles nested/repeated)
        cleaned = re.sub(r'<think>[\s\S]*?</think>', '', text)
        # Also strip standalone </think> that survived (partial blocks)
        cleaned = re.sub(r'</?think>', '', cleaned)
        return cleaned.strip()

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Extract and parse the first complete JSON object from text."""
        import json as _json
        # Strip markdown fences
        if "```" in text:
            lines = [l for l in text.split("\n") if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        # Direct parse
        try:
            return _json.loads(text)
        except _json.JSONDecodeError:
            pass

        # Find first { ... } block
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return _json.loads(text[start:end])

        raise ValueError(f"No JSON object found in: {text[:200]!r}")

    async def _call_json(self, messages: list[dict],
                         max_tokens: int = None,
                         on_token=None) -> dict:
        """Call the 2B Specialist and return a parsed JSON dict.

        Key design decisions:
        - NO response_format json_object: grammar-forcing conflicts with Qwen3
          thinking tokens and causes looping/spiral behaviour.
        - Strip <think> blocks before JSON extraction.
        - Retries collect internally (no re-streaming to client on retry).
        """
        payload = {
            "model": "qwen",
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": False,  # always collect internally; stream to client after
            "chat_template_kwargs": {"enable_thinking": False},
        }

        last_error = None
        raw = ""

        for attempt in range(_MAX_JSON_RETRIES + 1):
            r = await self.client.post(
                f"{self.base_url}/v1/chat/completions", json=payload
            )
            if not r.is_success:
                raise httpx.HTTPStatusError(
                    f"{r.status_code}: {r.text[:500]}",
                    request=r.request, response=r,
                )
            raw = r.json()["choices"][0]["message"]["content"].strip()
            raw = self._strip_thinking(raw)

            try:
                result = self._extract_json(raw)
                # Emit tokens to client now that we have a valid result
                if on_token:
                    on_token(raw)
                return result
            except (ValueError, Exception) as e:
                last_error = e
                # On retry: slightly higher temperature to break out of bad pattern
                payload["temperature"] = min(self.temperature + 0.1 * (attempt + 1), 0.5)

        raise ValueError(
            f"Specialist failed to produce valid JSON after "
            f"{_MAX_JSON_RETRIES + 1} attempts. Last error: {last_error}. "
            f"Raw: {raw[:300]!r}"
        )

    async def _stream_collect(self, payload: dict, on_token) -> str:
        """Stream tokens and collect full response."""
        text = ""
        async with self.client.stream(
            "POST", f"{self.base_url}/v1/chat/completions", json=payload
        ) as response:
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    token = chunk["choices"][0].get("delta", {}).get("content", "")
                    if token:
                        text += token
                        on_token(token)
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
        return text.strip()

    # ── Consultant mode ───────────────────────────────────────────────

    async def consult(self, goal: str,
                      conversation: list[dict] = None,
                      on_token=None) -> dict:
        """Get design consultation: palette, typography, sections, rationale."""
        messages = [
            {"role": "system", "content": _CONSULTANT_SYSTEM},
            {"role": "user", "content": f"Design brief for: {goal}"},
        ]
        if conversation:
            system = messages[:1]
            rest = messages[1:]
            messages = system + conversation + rest

        try:
            return await self._call_json(messages, max_tokens=512, on_token=on_token)
        except (ValueError, httpx.HTTPStatusError):
            # Fallback: return safe defaults so pipeline doesn't crash
            return {
                "palette": {
                    "background": "#0a0a0f",
                    "text": "#e0e0e0",
                    "accent": "#6366f1",
                    "secondary": "#1e1e2e",
                    "border": "#2a2a3a",
                },
                "typography": {
                    "heading_font": "Inter",
                    "body_font": "Inter",
                    "style_direction": "clean modern minimal",
                },
                "sections": [
                    "Hero", "Features", "About",
                    "Testimonials", "Pricing", "Footer",
                ],
                "rationale": "Default design (specialist unavailable)",
            }

    # ── Reviewer mode ─────────────────────────────────────────────────

    async def review(self, goal: str, code: str,
                     conversation: list[dict] = None) -> dict:
        """Review generated code. Returns {pass, critical_issues, fix_instructions}."""
        # Truncate code for review context (2B can't handle huge inputs well)
        code_preview = code[:4000] if len(code) > 4000 else code

        messages = [
            {"role": "system", "content": _REVIEWER_SYSTEM},
            {"role": "user", "content": (
                f"Task: {goal}\n\n"
                f"Generated code:\n{code_preview}"
            )},
        ]
        if conversation:
            system = messages[:1]
            rest = messages[1:]
            messages = system + conversation + rest

        try:
            result = await self._call_json(messages, max_tokens=512)
            # Normalize the result
            return {
                "pass": bool(result.get("pass", False)),
                "critical_issues": result.get("critical_issues", []),
                "fix_instructions": result.get("fix_instructions", ""),
            }
        except (ValueError, httpx.HTTPStatusError):
            # If specialist fails, fall back to programmatic validation only
            return {
                "pass": True,
                "critical_issues": [],
                "fix_instructions": "",
            }

    # ── Planner mode ──────────────────────────────────────────────────

    async def plan(self, goal: str, route: str) -> dict:
        """Produce a structured task breakdown before code generation."""
        messages = [
            {"role": "system", "content": _PLANNER_SYSTEM},
            {"role": "user", "content": f"Request: {goal}"},
        ]
        _valid_types = ("html_page", "python_script", "javascript", "api", "other")
        _valid_complexity = ("simple", "moderate", "complex")
        _default_type = "html_page" if route == "ROUTE_DESIGN" else "python_script"
        try:
            result = await self._call_json(messages, max_tokens=512)
            if result.get("output_type") not in _valid_types:
                result["output_type"] = _default_type
            if result.get("complexity") not in _valid_complexity:
                result["complexity"] = "moderate"
            if not isinstance(result.get("components"), list):
                result["components"] = []
            # Ensure each component has id, name, description
            components = []
            for i, c in enumerate(result["components"][:6]):
                components.append({
                    "id": c.get("id", i + 1),
                    "name": str(c.get("name", f"Component {i + 1}")),
                    "description": str(c.get("description", "")),
                })
            result["components"] = components
            return result
        except (ValueError, httpx.HTTPStatusError):
            return {
                "output_type": _default_type,
                "components": [],
                "complexity": "moderate",
            }

    async def route(self, goal: str,
                    conversation: list[dict] = None) -> str:
        """Classify the request. Returns ROUTE_DESIGN | ROUTE_CODE | ROUTE_DIRECT."""
        messages = [
            {"role": "system", "content": _ROUTER_SYSTEM},
            {"role": "user", "content": goal},
        ]
        if conversation:
            system = messages[:1]
            rest = messages[1:]
            messages = system + conversation + rest

        raw = await self._call(messages, max_tokens=32)
        raw_upper = raw.upper().strip().strip('"')

        if "DESIGN" in raw_upper:
            return "ROUTE_DESIGN"
        if "CODE" in raw_upper:
            return "ROUTE_CODE"

        # Keyword fallback
        goal_lower = goal.lower()
        if any(kw in goal_lower for kw in _CODE_KEYWORDS):
            return "ROUTE_CODE"

        return "ROUTE_DIRECT"

    async def close(self):
        await self.client.aclose()
