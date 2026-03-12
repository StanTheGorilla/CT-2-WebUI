import json
from pathlib import Path
from ct1.memory.journal import Journal

class PreferenceExtractor:
    def __init__(self, journal_dir: str = "ct1/data/journals"):
        self.journal = Journal(journal_dir)

    def extract_pairs(self, min_score_gap: float = 0.3) -> list[dict]:
        entries = self.journal.read_all()
        good = [e for e in entries if e.get("self_score", 0) >= 0.7]
        bad  = [e for e in entries if e.get("self_score", 0) <= 0.4]

        pairs = []
        for g in good:
            for b in bad:
                g_words = set(str(g.get("goal", "")).lower().split())
                b_words = set(str(b.get("goal", "")).lower().split())
                union = g_words | b_words
                if not union:
                    continue
                overlap = len(g_words & b_words) / len(union)
                if overlap >= 0.3:
                    pairs.append({
                        "prompt": g["goal"],
                        "chosen": g["outcome"],
                        "rejected": b["outcome"],
                        "score_gap": g["self_score"] - b["self_score"]
                    })
        return pairs

    def save_dataset(self, output_path: str = "ct1/data/dpo_dataset.jsonl") -> int:
        pairs = self.extract_pairs()
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for p in pairs:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
        return len(pairs)
