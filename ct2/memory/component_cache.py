"""Component cache: stores high-scoring HTML outputs for reuse.

High-scoring outputs (reflection >= 0.85 or user thumbs-up) get cached.
The specialist can reference cached components during the CONSULT phase
to produce better plans and design data.
"""
import uuid
import re
import aiosqlite
from pathlib import Path
from datetime import datetime, timezone


class ComponentCache:
    def __init__(self, db_path: str = "ct2/data/ct2.db"):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS component_cache (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                tags TEXT NOT NULL,
                html_snippet TEXT NOT NULL,
                score REAL NOT NULL,
                source_goal TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_cache_category
                ON component_cache(category);
            CREATE INDEX IF NOT EXISTS idx_cache_score
                ON component_cache(score DESC);
            """
        )
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def save_component(
        self,
        category: str,
        tags: list[str],
        html: str,
        score: float,
        goal: str = "",
    ) -> str:
        comp_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "INSERT INTO component_cache "
            "(id, category, tags, html_snippet, score, source_goal, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (comp_id, category, ",".join(tags), html, score, goal[:200], now),
        )
        await self._conn.commit()
        return comp_id

    async def search_similar(
        self, keywords: list[str], limit: int = 3
    ) -> list[dict]:
        """Find cached components matching any of the keywords (in tags or category)."""
        if not keywords:
            return []
        # Build OR conditions for tag/category matching
        conditions = []
        params = []
        for kw in keywords[:10]:  # cap to avoid huge queries
            kw_lower = kw.lower().strip()
            if kw_lower:
                conditions.append("(LOWER(tags) LIKE ? OR LOWER(category) LIKE ?)")
                params.extend([f"%{kw_lower}%", f"%{kw_lower}%"])

        if not conditions:
            return []

        where = " OR ".join(conditions)
        cursor = await self._conn.execute(
            f"SELECT id, category, tags, html_snippet, score, source_goal, created_at "
            f"FROM component_cache WHERE {where} "
            f"ORDER BY score DESC LIMIT ?",
            (*params, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def list_all(self, limit: int = 20) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT id, category, tags, score, source_goal, created_at "
            "FROM component_cache ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def delete(self, comp_id: str) -> bool:
        cursor = await self._conn.execute(
            "DELETE FROM component_cache WHERE id = ?", (comp_id,)
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def extract_tags(goal: str, specialist_data: dict | None = None) -> list[str]:
        """Extract searchable tags from goal text and specialist data."""
        tags = set()
        lower = goal.lower()

        # Category keywords
        category_kw = {
            "landing": "landing-page", "portfolio": "portfolio",
            "dashboard": "dashboard", "form": "form",
            "login": "form", "signup": "form",
            "blog": "blog", "store": "store", "shop": "store",
            "admin": "dashboard", "calculator": "component",
            "navbar": "component", "card": "component",
            "hero": "component", "footer": "component",
        }
        for kw, cat in category_kw.items():
            if kw in lower:
                tags.add(cat)

        # Extract nouns/topics from goal (simple word extraction)
        words = re.findall(r'\b[a-z]{3,}\b', lower)
        stop = {"the", "and", "for", "with", "that", "this", "from", "have",
                "are", "was", "been", "will", "can", "make", "create", "build",
                "design", "code", "generate", "write", "page", "website", "app"}
        for w in words:
            if w not in stop:
                tags.add(w)

        # Tags from specialist data
        if specialist_data:
            if specialist_data.get("sections"):
                for s in specialist_data["sections"]:
                    tags.add(s.lower())

        return list(tags)[:15]

    @staticmethod
    def categorize(goal: str, plan: dict | None = None) -> str:
        """Determine category from goal text and plan."""
        if plan and plan.get("output_type"):
            ot = plan["output_type"]
            if ot == "python_script":
                return "python"
            if ot == "javascript":
                return "javascript"

        lower = goal.lower()
        if any(k in lower for k in ("landing", "homepage", "home page")):
            return "landing-page"
        if any(k in lower for k in ("dashboard", "admin", "analytics")):
            return "dashboard"
        if any(k in lower for k in ("portfolio", "resume", "cv")):
            return "portfolio"
        if any(k in lower for k in ("form", "login", "signup", "register")):
            return "form"
        if any(k in lower for k in ("blog", "article", "post")):
            return "blog"
        if any(k in lower for k in ("store", "shop", "ecommerce", "product")):
            return "store"
        return "component"
