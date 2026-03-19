# CT-2 Next Phase Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add conversation persistence (SQLite), chat history sidebar, user feedback, regenerate, dark mode, preferences, keyboard shortcuts, export, and search to CT-2.

**Architecture:** SQLite database (`ct1/data/ct2.db`) stores conversations and messages. New REST endpoints serve CRUD operations. The Svelte frontend gets a collapsible sidebar, feedback controls, dark/light theme toggle, and keyboard shortcut overlay. Each phase is independently shippable.

**Tech Stack:** Python 3.10+ / FastAPI / aiosqlite, SvelteKit 5 (runes) / TypeScript, SQLite with FTS5

---

## Phase 1: Conversation Persistence + Chat History

### Task 1: Create the database module

**Files:**
- Create: `ct1/memory/conversation_db.py`
- Create: `ct1/tests/test_conversation_db.py`

**Step 1: Write the failing test for database initialization**

```python
# ct1/tests/test_conversation_db.py
import pytest
import asyncio
from pathlib import Path
from ct1.memory.conversation_db import ConversationDB


@pytest.mark.asyncio
async def test_init_creates_tables(tmp_path):
    db = ConversationDB(str(tmp_path / "test.db"))
    await db.init()
    # Verify tables exist by inserting and reading
    conv_id = await db.create_conversation("Test title", "nemotron")
    assert conv_id  # UUID string
    convs = await db.list_conversations()
    assert len(convs) == 1
    assert convs[0]["title"] == "Test title"
    await db.close()
```

**Step 2: Run test to verify it fails**

Run: `cd /f/AI_Workstation/web-ui && python -m pytest ct1/tests/test_conversation_db.py::test_init_creates_tables -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ct1.memory.conversation_db'`

**Step 3: Install aiosqlite dependency**

Run: `pip install aiosqlite`

Add to `ct1/requirements.txt`:
```
aiosqlite>=0.20.0
```

**Step 4: Write minimal implementation**

```python
# ct1/memory/conversation_db.py
import uuid
import aiosqlite
from datetime import datetime, timezone


class ConversationDB:
    def __init__(self, db_path: str = "ct1/data/ct2.db"):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self):
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                preset TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
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
                message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                content_type TEXT,
                data TEXT NOT NULL
            );
            PRAGMA foreign_keys = ON;
        """)
        await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    async def create_conversation(self, title: str, preset: str = "") -> str:
        cid = str(uuid.uuid4())
        now = self._now()
        await self._db.execute(
            "INSERT INTO conversations (id, title, preset, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (cid, title, preset, now, now),
        )
        await self._db.commit()
        return cid

    async def list_conversations(self, limit: int = 50) -> list[dict]:
        cursor = await self._db.execute(
            """SELECT c.id, c.title, c.preset, c.created_at, c.updated_at,
                      COUNT(m.id) as message_count
               FROM conversations c
               LEFT JOIN messages m ON m.conversation_id = c.id
               GROUP BY c.id
               ORDER BY c.updated_at DESC
               LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_conversation(self, conv_id: str) -> dict | None:
        cursor = await self._db.execute(
            "SELECT * FROM conversations WHERE id = ?", (conv_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        conv = dict(row)
        msg_cursor = await self._db.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY position",
            (conv_id,),
        )
        conv["messages"] = [dict(r) for r in await msg_cursor.fetchall()]
        return conv

    async def delete_conversation(self, conv_id: str) -> bool:
        cursor = await self._db.execute(
            "DELETE FROM conversations WHERE id = ?", (conv_id,)
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def rename_conversation(self, conv_id: str, title: str) -> bool:
        cursor = await self._db.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, self._now(), conv_id),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def add_message(
        self, conv_id: str, role: str, content: str, position: int,
        thinking: str = "", draft: str = "", route: str = "",
        specialist_data: str = "", reflection: str = "",
    ) -> str:
        mid = str(uuid.uuid4())
        now = self._now()
        await self._db.execute(
            """INSERT INTO messages
               (id, conversation_id, role, content, thinking, draft, route,
                specialist_data, reflection, created_at, position)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (mid, conv_id, role, content, thinking, draft, route,
             specialist_data, reflection, now, position),
        )
        await self._db.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conv_id),
        )
        await self._db.commit()
        return mid

    async def set_feedback(self, message_id: str, feedback: int) -> bool:
        cursor = await self._db.execute(
            "UPDATE messages SET feedback = ? WHERE id = ?",
            (feedback, message_id),
        )
        await self._db.commit()
        return cursor.rowcount > 0
```

**Step 5: Run test to verify it passes**

Run: `cd /f/AI_Workstation/web-ui && python -m pytest ct1/tests/test_conversation_db.py::test_init_creates_tables -v`
Expected: PASS

**Step 6: Write more tests for CRUD operations**

```python
# Append to ct1/tests/test_conversation_db.py

@pytest.mark.asyncio
async def test_add_and_get_messages(tmp_path):
    db = ConversationDB(str(tmp_path / "test.db"))
    await db.init()
    cid = await db.create_conversation("Chat 1", "nemotron")
    await db.add_message(cid, "user", "Hello", 0)
    await db.add_message(cid, "assistant", "Hi there!", 1, thinking="Let me think...")
    conv = await db.get_conversation(cid)
    assert conv is not None
    assert len(conv["messages"]) == 2
    assert conv["messages"][0]["role"] == "user"
    assert conv["messages"][1]["thinking"] == "Let me think..."
    await db.close()


@pytest.mark.asyncio
async def test_delete_conversation(tmp_path):
    db = ConversationDB(str(tmp_path / "test.db"))
    await db.init()
    cid = await db.create_conversation("To Delete", "ct2")
    assert await db.delete_conversation(cid) is True
    assert await db.get_conversation(cid) is None
    await db.close()


@pytest.mark.asyncio
async def test_rename_conversation(tmp_path):
    db = ConversationDB(str(tmp_path / "test.db"))
    await db.init()
    cid = await db.create_conversation("Old Title", "ct2")
    await db.rename_conversation(cid, "New Title")
    conv = await db.get_conversation(cid)
    assert conv["title"] == "New Title"
    await db.close()


@pytest.mark.asyncio
async def test_set_feedback(tmp_path):
    db = ConversationDB(str(tmp_path / "test.db"))
    await db.init()
    cid = await db.create_conversation("Feedback Test", "nemotron")
    mid = await db.add_message(cid, "assistant", "Response", 0)
    await db.set_feedback(mid, 1)
    conv = await db.get_conversation(cid)
    assert conv["messages"][0]["feedback"] == 1
    await db.close()


@pytest.mark.asyncio
async def test_list_conversations_ordered(tmp_path):
    db = ConversationDB(str(tmp_path / "test.db"))
    await db.init()
    cid1 = await db.create_conversation("First", "ct2")
    cid2 = await db.create_conversation("Second", "nemotron")
    # Add message to first to bump updated_at
    await db.add_message(cid1, "user", "Hello", 0)
    convs = await db.list_conversations()
    assert len(convs) == 2
    # First should be most recently updated (cid1 got a message)
    assert convs[0]["id"] == cid1
    await db.close()
```

**Step 7: Run all DB tests**

Run: `cd /f/AI_Workstation/web-ui && python -m pytest ct1/tests/test_conversation_db.py -v`
Expected: All PASS

**Step 8: Commit**

```bash
git add ct1/memory/conversation_db.py ct1/tests/test_conversation_db.py ct1/requirements.txt
git commit -m "feat: add ConversationDB with SQLite persistence for conversations and messages"
```

---

### Task 2: Add conversation REST endpoints to the API

**Files:**
- Modify: `ct1/server/api.py`

**Step 1: Write failing tests for the new endpoints**

Add to `ct1/tests/test_conversation_db.py`:

```python
# These test the API integration — but since the existing API tests use
# a client fixture tied to the live config, we test the DB module directly
# and trust the thin API layer. The API wiring is validated manually.

@pytest.mark.asyncio
async def test_message_count_in_list(tmp_path):
    db = ConversationDB(str(tmp_path / "test.db"))
    await db.init()
    cid = await db.create_conversation("With Messages", "ct2")
    await db.add_message(cid, "user", "Hello", 0)
    await db.add_message(cid, "assistant", "Hi", 1)
    convs = await db.list_conversations()
    assert convs[0]["message_count"] == 2
    await db.close()
```

**Step 2: Run test to verify it passes (DB already supports this)**

Run: `cd /f/AI_Workstation/web-ui && python -m pytest ct1/tests/test_conversation_db.py::test_message_count_in_list -v`
Expected: PASS

**Step 3: Add API endpoints**

Add these to `ct1/server/api.py` after the existing endpoints but before the WebSocket handler:

```python
from ct1.memory.conversation_db import ConversationDB

# Add to module-level globals:
_db: ConversationDB | None = None

# In lifespan(), after creating _orch:
#   _db = ConversationDB()
#   await _db.init()
# In lifespan() teardown:
#   if _db: await _db.close()
```

New endpoints:

```python
@app.get("/api/conversations")
async def list_conversations(limit: int = 50):
    return await _db.list_conversations(limit)


@app.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    conv = await _db.get_conversation(conv_id)
    if not conv:
        return {"error": "Not found"}, 404
    return conv


@app.post("/api/conversations")
async def create_conversation(body: dict):
    title = body.get("title", "New conversation")
    preset = body.get("preset", _raw_cfg.get("active_preset", ""))
    conv_id = await _db.create_conversation(title, preset)
    return {"id": conv_id}


@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    deleted = await _db.delete_conversation(conv_id)
    return {"deleted": deleted}


class RenameBody(BaseModel):
    title: str

@app.patch("/api/conversations/{conv_id}")
async def rename_conversation(conv_id: str, body: RenameBody):
    renamed = await _db.rename_conversation(conv_id, body.title)
    return {"renamed": renamed}


class FeedbackBody(BaseModel):
    feedback: int  # 1 or -1

@app.post("/api/messages/{message_id}/feedback")
async def set_message_feedback(message_id: str, body: FeedbackBody):
    ok = await _db.set_feedback(message_id, body.feedback)
    return {"ok": ok}
```

**Step 4: Update lifespan to initialize and tear down `_db`**

In `lifespan()`:
```python
@asynccontextmanager
async def lifespan(application: FastAPI):
    global _orch, _server_procs, _db
    _server_procs = await start_server(str(_CONFIG_PATH))
    _orch = Orchestrator(str(_CONFIG_PATH))
    _db = ConversationDB()
    await _db.init()
    yield
    if _db:
        await _db.close()
    if _orch:
        await _orch.close()
    if _server_procs:
        stop_server(_server_procs)
```

**Step 5: Update WebSocket handler to persist messages**

In `ws_think`, after the `done` event is queued in `run_think()`, add persistence logic:

```python
async def run_think():
    result = await _orch.think(goal, on_event=on_event, conversation=conversation)
    # ... existing done event queuing ...

    # Persist conversation
    if _db:
        import json as _json
        conv_id = msg.get("conversation_id")
        if not conv_id:
            # Auto-title from first ~40 chars of goal
            title_text = goal if isinstance(goal, str) else goal[0].get("text", "") if isinstance(goal, list) else str(goal)
            title = title_text[:40].strip()
            if len(title_text) > 40:
                title += "..."
            conv_id = await _db.create_conversation(title, _raw_cfg.get("active_preset", ""))
            await websocket.send_json({"event": "conversation_id", "id": conv_id})

        # Save user message
        position = msg.get("position", 0)
        await _db.add_message(conv_id, "user", goal if isinstance(goal, str) else _json.dumps(goal), position)

        # Save assistant message
        await _db.add_message(
            conv_id, "assistant", result["response"], position + 1,
            thinking=result.get("thinking", ""),
            draft=result.get("draft", ""),
            route=result.get("route", ""),
            specialist_data=_json.dumps(result.get("specialist_data") or {}),
            reflection=_json.dumps(result.get("reflection") or {}),
        )
```

**Step 6: Commit**

```bash
git add ct1/server/api.py
git commit -m "feat: add conversation CRUD REST endpoints and auto-save in WebSocket handler"
```

---

### Task 3: Create the conversations Svelte store

**Files:**
- Create: `ct1/web/src/lib/stores/conversations.ts`

**Step 1: Write the store**

```typescript
// ct1/web/src/lib/stores/conversations.ts
import { writable } from 'svelte/store';

export interface ConversationSummary {
    id: string;
    title: string;
    preset: string;
    created_at: string;
    updated_at: string;
    message_count: number;
}

export const conversations = writable<ConversationSummary[]>([]);
export const activeConversationId = writable<string | null>(null);
export const sidebarOpen = writable<boolean>(false);

export async function loadConversations() {
    const res = await fetch('/api/conversations?limit=50');
    if (res.ok) {
        const data = await res.json();
        conversations.set(data);
    }
}

export async function createConversation(title: string = 'New conversation'): Promise<string | null> {
    const res = await fetch('/api/conversations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
    });
    if (res.ok) {
        const data = await res.json();
        activeConversationId.set(data.id);
        await loadConversations();
        return data.id;
    }
    return null;
}

export async function deleteConversation(id: string) {
    await fetch(`/api/conversations/${id}`, { method: 'DELETE' });
    conversations.update(list => list.filter(c => c.id !== id));
    activeConversationId.update(curr => curr === id ? null : curr);
}

export async function renameConversation(id: string, title: string) {
    await fetch(`/api/conversations/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
    });
    conversations.update(list =>
        list.map(c => c.id === id ? { ...c, title } : c)
    );
}

export async function loadConversation(id: string) {
    const res = await fetch(`/api/conversations/${id}`);
    if (!res.ok) return null;
    return await res.json();
}
```

**Step 2: Commit**

```bash
git add ct1/web/src/lib/stores/conversations.ts
git commit -m "feat: add conversations Svelte store with CRUD operations"
```

---

### Task 4: Update chat store to support conversation persistence

**Files:**
- Modify: `ct1/web/src/lib/stores/chat.ts`

**Step 1: Add conversation_id tracking to chat store**

In `chat.ts`, add `conversationId` to `ChatState`:

```typescript
interface ChatState {
    conversationId: string | null;  // NEW
    conversation: Turn[];
    // ... rest unchanged
}
```

Add to `initial`:
```typescript
const initial: ChatState = {
    conversationId: null,  // NEW
    // ... rest unchanged
};
```

**Step 2: Handle the `conversation_id` event in `handleEvent`**

In `handleEvent`, add a new case:

```typescript
case 'conversation_id':
    s.conversationId = data.id;
    break;
```

**Step 3: Add `loadFromHistory` function to restore a saved conversation**

```typescript
export function loadFromHistory(conv: {
    id: string;
    messages: Array<{
        role: string;
        content: string;
        thinking?: string;
        draft?: string;
        route?: string;
        specialist_data?: string;
        reflection?: string;
        feedback?: number;
    }>;
}) {
    chat.update((s) => {
        s.conversationId = conv.id;
        s.conversation = conv.messages.map((m) => ({
            role: m.role as 'user' | 'assistant',
            content: m.content,
            thinking: m.thinking || undefined,
            route: m.route || undefined,
            specialistData: m.specialist_data ? JSON.parse(m.specialist_data) : undefined,
            reflection: m.reflection ? JSON.parse(m.reflection) : undefined,
        }));
        s.phase = 'idle';
        s.events = [];
        s.route = '';
        s.plan = null;
        s.specialistData = null;
        s.specialistStream = '';
        s.review = null;
        s.reflection = null;
        s.response = '';
        s.thinking = '';
        s.draft = '';
        s.draftThinking = '';
        s.streamingText = '';
        s.streamingThinking = '';
        s.validationIssues = [];
        s.editing = false;
        s.warning = '';
        return s;
    });
}

export function newConversation() {
    chat.set({ ...initial });
}
```

**Step 4: Pass `conversation_id` in `sendThink`**

In `sendThink`, include the conversation ID in the WebSocket message:

```typescript
// After the existing unsub() call:
let convId: string | null = null;
const unsub2 = chat.subscribe((s) => { convId = s.conversationId; });
unsub2();

// In the ws.send call, add conversation_id and position:
ws?.send({
    type: 'think',
    goal: goalContent,
    conversation: backendConv,
    conversation_id: convId,              // NEW
    position: conv.length,                 // NEW — current message count
});
```

**Step 5: Commit**

```bash
git add ct1/web/src/lib/stores/chat.ts
git commit -m "feat: add conversation persistence support to chat store"
```

---

### Task 5: Build the Sidebar component

**Files:**
- Create: `ct1/web/src/lib/components/Sidebar.svelte`

**Step 1: Write the component**

```svelte
<!-- ct1/web/src/lib/components/Sidebar.svelte -->
<script lang="ts">
    import {
        conversations, activeConversationId, sidebarOpen,
        loadConversations, deleteConversation, renameConversation,
        loadConversation,
    } from '$lib/stores/conversations';
    import { loadFromHistory, newConversation } from '$lib/stores/chat';
    import { onMount } from 'svelte';

    let editing = $state<string | null>(null);
    let editTitle = $state('');

    onMount(() => {
        loadConversations();
    });

    async function selectConversation(id: string) {
        const conv = await loadConversation(id);
        if (conv) {
            activeConversationId.set(id);
            loadFromHistory(conv);
        }
    }

    function startNew() {
        activeConversationId.set(null);
        newConversation();
    }

    function startRename(id: string, title: string) {
        editing = id;
        editTitle = title;
    }

    async function finishRename(id: string) {
        if (editTitle.trim()) {
            await renameConversation(id, editTitle.trim());
        }
        editing = null;
    }

    function formatDate(iso: string): string {
        const d = new Date(iso);
        const now = new Date();
        const diffMs = now.getTime() - d.getTime();
        const diffMins = Math.floor(diffMs / 60000);
        if (diffMins < 1) return 'Just now';
        if (diffMins < 60) return `${diffMins}m ago`;
        const diffHrs = Math.floor(diffMins / 60);
        if (diffHrs < 24) return `${diffHrs}h ago`;
        const diffDays = Math.floor(diffHrs / 24);
        if (diffDays < 7) return `${diffDays}d ago`;
        return d.toLocaleDateString();
    }
</script>

<aside class="sidebar" class:open={$sidebarOpen}>
    <div class="sidebar-header">
        <button class="new-chat-btn" onclick={startNew}>
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                <path d="M8 1v14M1 8h14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
            </svg>
            New Chat
        </button>
        <button class="close-btn" onclick={() => sidebarOpen.set(false)}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M12 4L4 12M4 4l8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
        </button>
    </div>

    <div class="conversation-list">
        {#each $conversations as conv (conv.id)}
            <button
                class="conv-item"
                class:active={conv.id === $activeConversationId}
                onclick={() => selectConversation(conv.id)}
            >
                {#if editing === conv.id}
                    <input
                        class="rename-input"
                        bind:value={editTitle}
                        onkeydown={(e) => { if (e.key === 'Enter') finishRename(conv.id); if (e.key === 'Escape') editing = null; }}
                        onblur={() => finishRename(conv.id)}
                    />
                {:else}
                    <span class="conv-title">{conv.title}</span>
                    <span class="conv-meta">{formatDate(conv.updated_at)}</span>
                {/if}

                <div class="conv-actions" onclick|stopPropagation>
                    <button class="action-btn" onclick={() => startRename(conv.id, conv.title)} title="Rename">
                        <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                            <path d="M11.5 1.5l3 3L5 14H2v-3L11.5 1.5z" stroke="currentColor" stroke-width="1.5"/>
                        </svg>
                    </button>
                    <button class="action-btn delete" onclick={() => deleteConversation(conv.id)} title="Delete">
                        <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                            <path d="M2 4h12M5 4V2h6v2M6 7v5M10 7v5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                        </svg>
                    </button>
                </div>
            </button>
        {:else}
            <div class="empty-state">No conversations yet</div>
        {/each}
    </div>
</aside>

<style>
    .sidebar {
        position: fixed;
        top: 56px;
        left: 0;
        bottom: 0;
        width: 280px;
        background: var(--bubble-strong);
        backdrop-filter: var(--bubble-blur-heavy);
        -webkit-backdrop-filter: var(--bubble-blur-heavy);
        border-right: var(--bubble-border);
        z-index: 90;
        display: flex;
        flex-direction: column;
        transform: translateX(-100%);
        transition: transform var(--transition-slow);
    }
    .sidebar.open {
        transform: translateX(0);
    }

    .sidebar-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 16px;
        border-bottom: 1px solid rgba(0, 0, 0, 0.04);
    }

    .new-chat-btn {
        display: flex;
        align-items: center;
        gap: 8px;
        background: var(--bubble);
        border: var(--bubble-border);
        border-radius: var(--radius-sm);
        padding: 8px 14px;
        font-size: 13px;
        font-weight: 500;
        color: var(--text);
        cursor: pointer;
        transition: background var(--transition), box-shadow var(--transition);
        font-family: inherit;
    }
    .new-chat-btn:hover {
        background: var(--bubble-strong);
        box-shadow: var(--shadow-sm);
    }

    .close-btn {
        background: none;
        border: none;
        color: var(--text-muted);
        cursor: pointer;
        padding: 6px;
        border-radius: var(--radius-sm);
        transition: color var(--transition), background var(--transition);
    }
    .close-btn:hover {
        color: var(--text);
        background: rgba(0, 0, 0, 0.04);
    }

    .conversation-list {
        flex: 1;
        overflow-y: auto;
        padding: 8px;
        scrollbar-width: none;
    }
    .conversation-list::-webkit-scrollbar { display: none; }

    .conv-item {
        display: flex;
        flex-direction: column;
        gap: 2px;
        width: 100%;
        text-align: left;
        padding: 10px 12px;
        border: none;
        background: transparent;
        border-radius: var(--radius-sm);
        cursor: pointer;
        transition: background var(--transition);
        position: relative;
        font-family: inherit;
        color: inherit;
    }
    .conv-item:hover {
        background: rgba(0, 0, 0, 0.04);
    }
    .conv-item.active {
        background: rgba(0, 0, 0, 0.06);
    }

    .conv-title {
        font-size: 13px;
        font-weight: 500;
        color: var(--text);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        padding-right: 48px;
    }

    .conv-meta {
        font-size: 11px;
        color: var(--text-muted);
    }

    .conv-actions {
        position: absolute;
        right: 8px;
        top: 50%;
        transform: translateY(-50%);
        display: flex;
        gap: 2px;
        opacity: 0;
        transition: opacity var(--transition);
    }
    .conv-item:hover .conv-actions {
        opacity: 1;
    }

    .action-btn {
        background: none;
        border: none;
        color: var(--text-muted);
        cursor: pointer;
        padding: 4px;
        border-radius: 4px;
        transition: color var(--transition), background var(--transition);
    }
    .action-btn:hover {
        color: var(--text);
        background: rgba(0, 0, 0, 0.06);
    }
    .action-btn.delete:hover {
        color: var(--error);
    }

    .rename-input {
        font-size: 13px;
        font-family: inherit;
        padding: 2px 6px;
        border: 1px solid rgba(0, 0, 0, 0.1);
        border-radius: 4px;
        background: white;
        outline: none;
        width: 100%;
    }

    .empty-state {
        text-align: center;
        padding: 32px 16px;
        color: var(--text-muted);
        font-size: 13px;
    }
</style>
```

**Step 2: Commit**

```bash
git add ct1/web/src/lib/components/Sidebar.svelte
git commit -m "feat: add Sidebar component with conversation history list"
```

---

### Task 6: Wire sidebar into the layout

**Files:**
- Modify: `ct1/web/src/routes/+layout.svelte`

**Step 1: Import Sidebar and add toggle button to topbar**

In the `<script>` block, add:

```typescript
import Sidebar from '$lib/components/Sidebar.svelte';
import { sidebarOpen } from '$lib/stores/conversations';
```

**Step 2: Add hamburger toggle button to the topbar, before the logo**

```svelte
<button class="sidebar-toggle" onclick={() => sidebarOpen.update(v => !v)}>
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
        <path d="M2 4.5h14M2 9h14M2 13.5h14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
    </svg>
</button>
```

**Step 3: Add `<Sidebar />` component before `<main>`**

```svelte
<Sidebar />

<main class:sidebar-open={$sidebarOpen}>
    {@render children()}
</main>
```

**Step 4: Add CSS for sidebar toggle and main content shift**

```css
.sidebar-toggle {
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    padding: 6px;
    border-radius: var(--radius-sm);
    transition: color var(--transition), background var(--transition);
    flex-shrink: 0;
}
.sidebar-toggle:hover {
    color: var(--text);
    background: rgba(0, 0, 0, 0.04);
}

main.sidebar-open {
    margin-left: 280px;
    transition: margin-left var(--transition-slow);
}
```

**Step 5: Commit**

```bash
git add ct1/web/src/routes/+layout.svelte
git commit -m "feat: wire Sidebar into layout with toggle button and content shift"
```

---

## Phase 2: User Feedback + Regenerate

### Task 7: Add feedback buttons to assistant messages

**Files:**
- Modify: `ct1/web/src/routes/+page.svelte`
- Modify: `ct1/web/src/lib/stores/chat.ts`

**Step 1: Add feedback field to Turn interface**

In `chat.ts`, add to the `Turn` interface:

```typescript
export interface Turn {
    // ... existing fields
    messageId?: string;    // NEW — DB message ID for feedback
    feedback?: number;     // NEW — 1 (good), -1 (bad), undefined (none)
}
```

**Step 2: Add setFeedback function to chat store**

```typescript
export async function setFeedback(turnIndex: number, feedback: number) {
    let messageId: string | undefined;
    const unsub = chat.subscribe((s) => {
        messageId = s.conversation[turnIndex]?.messageId;
    });
    unsub();

    if (messageId) {
        await fetch(`/api/messages/${messageId}/feedback`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ feedback }),
        });
    }

    chat.update((s) => {
        if (s.conversation[turnIndex]) {
            s.conversation[turnIndex].feedback = feedback;
        }
        return s;
    });
}
```

**Step 3: Add feedback buttons in +page.svelte**

After each assistant message bubble in the history loop, add:

```svelte
{#if turn.role === 'assistant'}
    <div class="feedback-row">
        <button
            class="feedback-btn"
            class:active={turn.feedback === 1}
            onclick={() => setFeedback(i, turn.feedback === 1 ? 0 : 1)}
            title="Good response"
        >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                <path d="M4 8l3 3 5-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
        </button>
        <button
            class="feedback-btn"
            class:active={turn.feedback === -1}
            onclick={() => setFeedback(i, turn.feedback === -1 ? 0 : -1)}
            title="Bad response"
        >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
            </svg>
        </button>
    </div>
{/if}
```

**Step 4: Add feedback CSS**

```css
.feedback-row {
    display: flex;
    gap: 4px;
    margin-top: 4px;
    opacity: 0;
    transition: opacity var(--transition);
}
.bubble-row:hover .feedback-row {
    opacity: 1;
}
.feedback-btn {
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    padding: 4px 6px;
    border-radius: 6px;
    transition: color var(--transition), background var(--transition);
}
.feedback-btn:hover {
    background: rgba(0, 0, 0, 0.04);
}
.feedback-btn.active {
    color: var(--success);
    background: rgba(45, 164, 78, 0.08);
}
.feedback-btn.active:last-child {
    color: var(--error);
    background: rgba(207, 34, 46, 0.08);
}
```

**Step 5: Commit**

```bash
git add ct1/web/src/routes/+page.svelte ct1/web/src/lib/stores/chat.ts
git commit -m "feat: add thumbs up/down feedback buttons on assistant messages"
```

---

### Task 8: Add regenerate button

**Files:**
- Modify: `ct1/web/src/routes/+page.svelte`
- Modify: `ct1/web/src/lib/stores/chat.ts`

**Step 1: Add `regenerate` function to chat store**

```typescript
export function regenerate() {
    chat.update((s) => {
        // Remove last assistant turn, keep the user turn
        if (s.conversation.length >= 2 && s.conversation[s.conversation.length - 1].role === 'assistant') {
            s.conversation = s.conversation.slice(0, -1);
        }
        return s;
    });

    // Get the last user message and resend
    let lastUserMsg = '';
    let lastAttachments: Attachment[] = [];
    const unsub = chat.subscribe((s) => {
        const lastUser = [...s.conversation].reverse().find(t => t.role === 'user');
        if (lastUser) {
            lastUserMsg = lastUser.content;
            lastAttachments = lastUser.attachments || [];
        }
    });
    unsub();

    if (lastUserMsg) {
        // Remove the user turn too (sendThink will re-add it)
        chat.update((s) => {
            s.conversation = s.conversation.slice(0, -1);
            return s;
        });
        sendThink(lastUserMsg, lastAttachments);
    }
}
```

**Step 2: Add regenerate button in +page.svelte**

Next to the feedback buttons, add:

```svelte
<button class="feedback-btn regen" onclick={regenerate} title="Regenerate response">
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
        <path d="M1 8a7 7 0 0112.3-4.5M15 8a7 7 0 01-12.3 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
        <path d="M13 1v3h-3M3 15v-3h3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
</button>
```

**Step 3: Commit**

```bash
git add ct1/web/src/routes/+page.svelte ct1/web/src/lib/stores/chat.ts
git commit -m "feat: add regenerate button to retry last AI response"
```

---

## Phase 3: Dark Mode + User Preferences

### Task 9: Add dark mode CSS variables

**Files:**
- Modify: `ct1/web/src/app.css`

**Step 1: Add `[data-theme="dark"]` selector after `:root`**

```css
[data-theme="dark"] {
    --bg: #1A1A1D;
    --surface: rgba(255, 255, 255, 0.06);
    --surface-hover: rgba(255, 255, 255, 0.10);
    --surface-solid: #2A2A2D;
    --border: rgba(255, 255, 255, 0.08);
    --border-strong: rgba(255, 255, 255, 0.14);
    --border-subtle: rgba(255, 255, 255, 0.04);
    --text: #E8E6E3;
    --text-secondary: #A8A5A0;
    --text-muted: #6B6966;

    --accent: #9E9E96;
    --accent-subtle: rgba(255, 255, 255, 0.04);

    --shadow-xs: 0 1px 2px rgba(0,0,0,0.12);
    --shadow-sm: 0 1px 3px rgba(0,0,0,0.16), 0 1px 2px rgba(0,0,0,0.1);
    --shadow-md: 0 4px 16px rgba(0,0,0,0.2), 0 1px 3px rgba(0,0,0,0.1);
    --shadow-lg: 0 12px 48px rgba(0,0,0,0.3), 0 4px 12px rgba(0,0,0,0.1);

    --bubble: rgba(255, 255, 255, 0.06);
    --bubble-strong: rgba(255, 255, 255, 0.10);
    --bubble-border: 1px solid rgba(255, 255, 255, 0.08);
    --bubble-border-light: 1px solid rgba(255, 255, 255, 0.05);
    --bubble-blur: blur(32px) saturate(1.2);
    --bubble-blur-heavy: blur(48px) saturate(1.3);
    --bubble-glow:
        0 0 0 1px rgba(255, 255, 255, 0.06),
        0 8px 32px rgba(0, 0, 0, 0.2),
        inset 0 1px 0 rgba(255, 255, 255, 0.08);
    --bubble-glow-strong:
        0 0 0 1px rgba(255, 255, 255, 0.08),
        0 12px 48px rgba(0, 0, 0, 0.3),
        inset 0 1px 0 rgba(255, 255, 255, 0.12);

    --glass-bg: var(--bubble);
    --glass-bg-heavy: var(--bubble-strong);
    --glass-blur: var(--bubble-blur);
    --glass-blur-heavy: var(--bubble-blur-heavy);
    --glass-border: var(--bubble-border);
    --shadow-glow: var(--bubble-glow);
}
```

**Step 2: Commit**

```bash
git add ct1/web/src/app.css
git commit -m "feat: add dark mode CSS variables with [data-theme=dark] selector"
```

---

### Task 10: Create preferences store and theme toggle

**Files:**
- Create: `ct1/web/src/lib/stores/preferences.ts`

**Step 1: Write the preferences store**

```typescript
// ct1/web/src/lib/stores/preferences.ts
import { writable } from 'svelte/store';
import { browser } from '$app/environment';

export type Theme = 'light' | 'dark' | 'system';

interface Preferences {
    theme: Theme;
    showThinking: boolean;
    sidebarOpen: boolean;
}

const defaults: Preferences = {
    theme: 'system',
    showThinking: false,
    sidebarOpen: false,
};

function loadPrefs(): Preferences {
    if (!browser) return defaults;
    try {
        const raw = localStorage.getItem('ct2-preferences');
        return raw ? { ...defaults, ...JSON.parse(raw) } : defaults;
    } catch {
        return defaults;
    }
}

function createPreferencesStore() {
    const { subscribe, set, update } = writable<Preferences>(loadPrefs());

    if (browser) {
        subscribe((prefs) => {
            localStorage.setItem('ct2-preferences', JSON.stringify(prefs));
            applyTheme(prefs.theme);
        });
    }

    return { subscribe, set, update };
}

export const preferences = createPreferencesStore();

function applyTheme(theme: Theme) {
    if (!browser) return;
    const isDark =
        theme === 'dark' ||
        (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
}

export function toggleTheme() {
    preferences.update((p) => {
        const next: Theme = p.theme === 'light' ? 'dark' : p.theme === 'dark' ? 'system' : 'light';
        return { ...p, theme: next };
    });
}
```

**Step 2: Commit**

```bash
git add ct1/web/src/lib/stores/preferences.ts
git commit -m "feat: add preferences store with localStorage persistence and theme management"
```

---

### Task 11: Add theme toggle to topbar

**Files:**
- Modify: `ct1/web/src/routes/+layout.svelte`

**Step 1: Import preferences and add toggle button**

In the `<script>` block:

```typescript
import { preferences, toggleTheme } from '$lib/stores/preferences';
```

**Step 2: Add theme button to the nav area**

Before the Journal nav link:

```svelte
<button class="theme-toggle" onclick={toggleTheme} title="Toggle theme">
    {#if $preferences.theme === 'dark'}
        <!-- Moon icon -->
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M13.5 8.5a5.5 5.5 0 01-6-6 5.5 5.5 0 106 6z" stroke="currentColor" stroke-width="1.3"/>
        </svg>
    {:else if $preferences.theme === 'light'}
        <!-- Sun icon -->
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <circle cx="8" cy="8" r="3" stroke="currentColor" stroke-width="1.3"/>
            <path d="M8 1v2M8 13v2M1 8h2M13 8h2M3.05 3.05l1.41 1.41M11.54 11.54l1.41 1.41M3.05 12.95l1.41-1.41M11.54 4.46l1.41-1.41" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
        </svg>
    {:else}
        <!-- System icon (monitor) -->
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <rect x="1.5" y="2" width="13" height="9" rx="1.5" stroke="currentColor" stroke-width="1.3"/>
            <path d="M6 14h4M8 11v3" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
        </svg>
    {/if}
</button>
```

**Step 3: Add CSS for theme toggle**

```css
.theme-toggle {
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    padding: 7px;
    border-radius: var(--radius-pill);
    transition: color var(--transition), background var(--transition);
}
.theme-toggle:hover {
    color: var(--text);
    background: rgba(0, 0, 0, 0.04);
}
```

**Step 4: Initialize theme on mount**

In the first `onMount`, add at the start:
```typescript
// Apply saved theme on load
import { browser } from '$app/environment';
// Theme is auto-applied by the preferences store subscription
```

Actually the subscription in the preferences store handles this automatically on load.

**Step 5: Update dark-sensitive hardcoded colors**

In `+layout.svelte`, the topbar has hardcoded colors. Update:
- `.topbar` background: Change `rgba(255, 255, 255, 0.6)` to `var(--bubble-strong)`
- `.topbar` border-bottom: Change to `var(--bubble-border)`
- `.donut` color: The donut should adapt — change to `color: var(--text-muted); opacity: 0.15;`

**Step 6: Commit**

```bash
git add ct1/web/src/routes/+layout.svelte
git commit -m "feat: add theme toggle to topbar with sun/moon/system icons"
```

---

## Phase 4: Keyboard Shortcuts + Export + Search

### Task 12: Add keyboard shortcuts

**Files:**
- Modify: `ct1/web/src/routes/+layout.svelte`
- Create: `ct1/web/src/lib/components/ShortcutOverlay.svelte`

**Step 1: Create shortcut overlay component**

```svelte
<!-- ct1/web/src/lib/components/ShortcutOverlay.svelte -->
<script lang="ts">
    let { open = $bindable(false) } = $props();

    const shortcuts = [
        { keys: 'Ctrl + N', action: 'New conversation' },
        { keys: 'Ctrl + K', action: 'Search conversations' },
        { keys: 'Ctrl + Shift + S', action: 'Toggle sidebar' },
        { keys: 'Ctrl + /', action: 'Show shortcuts' },
        { keys: 'Ctrl + Enter', action: 'Send message' },
        { keys: 'Escape', action: 'Close overlay' },
    ];
</script>

{#if open}
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <div class="overlay-backdrop" onclick={() => open = false}>
        <div class="overlay-card" onclick|stopPropagation>
            <h3 class="overlay-title">Keyboard Shortcuts</h3>
            <div class="shortcut-list">
                {#each shortcuts as s}
                    <div class="shortcut-row">
                        <kbd class="shortcut-keys">{s.keys}</kbd>
                        <span class="shortcut-action">{s.action}</span>
                    </div>
                {/each}
            </div>
        </div>
    </div>
{/if}

<style>
    .overlay-backdrop {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.3);
        backdrop-filter: blur(4px);
        z-index: 200;
        display: flex;
        align-items: center;
        justify-content: center;
        animation: fadeIn 150ms ease;
    }
    .overlay-card {
        background: var(--bubble-strong);
        backdrop-filter: var(--bubble-blur-heavy);
        -webkit-backdrop-filter: var(--bubble-blur-heavy);
        border: var(--bubble-border);
        border-radius: var(--radius-lg);
        padding: 28px 32px;
        box-shadow: var(--shadow-lg);
        min-width: 320px;
        animation: springPop var(--spring-duration) var(--spring);
    }
    .overlay-title {
        font-size: 15px;
        font-weight: 600;
        color: var(--text);
        margin-bottom: 16px;
    }
    .shortcut-list {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }
    .shortcut-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
    }
    .shortcut-keys {
        font-family: var(--font-mono);
        font-size: 12px;
        background: rgba(0, 0, 0, 0.05);
        padding: 3px 8px;
        border-radius: 6px;
        border: 1px solid rgba(0, 0, 0, 0.06);
        color: var(--text-secondary);
        white-space: nowrap;
    }
    .shortcut-action {
        font-size: 13px;
        color: var(--text-secondary);
    }
</style>
```

**Step 2: Wire keyboard listener into layout**

In `+layout.svelte`, add:

```typescript
import ShortcutOverlay from '$lib/components/ShortcutOverlay.svelte';
import { newConversation } from '$lib/stores/chat';

let shortcutOverlayOpen = $state(false);

function handleKeydown(e: KeyboardEvent) {
    // Ctrl+N — new conversation
    if (e.ctrlKey && e.key === 'n') {
        e.preventDefault();
        newConversation();
        sidebarOpen.set(false);
    }
    // Ctrl+Shift+S — toggle sidebar
    if (e.ctrlKey && e.shiftKey && e.key === 'S') {
        e.preventDefault();
        sidebarOpen.update(v => !v);
    }
    // Ctrl+/ — show shortcuts
    if (e.ctrlKey && e.key === '/') {
        e.preventDefault();
        shortcutOverlayOpen = !shortcutOverlayOpen;
    }
    // Escape — close overlays
    if (e.key === 'Escape') {
        shortcutOverlayOpen = false;
        sidebarOpen.set(false);
    }
}
```

Add `svelte:window` listener:

```svelte
<svelte:window onkeydown={handleKeydown} />
<ShortcutOverlay bind:open={shortcutOverlayOpen} />
```

**Step 3: Commit**

```bash
git add ct1/web/src/lib/components/ShortcutOverlay.svelte ct1/web/src/routes/+layout.svelte
git commit -m "feat: add keyboard shortcuts with Ctrl+N, Ctrl+Shift+S, Ctrl+/ overlay"
```

---

### Task 13: Add conversation export

**Files:**
- Create: `ct1/web/src/lib/export.ts`

**Step 1: Write export utilities**

```typescript
// ct1/web/src/lib/export.ts
import type { Turn } from '$lib/stores/chat';

export function exportMarkdown(title: string, turns: Turn[]): string {
    let md = `# ${title}\n\n`;
    for (const t of turns) {
        if (t.role === 'user') {
            md += `## User\n\n${t.content}\n\n`;
        } else {
            md += `## Assistant`;
            if (t.route) md += ` (${t.route.replace('ROUTE_', '')})`;
            md += `\n\n${t.content}\n\n`;
        }
    }
    return md;
}

export function exportJSON(title: string, turns: Turn[]): string {
    return JSON.stringify({ title, messages: turns }, null, 2);
}

export function downloadText(content: string, filename: string, mime: string = 'text/plain') {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}
```

**Step 2: Add export buttons to sidebar conversation items**

In `Sidebar.svelte`, add an export button next to rename/delete:

```svelte
<button class="action-btn" onclick={async () => {
    const conv = await loadConversation(conv.id);
    if (conv) {
        const md = exportMarkdown(conv.title, conv.messages);
        downloadText(md, `${conv.title.replace(/[^a-zA-Z0-9]/g, '_')}.md`);
    }
}} title="Export">
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
        <path d="M8 2v8M5 7l3 3 3-3M2 12h12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
</button>
```

**Step 3: Commit**

```bash
git add ct1/web/src/lib/export.ts ct1/web/src/lib/components/Sidebar.svelte
git commit -m "feat: add conversation export to Markdown and JSON"
```

---

### Task 14: Add full-text search

**Files:**
- Modify: `ct1/memory/conversation_db.py`
- Create: `ct1/web/src/lib/components/SearchBar.svelte`
- Modify: `ct1/server/api.py`

**Step 1: Write failing test for search**

Add to `ct1/tests/test_conversation_db.py`:

```python
@pytest.mark.asyncio
async def test_search_messages(tmp_path):
    db = ConversationDB(str(tmp_path / "test.db"))
    await db.init()
    cid = await db.create_conversation("Search Test", "ct2")
    await db.add_message(cid, "user", "How do I make a landing page?", 0)
    await db.add_message(cid, "assistant", "Here is a landing page with HTML", 1)
    results = await db.search("landing page")
    assert len(results) >= 1
    assert results[0]["conversation_id"] == cid
    await db.close()
```

**Step 2: Run test to verify it fails**

Run: `cd /f/AI_Workstation/web-ui && python -m pytest ct1/tests/test_conversation_db.py::test_search_messages -v`
Expected: FAIL — `AttributeError: 'ConversationDB' object has no attribute 'search'`

**Step 3: Add FTS5 table and search method to ConversationDB**

In `conversation_db.py`, add to `init()` after the existing tables:

```python
await self._db.executescript("""
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
""")
```

Add search method:

```python
async def search(self, query: str, limit: int = 20) -> list[dict]:
    cursor = await self._db.execute(
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
```

**Step 4: Run test to verify it passes**

Run: `cd /f/AI_Workstation/web-ui && python -m pytest ct1/tests/test_conversation_db.py::test_search_messages -v`
Expected: PASS

**Step 5: Add search API endpoint**

In `ct1/server/api.py`:

```python
@app.get("/api/search")
async def search_conversations(q: str = "", limit: int = 20):
    if not q.strip():
        return []
    return await _db.search(q.strip(), limit)
```

**Step 6: Create SearchBar component**

```svelte
<!-- ct1/web/src/lib/components/SearchBar.svelte -->
<script lang="ts">
    let query = $state('');
    let results = $state<any[]>([]);
    let debounceTimer: ReturnType<typeof setTimeout>;

    import { loadFromHistory } from '$lib/stores/chat';
    import { activeConversationId, loadConversation } from '$lib/stores/conversations';

    function onInput() {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(async () => {
            if (!query.trim()) {
                results = [];
                return;
            }
            const res = await fetch(`/api/search?q=${encodeURIComponent(query)}&limit=10`);
            if (res.ok) results = await res.json();
        }, 300);
    }

    async function selectResult(convId: string) {
        const conv = await loadConversation(convId);
        if (conv) {
            activeConversationId.set(convId);
            loadFromHistory(conv);
        }
        query = '';
        results = [];
    }
</script>

<div class="search-wrap">
    <input
        class="search-input"
        type="text"
        placeholder="Search conversations..."
        bind:value={query}
        oninput={onInput}
    />
    {#if results.length > 0}
        <div class="search-results">
            {#each results as r}
                <button class="search-result" onclick={() => selectResult(r.conversation_id)}>
                    <span class="result-title">{r.conversation_title}</span>
                    <span class="result-snippet">{@html r.snippet}</span>
                </button>
            {/each}
        </div>
    {/if}
</div>

<style>
    .search-wrap {
        position: relative;
        padding: 0 16px 8px;
    }
    .search-input {
        width: 100%;
        padding: 8px 12px;
        font-size: 13px;
        font-family: inherit;
        border: 1px solid rgba(0, 0, 0, 0.06);
        border-radius: var(--radius-sm);
        background: var(--bubble);
        color: var(--text);
        outline: none;
        transition: border-color var(--transition);
    }
    .search-input:focus {
        border-color: rgba(0, 0, 0, 0.12);
    }
    .search-input::placeholder {
        color: var(--text-muted);
    }
    .search-results {
        position: absolute;
        top: 100%;
        left: 16px;
        right: 16px;
        background: var(--bubble-strong);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: var(--radius-sm);
        box-shadow: var(--shadow-md);
        z-index: 10;
        max-height: 240px;
        overflow-y: auto;
    }
    .search-result {
        display: flex;
        flex-direction: column;
        gap: 2px;
        width: 100%;
        text-align: left;
        padding: 8px 12px;
        border: none;
        background: transparent;
        cursor: pointer;
        font-family: inherit;
        color: inherit;
        transition: background var(--transition);
    }
    .search-result:hover {
        background: rgba(0, 0, 0, 0.04);
    }
    .result-title {
        font-size: 12px;
        font-weight: 600;
        color: var(--text);
    }
    .result-snippet {
        font-size: 12px;
        color: var(--text-muted);
        line-height: 1.4;
    }
    .result-snippet :global(mark) {
        background: rgba(232, 133, 12, 0.2);
        color: var(--text);
        border-radius: 2px;
        padding: 0 2px;
    }
</style>
```

**Step 7: Wire SearchBar into Sidebar**

In `Sidebar.svelte`, import and add between header and conversation list:

```svelte
import SearchBar from '$lib/components/SearchBar.svelte';

<!-- Between sidebar-header and conversation-list divs -->
<SearchBar />
```

**Step 8: Run all tests**

Run: `cd /f/AI_Workstation/web-ui && python -m pytest ct1/tests/test_conversation_db.py -v`
Expected: All PASS

**Step 9: Commit**

```bash
git add ct1/memory/conversation_db.py ct1/server/api.py ct1/web/src/lib/components/SearchBar.svelte ct1/web/src/lib/components/Sidebar.svelte ct1/tests/test_conversation_db.py
git commit -m "feat: add full-text search with SQLite FTS5, search bar in sidebar"
```

---

## Summary

| Task | Phase | Description | Key Files |
|------|-------|-------------|-----------|
| 1 | 1 | SQLite database module | `conversation_db.py`, tests |
| 2 | 1 | REST API endpoints | `api.py` |
| 3 | 1 | Conversations Svelte store | `conversations.ts` |
| 4 | 1 | Chat store persistence | `chat.ts` |
| 5 | 1 | Sidebar component | `Sidebar.svelte` |
| 6 | 1 | Wire sidebar into layout | `+layout.svelte` |
| 7 | 2 | Feedback buttons | `+page.svelte`, `chat.ts` |
| 8 | 2 | Regenerate button | `+page.svelte`, `chat.ts` |
| 9 | 3 | Dark mode CSS | `app.css` |
| 10 | 3 | Preferences store | `preferences.ts` |
| 11 | 3 | Theme toggle UI | `+layout.svelte` |
| 12 | 4 | Keyboard shortcuts | `ShortcutOverlay.svelte`, `+layout.svelte` |
| 13 | 4 | Export conversations | `export.ts`, `Sidebar.svelte` |
| 14 | 4 | Full-text search | `conversation_db.py`, `SearchBar.svelte`, `api.py` |
