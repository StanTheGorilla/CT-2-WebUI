import shutil
from pathlib import Path
from datetime import datetime

class AdapterManager:
    def __init__(self, adapter_dir: str = "ct1/data/adapters"):
        self.dir = Path(adapter_dir)
        self.archive = self.dir / "archive"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.archive.mkdir(parents=True, exist_ok=True)

    def current_version(self, model_name: str) -> str:
        adapters = sorted(self.dir.glob(f"{model_name}_v*.bin"))
        return adapters[-1].name if adapters else "none"

    def _archive_current(self, model_name: str):
        for f in self.dir.glob(f"{model_name}_v*.bin"):
            shutil.move(str(f), str(self.archive / f.name))

    def promote(self, model_name: str, new_adapter_path: str) -> str:
        self._archive_current(model_name)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = self.dir / f"{model_name}_v{ts}.bin"
        shutil.copy(str(new_adapter_path), str(dest))
        return str(dest)

    def rollback(self, model_name: str) -> bool:
        archived = sorted(self.archive.glob(f"{model_name}_v*.bin"))
        current = sorted(self.dir.glob(f"{model_name}_v*.bin"))

        if archived:
            # Restore the most recently archived version
            latest = archived[-1]
            self._archive_current(model_name)
            shutil.copy(str(latest), str(self.dir / latest.name))
            return True
        elif current:
            # No archive but a promoted version exists — nothing to roll back to,
            # but the current version is intact; archive it and keep a copy active
            latest = current[-1]
            shutil.copy(str(latest), str(self.archive / latest.name))
            return True
        else:
            return False
