import uuid
import aiosqlite
from pathlib import Path
from datetime import datetime, timezone


class ConversationDB:
    """SQLite-backed storage for conversations and messages."""

    def __init__(self, db_path: str = "ct1/data/ct2.db"):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Create connection, create tables, enable foreign keys."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                preset TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL
                    REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                thinking TEXT,
                draft TEXT,
                route TEXT,
                specialist_data TEXT,
                reflection TEXT,
                feedback INTEGER,
                created_at TEXT NOT NULL,
                position INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS attachments (
                id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL
                    REFERENCES messages(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                content_type TEXT,
                data TEXT NOT NULL
            );
            """
        )
        await self._conn.commit()

        await self._conn.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                content,
                content=messages,
                content_rowid=rowid
            );

            CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content);
            END;

            CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.rowid, old.content);
            END;
            """
        )
        await self._conn.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def create_conversation(
        self, title: str, preset: str | None = None
    ) -> str:
        """Create a new conversation, returns its UUID."""
        conv_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "INSERT INTO conversations (id, title, preset, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (conv_id, title, preset, now, now),
        )
        await self._conn.commit()
        return conv_id

    async def list_conversations(self, limit: int = 50) -> list[dict]:
        """List conversations ordered by updated_at DESC, with message_count."""
        cursor = await self._conn.execute(
            """
            SELECT c.id, c.title, c.preset, c.created_at, c.updated_at,
                   COUNT(m.id) AS message_count
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            GROUP BY c.id
            ORDER BY c.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "preset": row["preset"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "message_count": row["message_count"],
            }
            for row in rows
        ]

    async def get_conversation(self, conv_id: str) -> dict | None:
        """Get a conversation with its messages ordered by position."""
        cursor = await self._conn.execute(
            "SELECT id, title, preset, created_at, updated_at "
            "FROM conversations WHERE id = ?",
            (conv_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        conv = {
            "id": row["id"],
            "title": row["title"],
            "preset": row["preset"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

        msg_cursor = await self._conn.execute(
            "SELECT id, role, content, thinking, draft, route, "
            "specialist_data, reflection, feedback, created_at, position "
            "FROM messages WHERE conversation_id = ? ORDER BY position",
            (conv_id,),
        )
        msg_rows = await msg_cursor.fetchall()
        conv["messages"] = [
            {
                "id": m["id"],
                "role": m["role"],
                "content": m["content"],
                "thinking": m["thinking"],
                "draft": m["draft"],
                "route": m["route"],
                "specialist_data": m["specialist_data"],
                "reflection": m["reflection"],
                "feedback": m["feedback"],
                "created_at": m["created_at"],
                "position": m["position"],
            }
            for m in msg_rows
        ]
        return conv

    async def delete_conversation(self, conv_id: str) -> bool:
        """Delete a conversation and its messages. Returns True if it existed."""
        cursor = await self._conn.execute(
            "DELETE FROM conversations WHERE id = ?", (conv_id,)
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def rename_conversation(self, conv_id: str, title: str) -> bool:
        """Rename a conversation. Returns True if it existed."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, now, conv_id),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def add_message(
        self,
        conv_id: str,
        role: str,
        content: str,
        position: int,
        thinking: str = "",
        draft: str = "",
        route: str = "",
        specialist_data: str = "",
        reflection: str = "",
    ) -> str:
        """Add a message to a conversation. Returns the message UUID.
        Also bumps the conversation's updated_at timestamp."""
        msg_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "INSERT INTO messages "
            "(id, conversation_id, role, content, thinking, draft, route, "
            "specialist_data, reflection, feedback, created_at, position) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
            (
                msg_id,
                conv_id,
                role,
                content,
                thinking,
                draft,
                route,
                specialist_data,
                reflection,
                now,
                position,
            ),
        )
        await self._conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conv_id),
        )
        await self._conn.commit()
        return msg_id

    async def search(self, query: str, limit: int = 20) -> list[dict]:
        cursor = await self._conn.execute(
            """SELECT m.id, m.conversation_id, m.role, m.content,
                      c.title as conversation_title,
                      snippet(messages_fts, 0, '<mark>', '</mark>', '...', 32) as snippet
               FROM messages_fts
               JOIN messages m ON m.rowid = messages_fts.rowid
               JOIN conversations c ON c.id = m.conversation_id
               WHERE messages_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (query, limit),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def set_feedback(self, message_id: str, feedback: int | None) -> bool:
        """Set feedback on a message (1=good, -1=bad, None=clear).
        Returns True if the message existed."""
        cursor = await self._conn.execute(
            "UPDATE messages SET feedback = ? WHERE id = ?",
            (feedback, message_id),
        )
        await self._conn.commit()
        return cursor.rowcount > 0
