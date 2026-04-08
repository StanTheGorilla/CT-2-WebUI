<script lang="ts">
    import {
        conversations, activeConversationId, sidebarOpen,
        loadConversations, deleteConversation, renameConversation,
        loadConversation,
    } from '$lib/stores/conversations';
    import { chat, loadFromHistory, newConversation, setWorkspaceId, setMode } from '$lib/stores/chat';
    import { exportMarkdown, downloadText } from '$lib/export';
    import SearchBar from '$lib/components/SearchBar.svelte';
    import { onMount } from 'svelte';

    let renamingId = $state<string | null>(null);
    let renameValue = $state('');
    let renameInput = $state<HTMLInputElement | null>(null);

    interface Workspace { id: string; name: string; file_count: number; }
    let workspaces = $state<Workspace[]>([]);
    let workspacesCollapsed = $state(false);

    onMount(() => {
        loadConversations();
        loadWorkspaces();
    });

    async function loadWorkspaces() {
        try {
            const res = await fetch('/api/workspaces');
            workspaces = await res.json();
        } catch {
            workspaces = [];
        }
    }

    function openWorkspace(id: string) {
        setWorkspaceId(id);
        setMode('computer');
        sidebarOpen.set(false);
    }

    async function createWorkspace() {
        const name = window.prompt('Workspace name:');
        if (name === null) return;
        try {
            const res = await fetch('/api/workspaces', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: name.trim() }),
            });
            const ws: Workspace = await res.json();
            workspaces = [ws, ...workspaces];
            openWorkspace(ws.id);
        } catch { /* ignore */ }
    }

    function formatRelativeDate(dateStr: string): string {
        const date = new Date(dateStr);
        const now = new Date();
        const diffMs = now.getTime() - date.getTime();
        const diffSec = Math.floor(diffMs / 1000);
        const diffMin = Math.floor(diffSec / 60);
        const diffHour = Math.floor(diffMin / 60);
        const diffDay = Math.floor(diffHour / 24);

        if (diffSec < 60) return 'just now';
        if (diffMin < 60) return `${diffMin}m ago`;
        if (diffHour < 24) return `${diffHour}h ago`;
        if (diffDay < 30) return `${diffDay}d ago`;
        return date.toLocaleDateString();
    }

    function startNew() {
        newConversation();
        activeConversationId.set(null);
        setWorkspaceId(null);
        setMode('chat');
        sidebarOpen.set(false);
    }

    async function selectConversation(id: string) {
        const conv = await loadConversation(id);
        if (conv) {
            activeConversationId.set(id);
            loadFromHistory(conv);
        }
        setWorkspaceId(null);
        setMode('chat');
        sidebarOpen.set(false);
    }

    function startRename(id: string, currentTitle: string) {
        renamingId = id;
        renameValue = currentTitle;
        requestAnimationFrame(() => {
            renameInput?.focus();
            renameInput?.select();
        });
    }

    async function commitRename(id: string) {
        if (renameValue.trim()) {
            await renameConversation(id, renameValue.trim());
        }
        renamingId = null;
        renameValue = '';
    }

    function handleRenameKeydown(e: KeyboardEvent, id: string) {
        if (e.key === 'Enter') {
            commitRename(id);
        } else if (e.key === 'Escape') {
            renamingId = null;
            renameValue = '';
        }
    }

    async function handleDelete(id: string) {
        await deleteConversation(id);
    }

    async function handleExport(id: string, title: string) {
        const conv = await loadConversation(id);
        if (conv && conv.messages) {
            const turns = conv.messages.map((m: any) => ({
                role: m.role,
                content: m.content,
                route: m.route || undefined,
            }));
            const md = exportMarkdown(title, turns);
            const safeTitle = title.replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 50);
            downloadText(md, `${safeTitle}.md`, 'text/markdown');
        }
    }
</script>

<aside class="sidebar" class:open={$sidebarOpen}>
    <div class="sidebar-inner">

        <!-- ── Workspaces ── -->
        <div class="section-header">
            <button class="section-toggle" onclick={() => workspacesCollapsed = !workspacesCollapsed}>
                <svg class="section-chevron" class:collapsed={workspacesCollapsed} width="10" height="10" viewBox="0 0 16 16" fill="none">
                    <path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <span class="section-title">Workspaces</span>
            </button>
            <button class="new-chat-btn" onclick={createWorkspace} title="New workspace">
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                    <path d="M8 2v12M2 8h12" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
                </svg>
            </button>
        </div>

        {#if !workspacesCollapsed}
        <div class="workspace-list">
            {#if workspaces.length === 0}
                <div class="section-empty">No workspaces yet</div>
            {:else}
                {#each workspaces as ws (ws.id)}
                    <div
                        class="conversation-item"
                        class:active={$chat.workspaceId === ws.id}
                        role="button"
                        tabindex="0"
                        onclick={() => openWorkspace(ws.id)}
                        onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') openWorkspace(ws.id); }}
                    >
                        <div class="conv-content">
                            <span class="conv-title">
                                <svg width="11" height="11" viewBox="0 0 16 16" fill="none" style="opacity:0.5;flex-shrink:0;margin-right:5px">
                                    <path d="M2 5V3a1 1 0 011-1h4l2 2h4a1 1 0 011 1v7a1 1 0 01-1 1H3a1 1 0 01-1-1V5z" stroke="currentColor" stroke-width="1.3"/>
                                </svg>
                                {ws.name}
                            </span>
                            <span class="conv-time">{ws.file_count} file{ws.file_count === 1 ? '' : 's'}</span>
                        </div>
                    </div>
                {/each}
            {/if}
        </div>
        {/if}

        <div class="section-divider"></div>

        <!-- ── Chats ── -->
        <div class="section-header">
            <span class="section-title">Chats</span>
            <button class="new-chat-btn" onclick={startNew} title="New conversation">
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                    <path d="M8 2v12M2 8h12" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
                </svg>
            </button>
        </div>

        <SearchBar />

        <div class="conversation-list">
            {#if $conversations.length === 0}
                <div class="empty-state">
                    <p>No conversations yet</p>
                    <span class="empty-hint">Start a new chat to begin</span>
                </div>
            {:else}
                {#each $conversations as conv (conv.id)}
                    <div
                        class="conversation-item"
                        class:active={$activeConversationId === conv.id}
                        role="button"
                        tabindex="0"
                        onclick={() => selectConversation(conv.id)}
                        onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') selectConversation(conv.id); }}
                    >
                        {#if renamingId === conv.id}
                            <input
                                class="rename-input"
                                bind:this={renameInput}
                                bind:value={renameValue}
                                onblur={() => commitRename(conv.id)}
                                onkeydown={(e) => handleRenameKeydown(e, conv.id)}
                                onclick={(e) => e.stopPropagation()}
                            />
                        {:else}
                            <div class="conv-content">
                                <span class="conv-title">{conv.title}</span>
                                <span class="conv-time">{formatRelativeDate(conv.updated_at)}</span>
                            </div>
                        {/if}

                        <div class="conv-actions" onclick={(e) => e.stopPropagation()}>
                            <button class="action-btn" title="Rename" onclick={() => startRename(conv.id, conv.title)}>
                                <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                                    <path d="M11.5 1.5l3 3L5 14H2v-3L11.5 1.5z" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
                                </svg>
                            </button>
                            <button class="action-btn" title="Export" onclick={() => handleExport(conv.id, conv.title)}>
                                <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                                    <path d="M8 2v8M5 7l3 3 3-3M3 12h10" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
                                </svg>
                            </button>
                            <button class="action-btn delete" title="Delete" onclick={() => handleDelete(conv.id)}>
                                <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                                    <path d="M2 4h12M5 4V2.5a.5.5 0 01.5-.5h5a.5.5 0 01.5.5V4M3.5 4l.75 9.5a1 1 0 001 .9h5.5a1 1 0 001-.9L12.5 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
                                    <path d="M6.5 7v4.5M9.5 7v4.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
                                </svg>
                            </button>
                        </div>
                    </div>
                {/each}
            {/if}
        </div>
    </div>
</aside>

<style>
    /* ---- Floating island sidebar ---- */
    .sidebar {
        position: fixed;
        top: 68px;
        left: 12px;
        bottom: 12px;
        width: 280px;
        z-index: 91;
        pointer-events: none;

        transform: translateX(-300px);
        opacity: 0;
        transition:
            transform 250ms cubic-bezier(0.4, 0, 0.2, 1),
            opacity 200ms ease;
    }
    .sidebar.open {
        pointer-events: auto;
        transform: translateX(0);
        opacity: 1;
        transition:
            transform 350ms cubic-bezier(0.22, 1.2, 0.36, 1),
            opacity 150ms ease;
    }

    .sidebar-inner {
        height: 100%;
        display: flex;
        flex-direction: column;
        background: var(--bubble-strong);
        backdrop-filter: var(--bubble-blur-heavy);
        -webkit-backdrop-filter: var(--bubble-blur-heavy);
        border: var(--bubble-border);
        border-radius: 20px;
        box-shadow:
            var(--bubble-glow-strong),
            0 24px 80px rgba(0, 0, 0, 0.08);
        overflow: hidden;
    }

    /* ── Section headers (workspaces / chats) ── */
    .section-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 14px 20px 6px;
    }

    .section-toggle {
        display: flex;
        align-items: center;
        gap: 5px;
        background: none;
        border: none;
        cursor: pointer;
        padding: 0;
        color: inherit;
    }
    .section-toggle:hover .section-title { color: var(--text-secondary); }

    .section-chevron {
        color: var(--text-muted);
        transition: transform 200ms ease;
        flex-shrink: 0;
    }
    .section-chevron.collapsed { transform: rotate(-90deg); }

    .section-title {
        font-size: 11px;
        font-weight: 600;
        color: var(--text-muted);
        letter-spacing: 0.06em;
        text-transform: uppercase;
        transition: color 150ms ease;
    }

    .section-divider {
        height: 1px;
        background: var(--border-subtle);
        margin: 6px 12px;
    }

    /* ── Workspace list (reuses .conversation-item styles) ── */
    .workspace-list {
        padding: 0 8px 4px;
    }

    .section-empty {
        font-size: 12px;
        color: var(--text-muted);
        padding: 8px 12px 10px;
    }

    /* conv-title in workspace rows needs flex for the folder icon */
    .workspace-list .conv-title {
        display: flex;
        align-items: center;
    }

    .new-chat-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 28px;
        height: 28px;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        color: var(--text-secondary);
        cursor: pointer;
        transition: all 200ms ease;
    }
    .new-chat-btn:hover {
        background: var(--surface-hover);
        color: var(--text);
        box-shadow: var(--shadow-sm);
    }

    /* ---- Conversation list ---- */
    .conversation-list {
        flex: 1;
        overflow-y: auto;
        padding: 4px 8px 12px;
        scrollbar-width: none;
    }
    .conversation-list::-webkit-scrollbar {
        display: none;
    }

    .empty-state {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 40px 20px;
        text-align: center;
        gap: 4px;
    }
    .empty-state p {
        font-size: 13px;
        font-weight: 500;
        color: var(--text-secondary);
    }
    .empty-hint {
        font-size: 12px;
        color: var(--text-muted);
    }

    /* ---- Conversation item ---- */
    .conversation-item {
        display: flex;
        align-items: center;
        width: 100%;
        padding: 10px 12px;
        background: none;
        border: none;
        border-radius: 10px;
        cursor: pointer;
        text-align: left;
        position: relative;
        transition: background 150ms ease;
    }
    .conversation-item:hover {
        background: var(--surface);
    }
    .conversation-item.active {
        background: var(--surface-hover);
    }

    .conv-content {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 2px;
        transition: max-width 150ms ease;
    }

    .conv-title {
        font-size: 13px;
        font-weight: 500;
        color: var(--text);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        line-height: 1.3;
        letter-spacing: -0.01em;
    }

    .conv-time {
        font-size: 11px;
        font-weight: 400;
        color: var(--text-muted);
        letter-spacing: 0.01em;
    }

    /* ---- Action buttons ---- */
    .conv-actions {
        display: none;
        align-items: center;
        gap: 1px;
        margin-left: auto;
        flex-shrink: 0;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 2px;
    }
    .conversation-item:hover .conv-actions {
        display: flex;
    }
    .conversation-item:hover .conv-content {
        /* Make room for action buttons by shrinking text */
        max-width: calc(100% - 90px);
    }

    .action-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 24px;
        height: 24px;
        background: none;
        border: none;
        border-radius: 6px;
        color: var(--text-muted);
        cursor: pointer;
        transition: color 150ms ease, background 150ms ease;
    }
    .action-btn:hover {
        color: var(--text);
        background: var(--surface);
    }
    .action-btn.delete:hover {
        color: var(--error);
        background: rgba(207, 34, 46, 0.08);
    }

    /* ---- Rename input ---- */
    .rename-input {
        flex: 1;
        font-size: 13px;
        font-weight: 500;
        color: var(--text);
        background: var(--surface);
        border: 1px solid var(--border-strong);
        border-radius: 8px;
        padding: 4px 10px;
        outline: none;
        min-width: 0;
        font-family: var(--font-body);
        letter-spacing: -0.01em;
    }
    .rename-input:focus {
        border-color: var(--accent);
        box-shadow: 0 0 0 2px rgba(107, 107, 107, 0.1);
    }
</style>
