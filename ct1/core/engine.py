"""CT-2 Engine: The unified model interface and code generator.

Operates in two modes:
  - ROUTER: Classifies intent → ROUTE_DESIGN | ROUTE_CODE | ROUTE_DIRECT
  - GENERATOR: Produces full code/answers
"""
import asyncio
import httpx
import json
import re as _re
from ct1.prompts.manager import _get_prompt_manager as _pm


def _compact_tool_history(head_len: int, current_messages: list) -> list:
    """Compact accumulated tool-call history into a summary when context overflows.

    Keeps the original setup messages (system + user goal), replaces all tool
    call/result turns with a brief summary, so the model can continue the task.
    """
    head = current_messages[:head_len]
    tool_turns = current_messages[head_len:]
    if not tool_turns:
        return current_messages

    steps = []
    last_output = ""
    for m in tool_turns:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                fn = tc.get("function", {})
                name = fn.get("name", "?")
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                    if name == "bash":
                        steps.append(f"ran: {args.get('command', '?')[:120]}")
                    elif name == "write_file":
                        steps.append(f"wrote: {args.get('path', '?')}")
                    elif name == "read_file":
                        steps.append(f"read: {args.get('path', '?')}")
                    else:
                        steps.append(f"called {name}")
                except Exception:
                    steps.append(f"called {name}")
        elif m.get("role") == "tool":
            last_output = str(m.get("content", ""))[:400]

    step_list = "\n".join(f"  - {s}" for s in steps) if steps else "  (steps not recorded)"
    summary = (
        f"[SESSION CONTEXT COMPACTED — {len(tool_turns)} messages summarized to save memory]\n"
        f"Steps you have already completed:\n{step_list}"
        + (f"\n\nMost recent command output:\n{last_output}" if last_output else "")
        + "\n\nContinue working on the original task. Do not repeat completed steps."
    )
    return head + [{"role": "user", "content": summary}]


def _repair_json(text: str) -> str:
    """Fix common LLM JSON mistakes so json.loads succeeds.

    Handles: trailing commas, single-quoted strings, unquoted keys,
    JS-style comments, and Python-style True/False/None.
    """
    # 1. Strip JS-style comments (// ... and /* ... */)
    text = _re.sub(r'//[^\n]*', '', text)
    text = _re.sub(r'/\*.*?\*/', '', text, flags=_re.DOTALL)

    # 2. Replace Python-style booleans/None outside of strings
    #    (quick pass — only replaces if not inside quotes)
    text = _re.sub(r'\bTrue\b', 'true', text)
    text = _re.sub(r'\bFalse\b', 'false', text)
    text = _re.sub(r'\bNone\b', 'null', text)

    # 3. Remove trailing commas before } or ]
    text = _re.sub(r',\s*([}\]])', r'\1', text)

    # 4. Replace single-quoted strings with double-quoted
    #    Walk char by char to avoid breaking apostrophes inside double-quoted strings
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '"':
            # Double-quoted string — pass through unchanged
            out.append(ch)
            i += 1
            while i < len(text):
                c = text[i]
                out.append(c)
                if c == '\\':
                    i += 1
                    if i < len(text):
                        out.append(text[i])
                elif c == '"':
                    break
                i += 1
            i += 1
        elif ch == "'":
            # Single-quoted string — convert to double-quoted
            out.append('"')
            i += 1
            while i < len(text):
                c = text[i]
                if c == '\\':
                    out.append(c)
                    i += 1
                    if i < len(text):
                        out.append(text[i])
                elif c == "'":
                    break
                elif c == '"':
                    out.append('\\"')  # escape inner double quotes
                    i += 1
                    continue
                else:
                    out.append(c)
                i += 1
            out.append('"')
            i += 1
        else:
            out.append(ch)
            i += 1
    text = ''.join(out)

    # 5. Escape literal newlines/tabs inside JSON strings BEFORE quoting unquoted keys.
    # Must run first: the unquoted-key regex uses \n as a delimiter, so a literal \n
    # inside a string value like "flex\ntext: center" would cause step 6 to incorrectly
    # treat "text" as an unquoted key and corrupt the string.
    result = []
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '"' and (i == 0 or text[i - 1] != '\\'):
            in_string = not in_string
            result.append(ch)
        elif in_string and ch == '\n':
            result.append('\\n')
        elif in_string and ch == '\r':
            result.append('\\r')
        elif in_string and ch == '\t':
            result.append('\\t')
        else:
            result.append(ch)
        i += 1
    text = ''.join(result)

    # 6. Quote unquoted keys: `  key:` → `  "key":`
    # Safe to run now: literal newlines inside strings have been escaped, so the
    # \n lookbehind only fires on structural JSON newlines (outside strings).
    text = _re.sub(
        r'(?<=[\{,\n])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:',
        r' "\1":',
        text,
    )

    return text

BRAIN_SYSTEM_TEMPLATE = _pm().get("brain_system")
_DESIGN_TOOLKIT = _pm().get("design_toolkit")


def _layered(base_name: str, user_name: str) -> str:
    """Combine a locked base prompt with a user-editable prompt."""
    base = _pm().get(base_name)
    user = _pm().get(user_name)
    if base and user:
        return base + "\n\n" + user
    return base or user


_GENERATOR_CODE_SYSTEM = _layered("generator_code_base", "generator_code")

_GENERATOR_DESIGN_SYSTEM = _layered("generator_design_base", "generator_design")
# Simplified design prompt for smaller models (medium/small tier).
# The full design director prompt overwhelms 9B-and-below models, causing
# them to respond conversationally instead of generating code.
# The spec already carries all design decisions (colors, fonts, layout).
_GENERATOR_DESIGN_LITE = _pm().get("generator_design_base")

_GENERATOR_COMPUTER_SYSTEM = _layered("generator_computer_base", "generator_computer")

_GENERATOR_TEXT_SYSTEM = _layered("generator_text_base", "generator_text")

_GENERATOR_EDIT_SYSTEM = _pm().get("generator_edit")

_GENERATOR_SECTION_EDIT_SYSTEM = _pm().get("generator_section_edit")

_GENERATOR_PATCH_SYSTEM = _pm().get("generator_patch")

_GENERATOR_DISCUSS_SYSTEM = _pm().get("generator_discuss")

_LENGTH_GUIDE = {
    "simple": "Target: 80-150 lines of code.",
    "moderate": "Target: 150-350 lines of code.",
    "complex": "Target: 350-600 lines of code.",
}

_INLINE_PLANNING_SUFFIX = _pm().get("inline_planning_suffix")

_INLINE_VERIFY_SUFFIX = _pm().get("inline_verify_suffix")

_DESIGN_FEWSHOT = _pm().get("design_fewshot")

_CODE_FEWSHOT = _pm().get("code_fewshot")


def get_system_prompt(route: str, tier: str = "small",
                      context_size: int = 16384) -> str:
    """Get the system prompt for a route, with tier-appropriate suffix.

    Small tier: append few-shot examples (if context allows) + inline planning
    Medium tier: append verification only
    Large tier: no suffix
    """
    prompts = {
        "ROUTE_DIRECT": _GENERATOR_TEXT_SYSTEM,
        "ROUTE_DESIGN": _GENERATOR_DESIGN_SYSTEM,
        "ROUTE_CODE": _GENERATOR_CODE_SYSTEM,
        "ROUTE_COMPUTER": _GENERATOR_COMPUTER_SYSTEM,
    }
    base = prompts.get(route, _GENERATOR_TEXT_SYSTEM)

    if tier == "small":
        suffix = ""
        # Add few-shot for code/design if context allows
        if context_size >= 8192:
            if route == "ROUTE_DESIGN":
                suffix += _DESIGN_FEWSHOT
                base = _GENERATOR_DESIGN_LITE  # skip long director prompt
            elif route == "ROUTE_CODE":
                suffix += _CODE_FEWSHOT
        suffix += _INLINE_PLANNING_SUFFIX
        return base + suffix
    elif tier == "medium":
        if route == "ROUTE_DESIGN":
            # Medium models (2B-14B) also use the lite prompt — the full
            # design director prompt is too long and causes conversational drift
            base = _GENERATOR_DESIGN_LITE
        return base + _INLINE_VERIFY_SUFFIX
    else:  # large
        return base


def truncate_conversation(
    conversation: list[dict],
    system_prompt: str,
    max_context: int,
    reserve_output: int = 2048,
    chars_per_token: float = 3.5,
) -> list[dict]:
    """Truncate conversation to fit within context budget.

    Keeps newest messages. Removes oldest turns first.
    Never splits user+assistant pairs.
    """
    if not conversation:
        return conversation

    system_tokens = len(system_prompt) / chars_per_token
    available = max_context - system_tokens - reserve_output

    if available <= 0:
        return conversation[-2:]  # Keep at least the last exchange

    result = []
    total = 0

    # Walk from newest to oldest, keep what fits
    for msg in reversed(conversation):
        msg_tokens = len(msg.get("content", "")) / chars_per_token
        if total + msg_tokens > available:
            break
        result.insert(0, msg)
        total += msg_tokens

    # Ensure we keep at least the most recent message
    if not result and conversation:
        result = [conversation[-1]]

    return result


class Engine:
    def __init__(self, base_url: str, temperature: float = 0.6,
                 top_p: float = 0.9, top_k: int = 40,
                 presence_penalty: float = 1.0, frequency_penalty: float = 0.0,
                 repeat_penalty: float = 1.05,
                 max_tokens: int = 100000,
                 thinking_budget: int = -1,
                 vision_supported: bool = False,
                 context_size: int = 16384,
                 model_name: str = "",
                 is_external: bool = False):
        self.base_url = base_url
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.presence_penalty = presence_penalty
        self.frequency_penalty = frequency_penalty
        self.repeat_penalty = repeat_penalty
        self.max_tokens = max_tokens
        self.thinking_budget = thinking_budget
        self.vision_supported = vision_supported
        self.context_size = context_size
        self.model_name = model_name
        self.is_external = is_external
        self.client = httpx.AsyncClient(timeout=600.0)
        self._client_lock = asyncio.Lock()
        self.tier: str = "large"  # overridden by orchestrator after detection
        self.lessons: list[str] = []
        self.last_session: str = ""

    def _sanitize_messages(self, messages: list[dict]) -> list[dict]:
        """Strip image content from messages if vision is not supported."""
        if self.vision_supported:
            return messages
        sanitized = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [p.get("text", "") for p in content
                              if p.get("type") == "text"]
                sanitized.append({
                    **msg,
                    "content": " ".join(text_parts) or "(image attachment — vision not available)",
                })
            else:
                sanitized.append(msg)
        return sanitized

    def _personality_prompt(self) -> str:
        lessons_text = ""
        if self.lessons:
            lessons_text = "From your journal:\n" + "\n".join(
                f"- {l}" for l in self.lessons[-10:]
            )
        session_text = ""
        if self.last_session:
            session_text = f"Last session: {self.last_session}"
        return (BRAIN_SYSTEM_TEMPLATE
                .replace("{lessons}", lessons_text)
                .replace("{session_summary}", session_text))

    async def _call(self, messages: list[dict], max_tokens: int = None,
                    presence_penalty: float = None,
                    temperature: float = None,
                    top_p: float = None,
                    conversation: list[dict] = None,
                    enable_thinking: bool = True,
                    thinking_budget: int = None):
        """Call the engine. Thinking enabled by default."""
        if conversation:
            system_prompt = messages[0].get("content", "") if messages else ""
            conversation = truncate_conversation(
                conversation, system_prompt, self.context_size)
            system = messages[:1]
            rest = messages[1:]
            messages = system + conversation + rest

        messages = self._sanitize_messages(messages)

        chat_kwargs = {"enable_thinking": enable_thinking}
        budget = thinking_budget if thinking_budget is not None else self.thinking_budget
        if enable_thinking and budget > 0:
            chat_kwargs["thinking_budget"] = budget

        payload = {
            "model": self.model_name or "local",
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "top_p": top_p if top_p is not None else self.top_p,
            "top_k": self.top_k,
            "presence_penalty": (presence_penalty if presence_penalty is not None
                                 else self.presence_penalty),
            "frequency_penalty": self.frequency_penalty,
            "repeat_penalty": self.repeat_penalty,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": False,
        }
        if not self.is_external:
            payload["chat_template_kwargs"] = chat_kwargs

        r = await self.client.post(
            f"{self.base_url}/v1/chat/completions", json=payload
        )
        if not r.is_success:
            raise httpx.HTTPStatusError(
                f"{r.status_code}: {r.text[:500]}",
                request=r.request, response=r,
            )

        response_json = r.json()
        choice = response_json["choices"][0]

        if enable_thinking:
            msg = choice["message"]
            content = msg.get("content", "").strip()
            reasoning = msg.get("reasoning_content", "").strip()
            text = content if content else reasoning
            thinking = reasoning if content else ""
            return {
                "text": text,
                "thinking": thinking,
                "finish_reason": choice.get("finish_reason"),
            }

        return {
            "text": choice["message"]["content"].strip(),
            "thinking": "",
            "finish_reason": choice.get("finish_reason"),
        }


    # ── Streaming call ────────────────────────────────────────────────

    @staticmethod
    def _detect_repetition(text: str, window: int = 40) -> bool:
        """Detect if the model is stuck in a repetition loop.

        Catches four patterns:
        1. Exact chunk repetition (same 40 chars 3+ times)
        2. Line repetition (same line 4+ times in last 30 lines)
        3. Paragraph repetition (similar paragraphs keep appearing)
        4. Long-pattern repetition (SVG paths, base64, etc. — 80-200 char cycles)
        """
        if len(text) < 500:
            return False
        from collections import Counter

        tail = text[-window * 4:]

        # 1. Exact chunk repetition (short patterns)
        pattern = tail[-window:]
        if tail.count(pattern) >= 3:
            return True

        # 2. Line-level repetition
        # Filter out short structural lines (}, },, ], );, etc.)
        # which naturally repeat in nested code and are NOT repetition loops
        lines = tail.split('\n')[-30:]
        non_empty = [l.strip() for l in lines
                     if l.strip() and len(l.strip()) > 5]
        if len(non_empty) >= 4:
            counts = Counter(non_empty)
            if counts.most_common(1)[0][1] >= 4:
                return True

        # 3. Paragraph/sentence repetition — catch the "That's fine. Timeout
        #    maybe due to..." pattern where sentences repeat with tiny variations
        if len(text) > 800:
            # Split into sentences, normalize whitespace, check for repeats
            last_chunk = text[-2000:]
            sentences = [s.strip() for s in last_chunk.replace('\n', ' ').split('.')
                         if len(s.strip()) > 20]
            if len(sentences) >= 6:
                # Normalize: lowercase, collapse spaces
                normed = [' '.join(s.lower().split()) for s in sentences]
                counts = Counter(normed)
                most_common_count = counts.most_common(1)[0][1]
                if most_common_count >= 4:
                    return True
                # Check for near-duplicates (same first 30 chars)
                prefixes = Counter(s[:30] for s in normed if len(s) >= 30)
                if prefixes and prefixes.most_common(1)[0][1] >= 5:
                    return True

        # 4. Long-pattern repetition — catches SVG path data, base64 strings,
        #    and any other dense single-line repeating content (cycle ~150-300 chars)
        #    Only activates after 5000+ chars to avoid false-positives on Tailwind config,
        #    CSS variables, and other structured but legitimate repeated content.
        if len(text) > 5000:
            last_chunk = text[-4000:]
            for pat_len in (150, 200, 250, 300):
                if len(last_chunk) < pat_len * 4:
                    continue
                pat = last_chunk[-pat_len:]
                if last_chunk.count(pat) >= 4:
                    return True

        # 5. Character-class entropy collapse — numeric oscillation / token soup
        # Catches "0.8, 0.7, 0.8, 0.9..." patterns that vary per token and evade
        # all exact-match checks above. If <15% of the last 300 chars is alphabetic,
        # the model has lost linguistic structure and is sampling noise.
        if len(text) > 300:
            tail = text[-300:]
            alpha_count = sum(1 for c in tail if c.isalpha())
            if alpha_count < len(tail) * 0.15:
                return True

        return False

    async def _call_stream(self, messages: list[dict], on_token=None,
                           max_tokens: int = None,
                           presence_penalty: float = None,
                           temperature: float = None,
                           top_p: float = None,
                           conversation: list[dict] = None,
                           enable_thinking: bool = True,
                           thinking_budget: int = None,
                           check_repetition: bool = True,
                           tools: list[dict] | None = None,
                           tool_executor=None):
        """Streaming call with token-by-token callback."""
        if conversation:
            system_prompt = messages[0].get("content", "") if messages else ""
            conversation = truncate_conversation(
                conversation, system_prompt, self.context_size)
            system = messages[:1]
            rest = messages[1:]
            messages = system + conversation + rest

        messages = self._sanitize_messages(messages)

        chat_kwargs = {"enable_thinking": enable_thinking}
        budget = thinking_budget if thinking_budget is not None else self.thinking_budget
        if enable_thinking and budget > 0:
            chat_kwargs["thinking_budget"] = budget

        payload = {
            "model": self.model_name or "local",
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "top_p": top_p if top_p is not None else self.top_p,
            "top_k": self.top_k,
            "presence_penalty": (presence_penalty if presence_penalty is not None
                                 else self.presence_penalty),
            "frequency_penalty": self.frequency_penalty,
            "repeat_penalty": self.repeat_penalty,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": True,
        }
        if not self.is_external:
            payload["chat_template_kwargs"] = chat_kwargs

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        text = ""
        thinking = ""
        content_token_count = 0
        thinking_token_count = 0
        async def _stream_once(request_messages: list[dict]):
            nonlocal text, thinking, content_token_count, thinking_token_count
            pending_tool_calls: list[dict] = []
            finish_reason: str | None = None
            start_len = len(text)

            # httpx.AsyncClient.stream() is implemented as an @asynccontextmanager
            # with a try/finally that calls response.aclose() unconditionally.
            # This means if a CancelledError propagates out of the async-for loop
            # (e.g. because the WebSocket client disconnected), aclose() is still
            # called immediately, closing the TCP connection to llama-server
            # without draining the remaining response body. CancelledError is then
            # re-raised by the context manager so the task cancellation propagates
            # correctly up the call stack. No additional try/except is needed here.
            async with self.client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                json={**payload, "messages": request_messages},
            ) as response:
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        choice = chunk["choices"][0]
                        delta = choice.get("delta", {})
                        token = delta.get("content", "")
                        reason = delta.get("reasoning_content", "")
                        if token:
                            text += token
                            if on_token:
                                on_token(token, "content")
                            # Check content for repetition every 150 tokens
                            # (disabled for design/code routes — HTML/CSS has legitimate repetition)
                            if check_repetition:
                                content_token_count += 1
                                if content_token_count >= 150:
                                    content_token_count = 0
                                    if self._detect_repetition(text):
                                        text = self._trim_repetition(text)
                                        break
                        if reason:
                            thinking += reason
                            if on_token:
                                on_token(reason, "thinking")
                            # Check thinking for repetition every 80 tokens
                            # (more aggressive than content — small models degrade faster in reasoning)
                            if check_repetition:
                                thinking_token_count += 1
                                if thinking_token_count >= 80:
                                    thinking_token_count = 0
                                    if self._detect_repetition(thinking):
                                        thinking = self._trim_repetition(thinking)
                                        break
                        tool_calls_raw = delta.get("tool_calls", [])
                        for tc_chunk in tool_calls_raw:
                            idx = tc_chunk.get("index", 0)
                            while len(pending_tool_calls) <= idx:
                                pending_tool_calls.append(
                                    {"id": "", "name": "", "arguments": ""}
                                )
                            if tc_chunk.get("id"):
                                pending_tool_calls[idx]["id"] = tc_chunk["id"]
                            fn = tc_chunk.get("function", {})
                            if fn.get("name"):
                                pending_tool_calls[idx]["name"] = fn["name"]
                            if fn.get("arguments"):
                                pending_tool_calls[idx]["arguments"] += fn["arguments"]
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

            return pending_tool_calls, finish_reason, text[start_len:]

        original_msg_len = len(messages)
        current_messages = list(messages)
        pending_tool_calls, finish_reason, pass_text = await _stream_once(current_messages)

        _compact_count = 0
        while finish_reason == "tool_calls" and tool_executor and pending_tool_calls:
            parsed_calls = []
            for tc in pending_tool_calls:
                try:
                    args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except json.JSONDecodeError:
                    args = {}
                parsed_calls.append({
                    "id": tc["id"],
                    "name": tc["name"],
                    "args": args,
                    "arguments": tc["arguments"],
                })

            tool_results = list(await tool_executor(parsed_calls) or [])
            if len(tool_results) < len(parsed_calls):
                tool_results.extend(
                    ["Tool returned no output."] * (len(parsed_calls) - len(tool_results))
                )
            elif len(tool_results) > len(parsed_calls):
                tool_results = tool_results[:len(parsed_calls)]

            current_messages = list(current_messages)
            current_messages.append({
                "role": "assistant",
                "content": pass_text or "",
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["arguments"],
                        },
                    }
                    for tc in parsed_calls
                ],
            })
            for tc, result in zip(parsed_calls, tool_results):
                current_messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": str(result),
                })

            pending_tool_calls, finish_reason, pass_text = await _stream_once(current_messages)

            # Context overflow mid-loop: compact history and retry so the task continues
            if (finish_reason == "length" and tool_executor
                    and _compact_count < 3
                    and len(current_messages) > original_msg_len + 2):
                _compact_count += 1
                current_messages = _compact_tool_history(original_msg_len, current_messages)
                pending_tool_calls, finish_reason, pass_text = await _stream_once(current_messages)

        # Fallback: if model emitted only reasoning (no content), use reasoning as response
        if not text and thinking:
            text, thinking = thinking, ""
        return {
            "text": text.strip(),
            "thinking": thinking.strip(),
            "finish_reason": finish_reason,
        }

    @staticmethod
    def _trim_repetition(text: str) -> str:
        """Find where repetition started and cut it off."""
        # HTML end markers
        for end_marker in ("</html>", "</body>", "</script>", "</style>",
                           "</section>", "</div>", "</footer>"):
            idx = text.rfind(end_marker)
            if idx != -1:
                return text[:idx + len(end_marker)]
        # Python/JS end markers — find last complete function or block
        for end_marker in ("\nif __name__", "\ndef ", "\nclass ",
                           "\nfunction ", "\nmodule.exports",
                           "\nint main(", "\nreturn 0;"):
            idx = text.rfind(end_marker)
            if idx != -1:
                # Find end of this block
                nl = text.find("\n\n", idx + len(end_marker))
                if nl != -1:
                    return text[:nl]
        # Fallback: cut at the last newline before the repetition zone
        cut = len(text) - 200
        nl = text.rfind("\n", 0, cut)
        if nl > 0:
            return text[:nl]
        return text[:cut]

    @staticmethod
    def _looks_incomplete(text: str) -> bool:
        """Return True if output was structurally cut mid-generation."""
        t = text.rstrip()
        if not t:
            return False
        if "<html" in t.lower() and "</html>" not in t.lower():
            return True
        if t.count("```") % 2 == 1:
            return True
        return False

    # ── Prompt building ───────────────────────────────────────────────

    @staticmethod
    def _build_plan_context(plan: dict) -> str:
        """Turn a plan into an explicit generation directive."""
        components = plan.get("components", [])
        if not components:
            return ""
        output_type = plan.get("output_type", "other")

        if output_type == "html_page":
            lines = ["Build ALL of the following sections/components:"]
            for c in components:
                lines.append(f"  {c['id']}. {c['name']}: {c['description']}")
            lines.append("Include every component listed above in the output.")
        else:
            lines = ["Implement ALL of the following functions/components:"]
            for c in components:
                lines.append(f"  {c['id']}. {c['name']}: {c['description']}")
            lines.append(
                "Write the complete script. Every function listed above must be implemented."
            )

        return "\n" + "\n".join(lines)

    # ── Task planning (model writes its own checklist) ──────────────

    _TASK_PLAN_SYSTEM = _pm().get("task_plan")

    async def plan_tasks(self, goal_text: str, specialist_data: dict = None,
                         task_overrides: dict = None) -> list[str]:
        """Engine writes its own project-specific task list.

        Returns a list of concrete task strings, or empty list on failure.
        """
        ovr = task_overrides or {}
        context = ""
        if specialist_data:
            context = self._format_specialist_context(specialist_data)

        messages = [
            {"role": "system", "content": self._TASK_PLAN_SYSTEM},
            {"role": "user", "content": f"{goal_text}{context}"},
        ]

        try:
            result = await self._call(
                messages, max_tokens=384,
                temperature=ovr.get("temperature", 0.4),
                top_p=ovr.get("top_p", 0.9),
                enable_thinking=False,
            )
            text = result if isinstance(result, str) else result.get("text", "")
            # Parse numbered lines: "1. ...", "2. ...", etc.
            import re
            tasks = []
            for line in text.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                # Strip leading number + dot/paren/dash
                cleaned = re.sub(r'^[\d\-\*]+[\.\)\:]?\s*', '', line).strip()
                if cleaned and len(cleaned) > 5:
                    # Hard truncate to ~80 chars at word boundary
                    if len(cleaned) > 80:
                        cut = cleaned[:80].rfind(' ')
                        cleaned = cleaned[:cut] if cut > 40 else cleaned[:80]
                    tasks.append(cleaned)
            return tasks[:8]
        except Exception as e:
            print(f"[director] task planning failed: {e}")
            return []

    # ── Generator mode ───────────────────────────────────────────────

    @staticmethod
    def _build_user_content(goal, suffix: str = ""):
        """Build user message content, preserving multimodal parts if present."""
        if isinstance(goal, list):
            # Multimodal: append suffix to the text part, keep image parts
            parts = []
            for p in goal:
                if p.get("type") == "text":
                    parts.append({"type": "text", "text": p["text"] + suffix})
                else:
                    parts.append(p)
            return parts
        return f"{goal}{suffix}"

    async def generate(self, goal, route: str,
                       specialist_data: dict = None,
                       plan: dict = None,
                       conversation: list[dict] = None,
                       on_token=None,
                       is_edit: bool = False,
                       code_context: str = None,
                       task_overrides: dict = None,
                       task_list: list[str] = None,
                       tools: list[dict] | None = None,
                       tool_executor=None) -> dict:
        """Generate the full response. Returns {"text": str, "thinking": str}.

        plan: structured task breakdown from Specialist.plan().
        on_token: if provided, streams tokens via callback(token, kind).
        is_edit: if True, uses edit-aware prompting to modify previous code.
        """
        is_code = route in ("ROUTE_DESIGN", "ROUTE_CODE", "ROUTE_COMPUTER")
        is_direct = route == "ROUTE_DIRECT"
        is_computer = route == "ROUTE_COMPUTER"
        # Unpack per-task overrides (e.g. Nemotron uses different temp per route)
        ovr = task_overrides or {}
        ovr_temp = ovr.get("temperature")
        ovr_top_p = ovr.get("top_p")
        ovr_pp = ovr.get("presence_penalty")
        ovr_thinking = ovr.get("enable_thinking")
        ovr_budget = ovr.get("thinking_budget")

        goal_text = goal if isinstance(goal, str) else " ".join(
            p.get("text", "") for p in goal if p.get("type") == "text"
        )

        # "Question about code" mode — answer about previously generated code
        if code_context and is_direct:
            truncated = self._truncate_context(code_context, 6000)
            prompt = (
                f"[Previously generated code for reference]\n{truncated}\n\n"
                f"User question: {goal_text}"
            )
            system = _GENERATOR_DISCUSS_SYSTEM
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ]
            if on_token:
                return await self._call_stream(
                    messages, on_token=on_token,
                    max_tokens=8192,
                    presence_penalty=0.0,
                    temperature=ovr_temp,
                    top_p=ovr_top_p,
                    conversation=conversation,
                    enable_thinking=ovr_thinking if ovr_thinking is not None else False,
                    thinking_budget=ovr_budget,
                    tools=tools,
                    tool_executor=tool_executor,
                )
            return await self._call(
                messages, max_tokens=8192,
                temperature=ovr_temp,
                top_p=ovr_top_p,
                conversation=conversation,
                enable_thinking=ovr_thinking if ovr_thinking is not None else False,
                thinking_budget=ovr_budget,
            )

        # For complex Python/scripts: use the micro-fill loop instead
        if (plan and not is_direct and not is_edit
                and plan.get("output_type") in ("python_script", "api")
                and plan.get("complexity") == "complex"
                and len(plan.get("components", [])) >= 4):
            return await self._generate_micro(
                goal_text, plan, conversation=conversation, on_token=on_token
            )

        # Build prompt — format specialist data as readable text, not JSON
        specialist_ctx = self._format_specialist_context(specialist_data)
        plan_ctx = self._build_plan_context(plan) if plan else ""

        # Output length guidance based on complexity
        complexity = plan.get("complexity", "moderate") if plan else "moderate"
        length_ctx = "\n" + _LENGTH_GUIDE.get(complexity, "") if plan else ""

        # Format task list as inline checklist the model sees while generating
        task_ctx = ""
        if task_list:
            items = "\n".join(f"  □ {t}" for t in task_list)
            task_ctx = (
                f"\n\n[YOUR TASK LIST — complete ALL of these]\n{items}\n"
                "Verify every task is done before finishing."
            )

        is_design = route == "ROUTE_DESIGN"

        if is_edit and is_code:
            prompt = f"Modify the code from the previous response:\n{goal_text}"
            system = _GENERATOR_EDIT_SYSTEM
        elif is_computer:
            prompt = self._build_user_content(goal, f"{plan_ctx}{specialist_ctx}{task_ctx}{length_ctx}")
            system = _GENERATOR_COMPUTER_SYSTEM
        elif is_design:
            prompt = self._build_user_content(goal, f"{specialist_ctx}{task_ctx}")
            # Use the full design director prompt only for large models (14B+).
            # Smaller models get the lite prompt — the full director overwhelms them
            # and causes conversational drift instead of code generation.
            system = _GENERATOR_DESIGN_SYSTEM if self.tier == "large" else _GENERATOR_DESIGN_LITE
        elif is_code:
            prompt = self._build_user_content(goal, f"{plan_ctx}{specialist_ctx}{task_ctx}{length_ctx}")
            system = _GENERATOR_CODE_SYSTEM
        elif is_direct:
            prompt = self._build_user_content(goal, f"{specialist_ctx}{task_ctx}")
            system = _GENERATOR_TEXT_SYSTEM
        else:
            prompt = self._build_user_content(goal, f"{plan_ctx}{specialist_ctx}{task_ctx}{length_ctx}")
            system = self._personality_prompt()

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

        # Resolve enable_thinking: override > route default > True
        thinking = (ovr_thinking if ovr_thinking is not None
                    else True)

        # Resolve presence_penalty: override > route default > instance default
        pp = ovr_pp if ovr_pp is not None else self.presence_penalty

        # Repetition detection: enabled for everything except design mode.
        # HTML has legitimate repeated patterns (class strings, closing tags,
        # CSS rules) that false-trigger the detector and cut off generation.
        check_repetition = route != "ROUTE_DESIGN"

        if on_token:
            result = await self._call_stream(
                messages,
                on_token=on_token,
                max_tokens=self.max_tokens,
                presence_penalty=pp,
                temperature=ovr_temp,
                top_p=ovr_top_p,
                conversation=conversation,
                enable_thinking=thinking,
                thinking_budget=ovr_budget,
                check_repetition=check_repetition,
                tools=tools,
                tool_executor=tool_executor,
            )
            if (result.get("finish_reason") == "length"
                    and self._looks_incomplete(result["text"])):
                cont_messages = [
                    messages[0],
                    messages[1],
                    {"role": "assistant", "content": result["text"]},
                    {"role": "user", "content": "Continue exactly from where you left off. Do not repeat anything already written."},
                ]
                cont = await self._call_stream(
                    cont_messages,
                    on_token=on_token,
                    max_tokens=self.max_tokens,
                    presence_penalty=pp,
                    temperature=ovr_temp,
                    top_p=ovr_top_p,
                    enable_thinking=thinking,
                    thinking_budget=ovr_budget,
                    check_repetition=check_repetition,
                )
                result = {
                    "text": result["text"] + cont["text"],
                    "thinking": result.get("thinking", "") + cont.get("thinking", ""),
                    "finish_reason": cont.get("finish_reason"),
                }
            return result

        return await self._call(
            messages,
            max_tokens=self.max_tokens,
            presence_penalty=pp,
            temperature=ovr_temp,
            top_p=ovr_top_p,
            conversation=conversation,
            enable_thinking=thinking,
            thinking_budget=ovr_budget,
        )

    # ── Precision-Design: Spec generation (Phase 0) ─────────────────────

    _SPEC_GENERATOR_SYSTEM = _pm().get("spec_generator")

    async def generate_spec(
        self, goal, conversation: list[dict] = None,
        task_overrides: dict = None,
        on_token=None,
    ) -> dict:
        """Phase 0: Generate JSON spec from user prompt.

        The Engine produces a structured JSON specification describing
        the page architecture. This spec drives all downstream generation.

        Returns parsed JSON dict. Raises ValueError if output is not valid JSON.
        """
        import json as _json

        ovr = task_overrides or {}
        goal_text = goal if isinstance(goal, str) else " ".join(
            p.get("text", "") for p in goal if p.get("type") == "text"
        )

        messages = [
            {"role": "system", "content": self._SPEC_GENERATOR_SYSTEM},
            {"role": "user", "content": goal_text},
        ]

        if on_token:
            result = await self._call_stream(
                messages,
                on_token=on_token,
                max_tokens=self.max_tokens,
                temperature=ovr.get("temperature", 0.35),
                top_p=ovr.get("top_p", 0.9),
                conversation=conversation,
                enable_thinking=True,
                thinking_budget=ovr.get("thinking_budget"),
            )
        else:
            result = await self._call(
                messages,
                max_tokens=self.max_tokens,
                temperature=ovr.get("temperature", 0.35),
                top_p=ovr.get("top_p", 0.9),
                conversation=conversation,
                enable_thinking=True,
                thinking_budget=ovr.get("thinking_budget"),
            )

        # Extract text from result
        text = result if isinstance(result, str) else result.get("text", "")

        # Strip think tags and markdown fences
        import re
        text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
        if "```" in text:
            lines = [l for l in text.split("\n") if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        # Extract the first syntactically complete JSON object.
        # Scan every '{' position — raw_decode stops at the matching '}' and
        # ignores any trailing text, so "Extra data" errors are impossible.
        decoder = _json.JSONDecoder()
        for i, ch in enumerate(text):
            if ch != '{':
                continue
            try:
                obj, _ = decoder.raw_decode(text, i)
                return obj
            except _json.JSONDecodeError:
                continue

        # Last-resort: repair Python-style booleans / trailing commas, then retry
        start = text.find("{")
        end = text.rfind("}") + 1
        if start < 0 or end <= start:
            raise ValueError(f"No JSON object found in Engine output: {text[:300]!r}")
        repaired = _repair_json(text[start:end])
        for i, ch in enumerate(repaired):
            if ch != '{':
                continue
            try:
                obj, _ = decoder.raw_decode(repaired, i)
                return obj
            except _json.JSONDecodeError:
                continue
        raise ValueError(f"Could not parse spec JSON after repair: {repaired[:200]!r}")

    # ── Self-refinement pass (design mode) ─────────────────────────────

    _REFINE_SYSTEM = _pm().get("refine")

    _REFINE_TARGETED_SYSTEM = _pm().get("refine_targeted")

    _REFINE_CSS_SYSTEM = _pm().get("refine_css")

    async def refine_design(self, html: str, on_token=None,
                            task_overrides: dict = None,
                            missing_items: list[str] = None) -> dict:
        """Self-refinement: model reviews and improves its own output.

        Pass 2 of design mode — the model receives its complete HTML output
        and rewrites it with unified spacing, consistent styles, hover states,
        and polish. Returns {"text": str, "thinking": str}.
        """
        ovr = task_overrides or {}

        # Use targeted prompt if specific issues are known
        if missing_items:
            issue_list = "\n".join(f"- {item}" for item in missing_items)
            system = (
                self._REFINE_TARGETED_SYSTEM
                + f"MISSING / BROKEN — fix these:\n{issue_list}\n"
            )
        else:
            system = self._REFINE_SYSTEM

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Here is the website to improve:\n\n{html}"},
        ]

        if on_token:
            return await self._call_stream(
                messages,
                on_token=on_token,
                max_tokens=self.max_tokens,
                temperature=ovr.get("temperature", 0.4),
                top_p=ovr.get("top_p", 0.9),
                enable_thinking=True,
                thinking_budget=ovr.get("thinking_budget"),
            )

        return await self._call(
            messages,
            max_tokens=self.max_tokens,
            temperature=ovr.get("temperature", 0.4),
            top_p=ovr.get("top_p", 0.9),
            enable_thinking=True,
            thinking_budget=ovr.get("thinking_budget"),
        )

    async def refine_css_only(self, css: str, task_overrides: dict = None) -> dict:
        """Refine only the CSS block of a design output.

        Much safer than full-page rewrite: the model only processes ~2-5 KB
        of CSS, preserving the original HTML structure entirely.
        Returns {"text": str, "thinking": str}.
        """
        ovr = task_overrides or {}
        messages = [
            {"role": "system", "content": self._REFINE_CSS_SYSTEM},
            {"role": "user", "content": f"Improve this CSS:\n\n{css}"},
        ]
        return await self._call_stream(
            messages,
            on_token=None,
            max_tokens=min(self.max_tokens, 8192),
            temperature=ovr.get("temperature", 0.3),
            top_p=ovr.get("top_p", 0.9),
            enable_thinking=False,
            thinking_budget=0,
        )

    # ── Section-level edit ──────────────────────────────────────────────

    async def generate_patch_edit(
        self, goal: str, code: str, on_token=None,
    ) -> dict:
        """Ask the director to output SEARCH/REPLACE patches instead of full code.

        Returns {"text": str, "thinking": str} where text contains patch blocks.
        """
        # Truncate code for context window — keep start + end
        if len(code) > 8000:
            code_for_prompt = (
                code[:5000]
                + "\n\n/* ... middle section ... */\n\n"
                + code[-3000:]
            )
        else:
            code_for_prompt = code

        prompt = (
            f"Original code:\n{code_for_prompt}\n\n"
            f"Change requested: {goal}"
        )

        messages = [
            {"role": "system", "content": _GENERATOR_PATCH_SYSTEM},
            {"role": "user", "content": prompt},
        ]

        if on_token:
            return await self._call_stream(
                messages, on_token=on_token,
                max_tokens=4096,
                presence_penalty=0.0,
                enable_thinking=True,
            )

        return await self._call(
            messages, max_tokens=4096,
            enable_thinking=True,
        )

    @staticmethod
    def _truncate_context(text: str, max_chars: int) -> str:
        """Truncate text keeping start and end for context."""
        if len(text) <= max_chars:
            return text
        half = max_chars // 2
        return text[:half] + "\n/* ... */\n" + text[-half:]

    async def extract_search_query(
        self,
        user_message: str,
        recent_history: list[dict] | None = None,
    ) -> str:
        """Extract a focused web search query from a user message.

        *recent_history* is an optional list of recent conversation turns
        (OpenAI-style ``[{"role": "user"|"assistant", "content": "..."}]``).
        Providing it lets the extractor resolve pronouns like "his", "it",
        "they" by anchoring them to the conversation context.

        Uses a fast, low-temperature, thinking-disabled call so it adds
        minimal latency. Falls back to the raw message (truncated) on error.
        """
        text = (user_message or "").strip()
        if not text:
            return ""

        # Build a compact conversation snippet (last ≤3 pairs, 800 chars cap).
        context_block = ""
        if recent_history:
            snippets: list[str] = []
            for turn in recent_history[-6:]:  # at most 3 user/assistant pairs
                role = turn.get("role", "")
                content = turn.get("content", "")
                if isinstance(content, list):
                    content = " ".join(
                        p.get("text", "") for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
                label = "User" if role == "user" else "Assistant"
                snippets.append(f"{label}: {str(content)[:200]}")
            if snippets:
                raw_ctx = "\n".join(snippets)[:800]
                context_block = f"\nRecent conversation:\n{raw_ctx}\n"

        from datetime import datetime as _dt
        _today = _dt.now().strftime("%B %d, %Y")  # e.g. "April 12, 2025"
        _year = _dt.now().year

        system = (
            f"Today is {_today}. "
            "You convert user messages into concise web search queries. "
            "Reply with ONLY the search query — 3 to 8 keywords, no quotes, "
            "no punctuation, no prefix like 'query:'. "
            "If the message contains pronouns (his, her, it, they, that), "
            "resolve them using the conversation context and include the "
            "specific subject in the query. "
            f"For questions about current events, news, or recent happenings, "
            f"append the year {_year} to the query to ensure recent results."
        )
        user = f"{context_block}\nUser message:\n{text[:600]}\n\nSearch query:"

        try:
            result = await self._call(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=40,
                temperature=0.2,
                top_p=0.9,
                enable_thinking=False,
                thinking_budget=0,
            )
            raw = result["text"] if isinstance(result, dict) else result
        except Exception as _e:
            print(f"[engine] extract_search_query failed ({_e}), using raw text fallback")
            return text[:120]

        query = (raw or "").strip().strip('"').strip("'").strip("`")
        # Strip any leading label the model might emit despite instructions.
        for prefix in ("search query:", "query:", "search:", "answer:"):
            if query.lower().startswith(prefix):
                query = query[len(prefix):].strip().strip('"').strip("'")
        # Take only the first line in case the model added explanation.
        query = query.splitlines()[0].strip() if query else ""
        # Hard cap at 120 chars to avoid pathological outputs.
        query = query[:120]
        return query or text[:120]

    async def generate_section_edit(
        self, goal: str, section: str,
        sections: dict[str, str],
        on_token=None,
    ) -> dict:
        """Regenerate a single HTML section. Returns {"text": str, "thinking": str}.

        section: which section to edit ('style', 'body', 'script', 'head')
        sections: dict of all section contents for read-only context
        """
        section_content = sections.get(section, "")

        # Build compact context from other sections (truncated to fit context window)
        context_parts = []
        for name, content in sections.items():
            if name == section:
                continue
            # Truncate large sections — director only needs a sketch for context
            truncated = self._truncate_context(content, 1500)
            context_parts.append(f"<{name}>\n{truncated}\n</{name}>")
        context = "\n\n".join(context_parts)

        prompt = (
            f"[CONTEXT — other sections for reference, do NOT output these]\n"
            f"{context}\n\n"
            f"[SECTION TO EDIT — <{section}>]\n"
            f"{section_content}\n\n"
            f"User request: {goal}\n\n"
            f"Output ONLY the modified <{section}> inner content. "
            f"No wrapping <{section}> tags. No <!DOCTYPE>. No other sections."
        )

        messages = [
            {"role": "system", "content": _GENERATOR_SECTION_EDIT_SYSTEM},
            {"role": "user", "content": prompt},
        ]

        if on_token:
            return await self._call_stream(
                messages, on_token=on_token,
                max_tokens=self.max_tokens,
                presence_penalty=self.presence_penalty,
                enable_thinking=True,
            )

        return await self._call(
            messages, max_tokens=self.max_tokens,
            enable_thinking=True,
        )

    # ── Polish pass ─────────────────────────────────────────────────

    async def polish_css(self, css: str) -> dict:
        """Improve CSS quality with design polish rules.

        Returns {"text": str} — thinking disabled to keep output clean.
        """
        system = _pm().get("polish_system")

        # Truncate if CSS is huge
        if len(css) > 6000:
            css_for_prompt = css[:4000] + "\n/* ... */\n" + css[-2000:]
        else:
            css_for_prompt = css

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Improve this CSS:\n\n{css_for_prompt}"},
        ]

        raw = await self._call(
            messages, max_tokens=self.max_tokens,
            enable_thinking=False,
        )
        # _call now returns a metadata dict even with thinking disabled.
        text = raw if isinstance(raw, str) else raw.get("text", "")
        return {"text": text}

    # ── HTML Scaffold + Fill loop ────────────────────────────────────

    async def _generate_html_scaffold(self, goal: str, plan: dict,
                                       specialist_data: dict = None,
                                       conversation: list[dict] = None,
                                       on_token=None,
                                       task_overrides: dict = None) -> dict:
        """Two-phase HTML generation: structure first, then style + content.

        Phase A: Generate HTML skeleton (structure + class names, minimal inline content)
        Phase B: Generate full CSS targeting those classes + fill body content

        This decouples structural decisions from visual ones, letting
        the 4B model focus on one concern at a time.
        """
        components = plan.get("components", []) if plan else []
        ovr = task_overrides or {}
        ovr_budget = ovr.get("thinking_budget")

        # Build specialist context
        specialist_ctx = self._format_specialist_context(specialist_data)
        plan_ctx = self._build_plan_context(plan) if plan else ""

        # Length guidance
        complexity = plan.get("complexity", "moderate") if plan else "moderate"
        length_guide = _LENGTH_GUIDE.get(complexity, "Target: 200-400 lines total.")

        # ── Phase A: HTML structure skeleton ─────────────────────────
        skel_prompt = (
            f"Task: {goal}\n{plan_ctx}{specialist_ctx}\n\n"
            f"Write the COMPLETE HTML from <!DOCTYPE html> to </html>.\n"
            f"Real, compelling content — never lorem ipsum. Write persuasive copy.\n"
            f"Descriptive, semantic class names.\n"
            f"Include <head> with Google Fonts link (for fonts in DESIGN SPEC), meta viewport, title.\n"
            f"Include EMPTY <style></style> — CSS will be added separately.\n"
            f"Include <script> with IntersectionObserver scroll-triggered fade-in animations.\n"
            f"No markdown fences. {length_guide}\n"
        )

        if on_token:
            on_token("[Phase 1: Building HTML structure...]\n", "thinking")

        # Route Phase A tokens to thinking stream only (content comes at end)
        def _skel_token(token, kind):
            if on_token:
                on_token(token, "thinking")

        skel_result = await self._call_stream(
            [{"role": "system", "content": _GENERATOR_CODE_SYSTEM},
             {"role": "user", "content": skel_prompt}],
            on_token=_skel_token,
            max_tokens=self.max_tokens,
            temperature=0.45,  # Moderate temp for structure + creative copy
            conversation=conversation,
            enable_thinking=True,
            thinking_budget=ovr_budget,
        )
        skeleton = skel_result["text"]
        skel_thinking = skel_result.get("thinking", "")

        # ── Phase B: CSS targeting the skeleton's classes ────────────
        # Extract just the body for context (model sees what classes exist)
        import re as _re
        body_match = _re.search(r'<body[^>]*>(.*?)</body>', skeleton,
                                _re.DOTALL | _re.IGNORECASE)
        body_preview = body_match.group(1)[:4000] if body_match else skeleton[:4000]

        css_prompt = (
            f"Task: {goal}\n{specialist_ctx}\n\n"
            f"HTML BODY (target these classes):\n{body_preview}\n\n"
            f"Write ALL CSS rules for this page. Output ONLY CSS — no HTML tags, no fences.\n\n"
            f"REQUIRED:\n"
            f"- :root with ALL color variables from the DESIGN SPEC above\n"
            f"- Typography: font-family, font-size with clamp(), letter-spacing, line-height\n"
            f"- Layered box-shadows on cards/buttons (subtle + medium layers)\n"
            f"- Transitions (0.3s cubic-bezier) + hover transforms (translateY, shadow lift)\n"
            f"- Hero section: full viewport, gradient background, centered content\n"
            f"- Responsive: @media (max-width: 768px) — stack grids, reduce padding\n"
            f"- Scroll animations: .fade-in-up with @keyframes\n"
            f"- Every section, every element must have complete styling — no unstyled gaps.\n"
        )

        if on_token:
            on_token("\n[Phase 2: Writing CSS...]\n", "thinking")

        css_result = await self._call(
            [{"role": "system", "content": (
                "You are a CSS expert. Output ONLY CSS rules. No HTML tags. "
                "No <style> wrappers. No markdown fences. No explanations. Just CSS."
            )},
             {"role": "user", "content": css_prompt}],
            max_tokens=self.max_tokens,
            temperature=0.5,  # Slightly higher for creative styling
            enable_thinking=False,
        )
        css_text = css_result if isinstance(css_result, str) else css_result.get("text", "")
        # Strip any fences or tags the model might add
        css_text = css_text.strip()
        if css_text.startswith("```"):
            lines = css_text.split("\n")
            css_text = "\n".join(l for l in lines if not l.startswith("```"))
        css_text = _re.sub(r'</?style[^>]*>', '', css_text)

        # ── Assemble: inject CSS into skeleton's empty <style> ──────
        style_match = _re.search(r'<style[^>]*></style>', skeleton,
                                  _re.IGNORECASE)
        if style_match:
            assembled = (skeleton[:style_match.start()]
                         + f"<style>\n{css_text}\n</style>"
                         + skeleton[style_match.end():])
        else:
            # Fallback: inject before </head>
            head_end = skeleton.find('</head>')
            if head_end != -1:
                assembled = (skeleton[:head_end]
                             + f"\n<style>\n{css_text}\n</style>\n"
                             + skeleton[head_end:])
            else:
                assembled = skeleton

        # Stream the final assembled output to the client
        if on_token:
            # Clear previous streaming and send the assembled version
            on_token(assembled, "content")

        return {"text": assembled, "thinking": skel_thinking}

    @staticmethod
    def _format_specialist_context(data: dict = None) -> str:
        """Format decomposition data as concise requirements context."""
        if not data:
            return ""
        route = data.get("_route", "")
        parts = ["\n\n[REQUIREMENTS]"]

        if route == "ROUTE_DESIGN":
            if data.get("project_type"):
                parts.append(f"Project: {data['project_type']}")
            if data.get("audience"):
                parts.append(f"Audience: {data['audience']}")
            if data.get("mood"):
                mood = data["mood"] if isinstance(data["mood"], list) else [data["mood"]]
                parts.append(f"Mood: {', '.join(mood)}")
            if data.get("theme"):
                parts.append(f"Theme: {data['theme']}")
            if data.get("sections"):
                parts.append(f"Sections: {' → '.join(data['sections'])}")
            if data.get("color_hints"):
                hints = [h for h in data["color_hints"] if h]
                if hints:
                    parts.append(f"Colors: {', '.join(hints)}")
            if data.get("special"):
                special = [s for s in data["special"] if s]
                if special:
                    parts.append(f"Special: {', '.join(special)}")

        elif route == "ROUTE_CODE":
            if data.get("language"):
                parts.append(f"Language: {data['language']}")
            if data.get("type"):
                parts.append(f"Type: {data['type']}")
            if data.get("requirements"):
                parts.append("Must do:")
                for r in data["requirements"]:
                    parts.append(f"  - {r}")
            if data.get("edge_cases"):
                cases = data["edge_cases"] if isinstance(data["edge_cases"], list) else [data["edge_cases"]]
                parts.append(f"Edge cases: {', '.join(cases)}")
            if data.get("output_format"):
                parts.append(f"Output: {data['output_format']}")

        elif route == "ROUTE_COMPUTER":
            if data.get("language"):
                parts.append(f"Language: {data['language']}")
            if data.get("framework") and data["framework"] != "none":
                parts.append(f"Framework: {data['framework']}")
            if data.get("files"):
                parts.append(f"Files: {', '.join(data['files'])}")
            if data.get("requirements"):
                parts.append("Must do:")
                for r in data["requirements"]:
                    parts.append(f"  - {r}")
            if data.get("run_command"):
                parts.append(f"Run: {data['run_command']}")

        elif route == "ROUTE_DIRECT":
            if data.get("topic"):
                parts.append(f"Topic: {data['topic']}")
            if data.get("answer_type"):
                parts.append(f"Answer type: {data['answer_type']}")
            if data.get("depth"):
                parts.append(f"Depth: {data['depth']}")
            if data.get("key_points"):
                points = [p for p in data["key_points"] if p]
                if points:
                    parts.append("Address:")
                    for p in points:
                        parts.append(f"  - {p}")

        if len(parts) <= 1:
            return ""
        return "\n".join(parts)

    # ── Micro-fill loop (complex Python/scripts) ─────────────────────

    async def _generate_micro(self, goal: str, plan: dict,
                               conversation: list[dict] = None,
                               on_token=None) -> dict:
        """Skeleton + targeted fill for complex Python/script generation.

        1. Generate a hollow skeleton with # TODO: {id} markers.
        2. For each component, fill in just that function in a focused call.
        3. Assemble and return the complete script.
        """
        components = plan.get("components", [])

        # ── Step 1: generate skeleton ────────────────────────────────
        skel_prompt = (
            f"Task: {goal}\n\n"
            f"Write a Python script skeleton. "
            f"Define the imports and all function signatures, "
            f"but leave each function body as exactly: "
            f"# TODO: {{id}}  (no other code inside).\n\n"
            f"Functions to define:\n"
            + "\n".join(
                f"  def {c['name'].lower().replace(' ', '_')}(): "
                f"# TODO: {c['id']}"
                for c in components
            )
            + "\n\nOutput ONLY the skeleton. No explanations."
        )

        if on_token:
            on_token("[Building skeleton...]\n", "thinking")

        skel_result = await self._call(
            [{"role": "system", "content": _GENERATOR_CODE_SYSTEM},
             {"role": "user", "content": skel_prompt}],
            max_tokens=2048,
            enable_thinking=False,
        )
        skeleton = skel_result if isinstance(skel_result, str) else skel_result.get("text", "")

        # ── Step 2: fill each TODO ────────────────────────────────────
        assembled = skeleton
        total_thinking = f"[Skeleton built: {len(skeleton)} chars]\n"

        for c in components:
            todo_marker = f"# TODO: {c['id']}"
            if todo_marker not in assembled:
                continue  # skeleton didn't include this one, skip

            if on_token:
                on_token(f"[Filling: {c['name']}]\n", "thinking")

            fill_prompt = (
                f"Task: {goal}\n\n"
                f"Here is the script skeleton:\n{assembled}\n\n"
                f"Fill in ONLY the function marked `{todo_marker}`.\n"
                f"Component: {c['name']} — {c['description']}\n"
                f"Return ONLY the replacement code for that function body. "
                f"No explanations. No other functions."
            )

            fill_result = await self._call(
                [{"role": "system", "content": _GENERATOR_CODE_SYSTEM},
                 {"role": "user", "content": fill_prompt}],
                max_tokens=1024,
                enable_thinking=False,
            )
            fill_text = (fill_result if isinstance(fill_result, str)
                         else fill_result.get("text", ""))

            # Extract just the function body lines (strip fences/preamble)
            fill_text = fill_text.strip()
            if fill_text.startswith("```"):
                lines = fill_text.split("\n")
                lines = [l for l in lines
                         if not l.startswith("```") and not l.startswith("```")]
                fill_text = "\n".join(lines).strip()

            # Replace the TODO marker with the filled body
            assembled = assembled.replace(todo_marker, fill_text, 1)
            total_thinking += f"[{c['name']}: {len(fill_text)} chars]\n"

        if on_token:
            on_token(assembled, "content")

        return {"text": assembled, "thinking": total_thinking}

    # ── Reflection (reused from brain) ───────────────────────────────

    async def reflect(self, goal: str, complexity: str, outcome: str,
                      conversation: list[dict] = None) -> dict:
        reflection_template = _pm().get("reflection_prompt")
        if len(outcome) > 500:
            outcome_for_prompt = (
                f"[Generated {len(outcome)} characters of output]"
            )
        else:
            outcome_for_prompt = outcome
        prompt = (reflection_template
                  .replace("{goal}", str(goal))
                  .replace("{complexity}", str(complexity))
                  .replace("{outcome}", outcome_for_prompt))
        messages = [
            {"role": "system", "content": "You are a helpful assistant that outputs valid JSON only."},
            {"role": "user", "content": prompt},
        ]
        # No conversation context — reflection is a standalone structured task.
        # Low temperature for reliable JSON output.
        raw = await self._call(
            messages, max_tokens=300,
            temperature=0.1,
            conversation=None,
            enable_thinking=False,
        )
        if isinstance(raw, dict):
            raw = raw.get("text", "")
        # Fix common LLM JSON formatting issues
        fixed = (raw
                 .replace("True", "true")
                 .replace("False", "false")
                 .replace("None", "null"))
        try:
            start = fixed.find("{")
            end = fixed.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(fixed[start:end])
        except Exception:
            pass
        return {
            "goal": goal, "complexity": complexity,
            "lesson": "reflection parse failed",
            "self_score": 0.5,
        }

    async def summarize_session(self, conversation: list[dict]) -> str | None:
        if not conversation:
            return None
        lines = [f"- {m['content'][:200]}"
                 for m in conversation if m["role"] == "user"][:20]
        prompt = (
            "Summarize this conversation in 2-3 sentences.\n\n"
            f"User messages:\n" + "\n".join(lines) + "\n\nSummary:"
        )
        messages = [
            {"role": "system", "content": "Concise summarizer. Output only the summary."},
            {"role": "user", "content": prompt},
        ]
        try:
            return await self._call(
                messages, max_tokens=128, enable_thinking=False
            )
        except Exception:
            return None

    async def clear_kv_cache(self) -> bool:
        """Erase llama-server's KV cache to reclaim VRAM between conversations.

        Calls POST /slots/0 with {"action": "erase"} — the standard llama-server
        slot management API (supported from llama-server build b3000+ onward).

        Returns True if the cache was cleared, False if the server doesn't support
        it (404) or is unreachable. Never raises.
        """
        try:
            resp = await self.client.post(
                f"{self.base_url}/slots/0",
                json={"action": "erase"},
                timeout=5.0,
            )
            if resp.status_code in (200, 204):
                return True
            # 404 = older llama-server build without slot API
            return False
        except Exception:
            return False

    async def reset_client(self) -> None:
        """Close and recreate the httpx client to flush stale TCP connections.

        Call this after llama-server restarts or model swaps to flush stale
        Windows TCP TIME_WAIT sockets that degrade inference throughput.

        Safe to call concurrently — guarded by _client_lock.
        IMPORTANT: Only call when no inference is in progress (i.e., server is
        offline/restarting), as the client will be unavailable during reset.
        """
        async with self._client_lock:
            try:
                await self.client.aclose()
            except Exception:
                pass
            self.client = httpx.AsyncClient(timeout=600.0)

    async def close(self):
        async with self._client_lock:
            await self.client.aclose()
