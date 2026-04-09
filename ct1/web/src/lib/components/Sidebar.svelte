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
    let projectsOpen = $state(true);

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
        newConversation();
        activeConversationId.set(null);
        setWorkspaceId(id);
        setMode('computer');
        sidebarOpen.set(false);
    }

    async function createWorkspace() {
        const name = window.prompt('Project name:');
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

    // ── Time-based grouping ──
    interface ConvGroup {
        label: string;
        items: typeof $conversations;
    }

    let grouped = $derived.by(() => {
        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const yesterday = new Date(today.getTime() - 86_400_000);
        const week = new Date(today.getTime() - 7 * 86_400_000);
        const month = new Date(today.getTime() - 30 * 86_400_000);

        const buckets: Record<string, typeof $conversations> = {
            Today: [], Yesterday: [], 'Previous 7 days': [], 'Previous 30 days': [], Older: [],
        };

        for (const c of $conversations) {
            const d = new Date(c.updated_at);
            if (d >= today) buckets.Today.push(c);
            else if (d >= yesterday) buckets.Yesterday.push(c);
            else if (d >= week) buckets['Previous 7 days'].push(c);
            else if (d >= month) buckets['Previous 30 days'].push(c);
            else buckets.Older.push(c);
        }

        const groups: ConvGroup[] = [];
        for (const [label, items] of Object.entries(buckets)) {
            if (items.length) groups.push({ label, items });
        }
        return groups;
    });

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

    function routeBadge(route: string | null): { label: string; cls: string } | null {
        if (!route || route === 'ROUTE_DIRECT') return null;
        if (route === 'ROUTE_CODE') return { label: 'code', cls: 'badge-code' };
        if (route === 'ROUTE_DESIGN') return { label: 'design', cls: 'badge-design' };
        if (route === 'ROUTE_COMPUTER') return { label: 'computer', cls: 'badge-computer' };
        return null;
    }
</script>

<aside class="sidebar" class:open={$sidebarOpen}>
    <div class="sidebar-inner">

        <!-- ── Top: New Chat + Search ── -->
        <div class="top-area">
            <button class="new-chat" onclick={startNew}>
                <svg width="18" height="18" viewBox="0 0 16 16" fill="none">
                    <path d="M12.5 2.5l1 1L6 11l-2.5.5L4 9l7.5-7.5z" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
                    <path d="M10.5 4.5l1 1" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
                </svg>
                New chat
            </button>

            <SearchBar />
        </div>

        <!-- ── Scrollable body ── -->
        <div class="scroll-area">

            <!-- ── Projects ── -->
            {#if workspaces.length > 0}
                <div class="section-head">
                    <button class="section-toggle" onclick={() => projectsOpen = !projectsOpen}>
                        <svg class="chevron" class:closed={!projectsOpen} width="12" height="12" viewBox="0 0 16 16" fill="none">
                            <path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                        Projects
                    </button>
                    <button class="section-plus" onclick={createWorkspace} title="New project">
                        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                            <path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                        </svg>
                    </button>
                </div>

                {#if projectsOpen}
                    {#each workspaces as ws (ws.id)}
                        <button
                            class="row project-row"
                            class:active={$chat.workspaceId === ws.id}
                            onclick={() => openWorkspace(ws.id)}
                        >
                            <svg class="row-icon" width="16" height="16" viewBox="0 0 16 16" fill="none">
                                <path d="M2 5V3.5A1.5 1.5 0 013.5 2h3.379a1.5 1.5 0 011.06.44l.622.62a1.5 1.5 0 001.06.44H12.5A1.5 1.5 0 0114 5v7.5a1.5 1.5 0 01-1.5 1.5h-9A1.5 1.5 0 012 12.5V5z" stroke="currentColor" stroke-width="1.1"/>
                            </svg>
                            <span class="row-text">{ws.name}</span>
                            {#if ws.file_count > 0}
                                <span class="badge">{ws.file_count}</span>
                            {/if}
                        </button>
                    {/each}
                    <div class="divider"></div>
                {/if}
            {/if}

            <!-- ── Conversations ── -->
            {#if $conversations.length === 0}
                <div class="empty">
                    <p>No conversations yet</p>
                    <span>Start a new chat to begin</span>
                </div>
            {:else}
                {#each grouped as group, gi}
                    <div class="time-group" class:first={gi === 0 && workspaces.length === 0}>
                        <div class="time-label">{group.label}</div>

                        {#each group.items as conv (conv.id)}
                            {@const badge = routeBadge(conv.last_route)}
                            <div
                                class="row conv-row"
                                class:active={$activeConversationId === conv.id}
                                class:renaming={renamingId === conv.id}
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
                                    <span class="row-text" title={conv.title}>{conv.title}</span>
                                {/if}

                                <div class="meta-slot">
                                    {#if badge}
                                        <span class="mode-badge {badge.cls}">{badge.label}</span>
                                    {/if}

                                    <div class="actions">
                                        <button class="act" title="Rename" onclick={(e) => { e.stopPropagation(); startRename(conv.id, conv.title); }}>
                                            <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                                                <path d="M11.5 1.5l3 3L5 14H2v-3L11.5 1.5z" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
                                            </svg>
                                        </button>
                                        <button class="act" title="Export" onclick={(e) => { e.stopPropagation(); handleExport(conv.id, conv.title); }}>
                                            <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                                                <path d="M8 2v8M5 7l3 3 3-3M3 12h10" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
                                            </svg>
                                        </button>
                                        <button class="act del" title="Delete" onclick={(e) => { e.stopPropagation(); handleDelete(conv.id); }}>
                                            <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                                                <path d="M2 4h12M5 4V2.5a.5.5 0 01.5-.5h5a.5.5 0 01.5.5V4M3.5 4l.75 9.5a1 1 0 001 .9h5.5a1 1 0 001-.9L12.5 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
                                                <path d="M6.5 7v4.5M9.5 7v4.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
                                            </svg>
                                        </button>
                                    </div>
                                </div>
                            </div>
                        {/each}
                    </div>
                {/each}
            {/if}
        </div>

        <!-- ── Bottom: create project shortcut ── -->
        {#if workspaces.length === 0}
            <div class="bottom-bar">
                <button class="bottom-link" onclick={createWorkspace}>
                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                        <path d="M2 5V3.5A1.5 1.5 0 013.5 2h3.379a1.5 1.5 0 011.06.44l.622.62a1.5 1.5 0 001.06.44H12.5A1.5 1.5 0 0114 5v7.5a1.5 1.5 0 01-1.5 1.5h-9A1.5 1.5 0 012 12.5V5z" stroke="currentColor" stroke-width="1.1"/>
                    </svg>
                    New project
                </button>
            </div>
        {/if}
    </div>
</aside>

<style>
    /* ═══════════════════════════════════════════════
       Sidebar — floating glass panel
       ═══════════════════════════════════════════════ */
    .sidebar {
        position: fixed;
        top: 64px;
        left: 16px;
        bottom: 16px;
        width: min(352px, calc(100vw - 32px));
        z-index: 91;
        pointer-events: none;
        transform: translateX(calc(-100% - 28px));
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
        position: relative;
        isolation: isolate;
        height: 100%;
        display: flex;
        flex-direction: column;
        background: color-mix(in srgb, var(--surface-solid) 76%, var(--bubble-strong));
        backdrop-filter: var(--bubble-blur-heavy);
        -webkit-backdrop-filter: var(--bubble-blur-heavy);
        border: 1px solid color-mix(in srgb, var(--surface-solid) 34%, var(--border));
        border-radius: 24px;
        box-shadow:
            0 18px 42px rgba(0, 0, 0, 0.08),
            0 6px 16px rgba(0, 0, 0, 0.04),
            inset 0 1px 0 rgba(255, 255, 255, 0.22);
        overflow: hidden;
    }
    .sidebar-inner::before {
        content: none;
    }
    :global([data-theme="dark"]) .sidebar-inner {
        background: rgba(13, 13, 18, 0.88);
        border-color: rgba(255, 255, 255, 0.10);
        box-shadow:
            0 22px 52px rgba(0, 0, 0, 0.42),
            0 8px 20px rgba(0, 0, 0, 0.24),
            inset 0 1px 0 rgba(255, 255, 255, 0.05);
    }

    /* ─── Top: New Chat + Search ─── */
    .top-area {
        position: relative;
        flex-shrink: 0;
        padding: 22px 20px 16px;
        border-bottom: 1px solid var(--border-subtle);
        background: color-mix(in srgb, var(--surface-solid) 18%, transparent);
    }

    .new-chat {
        display: flex;
        align-items: center;
        gap: 10px;
        width: 100%;
        min-height: 48px;
        padding: 0 18px;
        margin-bottom: 16px;
        border: 1px solid var(--border);
        border-radius: 16px;
        background: color-mix(in srgb, var(--surface-solid) 58%, var(--surface));
        color: var(--text);
        font-family: var(--font-body);
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        transition: background 180ms ease, border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease;
        letter-spacing: -0.015em;
        box-shadow: none;
    }
    .new-chat:hover {
        background: var(--surface-hover);
        border-color: var(--border-strong);
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.04);
    }
    .new-chat:active {
        transform: scale(0.98);
    }
    .new-chat svg {
        width: 30px;
        height: 30px;
        padding: 0;
        color: var(--text-muted);
        flex-shrink: 0;
    }

    /* ─── Scrollable body ─── */
    .scroll-area {
        flex: 1;
        overflow-y: auto;
        padding: 8px 12px 24px;
        scrollbar-width: none;
    }
    .scroll-area::-webkit-scrollbar { display: none; }

    /* ─── Section header (Projects) ─── */
    .section-head {
        display: flex;
        align-items: center;
        padding: 10px 10px 8px;
    }

    .section-toggle {
        display: flex;
        align-items: center;
        gap: 8px;
        flex: 1;
        background: none;
        border: none;
        cursor: pointer;
        padding: 0;
        font-family: var(--font-body);
        font-size: 11px;
        font-weight: 600;
        color: var(--text-muted);
        letter-spacing: 0.09em;
        text-transform: uppercase;
        transition: color 150ms ease;
    }
    .section-toggle:hover { color: var(--text-secondary); }

    .chevron {
        color: var(--text-muted);
        transition: transform 200ms ease;
        flex-shrink: 0;
    }
    .chevron.closed { transform: rotate(-90deg); }

    .section-plus {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 26px;
        height: 26px;
        background: none;
        border: none;
        border-radius: 8px;
        color: var(--text-muted);
        cursor: pointer;
        opacity: 0.5;
        transition: all 150ms ease;
    }
    .section-head:hover .section-plus { opacity: 1; }
    .section-plus:hover {
        color: var(--text);
        background: var(--surface);
    }

    /* ─── Shared row style ─── */
    .row {
        display: flex;
        align-items: center;
        gap: 12px;
        width: 100%;
        min-height: 50px;
        padding: 12px 14px;
        border: none;
        border-radius: 14px;
        background: none;
        cursor: pointer;
        text-align: left;
        position: relative;
        overflow: hidden;
        transition: background 150ms ease, box-shadow 150ms ease;
        font-family: var(--font-body);
        margin-bottom: 4px;
        box-shadow: inset 0 0 0 1px transparent;
    }
    .row:hover {
        background: color-mix(in srgb, var(--surface-solid) 46%, var(--surface));
        box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--surface-solid) 18%, transparent);
    }
    .row.active {
        background: color-mix(in srgb, var(--surface-hover) 90%, var(--accent-subtle));
        box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 10%, transparent);
    }
    .row:focus-visible {
        outline: none;
        background: color-mix(in srgb, var(--surface-solid) 46%, var(--surface));
        box-shadow: inset 0 0 0 1px var(--border-strong);
    }
    .row::before {
        content: '';
        position: absolute;
        left: 0;
        top: 50%;
        transform: translateY(-50%);
        width: 3px;
        height: 0;
        background: var(--accent);
        border-radius: 0 2px 2px 0;
        transition: height 150ms ease;
    }
    .row.active::before {
        height: 62%;
        box-shadow: none;
    }

    .row-icon {
        color: var(--text-muted);
        flex-shrink: 0;
        transition: color 150ms ease;
    }
    .row.active .row-icon { color: var(--text-secondary); }

    .row-text {
        flex: 1;
        min-width: 0;
        font-size: 14px;
        font-weight: 550;
        color: var(--text);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        line-height: 1.45;
        letter-spacing: -0.015em;
    }

    .badge {
        font-size: 11px;
        font-weight: 600;
        color: var(--text-muted);
        background: var(--accent-subtle);
        padding: 2px 8px;
        border-radius: 999px;
        flex-shrink: 0;
        border: 1px solid transparent;
    }

    .mode-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 10px;
        font-weight: 600;
        min-width: 0;
        max-width: 100%;
        padding: 4px 8px;
        border-radius: 999px;
        flex-shrink: 0;
        letter-spacing: 0.06em;
        opacity: 0.8;
        text-transform: uppercase;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        transition: opacity 150ms ease, transform 150ms ease;
        border: 1px solid transparent;
        box-shadow: none;
    }
    .badge-code {
        color: rgb(59, 130, 246);
        background: rgba(59, 130, 246, 0.12);
        border-color: transparent;
    }
    .badge-design {
        color: rgb(139, 92, 246);
        background: rgba(139, 92, 246, 0.12);
        border-color: transparent;
    }
    .badge-computer {
        color: rgb(34, 197, 94);
        background: rgba(34, 197, 94, 0.12);
        border-color: transparent;
    }

    /* ─── Divider ─── */
    .divider {
        height: 1px;
        background: var(--border-subtle);
        margin: 12px 10px 6px;
    }

    /* ─── Time groups ─── */
    .time-group {
        margin-top: 6px;
    }
    .time-group:not(.first) {
        margin-top: 16px;
        border-top: 1px solid var(--border-subtle);
        padding-top: 8px;
    }
    .time-group.first {
        margin-top: 0;
    }

    .time-label {
        font-size: 10px;
        font-weight: 700;
        color: var(--text-muted);
        padding: 8px 14px 6px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
    }

    /* ─── Conversation rows ─── */
    .conv-row {
        gap: 12px;
    }

    .project-row {
        background: color-mix(in srgb, var(--accent-subtle) 92%, transparent);
        box-shadow: inset 0 0 0 1px transparent;
    }
    .project-row:hover {
        background: color-mix(in srgb, var(--surface-hover) 90%, var(--accent-subtle));
    }
    .project-row.active {
        background: color-mix(in srgb, var(--surface-hover) 94%, var(--accent-subtle));
    }

    /* ─── Hover action buttons ─── */
    .meta-slot {
        position: relative;
        display: flex;
        align-items: center;
        justify-content: flex-end;
        width: 92px;
        min-width: 92px;
        margin-left: auto;
    }

    .actions {
        position: absolute;
        right: 0;
        top: 50%;
        display: flex;
        align-items: center;
        gap: 1px;
        flex-shrink: 0;
        background: color-mix(in srgb, var(--surface-solid) 78%, var(--surface));
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 2px;
        opacity: 0;
        pointer-events: none;
        transform: translateY(-50%) translateX(6px);
        transition: opacity 150ms ease, transform 150ms ease;
        box-shadow: 0 8px 20px rgba(0, 0, 0, 0.10);
    }
    .conv-row:not(.renaming):hover .actions,
    .conv-row:not(.renaming):focus-within .actions {
        opacity: 1;
        pointer-events: auto;
        transform: translateY(-50%) translateX(0);
    }
    .conv-row:hover .mode-badge,
    .conv-row:focus-within .mode-badge,
    .conv-row.renaming .mode-badge {
        opacity: 0;
        transform: translateY(-2px);
    }

    .act {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 27px;
        height: 27px;
        background: none;
        border: none;
        border-radius: 6px;
        color: var(--text-muted);
        cursor: pointer;
        transition: color 150ms ease, background 150ms ease, transform 150ms ease;
    }
    .act:hover {
        color: var(--text);
        background: var(--surface-hover);
        transform: none;
    }
    .act.del:hover {
        color: var(--error);
        background: rgba(207, 34, 46, 0.08);
    }

    /* ─── Rename ─── */
    .rename-input {
        flex: 1;
        font-size: 14px;
        font-weight: 500;
        color: var(--text);
        background: var(--surface);
        border: 1px solid var(--border-strong);
        border-radius: 8px;
        padding: 4px 12px;
        outline: none;
        min-width: 0;
        font-family: var(--font-body);
        letter-spacing: -0.01em;
    }
    .rename-input:focus {
        border-color: var(--accent);
        box-shadow: 0 0 0 2px rgba(107, 107, 107, 0.1);
    }

    /* ─── Empty state ─── */
    .empty {
        display: flex;
        flex-direction: column;
        align-items: center;
        padding: 48px 24px;
        text-align: center;
        gap: 6px;
    }
    .empty p {
        font-size: 14px;
        font-weight: 500;
        color: var(--text-secondary);
        margin: 0;
    }
    .empty span {
        font-size: 13px;
        color: var(--text-muted);
    }

    /* ─── Bottom bar ─── */
    .bottom-bar {
        flex-shrink: 0;
        padding: 14px 20px 20px;
        border-top: 1px solid var(--border-subtle);
        background: transparent;
    }
    .bottom-link {
        display: flex;
        align-items: center;
        gap: 10px;
        width: 100%;
        padding: 12px 14px;
        border: 1px solid transparent;
        border-radius: 14px;
        background: none;
        color: var(--text-muted);
        font-family: var(--font-body);
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        transition: all 150ms ease;
    }
    .bottom-link:hover {
        color: var(--text-secondary);
        background: color-mix(in srgb, var(--surface-solid) 40%, var(--surface));
        border-color: var(--border);
    }
</style>
