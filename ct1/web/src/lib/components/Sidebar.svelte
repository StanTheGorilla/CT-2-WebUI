<script lang="ts">
    import {
        conversations, activeConversationId, sidebarOpen,
        loadConversations, deleteConversation, renameConversation,
        loadConversation,
    } from '$lib/stores/conversations';
    import { loadFromHistory, newConversation } from '$lib/stores/chat';
    import { exportMarkdown, downloadText } from '$lib/export';
    import { onMount } from 'svelte';

    let renamingId = $state<string | null>(null);
    let renameValue = $state('');
    let renameInput = $state<HTMLInputElement | null>(null);

    onMount(() => {
        loadConversations();
    });

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
        sidebarOpen.set(false);
    }

    async function selectConversation(id: string) {
        const conv = await loadConversation(id);
        if (conv) {
            activeConversationId.set(id);
            loadFromHistory(conv);
        }
        sidebarOpen.set(false);
    }

    function startRename(id: string, currentTitle: string) {
        renamingId = id;
        renameValue = currentTitle;
        // Focus input on next tick
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

    function closeSidebar() {
        sidebarOpen.set(false);
    }
</script>

<aside class="sidebar" class:open={$sidebarOpen}>
    <div class="sidebar-header">
        <button class="new-chat-btn" onclick={startNew}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M8 1v14M1 8h14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
            New Chat
        </button>
        <button class="close-btn" onclick={closeSidebar}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M12 4L4 12M4 4l8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
        </button>
    </div>

    <div class="conversation-list">
        {#if $conversations.length === 0}
            <div class="empty-state">
                <span class="empty-icon">
                    <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
                        <path d="M8 12h16M8 16h10M8 20h13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                        <rect x="4" y="6" width="24" height="20" rx="4" stroke="currentColor" stroke-width="1.5" fill="none"/>
                    </svg>
                </span>
                <p>No conversations yet</p>
                <span class="empty-hint">Start a new chat to begin</span>
            </div>
        {:else}
            {#each $conversations as conv (conv.id)}
                <button
                    class="conversation-item"
                    class:active={$activeConversationId === conv.id}
                    onclick={() => selectConversation(conv.id)}
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
                        <span class="conv-title">{conv.title}</span>
                        <span class="conv-time">{formatRelativeDate(conv.updated_at)}</span>
                    {/if}

                    <div class="conv-actions" onclick={(e) => e.stopPropagation()}>
                        <button
                            class="action-btn"
                            title="Rename"
                            onclick={() => startRename(conv.id, conv.title)}
                        >
                            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                                <path d="M11.5 1.5l3 3L5 14H2v-3L11.5 1.5z" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
                            </svg>
                        </button>
                        <button
                            class="action-btn"
                            title="Export"
                            onclick={() => handleExport(conv.id, conv.title)}
                        >
                            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                                <path d="M8 2v8M5 7l3 3 3-3M3 12h10" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
                            </svg>
                        </button>
                        <button
                            class="action-btn delete"
                            title="Delete"
                            onclick={() => handleDelete(conv.id)}
                        >
                            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                                <path d="M2 4h12M5 4V2h6v2M6 7v5M10 7v5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
                            </svg>
                        </button>
                    </div>
                </button>
            {/each}
        {/if}
    </div>
</aside>

<style>
    .sidebar {
        position: fixed;
        top: 56px;
        left: 0;
        bottom: 0;
        width: 280px;
        z-index: 90;
        background: var(--bubble-strong);
        backdrop-filter: var(--bubble-blur-heavy);
        -webkit-backdrop-filter: var(--bubble-blur-heavy);
        border-right: var(--bubble-border);
        box-shadow: var(--bubble-glow);
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
        gap: 8px;
        padding: 16px;
        border-bottom: 1px solid rgba(0, 0, 0, 0.05);
    }

    .new-chat-btn {
        flex: 1;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        padding: 9px 16px;
        background: var(--bubble);
        border: var(--bubble-border);
        border-radius: var(--radius-sm);
        color: var(--text);
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        transition: background var(--transition), box-shadow var(--transition);
    }
    .new-chat-btn:hover {
        background: var(--bubble-strong);
        box-shadow: var(--shadow-sm);
    }

    .close-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 32px;
        height: 32px;
        background: none;
        border: none;
        border-radius: var(--radius-sm);
        color: var(--text-muted);
        cursor: pointer;
        transition: color var(--transition), background var(--transition);
        flex-shrink: 0;
    }
    .close-btn:hover {
        color: var(--text);
        background: rgba(0, 0, 0, 0.05);
    }

    .conversation-list {
        flex: 1;
        overflow-y: auto;
        padding: 8px;
    }

    .empty-state {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 48px 24px;
        text-align: center;
        gap: 8px;
    }
    .empty-icon {
        color: var(--text-muted);
        opacity: 0.4;
        margin-bottom: 4px;
    }
    .empty-state p {
        font-size: 14px;
        font-weight: 500;
        color: var(--text-secondary);
    }
    .empty-hint {
        font-size: 12px;
        color: var(--text-muted);
    }

    .conversation-item {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 4px;
        width: 100%;
        padding: 10px 12px;
        background: none;
        border: none;
        border-radius: var(--radius-sm);
        cursor: pointer;
        text-align: left;
        position: relative;
        transition: background var(--transition);
    }
    .conversation-item:hover {
        background: rgba(0, 0, 0, 0.04);
    }
    .conversation-item.active {
        background: rgba(0, 0, 0, 0.06);
    }

    .conv-title {
        flex: 1;
        font-size: 13px;
        font-weight: 500;
        color: var(--text);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        min-width: 0;
    }

    .conv-time {
        font-size: 11px;
        color: var(--text-muted);
        flex-shrink: 0;
    }

    .conv-actions {
        display: none;
        align-items: center;
        gap: 2px;
        position: absolute;
        right: 8px;
        top: 50%;
        transform: translateY(-50%);
        background: var(--bubble-strong);
        border-radius: 6px;
        padding: 2px;
    }
    .conversation-item:hover .conv-actions {
        display: flex;
    }

    .action-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 26px;
        height: 26px;
        background: none;
        border: none;
        border-radius: 5px;
        color: var(--text-muted);
        cursor: pointer;
        transition: color var(--transition), background var(--transition);
    }
    .action-btn:hover {
        color: var(--text);
        background: rgba(0, 0, 0, 0.06);
    }
    .action-btn.delete:hover {
        color: var(--error);
        background: rgba(207, 34, 46, 0.06);
    }

    .rename-input {
        flex: 1;
        font-size: 13px;
        font-weight: 500;
        color: var(--text);
        background: rgba(255, 255, 255, 0.6);
        border: 1px solid rgba(0, 0, 0, 0.1);
        border-radius: 6px;
        padding: 3px 8px;
        outline: none;
        min-width: 0;
        font-family: var(--font-body);
    }
    .rename-input:focus {
        border-color: rgba(0, 0, 0, 0.2);
        box-shadow: 0 0 0 2px rgba(0, 0, 0, 0.04);
    }
</style>
