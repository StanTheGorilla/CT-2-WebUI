import asyncio
import yaml
from pathlib import Path
from ct1.core.brain import Brain
from ct1.core.mind import Mind
from ct1.core.message_bus import MessageBus, MessageType
from ct1.core.tension_detector import TensionDetector
from ct1.memory.journal import Journal
from ct1.memory.journal_reader import JournalReader
from ct1.memory.session_store import SessionStore

_CONFIG_PATH = Path(__file__).parent.parent.parent / "ct1" / "server" / "model_config.yaml"

class Orchestrator:
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = str(_CONFIG_PATH)

        cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        brain_url = f"http://localhost:{cfg['llama_server']['port']}"
        minds_url = f"http://localhost:{cfg['llama_server_minds']['port']}"
        mc = cfg["models"]
        dc = cfg["deliberation"]

        self.brain = Brain(
            base_url=brain_url,
            temperature=mc["brain"]["temperature"],
            top_p=mc["brain"]["top_p"],
            top_k=mc["brain"]["top_k"],
            presence_penalty=mc["brain"]["presence_penalty"],
            max_tokens=mc["brain"]["max_tokens"],
        )

        def _make_mind(name, key):
            return Mind(name, minds_url,
                        mc[key]["temperature"],
                        mc[key]["top_p"],
                        mc[key]["top_k"],
                        mc[key]["presence_penalty"],
                        mc[key]["max_tokens"],
                        enable_thinking=mc[key].get("enable_thinking", True))

        self.minds = {
            "alpha": _make_mind("alpha", "mind_alpha"),
            "beta":  _make_mind("beta",  "mind_beta"),
            "gamma": _make_mind("gamma", "mind_gamma"),
        }
        self.bus = MessageBus()
        self.tension_detector = TensionDetector()
        self.journal = Journal(cfg["journal"]["path"])
        self.journal_reader = JournalReader(cfg["journal"]["path"])
        self.max_rounds = dc["max_rounds"]
        self.confidence_threshold = dc["confidence_threshold"]
        self.min_turns = dc.get("min_turns", 9)
        self.turn_max_tokens = dc.get("turn_max_tokens", 256)
        self.verbose = False

        lessons = self.journal_reader.get_recent_lessons(cfg["journal"]["lessons_on_startup"])
        self.brain.lessons = lessons

        self.session_store = SessionStore(cfg.get("sessions", {}).get("path", "ct1/data/sessions"))
        last_session = self.session_store.read_latest()
        self.brain.last_session = last_session or ""

    async def _deliberate(self, goal: str, on_event=None,
                           conversation: list[dict] = None) -> dict:
        if conversation is None:
            conversation = []

        def emit(event: str, **data):
            if on_event:
                on_event(event, **data)

        self.bus.clear()

        # ── Phase 1: Intent Extraction ────────────────────────────────────────
        emit("framing")
        intent = await self.brain.extract_intent(goal, conversation=conversation)
        intent["agreed_approach"] = ""          # populated after convergence
        complexity = intent.get("complexity", "moderate")
        emit("framed",
             task_type=intent.get("task_type", "general"),
             what_to_produce=intent.get("what_to_produce", goal),
             requirements=intent.get("requirements", []),
             complexity=complexity)

        # ── Phase 2: Free-Form Deliberation ──────────────────────────────────
        brief = self.brain.write_deliberation_brief(intent)
        dialogue: list[dict] = []
        rounds_used = 0

        # Continuous deliberation — minds converse freely, brain checks convergence
        # only after enough substance has built up (min_turns). Like human thinking:
        # the conversation goes as long as it needs to.
        mind_cycle = ("alpha", "beta", "gamma")
        turn_count = 0

        while True:
            mind_name = mind_cycle[turn_count % 3]
            current_pass = (turn_count // 3) + 1

            if turn_count % 3 == 0:
                emit("round_start", round_num=current_pass)

            text = await self.minds[mind_name].converse(
                brief, dialogue, conversation=conversation,
                complexity=complexity, max_tokens=self.turn_max_tokens
            )
            dialogue.append({"mind": mind_name, "round": current_pass, "text": text})
            emit("mind_turn", name=mind_name, text=text)
            self.bus.post(f"mind-{mind_name}", "brain",
                          MessageType.RESPONSE, text,
                          confidence=0.0, round_num=current_pass)

            turn_count += 1

            # Only check convergence after min_turns, at the end of a full 3-mind cycle
            if turn_count >= self.min_turns and turn_count % 3 == 0:
                convergence = await self.brain.check_convergence(
                    brief, dialogue, conversation=conversation
                )
                if convergence.get("ready_to_execute", False) or current_pass >= self.max_rounds:
                    intent["agreed_approach"] = convergence.get("agreed_approach", "")
                    rounds_used = current_pass
                    emit("converging",
                         confidence=1.0,
                         strongest=convergence.get("agreed_approach", ""))
                    break

                emit("tension",
                     description=convergence.get("reason", ""),
                     followup="")

        # ── Phase 3: Execution ────────────────────────────────────────────────
        emit("synthesizing")
        final_response = await self.brain.synthesize(
            goal, intent, dialogue, conversation=conversation
        )

        # Reflection
        reflection = await self.brain.reflect(
            goal, complexity, rounds_used, final_response,
            conversation=conversation
        )
        reflection["rounds"] = rounds_used
        reflection["_dialogue"] = dialogue
        self.journal.write(reflection)

        return {
            "response": final_response,
            "rounds": rounds_used,
            "complexity": complexity,
            "tension_detected": rounds_used > 1,
            "reflection": reflection,
            "dialogue": dialogue,
            "bus_history": self.bus.to_dict_list(),
        }

    async def think(self, goal: str, on_event=None,
                    conversation: list[dict] = None) -> dict:
        return await self._deliberate(goal, on_event=on_event,
                                      conversation=conversation or [])

    async def close(self):
        await self.brain.close()
        for m in self.minds.values():
            await m.close()
