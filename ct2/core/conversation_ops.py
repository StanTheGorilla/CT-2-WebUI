"""Extracted from Orchestrator — see ct2/core/orchestrator.py."""
import re

from ct2.core.formatter import strip_think_tags


class ConversationOpsMixin:
    async def compact_conversation(
        self,
        conversation: list[dict],
        fast: bool = False,
    ) -> list[dict]:
        """Compact a long conversation into an actionable summary + latest artifact.

        Returns 1-2 turns: a user-role summary and optionally the latest code
        as an assistant turn, so the model can continue editing it.

        When ``fast=True`` (or when the LLM summarizer fails), a mechanical
        summary is built locally without any model call. This guarantees the
        compaction step always finishes in milliseconds — the safety net that
        keeps the UI from hanging on slow hardware.
        """
        if not conversation:
            return []

        # Find the latest code artifact (HTML page, script, etc.)
        latest_code = ""
        for msg in reversed(conversation):
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                if not isinstance(content, str):
                    continue
                s = content.strip()
                is_bare_html = s.lower().startswith(("<!doctype", "<html"))
                is_bare_script = (
                    len(s) > 200
                    and s.startswith((
                        "import ", "from ", "def ", "class ",
                        "const ", "let ", "var ", "function ",
                    ))
                    and "```" not in s[:200]
                )
                if is_bare_html or is_bare_script:
                    latest_code = content
                    break

        def _user_text(m: dict) -> str:
            """Pull user-authored text out of a turn, handling multimodal content."""
            c = m.get("content", "")
            if isinstance(c, list):
                for part in c:
                    if isinstance(part, dict) and part.get("type") == "text":
                        c = part.get("text", "")
                        break
            return c.strip() if isinstance(c, str) else ""

        # IMMUTABLE LAYER — preserve every word the user said. The LLM summary
        # paraphrases assistant turns (lossy is fine), but the user's brief and
        # corrections are pinned verbatim so the model never drifts off the
        # original intent. This is the load-bearing fix for "after compaction
        # the AI built something completely different".
        user_turns = [t for t in (_user_text(m) for m in conversation if m.get("role") == "user") if t]
        original_brief = ""
        later_directives: list[str] = []
        if user_turns:
            # First user message = the brief. Cap at 1500 chars to bound size.
            original_brief = user_turns[0][:1500] + ("…" if len(user_turns[0]) > 1500 else "")
            # Subsequent user messages = corrections/refinements. Keep them all
            # if they fit, else last 8. Each capped at 400 chars.
            tail = user_turns[1:] if len(user_turns) <= 9 else user_turns[-8:]
            later_directives = [t[:400] + ("…" if len(t) > 400 else "") for t in tail]
        verbatim_block = ""
        if original_brief:
            verbatim_block += f"ORIGINAL REQUEST (user, verbatim):\n{original_brief}\n"
        if later_directives:
            quoted = "\n".join(f'  - "{d}"' for d in later_directives)
            verbatim_block += f"\nUSER CORRECTIONS / REFINEMENTS (verbatim, in order):\n{quoted}\n"

        def _mechanical_summary() -> str:
            """Deterministic summary without any LLM call. The user-intent
            block is added separately (verbatim) — this just describes what
            the assistant has done so far."""
            assistant_count = sum(1 for m in conversation if m.get("role") == "assistant")
            return (
                f"COMPLETED: {assistant_count} prior assistant turns ({len(conversation)} total messages elided).\n"
                "CURRENT STATE: Latest artifact preserved below if present.\n"
                "PENDING: Honor the user intent above and continue from where the latest artifact leaves off."
            )

        # Build a transcript, skipping slim placeholders and truncating large blobs
        lines = []
        for m in conversation:
            role = m.get("role", "")
            content = m.get("content", "")
            # Tool call turns: summarize each called function
            if role == "assistant" and m.get("tool_calls"):
                calls_desc = []
                for tc in m["tool_calls"]:
                    fn = tc.get("function", {})
                    name = fn.get("name", "?")
                    try:
                        import json as _json
                        args = _json.loads(fn.get("arguments", "{}"))
                        if name == "bash":
                            calls_desc.append(f"bash({args.get('command','?')[:80]})")
                        elif name == "write_file":
                            calls_desc.append(f"write_file({args.get('path','?')})")
                        elif name == "read_file":
                            calls_desc.append(f"read_file({args.get('path','?')})")
                        else:
                            calls_desc.append(name)
                    except Exception:
                        calls_desc.append(name)
                lines.append(f"ASSISTANT [tool]: {', '.join(calls_desc)}")
                continue
            # Tool result turns
            if role == "tool":
                result_preview = (str(content)[:300] + "…") if len(str(content)) > 300 else str(content)
                lines.append(f"TOOL RESULT: {result_preview}")
                continue
            if not isinstance(content, str):
                continue
            if content.strip() in ("(Previous code output omitted.)",):
                continue
            preview = (content[:500] + "…") if len(content) > 500 else content
            lines.append(f"{role.upper()}: {preview}")
        transcript = "\n\n".join(lines)

        prompt = (
            "Summarize this AI assistant conversation into a compact, actionable context block.\n"
            "The user's exact words will be preserved verbatim alongside your summary, "
            "so focus on describing what the assistant DID and the current state — "
            "do not re-paraphrase the user's requirements.\n"
            "Use exactly these section headers:\n"
            "COMPLETED: [what has been finished — include files created and commands run]\n"
            "CURRENT STATE: [the current output or working state — describe concisely]\n"
            "PENDING: [unfinished work, errors still to fix, or next steps the user mentioned]\n\n"
            "Be specific and actionable. Bullet points inside sections are fine.\n\n"
            f"CONVERSATION TO SUMMARIZE:\n{transcript}"
        )

        if fast:
            summary = _mechanical_summary()
        else:
            try:
                raw = await self.engine._call(
                    [{"role": "user", "content": prompt}],
                    max_tokens=400,
                    temperature=0.1,
                    enable_thinking=False,
                )
                summary = raw if isinstance(raw, str) else raw.get("text", "")
                summary = strip_think_tags(summary).strip()
                if not summary:
                    summary = _mechanical_summary()
            except Exception as e:
                print(f"[orch] compact_conversation LLM summary failed, using mechanical: {e}")
                summary = _mechanical_summary()

        # Compose final compacted turn: header + verbatim user intent + summary.
        # Verbatim block goes BEFORE the LLM summary so it's the first thing the
        # model attends to when reading the context.
        compacted_content = f"[CONTEXT SUMMARY — {len(conversation)} turns compacted to save memory]\n\n"
        if verbatim_block:
            compacted_content += (
                "═══ USER INTENT (preserved verbatim — treat as authoritative) ═══\n"
                f"{verbatim_block}\n"
                "═══ ASSISTANT PROGRESS (summarized) ═══\n"
            )
        compacted_content += summary

        compacted = [{"role": "user", "content": compacted_content}]

        if latest_code:
            # Truncate very large artifacts; enough for the model to edit
            if len(latest_code) > 12000:
                latest_code = latest_code[:12000] + "\n\n/* ... truncated for context ... */"
            compacted.append({"role": "assistant", "content": latest_code})

        return compacted

    @staticmethod
    def _merge_continuation(existing: str, continuation: str) -> str:
        """Append a continuation while trimming small repeated overlaps."""
        if not continuation:
            return existing
        if not existing:
            return continuation

        max_overlap = min(len(existing), len(continuation), 400)
        for size in range(max_overlap, 24, -1):
            if existing[-size:] == continuation[:size]:
                return existing + continuation[size:]

        stripped = continuation.strip()
        if stripped and stripped in existing[-2000:]:
            return existing
        return existing + continuation

    @staticmethod
    def _continuation_prompt(route: str) -> str:
        """Instruction used when a response hit the context limit mid-generation.

        Kept intentionally short — small models echo long instructions verbatim
        into the code output, corrupting the generated file.
        """
        return "Continue."

    async def _continue_after_length(
        self,
        draft: str,
        draft_thinking: str,
        finish_reason: str | None,
        goal_text: str,
        route: str,
        continuation_context: list[dict],
        specialist_data: dict | None,
        plan: dict | None,
        task_ovr: dict,
        emit,
        on_token,
        tools: list[dict] | None = None,
        tool_executor=None,
    ) -> tuple[str, str, str | None, int]:
        """Compact older history and continue when generation hit a length/context stop."""
        attempts = 0
        current_reason = finish_reason
        is_incomplete = self.engine._looks_incomplete(draft)
        if not (current_reason == "length" or is_incomplete) or not draft.strip():
            return draft, draft_thinking, current_reason, attempts

        while (current_reason == "length" or self.engine._looks_incomplete(draft)) and attempts < 3:
            attempts += 1
            emit(
                "compacting",
                message="Context limit reached — compacting older history and continuing…",
                source="generation",
                attempt=attempts,
            )

            # fast=True: mechanical truncation only — mid-generation context
            # overflow must recover in milliseconds, not minutes. The model is
            # already past its context budget; running another LLM summary call
            # would just compound the slowness.
            compacted_history = await self.compact_conversation(
                continuation_context
                or [{"role": "user", "content": goal_text}],
                fast=True,
            )
            summary_turn = (
                compacted_history[:1]
                if compacted_history
                else [{"role": "user", "content": f"[CONTEXT SUMMARY]\nCurrent request: {goal_text}"}]
            )
            continuation_conversation = [
                *summary_turn,
                {"role": "assistant", "content": draft},
            ]

            continuation_result = await self.engine.generate(
                self._continuation_prompt(route),
                route,
                specialist_data=specialist_data,
                plan=plan,
                conversation=continuation_conversation,
                on_token=on_token,
                task_overrides=task_ovr,
                tools=tools,
                tool_executor=tool_executor,
            )
            continuation_text = continuation_result.get("text", "")
            draft = self._merge_continuation(draft, continuation_text)
            cont_thinking = continuation_result.get("thinking", "")
            if cont_thinking:
                draft_thinking = (
                    f"{draft_thinking}\n\n{cont_thinking}" if draft_thinking else cont_thinking
                )
            current_reason = continuation_result.get("finish_reason")

        if attempts > 0:
            emit(
                "continued",
                message=(
                    "" if current_reason != "length"
                    else "Response still hit the context limit after continuing. The message may be incomplete."
                ),
                source="generation",
                attempt=attempts,
                truncated=(current_reason == "length"),
            )
        return draft, draft_thinking, current_reason, attempts

    async def _classify_is_question(self, message: str) -> bool:
        """Use the LLM to decide if a message is asking for information vs. requesting action.

        Works in any language — no keyword dependency. Returns True if the message
        is a pure information request (explain, describe, summarize, etc.).
        Defaults to False (action) on any error so generation is never blocked."""
        # Fast-path: clear action verbs → skip the LLM roundtrip entirely.
        _lower = message.lower().strip()
        _action_words = (
            "add ", "fix ", "make ", "change ", "update ", "remove ", "delete ",
            "create ", "build ", "write ", "refactor ", "edit ", "improve ",
            "rename ", "move ", "replace ", "implement ", "style ", "convert ",
            "generate ", "rewrite ", "include ",
        )
        if any(_lower.startswith(w) for w in _action_words):
            return False
        # Fast-path: clear question starters → also skip LLM.
        _question_starts = ("what ", "why ", "how ", "when ", "where ", "who ",
                            "which ", "explain ", "describe ", "what's ", "what is ")
        if any(_lower.startswith(w) for w in _question_starts) or _lower.endswith("?"):
            return True

        try:
            prompt = (
                f'Message: "{message}"\n\n'
                "Is the user asking for INFORMATION (explanation, description, summary) "
                "or requesting an ACTION (write, fix, add, change, create, extend)?\n"
                "Reply with one word only: information or action"
            )
            result = await self.engine._call(
                [{"role": "system", "content": "You classify user intent. Reply with one word only: information or action."},
                 {"role": "user", "content": prompt}],
                max_tokens=5,
                temperature=0.0,
                enable_thinking=False,
                conversation=None,
            )
            text = (result if isinstance(result, str) else result.get("text", "")).strip().lower()
            return "information" in text
        except Exception:
            return False  # default: treat as action, never silently break generation

