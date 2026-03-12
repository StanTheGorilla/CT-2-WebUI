from ct1.memory.journal import Journal

class JournalReader:
    def __init__(self, journal_dir: str = "ct1/data/journals"):
        self.journal = Journal(journal_dir)

    def get_recent_lessons(self, n: int = 10) -> list[str]:
        entries = self.journal.read_recent(n * 3)
        lessons = []
        for e in reversed(entries):
            lesson = e.get("lesson", "")
            if lesson and lesson != "reflection parse failed":
                lessons.append(lesson)
            if len(lessons) >= n:
                break
        return list(reversed(lessons))

    def get_stats(self) -> dict:
        entries = self.journal.read_all()
        if not entries:
            return {"total": 0}
        avg_score = sum(e.get("self_score", 0.5) for e in entries) / len(entries)
        avg_rounds = sum(e.get("rounds", 1) for e in entries) / len(entries)
        mind_useful = {"alpha": 0, "beta": 0, "gamma": 0}
        for e in entries:
            for mind, data in e.get("mind_contributions", {}).items():
                if isinstance(data, dict) and data.get("useful"):
                    mind_useful[mind] = mind_useful.get(mind, 0) + 1
        return {
            "total": len(entries),
            "avg_self_score": round(avg_score, 3),
            "avg_rounds": round(avg_rounds, 2),
            "mind_useful_counts": mind_useful
        }
