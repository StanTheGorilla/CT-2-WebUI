from pathlib import Path
from datetime import datetime

class SessionStore:
    def __init__(self, sessions_dir: str = "ct2/data/sessions"):
        self.dir = Path(sessions_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def write(self, summary: str) -> None:
        date = datetime.now().strftime("%Y-%m-%d")
        existing = sorted(self.dir.glob(f"{date}_*.txt"))
        idx = 1
        if existing:
            last = existing[-1].stem  # e.g. "2026-03-13_002"
            idx = int(last.split("_")[-1]) + 1
        path = self.dir / f"{date}_{idx:03d}.txt"
        path.write_text(summary, encoding="utf-8")

    def read_latest(self) -> str | None:
        files = sorted(self.dir.glob("*.txt"))
        if not files:
            return None
        return files[-1].read_text(encoding="utf-8").strip()
