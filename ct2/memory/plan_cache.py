"""
PlanCache — SQLite-backed execution plan cache for skipping deliberation.

Each cache entry maps an "intent signature" (normalized keywords + output type)
to a compact execution plan that tells the orchestrator how to handle similar
future requests directly — without multi-voice deliberation.
"""

import json
import re
import sqlite3
import time
from pathlib import Path


class PlanCache:
    """Fast-path lookup for known task patterns.

    When the orchestrator sees a goal whose intent signature matches a cached
    plan, it skips the extract_intent → 3-voice deliberation → convergence
    cycle and goes straight to generation.
    """

    def __init__(self, db_path: str = "ct2/data/plan_cache.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    # ── DB lifecycle ────────────────────────────────────────────────

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                intent_sig TEXT NOT NULL UNIQUE,
                task_type TEXT NOT NULL DEFAULT 'direct',
                output_type TEXT DEFAULT '',
                complexity TEXT DEFAULT 'moderate',
                template_hint TEXT DEFAULT '',
                success_count INTEGER DEFAULT 1,
                total_score REAL DEFAULT 0.5,
                last_used REAL DEFAULT 0,
                created_at REAL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_intent_sig ON plans(intent_sig);
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_last_used ON plans(last_used);
        """)
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Intent signature extraction ─────────────────────────────────

    @staticmethod
    def _extract_keywords(text: str, max_words: int = 40) -> list[str]:
        """Extract significant lowercase terms (4+ chars) from a goal."""
        words = re.findall(r'[a-zA-Z]{4,}', text.lower())
        # Remove noise words
        stop = {
            "what", "when", "where", "which", "this", "that", "with", "from",
            "have", "been", "were", "they", "them", "their", "there", "would",
            "about", "should", "could", "these", "those", "into", "over", "your",
            "some", "more", "than", "then", "also", "just", "like", "make",
            "very", "much", "many", "only", "other", "each", "every", "being",
        }
        keywords = [w for w in words if w not in stop][:max_words]
        return keywords

    @staticmethod
    def signature_for(goal: str, output_type: str = "") -> str:
        """Build a deterministic intent signature from a goal string."""
        kw = PlanCache._extract_keywords(goal, 8)
        if not kw:
            kw = ["direct"]
        base = "|".join(sorted(set(kw)))
        if output_type:
            base = f"{base}#{output_type}"
        return base

    # ── Cache operations ────────────────────────────────────────────

    def lookup(self, goal: str, output_type: str = "") -> dict | None:
        """Try to find a cached plan for this goal.

        Returns None if no match or match is too weak.
        """
        sig = self.signature_for(goal, output_type)
        conn = self._get_conn()
        row = conn.execute(
            "SELECT id, task_type, template_hint, complexity, success_count, total_score "
            "FROM plans WHERE intent_sig = ? LIMIT 1",
            (sig,),
        ).fetchone()

        if row is None:
            # Try partial match: check any signature that shares at least 3 keywords
            kw_set = set(self._extract_keywords(goal, 8))
            if len(kw_set) < 2:
                return None
            rows = conn.execute(
                "SELECT id, intent_sig, task_type, template_hint, complexity, "
                "success_count, total_score FROM plans "
                "ORDER BY success_count DESC LIMIT 30"
            ).fetchall()
            best = None
            best_overlap = 0
            for r in rows:
                sig_kw = set(r[1].split("#")[0].split("|"))
                overlap = len(kw_set & sig_kw)
                if overlap >= 3 and overlap > best_overlap:
                    best = r
                    best_overlap = overlap
            if best is None:
                return None
            row = best[1:]  # skip id

        plan = {
            "task_type": row[0] if row[0] else "direct",
            "template_hint": row[1] or "",
            "complexity": row[2] or "moderate",
            "confidence": min(0.95, (row[3] or 1) / max((row[3] or 1) + 2, 1)),
            "score": row[4] or 0.5,
        }
        # Update last_used
        conn.execute(
            "UPDATE plans SET last_used = ? WHERE intent_sig = ?",
            (time.time(), sig),
        )
        conn.commit()
        return plan

    def add(
        self,
        goal: str,
        output_type: str = "",
        task_type: str = "direct",
        complexity: str = "moderate",
        template_hint: str = "",
        score: float = 0.5,
    ) -> None:
        """Insert or update a plan cache entry."""
        sig = self.signature_for(goal, output_type)
        conn = self._get_conn()
        now = time.time()
        conn.execute(
            """INSERT INTO plans
               (intent_sig, task_type, output_type, complexity, template_hint,
                success_count, total_score, last_used, created_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
               ON CONFLICT(intent_sig) DO UPDATE SET
               task_type = excluded.task_type,
               complexity = excluded.complexity,
               template_hint = CASE WHEN excluded.template_hint != ''
                                    THEN excluded.template_hint
                                    ELSE template_hint END,
               success_count = success_count + 1,
               total_score = (total_score + excluded.total_score) / 2,
               last_used = excluded.last_used""",
            (sig, task_type, output_type, complexity, template_hint, score, now, now),
        )
        conn.commit()

    def stats(self) -> dict:
        """Return cache statistics for the UI."""
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0]
        if total == 0:
            return {"entries": 0, "avg_score": 0, "recent": []}
        avg_score = conn.execute("SELECT AVG(total_score) FROM plans").fetchone()[0] or 0
        recent = conn.execute(
            "SELECT intent_sig, task_type, complexity, success_count, "
            "ROUND(total_score, 2) as score "
            "FROM plans ORDER BY last_used DESC LIMIT 12"
        ).fetchall()
        return {
            "entries": total,
            "avg_score": round(avg_score, 2),
            "recent": [
                {
                    "sig": r[0],
                    "task_type": r[1],
                    "complexity": r[2],
                    "count": r[3],
                    "score": r[4],
                }
                for r in recent
            ],
        }

    def clear(self) -> int:
        """Delete all cached plans. Returns number removed."""
        conn = self._get_conn()
        count = conn.execute("DELETE FROM plans").rowcount
        conn.commit()
        return count

    def prune(self, max_entries: int = 200) -> int:
        """Remove oldest entries if over max_entries."""
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0]
        if total <= max_entries:
            return 0
        excess = total - max_entries
        conn.execute(
            "DELETE FROM plans WHERE id IN "
            "(SELECT id FROM plans ORDER BY last_used ASC LIMIT ?)",
            (excess,),
        )
        conn.commit()
        return excess
