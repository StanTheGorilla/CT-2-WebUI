"""CT-2 Orchestrator: Sequential Supervisor-Worker pipeline.

6-phase pipeline:
  1. ROUTE    — Specialist classifies intent (ROUTE_DESIGN | ROUTE_CODE | ROUTE_DIRECT)
  2. PLAN     — Specialist produces a structured task breakdown (code routes only)
  3. CONSULT  — Specialist provides design data (ROUTE_DESIGN only)
  4. GENERATE — Director produces full response (with plan context injected)
  5. VALIDATE — Output-type-aware validation (HTML structural / Python AST / JS braces)
  6. FORMAT   — Deterministic Python cleanup
"""
import yaml
from pathlib import Path
from ct1.core.director import Director
from ct1.core.specialist import Specialist
from ct1.core.formatter import clean_response, validate_output
from ct1.memory.journal import Journal
from ct1.memory.journal_reader import JournalReader
from ct1.memory.session_store import SessionStore

_CONFIG_PATH = (Path(__file__).parent.parent.parent
                / "ct1" / "server" / "model_config.yaml")


class Orchestrator:
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = str(_CONFIG_PATH)

        cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        director_url = f"http://localhost:{cfg['llama_server']['port']}"
        specialist_url = f"http://localhost:{cfg['llama_server_specialist']['port']}"
        dc = cfg["models"]["director"]
        sc = cfg["models"]["specialist"]

        self.director = Director(
            base_url=director_url,
            temperature=dc["temperature"],
            top_p=dc["top_p"],
            top_k=dc["top_k"],
            presence_penalty=dc["presence_penalty"],
            max_tokens=dc["max_tokens"],
        )

        self.specialist = Specialist(
            base_url=specialist_url,
            temperature=sc["temperature"],
            top_p=sc["top_p"],
            top_k=sc["top_k"],
            max_tokens=sc["max_tokens"],
        )

        self.journal = Journal(cfg["journal"]["path"])
        self.journal_reader = JournalReader(cfg["journal"]["path"])
        self.verbose = False

        # Load lessons into Director personality
        lessons = self.journal_reader.get_recent_lessons(
            cfg["journal"]["lessons_on_startup"]
        )
        self.director.lessons = lessons

        # Load last session for continuity
        self.session_store = SessionStore(
            cfg.get("sessions", {}).get("path", "ct1/data/sessions")
        )
        last_session = self.session_store.read_latest()
        self.director.last_session = last_session or ""

    # ── Main pipeline ────────────────────────────────────────────────

    async def _pipeline(self, goal: str, on_event=None,
                        conversation: list[dict] = None) -> dict:
        if conversation is None:
            conversation = []

        def emit(event: str, **data):
            if on_event:
                on_event(event, **data)

        # ── Phase 1: ROUTE ──────────────────────────────────────────
        emit("routing")
        route = await self.specialist.route(goal, conversation=conversation)
        is_code = route in ("ROUTE_DESIGN", "ROUTE_CODE")
        emit("routed", route=route)

        # ── Phase 2: PLAN (code routes only) ────────────────────────
        plan = None
        if is_code:
            plan = await self.specialist.plan(goal, route)
            emit("planned", plan=plan)

        # ── Phase 3: CONSULT (ROUTE_DESIGN only — palette/sections) ──
        # No streaming: specialist collects internally to avoid showing
        # raw think-blocks or JSON fragments to the user.
        specialist_data = None
        if route == "ROUTE_DESIGN":
            emit("consulting")
            specialist_data = await self.specialist.consult(
                goal, conversation=conversation,
            )
            emit("consulted", data=specialist_data)

        # ── Phase 4: GENERATE (streamed) ──────────────────────────────
        emit("generating")

        def on_token(token, kind):
            emit("token", text=token, kind=kind)

        result = await self.director.generate(
            goal, route,
            specialist_data=specialist_data,
            plan=plan,
            conversation=conversation,
            on_token=on_token,
        )
        draft = result["text"]
        draft_thinking = result.get("thinking", "")
        emit("draft", text=draft, thinking=draft_thinking)

        final_response = draft
        final_thinking = draft_thinking

        # ── Phase 5: VALIDATE (output-type-aware) ────────────────────
        if is_code:
            output_type = plan.get("output_type", "html_page") if plan else "html_page"

            # Programmatic validation (real syntax check, no AI)
            issues = validate_output(draft, output_type)

            # Specialist review only for HTML (2B can't audit Python logic)
            review_result = {"pass": True, "critical_issues": [], "fix_instructions": ""}
            if output_type in ("html_page", "other"):
                review_result = await self.specialist.review(
                    goal, draft, conversation=conversation
                )

            all_issues = list(issues)
            if not review_result["pass"]:
                all_issues.extend(review_result.get("critical_issues", []))

            if all_issues:
                emit("validating", issues=all_issues, review=review_result)
                emit("fixing")

                fix_prompt = (
                    f"Fix ALL these issues in the code:\n"
                    + "\n".join(f"- {i}" for i in all_issues)
                    + (f"\n\n{review_result['fix_instructions']}"
                       if review_result.get("fix_instructions") else "")
                    + f"\n\nOriginal code:\n{draft}"
                )

                def on_fix_token(token, kind):
                    emit("token", text=token, kind=kind)

                fix_result = await self.director.generate(
                    fix_prompt, route,
                    specialist_data=specialist_data,
                    plan=None,  # don't re-plan for fix pass
                    conversation=conversation,
                    on_token=on_fix_token,
                )
                final_response = fix_result["text"]
                final_thinking = fix_result.get("thinking", "")
            else:
                emit("validated", issues=[], review=review_result)

        # ── Phase 6: FORMAT ──────────────────────────────────────────
        output_type = plan.get("output_type", "html_page") if plan else "html_page"
        final_response = clean_response(
            final_response, is_code=is_code, output_type=output_type
        )

        # ── Reflection ───────────────────────────────────────────────
        complexity = plan.get("complexity", "moderate") if plan else "moderate"
        reflection = await self.director.reflect(
            goal, complexity, final_response,
            conversation=conversation,
        )
        self.journal.write(reflection)

        return {
            "response": final_response,
            "thinking": final_thinking,
            "draft": draft,
            "draft_thinking": draft_thinking,
            "route": route,
            "specialist_data": specialist_data,
            "plan": plan,
            "reflection": reflection,
        }

    async def think(self, goal: str, on_event=None,
                    conversation: list[dict] = None) -> dict:
        return await self._pipeline(
            goal, on_event=on_event, conversation=conversation or []
        )

    async def close(self):
        await self.director.close()
        await self.specialist.close()
