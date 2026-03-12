import asyncio
import yaml
from pathlib import Path
from ct1.core.brain import Brain
from ct1.core.mind import Mind
from ct1.core.message_bus import MessageBus, MessageType
from ct1.core.tension_detector import TensionDetector
from ct1.memory.journal import Journal
from ct1.memory.journal_reader import JournalReader

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
        self.minds = {
            "alpha": Mind("alpha", base_url,
                          mc["mind_alpha"]["temperature"],
                          mc["mind_alpha"]["top_p"],
                          mc["mind_alpha"]["top_k"],
                          mc["mind_alpha"]["presence_penalty"],
                          mc["mind_alpha"]["max_tokens"]),
            "beta": Mind("beta", base_url,
                         mc["mind_beta"]["temperature"],
                         mc["mind_beta"]["top_p"],
                         mc["mind_beta"]["top_k"],
                         mc["mind_beta"]["presence_penalty"],
                         mc["mind_beta"]["max_tokens"]),
            "gamma": Mind("gamma", base_url,
                          mc["mind_gamma"]["temperature"],
                          mc["mind_gamma"]["top_p"],
                          mc["mind_gamma"]["top_k"],
                          mc["mind_gamma"]["presence_penalty"],
                          mc["mind_gamma"]["max_tokens"]),
        }
        self.bus = MessageBus()
        self.tension_detector = TensionDetector()
        self.journal = Journal(cfg["journal"]["path"])
        self.journal_reader = JournalReader(cfg["journal"]["path"])
        self.max_rounds = dc["max_rounds"]
        self.confidence_threshold = dc["confidence_threshold"]

        # Load past lessons into brain memory
        lessons = self.journal_reader.get_recent_lessons(cfg["journal"]["lessons_on_startup"])
        self.brain.lessons = lessons

    async def _deliberate(self, goal: str) -> dict:
        self.bus.clear()
        rounds_data = []

        framed = await self.brain.frame_problem(goal)
        current_question = framed
        rounds_used = 0
        tension_ever_detected = False

        for round_num in range(1, self.max_rounds + 1):
            rounds_used = round_num

            # Parallel broadcast to all 3 minds
            alpha_r, beta_r, gamma_r = await asyncio.gather(
                self.minds["alpha"].think(current_question),
                self.minds["beta"].think(current_question),
                self.minds["gamma"].think(current_question),
            )

            self.bus.post("mind-alpha", "brain", MessageType.RESPONSE, alpha_r,
                          confidence=0.0, round_num=round_num)
            self.bus.post("mind-beta", "brain", MessageType.RESPONSE, beta_r,
                          confidence=0.0, round_num=round_num)
            self.bus.post("mind-gamma", "brain", MessageType.RESPONSE, gamma_r,
                          confidence=0.0, round_num=round_num)

            rounds_data.append({
                "round": round_num,
                "question": current_question,
                "responses": {"alpha": alpha_r, "beta": beta_r, "gamma": gamma_r}
            })

            tension = await self.brain.detect_tension(
                current_question, alpha_r, beta_r, gamma_r
            )

            confident = tension.get("confidence", 0) >= self.confidence_threshold
            agreed = tension.get("agreement", False)

            if confident or agreed or round_num == self.max_rounds:
                break
            else:
                tension_ever_detected = True
                followup = tension.get("followup_question") or current_question
                self.bus.post("brain", "all", MessageType.TENSION,
                              tension.get("tension_description", ""), round_num=round_num)
                current_question = followup

        final_response = await self.brain.synthesize(goal, rounds_data)

        reflection = await self.brain.reflect(goal, rounds_used, final_response)
        reflection["rounds"] = rounds_used
        self.journal.write(reflection)

        return {
            "response": final_response,
            "rounds": rounds_used,
            "tension_detected": tension_ever_detected,
            "reflection": reflection,
            "bus_history": self.bus.to_dict_list(),
        }

    async def think(self, goal: str) -> dict:
        return await self._deliberate(goal)

    async def close(self):
        await self.brain.close()
        for m in self.minds.values():
            await m.close()
