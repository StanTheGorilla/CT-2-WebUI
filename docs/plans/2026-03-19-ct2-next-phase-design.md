# CT-2 Next Phase Design

**Date:** 2026-03-19
**Status:** Approved
**Scope:** Conversation persistence, feedback loop, dark mode, keyboard shortcuts, export, and search

---

## Phase 1 — Conversation Persistence + Chat History

### Problem
Every page reload or tab switch loses the entire conversation. Users can't reference past conversations or continue where they left off.

### Solution
SQLite database at `ct1/data/ct2.db` with three tables:

```sql
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,        -- UUID
    title TEXT,                 -- auto-generated from first message
    created_at TEXT,
    updated_at TEXT,
    preset TEXT                 -- which model preset was active
);

CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    role TEXT,                  -- 'user' | 'assistant'
    content TEXT,
    thinking TEXT,              -- director thinking (if any)
    draft TEXT,                 -- raw draft before formatting
    route TEXT,                 -- ROUTE_CODE | ROUTE_DESIGN | ROUTE_DIRECT
    specialist_data TEXT,       -- JSON blob (plan, review, etc.)
    reflection TEXT,            -- JSON blob
    created_at TEXT,
    position INTEGER            -- ordering within conversation
);

CREATE TABLE attachments (
    id TEXT PRIMARY KEY,
    message_id TEXT REFERENCES messages(id),
    filename TEXT,
    content_type TEXT,
    data BLOB
);
```

### API Endpoints
- `GET /api/conversations` — list conversations (id, title, updated_at, message_count)
- `GET /api/conversations/:id` — full conversation with messages
- `POST /api/conversations` — create new conversation
- `DELETE /api/conversations/:id` — delete conversation
- `PATCH /api/conversations/:id` — rename conversation

### Frontend
- Collapsible sidebar on the left with conversation list
- "New Chat" button at top
- Click to load a past conversation
- Auto-title from first user message (truncated to ~40 chars)
- Current conversation highlighted
- Sidebar hidden on mobile, toggled via hamburger icon

### Auto-save
- Each message pair (user + assistant) saved immediately after the assistant response completes
- Conversation created on first message send
- `updated_at` bumped on every new message

---

## Phase 2 — User Feedback + Regenerate

### Problem
No way to signal which responses were good/bad. No way to retry a bad response.

### Solution

#### Thumbs Up/Down
- Small thumbs-up and thumbs-down buttons below each assistant message
- Stored in a `feedback` column on the `messages` table (`1`, `-1`, or `NULL`)
- Visual state: neutral (gray), positive (green checkmark), negative (red x)
- Feedback persisted to SQLite immediately on click

#### Regenerate
- "Regenerate" button (refresh icon) next to the feedback buttons
- Removes the last assistant message from the conversation
- Re-sends the same user message through the pipeline
- The old response is kept in a `regenerations` table for potential future analysis

#### Learning Loop (Future)
- `GET /api/feedback/summary` — aggregate feedback stats per route/preset
- Display on settings page: "85% positive on code tasks, 60% on design"
- Informs the user which preset works best for which task type

---

## Phase 3 — Dark Mode + User Preferences

### Problem
No dark mode. No way to persist user preferences like font size or theme.

### Solution

#### CSS Variables
Add a `[data-theme="dark"]` selector to `app.css` with inverted palette:

```css
[data-theme="dark"] {
    --bg: #1A1A1D;
    --text: #E8E6E3;
    --text-secondary: #A8A5A0;
    --text-muted: #6B6966;
    --bubble: rgba(255, 255, 255, 0.06);
    --bubble-strong: rgba(255, 255, 255, 0.10);
    --bubble-border: 1px solid rgba(255, 255, 255, 0.08);
    --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.3);
    /* ... all tokens inverted */
}
```

#### Toggle
- Sun/moon icon in the top nav bar
- Toggles `data-theme` attribute on `<html>`
- Preference saved to `localStorage`
- Respects `prefers-color-scheme` on first visit

#### User Preferences Store
- `localStorage`-backed Svelte store for:
  - `theme`: `'light' | 'dark' | 'system'`
  - `fontSize`: `'small' | 'default' | 'large'`
  - `showThinking`: `boolean` (whether to expand thinking by default)
  - `sidebarOpen`: `boolean`

---

## Phase 4 — Keyboard Shortcuts + Export + Search

### Keyboard Shortcuts
- `Ctrl+N` — new conversation
- `Ctrl+K` — focus search
- `Ctrl+Shift+S` — toggle sidebar
- `Ctrl+/` — show shortcut help overlay
- `Escape` — close any open overlay/panel

### Export
- Export button on each conversation (in sidebar or header)
- Formats: Markdown (`.md`) and JSON (`.json`)
- Markdown format: clean readable transcript with headers, code blocks preserved
- JSON format: full data including thinking, specialist data, metadata

### Search
- SQLite FTS5 virtual table for full-text search across all conversations
- Search bar in sidebar header
- Results show matching conversations with highlighted snippets
- Debounced input (300ms) to avoid excessive queries

```sql
CREATE VIRTUAL TABLE messages_fts USING fts5(
    content,
    content=messages,
    content_rowid=rowid
);
```

---

## Implementation Priority

| Phase | Features | Estimated Complexity |
|-------|----------|---------------------|
| 1 | SQLite + history sidebar | High — new backend module + major UI addition |
| 2 | Feedback + regenerate | Medium — new UI controls + DB columns |
| 3 | Dark mode + preferences | Medium — CSS work + localStorage store |
| 4 | Shortcuts + export + search | Medium — utilities + FTS5 |

Each phase is independently shippable. Phase 1 is the foundation that Phase 2 and 4 depend on. Phase 3 is fully independent.
