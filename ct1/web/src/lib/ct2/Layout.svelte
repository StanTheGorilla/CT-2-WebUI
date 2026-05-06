<script lang="ts">
    import { goto } from '$app/navigation';
    import { page } from '$app/stores';
    import { onMount } from 'svelte';
    import { chat, newConversation, stopGeneration, setWorkspaceId, setMode } from '$lib/stores/chat';
    import { preferences, toggleTheme } from '$lib/stores/preferences';
    import {
        sidebarOpen,
        conversations,
        loadConversations,
        loadConversation,
        deleteConversation,
        renameConversation,
    } from '$lib/stores/conversations';
    import { loadFromHistory } from '$lib/stores/chat';
    import { modelSwitchCount, notifyModelSwitch, modelSwapping } from '$lib/stores/model';
    import { backgroundTasks, setModelSwapping, clearModelSwapping } from '$lib/stores/backgroundTasks';
    import { fly } from 'svelte/transition';

    let { children } = $props();

    // ── Model switcher state ──────────────────────────────────────
    interface ModelFile { name: string; size_gb: number; thinking: boolean; vision: boolean }
    let activeModel = $state('');
    let modelThinking = $state(false);
    let modelSwitching = $state(false);
    let swapTarget = $state('');       // model being switched TO
    let modelPickerOpen = $state(false);
    let models = $state<ModelFile[]>([]);
    let modelsLoaded = $state(false);

    function shortName(name: string) {
        return name.replace(/\.gguf$/i, '').replace(/[._-][Qq]\d+[_A-Za-z0-9]*$/, '');
    }

    // ── Workspaces ────────────────────────────────────────────────
    interface Workspace { id: string; name: string; file_count: number; }
    let workspaces = $state<Workspace[]>([]);
    let creatingWs = $state(false);
    let newWsName = $state('');
    let newWsInput = $state<HTMLInputElement | null>(null);

    async function loadWorkspaces() {
        try { workspaces = await (await fetch('/api/workspaces')).json(); } catch {}
    }

    async function openWorkspace(id: string) {
        sidebarOpen.set(false);
        try {
            const conv = await fetch(`/api/workspaces/${id}/conversation`).then(r => r.json());
            if (conv?.id) {
                loadFromHistory(conv);
            } else {
                newConversation();
            }
        } catch {
            newConversation();
        }
        setWorkspaceId(id);
        setMode('computer');
        goto('/');
    }

    function startWsCreate() {
        creatingWs = true;
        newWsName = '';
        requestAnimationFrame(() => newWsInput?.focus());
    }

    async function submitWsCreate() {
        const name = newWsName.trim();
        creatingWs = false;
        newWsName = '';
        if (!name) return;
        try {
            const res = await fetch('/api/workspaces', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name }),
            });
            const ws: Workspace = await res.json();
            workspaces = [ws, ...workspaces];
            openWorkspace(ws.id);
        } catch {}
    }

    function cancelWsCreate() { creatingWs = false; newWsName = ''; }

    function handleWsCreateKey(e: KeyboardEvent) {
        if (e.key === 'Enter') submitWsCreate();
        else if (e.key === 'Escape') cancelWsCreate();
    }

    onMount(async () => {
        await Promise.all([loadConversations(), loadWorkspaces()]);
        await fetchActiveModel();
    });

    async function fetchActiveModel() {
        try {
            const res = await fetch('/api/model');
            const data = await res.json();
            activeModel = data.active_model || '';
            modelThinking = data.enable_thinking ?? false;
        } catch {}
    }

    // Sync when settings changes the model
    $effect(() => {
        $modelSwitchCount;
        fetchActiveModel();
    });

    async function openModelPicker() {
        modelPickerOpen = !modelPickerOpen;
        if (modelPickerOpen && !modelsLoaded) {
            try {
                const res = await fetch('/api/models');
                models = (await res.json()).models ?? [];
                modelsLoaded = true;
            } catch {}
        }
    }

    async function selectModel(name: string) {
        if (name === activeModel) { modelPickerOpen = false; return; }
        modelPickerOpen = false;
        modelSwitching = true;
        swapTarget = shortName(name);
        setModelSwapping(shortName(name));
        try {
            const res = await fetch('/api/model/select', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model: name }),
            });
            const data = await res.json();
            if (data.error) throw new Error(data.error);
            activeModel = name;
            modelThinking = data.enable_thinking ?? false;
            modelsLoaded = false;
            notifyModelSwitch();
        } catch {}
        finally {
            modelSwitching = false;
            swapTarget = '';
            clearModelSwapping();
        }
    }

    function closeModelPicker(e: MouseEvent) {
        if (!(e.target as Element)?.closest?.('.c2-model-pill')) modelPickerOpen = false;
    }

    // ── Phase indicator ───────────────────────────────────────────
    const phases = ['routing', 'planning', 'generating', 'polishing', 'validating'];
    const phaseLabels = ['Classify', 'Plan', 'Generate', 'Polish', 'Validate'];
    let isGenerating = $derived(
        $chat.phase !== 'idle' && $chat.phase !== 'done'
    );
    let activePhaseIdx = $derived(phases.indexOf($chat.phase));
    let currentPhaseLabel = $derived(() => {
        const labels: Record<string,string> = {
            routing: 'Classifying', planning: 'Planning', generating: 'Generating',
            polishing: 'Polishing', refining: 'Refining', validating: 'Validating',
            fixing: 'Fixing',
        };
        return labels[$chat.phase] || $chat.phase;
    });

    // ── Sidebar ───────────────────────────────────────────────────
    let sidebarQuery = $state('');

    function groupByDate(convs: { id: string; title: string; updated_at: string }[]) {
        const now = new Date();
        const today = now.toDateString();
        const yesterday = new Date(now.getTime() - 86400000).toDateString();
        const groups: Record<string, typeof convs> = {};
        for (const c of convs) {
            const d = new Date(c.updated_at).toDateString();
            const label = d === today ? 'Today' : d === yesterday ? 'Yesterday' : 'Earlier';
            (groups[label] ??= []).push(c);
        }
        return ['Today', 'Yesterday', 'Earlier']
            .filter(g => groups[g]?.length)
            .map(g => ({ group: g, items: groups[g] }));
    }

    let filteredConvs = $derived(
        $conversations.filter(c =>
            !sidebarQuery || c.title.toLowerCase().includes(sidebarQuery.toLowerCase())
        )
    );
    let groupedConvs = $derived(groupByDate(filteredConvs));

    async function pickConversation(id: string) {
        sidebarOpen.set(false);
        const data = await loadConversation(id);
        if (data) {
            setWorkspaceId(null);
            setMode('chat');
            loadFromHistory(data);
            goto('/');
        }
    }

    function startNew() {
        newConversation();
        sidebarOpen.set(false);
        goto('/');
    }

    let deletingId = $state<string | null>(null);
    let renamingId = $state<string | null>(null);
    let renameValue = $state('');

    // ── Notification bubbles ──────────────────────────────────────
    let dismissedIds = $state(new Set<string>());
    let visibleTasks = $derived($backgroundTasks.filter(t => !dismissedIds.has(t.id)));
    function dismiss(id: string) { dismissedIds = new Set([...dismissedIds, id]); }
    // Clear dismissed ids when a task leaves the store (so re-appearing tasks show again)
    $effect(() => {
        const active = new Set($backgroundTasks.map(t => t.id));
        const pruned = [...dismissedIds].filter(id => active.has(id));
        if (pruned.length !== dismissedIds.size) dismissedIds = new Set(pruned);
    });

    async function doDelete(id: string) {
        deletingId = id;
        await deleteConversation(id);
        deletingId = null;
    }

    function startRename(id: string, current: string) {
        renamingId = id;
        renameValue = current;
    }

    async function commitRename() {
        if (renamingId && renameValue.trim()) {
            await renameConversation(renamingId, renameValue.trim());
        }
        renamingId = null;
    }
</script>

<svelte:window onclick={closeModelPicker} />

<!-- Ambient background layers -->
<div class="c2-shell" aria-hidden="false">
    {#if ($preferences.ct2Bg ?? 'image') !== 'none'}
        <div class="c2-img-bg" aria-hidden="true"></div>
    {/if}
    <div class="c2-ambient" aria-hidden="true"></div>

    <!-- Topbar -->
    <header class="c2-topbar">
        <!-- Left: burger + logo -->
        <div class="c2-tb-left">
            <button
                class="c2-icon-btn"
                class:c2-icon-btn-active={$sidebarOpen}
                onclick={() => sidebarOpen.update(v => !v)}
                aria-label="Conversations"
            >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                    <path d="M3 6h18M3 12h18M3 18h18" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                </svg>
            </button>
            <a href="/" class="c2-logo">
                <span class="c2-logo-text">ct·2</span>
            </a>
        </div>

        <!-- Center: phase indicator or model switcher -->
        <div class="c2-tb-center">
            {#if isGenerating}
                <div class="c2-phase-pill">
                    <span class="c2-pulse-dot"></span>
                    <span class="c2-phase-text">{currentPhaseLabel()}</span>
                    <div class="c2-phase-dots">
                        {#each phaseLabels as _l, i}
                            <span
                                class="c2-phase-seg"
                                class:c2-phase-seg-done={i < activePhaseIdx}
                                class:c2-phase-seg-active={i === activePhaseIdx}
                            ></span>
                        {/each}
                    </div>
                </div>
            {:else}
                <div class="c2-model-pill">
                    <button
                        class="c2-model-btn"
                        class:c2-model-btn-open={modelPickerOpen}
                        onclick={openModelPicker}
                        disabled={modelSwitching}
                    >
                        {#if modelSwitching || $modelSwapping}
                            <span class="c2-spinner"></span>
                            <span class="c2-model-name">Switching to {swapTarget || $modelSwapping || '…'}</span>
                        {:else}
                            <span
                                class="c2-status-dot"
                                class:c2-status-thinking={modelThinking}
                            ></span>
                            {#if activeModel}
                                {@const parts = shortName(activeModel).split(' ')}
                                <span class="c2-model-name">{parts[0]}</span>
                                {#if parts[1]}
                                    <span class="c2-model-size">{parts[1]}</span>
                                {/if}
                                {#if modelThinking}
                                    <span class="c2-think-badge">Thinking</span>
                                {/if}
                            {:else}
                                <span class="c2-model-name c2-muted">No model</span>
                            {/if}
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" class="c2-chevron" class:c2-chevron-open={modelPickerOpen}>
                                <path d="M6 9l6 6 6-6" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
                            </svg>
                        {/if}
                    </button>

                    {#if modelPickerOpen}
                        <div class="c2-model-dropdown">
                            {#if models.length === 0}
                                <div class="c2-dropdown-empty">No models found</div>
                            {:else}
                                {#each models as m}
                                    <button
                                        class="c2-dropdown-item"
                                        class:c2-dropdown-item-active={m.name === activeModel}
                                        onclick={() => selectModel(m.name)}
                                    >
                                        <div class="c2-di-info">
                                            <span class="c2-di-name">{shortName(m.name)}</span>
                                            <div class="c2-di-meta">
                                                <span class="c2-di-badge">{m.size_gb} GB</span>
                                                {#if m.thinking}
                                                    <span class="c2-di-badge c2-di-badge-think">Thinking</span>
                                                {/if}
                                                {#if m.vision}
                                                    <span class="c2-di-badge">Vision</span>
                                                {/if}
                                            </div>
                                        </div>
                                        {#if m.name === activeModel}
                                            <svg class="c2-di-check" width="14" height="14" viewBox="0 0 24 24" fill="none">
                                                <path d="M20 6L9 17l-5-5" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
                                            </svg>
                                        {/if}
                                    </button>
                                {/each}
                            {/if}
                        </div>
                    {/if}
                </div>
            {/if}
        </div>

        <!-- Right: theme toggle, journal, settings -->
        <div class="c2-tb-right">
            <button class="c2-icon-btn" onclick={toggleTheme} aria-label="Toggle theme">
                {#if $preferences.theme === 'dark'}
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
                        <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                {:else}
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
                        <circle cx="12" cy="12" r="5" stroke="currentColor" stroke-width="1.6"/>
                        <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M17.36 17.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M17.36 6.64l1.42-1.42" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
                    </svg>
                {/if}
            </button>
            <a
                href="/journal"
                class="c2-nav-btn"
                class:c2-nav-btn-active={$page.url.pathname === '/journal'}
            >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                    <path d="M4 19.5A2.5 2.5 0 016.5 17H20" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
                    <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                Learn
            </a>
            <a
                href="/settings"
                class="c2-nav-btn"
                class:c2-nav-btn-active={$page.url.pathname === '/settings'}
            >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                    <path d="M12.22 2h-.44a2 2 0 00-2 2v.18a2 2 0 01-1 1.73l-.43.25a2 2 0 01-2 0l-.15-.08a2 2 0 00-2.73.73l-.22.38a2 2 0 00.73 2.73l.15.1a2 2 0 011 1.72v.51a2 2 0 01-1 1.74l-.15.09a2 2 0 00-.73 2.73l.22.38a2 2 0 002.73.73l.15-.08a2 2 0 012 0l.43.25a2 2 0 011 1.73V20a2 2 0 002 2h.44a2 2 0 002-2v-.18a2 2 0 011-1.73l.43-.25a2 2 0 012 0l.15.08a2 2 0 002.73-.73l.22-.39a2 2 0 00-.73-2.73l-.15-.08a2 2 0 01-1-1.74v-.5a2 2 0 011-1.74l.15-.09a2 2 0 00.73-2.73l-.22-.38a2 2 0 00-2.73-.73l-.15.08a2 2 0 01-2 0l-.43-.25a2 2 0 01-1-1.73V4a2 2 0 00-2-2z" stroke="currentColor" stroke-width="1.5"/>
                    <circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="1.5"/>
                </svg>
                Settings
            </a>
        </div>
    </header>

    <!-- ── Notification bubbles (top-right) ─────────────────────── -->
    {#if visibleTasks.length > 0}
        <div class="c2-notif-tray" role="status" aria-live="polite">
            {#each visibleTasks as task (task.id)}
                <div
                    class="c2-notif"
                    class:c2-notif-done={task.progress === 100}
                    transition:fly={{ x: 48, duration: 200 }}
                >
                    <div class="c2-notif-head">
                        <div class="c2-notif-icon-label">
                            {#if task.variant === 'pulse' || task.progress < 0}
                                <span class="c2-spinner c2-spinner-sm"></span>
                            {:else if task.progress === 100}
                                <svg class="c2-notif-ok" width="13" height="13" viewBox="0 0 24 24" fill="none">
                                    <path d="M20 6L9 17l-5-5" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
                                </svg>
                            {:else}
                                <span class="c2-notif-pct">{task.progress}%</span>
                            {/if}
                            <span class="c2-notif-label">{task.label}</span>
                        </div>
                        <button class="c2-notif-close" onclick={() => dismiss(task.id)} aria-label="Dismiss">
                            <svg width="10" height="10" viewBox="0 0 24 24" fill="none">
                                <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>
                            </svg>
                        </button>
                    </div>
                    {#if task.detail}
                        <p class="c2-notif-detail">{task.detail}</p>
                    {/if}
                    {#if task.progress >= 0 && task.progress < 100}
                        <div class="c2-notif-bar">
                            <div class="c2-notif-fill" style="width: {task.progress}%"></div>
                        </div>
                    {/if}
                </div>
            {/each}
        </div>
    {/if}

    <!-- Sidebar overlay -->
    {#if $sidebarOpen}
        <button
            type="button"
            class="c2-overlay"
            onclick={() => sidebarOpen.set(false)}
            aria-label="Close sidebar"
        ></button>
    {/if}
    <aside class="c2-sidebar" class:c2-sidebar-open={$sidebarOpen}>
        <div class="c2-sb-header">
            <span class="c2-sb-title">History</span>
            <button class="c2-icon-btn" onclick={() => sidebarOpen.set(false)} aria-label="Close">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                    <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                </svg>
            </button>
        </div>

        <button class="c2-new-btn" onclick={startNew}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
                <path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
            </svg>
            New chat
            <span class="c2-new-kbd">⌘N</span>
        </button>

        <div class="c2-sb-search">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                <circle cx="11" cy="11" r="8" stroke="currentColor" stroke-width="1.8"/>
                <path d="M21 21l-4.35-4.35" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
            </svg>
            <input
                bind:value={sidebarQuery}
                placeholder="Search"
                class="c2-sb-input"
            />
            {#if sidebarQuery}
                <button onclick={() => sidebarQuery = ''} class="c2-sb-clear" aria-label="Clear search">
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
                        <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                    </svg>
                </button>
            {/if}
        </div>

        <div class="c2-sb-list c2-sb-projects">
            <div class="c2-sb-proj-head">
                <span class="c2-sb-section-label" style="padding:0">Projects</span>
                <button class="c2-sb-proj-add" onclick={startWsCreate} title="New project" aria-label="New project">
                    <svg width="11" height="11" viewBox="0 0 16 16" fill="none">
                        <path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
                    </svg>
                </button>
            </div>

            {#if creatingWs}
                <div class="c2-ws-create-row">
                    <input
                        class="c2-ws-create-input"
                        bind:this={newWsInput}
                        bind:value={newWsName}
                        placeholder="Project name"
                        onkeydown={handleWsCreateKey}
                        onblur={cancelWsCreate}
                    />
                </div>
            {/if}

            {#each workspaces as ws (ws.id)}
                <div
                    class="c2-ws-item"
                    class:c2-ws-active={$chat.workspaceId === ws.id}
                    role="button"
                    tabindex="0"
                    onclick={() => openWorkspace(ws.id)}
                    onkeydown={(e) => e.key === 'Enter' && openWorkspace(ws.id)}
                >
                    <div class="c2-ws-row">
                        <svg width="13" height="13" viewBox="0 0 16 16" fill="none" class="c2-ws-icon">
                            <path d="M2 5V3.5A1.5 1.5 0 013.5 2h3.379a1.5 1.5 0 011.06.44l.622.62a1.5 1.5 0 001.06.44H12.5A1.5 1.5 0 0114 5v7.5a1.5 1.5 0 01-1.5 1.5h-9A1.5 1.5 0 012 12.5V5z" stroke="currentColor" stroke-width="1.1"/>
                        </svg>
                        <span class="c2-ws-name">{ws.name}</span>
                    </div>
                    {#if ws.file_count > 0}
                        <span class="c2-ws-count">{ws.file_count}</span>
                    {/if}
                </div>
            {/each}

            {#if workspaces.length === 0 && !creatingWs}
                <div class="c2-sb-empty" style="padding:8px 10px;font-size:11.5px">No projects yet</div>
            {/if}
        </div>

        <div class="c2-sb-list">
            <div class="c2-sb-section-label">Conversations</div>
            {#each groupedConvs as group}
                <div class="c2-sb-group-label">{group.group}</div>
                {#each group.items as conv}
                    <div
                        class="c2-conv-item"
                        class:c2-conv-active={$chat.conversationId === conv.id}
                        role="button"
                        tabindex="0"
                        onclick={() => pickConversation(conv.id)}
                        onkeydown={(e) => e.key === 'Enter' && pickConversation(conv.id)}
                    >
                        {#if renamingId === conv.id}
                            <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
                            <input
                                class="c2-rename-input"
                                bind:value={renameValue}
                                onblur={commitRename}
                                onkeydown={(e) => { if (e.key === 'Enter') commitRename(); if (e.key === 'Escape') renamingId = null; }}
                                onclick={(e) => e.stopPropagation()}
                            />
                        {:else}
                            <span class="c2-conv-title">{conv.title}</span>
                            <div class="c2-conv-actions">
                                <button
                                    class="c2-conv-action"
                                    onclick={(e) => { e.stopPropagation(); startRename(conv.id, conv.title); }}
                                    aria-label="Rename"
                                >
                                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
                                        <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                                        <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                                    </svg>
                                </button>
                                <button
                                    class="c2-conv-action c2-conv-danger"
                                    onclick={(e) => { e.stopPropagation(); doDelete(conv.id); }}
                                    disabled={deletingId === conv.id}
                                    aria-label="Delete"
                                >
                                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
                                        <path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                                    </svg>
                                </button>
                            </div>
                        {/if}
                    </div>
                {/each}
            {/each}
            {#if filteredConvs.length === 0}
                <div class="c2-sb-empty">No conversations yet</div>
            {/if}
        </div>

        <div class="c2-sb-footer">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            Local · Private · GPU
        </div>
    </aside>

    <!-- Page content -->
    <main class="c2-main">
        {@render children()}
    </main>
</div>

<style>
    /* ── Shell ─────────────────────────────────────────────────── */
    .c2-shell {
        position: fixed;
        inset: 0;
        display: flex;
        flex-direction: column;
        background: var(--c2-bg-0);
        color: var(--c2-fg-0);
        font-family: 'Geist', ui-sans-serif, system-ui, -apple-system, sans-serif;
        font-size: 14px;
        overflow: hidden;
    }

    /* ── Image background ──────────────────────────────────────── */
    .c2-img-bg {
        position: absolute;
        inset: 0;
        pointer-events: none;
        z-index: 0;
        background:
            linear-gradient(oklch(0.10 0.005 70 / 0.76), oklch(0.10 0.005 70 / 0.76)),
            url('/ascii-art-bg.jpg') center / cover no-repeat;
    }
    :global([data-theme="light"]) .c2-img-bg {
        background:
            linear-gradient(oklch(0.985 0.002 90 / 0.65), oklch(0.97 0.002 90 / 0.75)),
            url('/ascii-art-bg.jpg') center / cover no-repeat;
    }

    /* ── Ambient background ────────────────────────────────────── */
    .c2-ambient {
        position: fixed;
        inset: 0;
        pointer-events: none;
        z-index: 1;
    }
    .c2-ambient::before {
        content: "";
        position: fixed; inset: -10%;
        background: radial-gradient(60% 40% at 20% 10%, oklch(0.40 0.04 70 / 0.10), transparent 70%);
        filter: blur(30px);
        pointer-events: none;
    }
    .c2-ambient::after {
        content: "";
        position: fixed; inset: 0;
        background-image: radial-gradient(oklch(1 0 0 / 0.025) 1px, transparent 1px);
        background-size: 22px 22px;
        pointer-events: none;
        mask-image: radial-gradient(ellipse at center, black 30%, transparent 80%);
        -webkit-mask-image: radial-gradient(ellipse at center, black 30%, transparent 80%);
    }
    /* Light mode ambient */
    :global([data-theme="light"]) .c2-ambient::before {
        background:
            radial-gradient(45% 30% at 18% 12%, oklch(0.78 0.12 68 / 0.35), transparent 60%),
            radial-gradient(50% 35% at 88% 22%, oklch(0.75 0.12 220 / 0.30), transparent 60%);
    }
    :global([data-theme="light"]) .c2-ambient::after {
        background-image: radial-gradient(oklch(0 0 0 / 0.06) 1px, transparent 1px);
        background-size: 22px 22px;
    }

    /* ── Topbar ────────────────────────────────────────────────── */
    .c2-topbar {
        position: relative;
        z-index: 50;
        height: 56px;
        display: flex;
        align-items: center;
        padding: 0 14px;
        background: oklch(0.155 0.003 260 / 0.88);
        backdrop-filter: blur(20px) saturate(1.2);
        -webkit-backdrop-filter: blur(20px) saturate(1.2);
        border-bottom: 1px solid var(--c2-border-1);
        flex-shrink: 0;
    }
    :global([data-theme="light"]) .c2-topbar {
        background: oklch(0.995 0.002 90 / 0.88);
    }
    .c2-tb-left {
        display: flex;
        align-items: center;
        gap: 10px;
        flex: 1;
    }
    .c2-tb-center {
        display: flex;
        align-items: center;
    }
    .c2-tb-right {
        display: flex;
        align-items: center;
        gap: 2px;
        flex: 1;
        justify-content: flex-end;
    }

    /* ── Icon button ───────────────────────────────────────────── */
    .c2-icon-btn {
        width: 32px;
        height: 32px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 8px;
        border: 1px solid transparent;
        background: transparent;
        color: var(--c2-fg-1);
        cursor: pointer;
        transition: background 120ms, color 120ms, border-color 120ms;
        flex-shrink: 0;
    }
    .c2-icon-btn:hover {
        background: var(--c2-bg-2);
        color: var(--c2-fg-0);
    }
    .c2-icon-btn-active {
        background: var(--c2-bg-3);
        border-color: var(--c2-border-2);
        color: var(--c2-fg-0);
    }

    /* ── Logo ──────────────────────────────────────────────────── */
    .c2-logo {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        text-decoration: none;
        color: inherit;
    }
    .c2-logo:hover { opacity: 1; }
    .c2-logo-text {
        font-size: 15px;
        font-weight: 500;
        color: var(--c2-fg-0);
        letter-spacing: -0.1px;
        line-height: 1;
    }

    /* ── Nav buttons (Journal, Settings) ──────────────────────── */
    .c2-nav-btn {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        height: 30px;
        padding: 0 10px;
        border-radius: 8px;
        font-size: 13px;
        color: var(--c2-fg-1);
        text-decoration: none;
        transition: background 120ms;
        white-space: nowrap;
    }
    .c2-nav-btn:hover { background: var(--c2-bg-2); color: var(--c2-fg-0); }
    .c2-nav-btn-active { background: var(--c2-bg-2); color: var(--c2-fg-0); }

    /* ── Model switcher ────────────────────────────────────────── */
    .c2-model-pill {
        position: relative;
    }
    .c2-model-btn {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        height: 32px;
        padding: 0 12px;
        border-radius: 999px;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-2);
        color: var(--c2-fg-0);
        font-size: 13px;
        cursor: pointer;
        transition: background 120ms, border-color 120ms;
        white-space: nowrap;
    }
    .c2-model-btn:hover:not(:disabled) { background: var(--c2-bg-2); }
    .c2-model-btn:disabled { opacity: 0.6; cursor: not-allowed; }
    .c2-model-btn-open { border-color: var(--c2-border-3); }

    .c2-status-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: var(--c2-fg-3);
        flex-shrink: 0;
    }
    .c2-status-ok { background: var(--c2-ok); }
    .c2-status-thinking { background: var(--c2-accent); animation: c2-pulse-dot 1.2s ease-in-out infinite; }

    .c2-model-name { font-size: 13px; font-weight: 500; line-height: 1; color: var(--c2-fg-0); }
    .c2-model-size { font-family: 'Geist Mono', monospace; font-size: 11px; color: var(--c2-fg-2); line-height: 1; }
    .c2-muted { color: var(--c2-fg-3); }
    .c2-think-badge {
        font-family: 'Geist Mono', monospace;
        font-size: 10px;
        color: var(--c2-fg-1);
        letter-spacing: 0.5px;
        font-weight: 500;
        padding: 2px 6px;
        border-radius: 4px;
        background: var(--c2-bg-2);
        border: 1px solid var(--c2-border-1);
        margin-left: 2px;
    }
    .c2-chevron {
        display: block;
        color: var(--c2-fg-3);
        margin-left: 2px;
        transition: transform 180ms;
    }
    .c2-chevron-open { transform: rotate(180deg); }
    .c2-spinner {
        width: 11px;
        height: 11px;
        border-radius: 50%;
        border: 1.5px solid var(--c2-border-2);
        border-top-color: var(--c2-accent);
        animation: c2-spin 600ms linear infinite;
        flex-shrink: 0;
    }

    /* Model dropdown */
    .c2-model-dropdown {
        position: absolute;
        top: 100%;
        left: 50%;
        translate: -50% 6px;
        min-width: 260px;
        max-width: 320px;
        max-height: 340px;
        overflow-y: auto;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-2);
        border-radius: 13px;
        padding: 6px;
        box-shadow: var(--c2-shadow-panel);
        z-index: 70;
        animation: c2-spring-up 200ms var(--c2-spring) both;
        scrollbar-width: thin;
        scrollbar-color: var(--c2-border-2) transparent;
    }
    .c2-dropdown-empty {
        padding: 14px 10px;
        font-size: 12.5px;
        color: var(--c2-fg-3);
        text-align: center;
    }
    .c2-dropdown-item {
        width: 100%;
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 10px 11px;
        border-radius: 8px;
        background: transparent;
        border: none;
        color: var(--c2-fg-0);
        text-align: left;
        cursor: pointer;
        transition: background 120ms;
        gap: 10px;
    }
    .c2-dropdown-item:hover { background: var(--c2-bg-2); }
    .c2-dropdown-item-active { background: var(--c2-bg-2); }

    .c2-di-info {
        display: flex;
        flex-direction: column;
        gap: 4px;
        min-width: 0;
        flex: 1;
    }
    .c2-di-name {
        font-size: 13px;
        font-weight: 500;
        color: var(--c2-fg-0);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .c2-di-meta {
        display: flex;
        flex-wrap: wrap;
        gap: 4px;
    }
    .c2-di-badge {
        font-family: 'Geist Mono', monospace;
        font-size: 9.5px;
        font-weight: 500;
        padding: 2px 6px;
        border-radius: 4px;
        background: var(--c2-bg-3);
        color: var(--c2-fg-2);
        border: 1px solid var(--c2-border-1);
        letter-spacing: 0.03em;
        text-transform: uppercase;
        white-space: nowrap;
    }
    .c2-di-badge-think {
        background: oklch(0.65 0.18 60 / 0.12);
        color: var(--c2-accent);
        border-color: oklch(0.65 0.18 60 / 0.2);
    }
    .c2-di-check {
        flex-shrink: 0;
        color: var(--c2-accent);
    }

    /* ── Phase indicator ───────────────────────────────────────── */
    .c2-phase-pill {
        display: inline-flex;
        align-items: center;
        gap: 12px;
        height: 32px;
        padding: 0 14px;
        border-radius: 999px;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-2);
    }
    .c2-pulse-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: var(--c2-accent);
        animation: c2-pulse-dot 1.2s ease-in-out infinite;
        flex-shrink: 0;
    }
    .c2-phase-text {
        font-size: 13px;
        color: var(--c2-fg-0);
        font-weight: 500;
    }
    .c2-phase-dots {
        display: inline-flex;
        gap: 3px;
        margin-left: 2px;
    }
    .c2-phase-seg {
        width: 5px;
        height: 3px;
        border-radius: 999px;
        background: var(--c2-bg-3);
        transition: all 320ms var(--c2-spring);
    }
    .c2-phase-seg-done {
        background: var(--c2-fg-2);
    }
    .c2-phase-seg-active {
        width: 14px;
        background: var(--c2-accent);
    }

    /* ── Sidebar overlay ───────────────────────────────────────── */
    .c2-overlay {
        position: fixed;
        inset: 0;
        z-index: 90;
        padding: 0;
        border: 0;
        background: oklch(0 0 0 / 0.38);
        animation: c2-fade-in 220ms ease both;
    }
    @keyframes c2-fade-in { from { opacity: 0; } to { opacity: 1; } }

    /* ── Sidebar ───────────────────────────────────────────────── */
    .c2-sidebar {
        position: fixed;
        top: 0;
        bottom: 0;
        left: 0;
        width: 312px;
        z-index: 100;
        background: var(--c2-bg-1);
        border-right: 1px solid var(--c2-border-2);
        box-shadow: var(--c2-shadow-panel);
        display: flex;
        flex-direction: column;
        transform: translateX(-106%);
        transition: transform 320ms var(--c2-spring);
    }
    .c2-sidebar-open {
        transform: translateX(0);
    }

    .c2-sb-header {
        padding: 14px 14px 0;
        display: flex;
        align-items: center;
        justify-content: space-between;
        height: 44px;
    }
    .c2-sb-title {
        font-size: 14px;
        font-weight: 500;
        color: var(--c2-fg-0);
    }

    .c2-new-btn {
        display: flex;
        align-items: center;
        gap: 10px;
        margin: 10px 14px 8px;
        height: 36px;
        padding: 0 12px;
        border-radius: 9px;
        background: var(--c2-bg-2);
        border: 1px solid var(--c2-border-2);
        color: var(--c2-fg-0);
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        transition: background 120ms;
        font-family: inherit;
    }
    .c2-new-btn:hover { background: var(--c2-bg-3); }
    .c2-new-kbd {
        font-family: 'Geist Mono', monospace;
        font-size: 10.5px;
        color: var(--c2-fg-3);
        border: 1px solid var(--c2-border-1);
        padding: 2px 5px;
        border-radius: 4px;
        margin-left: auto;
    }

    .c2-sb-search {
        display: flex;
        align-items: center;
        gap: 8px;
        margin: 0 14px 8px;
        padding: 0 10px;
        height: 30px;
        border-radius: 8px;
        background: var(--c2-bg-0);
        border: 1px solid var(--c2-border-1);
        color: var(--c2-fg-3);
    }
    .c2-sb-input {
        flex: 1;
        font-size: 12.5px;
        color: var(--c2-fg-0);
        background: transparent;
        border: none;
        outline: none;
        font-family: inherit;
    }
    .c2-sb-input::placeholder { color: var(--c2-fg-3); }
    .c2-sb-clear {
        color: var(--c2-fg-3);
        background: none;
        border: none;
        cursor: pointer;
        display: flex;
        align-items: center;
    }

    .c2-sb-list {
        flex: 1;
        overflow-y: auto;
        padding: 4px 8px 14px;
        scrollbar-width: thin;
        scrollbar-color: var(--c2-border-2) transparent;
    }
    .c2-sb-projects {
        flex: none;
        overflow: visible;
        padding-bottom: 10px;
    }
    .c2-sb-projects::after {
        content: "";
        display: block;
        height: 1px;
        margin: 2px 8px 0;
        background: linear-gradient(
            to right,
            transparent,
            var(--c2-border-1) 15%,
            var(--c2-border-1) 85%,
            transparent
        );
    }
    .c2-sb-proj-head {
        display: flex;
        align-items: center;
        padding: 2px 8px 6px;
    }
    .c2-sb-proj-add {
        width: 20px;
        height: 20px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 5px;
        background: none;
        border: none;
        color: var(--c2-fg-3);
        cursor: pointer;
        opacity: 0;
        transition: opacity 120ms, color 120ms, background 120ms;
        margin-left: auto;
    }
    .c2-sb-proj-head:hover .c2-sb-proj-add { opacity: 1; }
    .c2-sb-proj-add:hover { color: var(--c2-fg-0); background: var(--c2-bg-3); }
    .c2-ws-create-row {
        padding: 3px 8px 6px;
    }
    .c2-ws-create-input {
        width: 100%;
        height: 28px;
        padding: 0 10px;
        font-size: 12.5px;
        font-family: inherit;
        color: var(--c2-fg-0);
        background: var(--c2-bg-2);
        border: 1px solid var(--c2-border-2);
        border-radius: 7px;
        outline: none;
        box-sizing: border-box;
    }
    .c2-ws-create-input:focus { border-color: var(--c2-accent); }
    .c2-ws-create-input::placeholder { color: var(--c2-fg-3); }

    /* ── Workspace items ──────────────────────────────────────── */
    .c2-ws-item {
        position: relative;
        display: grid;
        grid-template-columns: 1fr auto;
        align-items: center;
        gap: 8px;
        padding: 8px 10px;
        border-radius: 8px;
        cursor: pointer;
        margin-bottom: 1px;
        height: 36px;
        transition: background 140ms ease, box-shadow 140ms ease;
        overflow: hidden;
    }
    .c2-ws-item:hover {
        background: var(--c2-bg-2);
    }
    .c2-ws-active {
        background: var(--c2-bg-3);
        box-shadow: inset 0 0 0 1px var(--c2-border-2);
    }
    .c2-ws-active::before {
        content: "";
        position: absolute;
        left: -1px;
        top: 8px;
        bottom: 8px;
        width: 2px;
        border-radius: 999px;
        background: var(--c2-accent);
    }

    .c2-ws-row {
        display: flex;
        align-items: center;
        gap: 10px;
        min-width: 0;
    }

    .c2-ws-icon {
        flex-shrink: 0;
        color: var(--c2-fg-3);
        transition: color 140ms ease;
    }
    .c2-ws-item:hover .c2-ws-icon,
    .c2-ws-active .c2-ws-icon {
        color: var(--c2-fg-2);
    }

    .c2-ws-name {
        font-size: 12.5px;
        font-weight: 500;
        color: var(--c2-fg-1);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        min-width: 0;
        transition: color 140ms ease;
    }
    .c2-ws-item:hover .c2-ws-name,
    .c2-ws-active .c2-ws-name {
        color: var(--c2-fg-0);
    }

    .c2-ws-count {
        font-family: 'Geist Mono', monospace;
        font-size: 10px;
        font-weight: 500;
        color: var(--c2-fg-3);
        background: var(--c2-bg-3);
        border: 1px solid var(--c2-border-1);
        padding: 2px 6px;
        border-radius: 999px;
        flex-shrink: 0;
        transition: all 140ms ease;
    }
    .c2-ws-item:hover .c2-ws-count {
        color: var(--c2-fg-2);
        background: var(--c2-bg-2);
        border-color: var(--c2-border-2);
    }
    .c2-sb-section-label {
        font-family: 'Geist Mono', monospace;
        font-size: 10px;
        color: var(--c2-fg-3);
        letter-spacing: 0.5px;
        text-transform: uppercase;
        padding: 2px 8px 6px;
    }
    .c2-sb-group-label {
        font-family: 'Geist Mono', monospace;
        font-size: 10px;
        color: var(--c2-fg-3);
        letter-spacing: 0.4px;
        padding: 8px 8px 4px;
    }
    .c2-sb-empty {
        font-size: 12.5px;
        color: var(--c2-fg-3);
        padding: 16px 10px;
        text-align: center;
    }

    .c2-conv-item {
        position: relative;
        display: grid;
        grid-template-columns: 1fr auto;
        align-items: center;
        gap: 8px;
        padding: 7px 10px;
        border-radius: 7px;
        cursor: pointer;
        margin-bottom: 1px;
        height: 32px;
        transition: background 120ms;
        overflow: hidden;
    }
    .c2-conv-item:hover { background: var(--c2-bg-2); }
    .c2-conv-active { background: var(--c2-bg-3); }
    .c2-conv-active::before {
        content: "";
        position: absolute;
        left: -1px;
        top: 7px;
        bottom: 7px;
        width: 2px;
        border-radius: 999px;
        background: var(--c2-accent);
    }
    .c2-conv-title {
        font-size: 12.5px;
        color: var(--c2-fg-1);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        min-width: 0;
    }
    .c2-conv-active .c2-conv-title { color: var(--c2-fg-0); font-weight: 500; }
    .c2-conv-actions {
        display: flex;
        gap: 0;
        opacity: 0;
        pointer-events: none;
        transition: opacity 120ms;
    }
    .c2-conv-item:hover .c2-conv-actions {
        opacity: 1;
        pointer-events: auto;
    }
    .c2-conv-action {
        width: 22px;
        height: 22px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 5px;
        border: none;
        background: none;
        color: var(--c2-fg-2);
        cursor: pointer;
        transition: background 120ms, color 120ms;
    }
    .c2-conv-action:hover { background: var(--c2-bg-3); color: var(--c2-fg-0); }
    .c2-conv-danger:hover { color: var(--c2-err); }
    .c2-rename-input {
        flex: 1;
        font-size: 12.5px;
        color: var(--c2-fg-0);
        background: var(--c2-bg-2);
        border: 1px solid var(--c2-border-2);
        border-radius: 5px;
        padding: 2px 6px;
        outline: none;
        font-family: inherit;
        width: 100%;
    }

    .c2-sb-footer {
        padding: 10px 14px;
        border-top: 1px solid var(--c2-border-1);
        display: flex;
        align-items: center;
        gap: 8px;
        font-family: 'Geist Mono', monospace;
        font-size: 11px;
        color: var(--c2-fg-3);
    }

    /* ── Main content ──────────────────────────────────────────── */
    .c2-main {
        flex: 1;
        overflow: hidden;
        position: relative;
        z-index: 1;
    }

    /* ── Notification bubbles (top-right) ─────────────────────── */
    .c2-notif-tray {
        position: fixed;
        top: 68px;
        right: 16px;
        z-index: 200;
        display: flex;
        flex-direction: column;
        gap: 8px;
        pointer-events: none;
        max-width: 320px;
    }
    .c2-notif {
        pointer-events: auto;
        background: oklch(0.155 0.003 260 / 0.92);
        backdrop-filter: blur(20px) saturate(1.3);
        -webkit-backdrop-filter: blur(20px) saturate(1.3);
        border: 1px solid var(--c2-border-2);
        border-radius: 13px;
        padding: 11px 13px;
        box-shadow: var(--c2-shadow-panel);
        min-width: 240px;
        display: flex;
        flex-direction: column;
        gap: 6px;
        transition: opacity 200ms;
    }
    :global([data-theme="light"]) .c2-notif {
        background: oklch(0.995 0.002 90 / 0.94);
    }
    .c2-notif-done { opacity: 0.65; }
    .c2-notif-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
    }
    .c2-notif-icon-label {
        display: flex;
        align-items: center;
        gap: 8px;
        min-width: 0;
        flex: 1;
    }
    .c2-notif-label {
        font-size: 12.5px;
        font-weight: 500;
        color: var(--c2-fg-0);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .c2-notif-pct {
        font-family: 'Geist Mono', monospace;
        font-size: 11px;
        font-weight: 600;
        color: var(--c2-accent);
        min-width: 30px;
        font-variant-numeric: tabular-nums;
        flex-shrink: 0;
    }
    .c2-notif-ok {
        color: var(--c2-ok);
        flex-shrink: 0;
    }
    .c2-notif-close {
        width: 20px;
        height: 20px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 5px;
        border: none;
        background: none;
        color: var(--c2-fg-3);
        cursor: pointer;
        flex-shrink: 0;
        transition: background 120ms, color 120ms;
    }
    .c2-notif-close:hover { background: var(--c2-bg-3); color: var(--c2-fg-0); }
    .c2-notif-detail {
        font-family: 'Geist Mono', monospace;
        font-size: 11px;
        color: var(--c2-fg-3);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        margin: 0;
        padding-left: 21px;
    }
    .c2-notif-bar {
        height: 3px;
        border-radius: 999px;
        background: var(--c2-bg-3);
        overflow: hidden;
        margin-top: 2px;
    }
    .c2-notif-fill {
        height: 100%;
        border-radius: 999px;
        background: var(--c2-accent);
        transition: width 300ms ease;
    }
    .c2-spinner-sm {
        width: 12px;
        height: 12px;
        border-width: 2px;
        flex-shrink: 0;
    }
</style>
