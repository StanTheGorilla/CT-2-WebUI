import json
import time
from datetime import datetime
from pathlib import Path

class Journal:
    def __init__(self, journal_dir: str = "ct1/data/journals"):
        self.dir = Path(journal_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _active_file(self) -> Path:
        today = datetime.now().strftime("%Y-%m-%d")
        idx = 1
        while True:
            path = self.dir / f"{today}_{idx:03d}.jsonl"
            if not path.exists():
                return path
            # ~200 bytes/entry × 1000 entries = 200 KB cap — single stat() call
            if path.stat().st_size < 200_000:
                return path
            idx += 1

    def write(self, entry: dict):
        entry["_written_at"] = time.time()
        path = self._active_file()
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def read_all(self) -> list[dict]:
        entries = []
        for path in sorted(self.dir.glob("*.jsonl")):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        return entries

    def read_recent(self, n: int = 50) -> list[dict]:
        return self.read_all()[-n:]

    def count(self) -> int:
        return len(self.read_all())
