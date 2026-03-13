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
        base_url = f"http://localhost:{cfg['llama_server']['port']}"
        mc = cfg["models"]
        dc = cfg["deliberation"]

        self.brain = Brain(
            base_url=base_url,
            temperature=mc["brain"]["temperature"],
            top_p=mc["brain"]["top_p"],
            top_k=mc["brain"]["top_k"],
            presence_penalty=mc["brain"]["presence_penalty"],
            max_tokens=mc["brain"]["max_tokens"],
        )

        def _make_mind(name, key):
            return Mind(name, base_url,
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
        rounds_data = []

        # Brain frames with complexity
        emit("framing")
        frame = await self.brain.frame_problem(goal, conversation=conversation)
        question = frame["question"]
        complexity = frame["complexity"]
        emit("framed", text=question, complexity=complexity)

        current_question = question
        rounds_used = 0
        tension_ever_detected = False
        tension_summary = ""

        for round_num in range(1, self.max_rounds + 1):
            rounds_used = round_num
            emit("round_start", round_num=round_num)

            # Parallel broadcast to all 3 minds with complexity
            alpha_r, beta_r, gamma_r = await asyncio.gather(
                self.minds["alpha"].think(current_question, complexity=complexity, conversation=conversation),
                self.minds["beta"].think(current_question, complexity=complexity, conversation=conversation),
                self.minds["gamma"].think(current_question, complexity=complexity, conversation=conversation),
            )

            emit("mind_response", name="alpha", response=alpha_r)
            emit("mind_response", name="beta",  response=beta_r)
            emit("mind_response", name="gamma", response=gamma_r)

            # Post conclusions to bus
            self.bus.post("mind-alpha", "brain", MessageType.RESPONSE,
                          alpha_r["conclusion"], confidence=0.0, round_num=round_num)
            self.bus.post("mind-beta", "brain", MessageType.RESPONSE,
                          beta_r["conclusion"], confidence=0.0, round_num=round_num)
            self.bus.post("mind-gamma", "brain", MessageType.RESPONSE,
                          gamma_r["conclusion"], confidence=0.0, round_num=round_num)

            rounds_data.append({
                "round": round_num,
                "question": current_question,
                "responses": {"alpha": alpha_r, "beta": beta_r, "gamma": gamma_r}
            })

            # Brain analyzes tension using conclusions
            tension = await self.brain.detect_tension(
                current_question,
                alpha_r["conclusion"],
                beta_r["conclusion"],
                gamma_r["conclusion"],
                conversation=conversation,
            )

            confident = tension.get("confidence", 0) >= self.confidence_threshold
            agreed = tension.get("agreement", False)

            if confident or agreed or round_num == self.max_rounds:
                strongest = tension.get("strongest_voice", "")
                conf = tension.get("confidence", 0.0)
                if tension_ever_detected:
                    tension_summary = f"After {rounds_used} rounds of deliberation, tension resolved. Strongest reasoning from {strongest}. Confidence: {conf:.2f}."
                else:
                    tension_summary = f"All three perspectives converge. Strongest reasoning from {strongest}. Confidence: {conf:.2f}."
                emit("converging", confidence=conf, strongest=strongest)
                break
            else:
                tension_ever_detected = True
                desc = tension.get("tension_description", "")
                followup = tension.get("followup_question") or current_question
                emit("tension", description=desc, followup=followup)
                self.bus.post("brain", "all", MessageType.TENSION, desc, round_num=round_num)
                current_question = followup

        # Evidence-based synthesis
        emit("synthesizing")
        final_response = await self.brain.synthesize(goal, rounds_data, tension_summary,
                                                      conversation=conversation)

        # Reflection with complexity
        reflection = await self.brain.reflect(goal, complexity, rounds_used, final_response,
                                               conversation=conversation)
        reflection["rounds"] = rounds_used
        # Store full reasoning traces in journal entry
        reflection["_reasoning_traces"] = {
            name: [rd["responses"][name]["reasoning"] for rd in rounds_data]
            for name in ("alpha", "beta", "gamma")
        }
        self.journal.write(reflection)

        return {
            "response": final_response,
            "rounds": rounds_used,
            "complexity": complexity,
            "tension_detected": tension_ever_detected,
            "reflection": reflection,
            "rounds_data": rounds_data,
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
