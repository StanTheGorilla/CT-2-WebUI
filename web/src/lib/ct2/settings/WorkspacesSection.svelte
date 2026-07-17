<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { newConversation, setWorkspaceId, setMode, loadFromHistory } from '$lib/stores/chat';
    import { preferences } from '$lib/stores/preferences';

    // ── Workspaces ────────────────────────────────────────────────
    interface Workspace { id: string; name: string; created_at: string; file_count: number; }
    let workspaces = $state<Workspace[]>([]);
    let deletingWs = $state<string | null>(null);
    let wsCreating = $state(false);
    let wsNewName = $state('');
    let wsNewInput = $state<HTMLInputElement | null>(null);

    async function loadWorkspaces() {
        try { workspaces = await (await fetch('/api/workspaces')).json(); } catch {}
    }

    function startWsCreate() {
        wsCreating = true;
        wsNewName = '';
        requestAnimationFrame(() => wsNewInput?.focus());
    }

    async function submitWsCreate() {
        const trimmed = wsNewName.trim();
        wsCreating = false;
        wsNewName = '';
        if (!trimmed) return;
        try {
            const res = await fetch('/api/workspaces', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: trimmed }),
            });
            const ws: Workspace = await res.json();
            workspaces = [ws, ...workspaces];
        } catch {}
    }

    function cancelWsCreate() { wsCreating = false; wsNewName = ''; }

    function handleWsCreateKeydown(e: KeyboardEvent) {
        if (e.key === 'Enter') submitWsCreate();
        else if (e.key === 'Escape') cancelWsCreate();
    }

    async function deleteWorkspace(id: string) {
        deletingWs = id;
        try {
            await fetch(`/api/workspaces/${id}`, { method: 'DELETE' });
            workspaces = workspaces.filter(w => w.id !== id);
            try { if (localStorage.getItem('ct2_workspace_id') === id) localStorage.removeItem('ct2_workspace_id'); } catch {}
        } finally { deletingWs = null; }
    }
    function fmtWsDate(iso: string) {
        try { return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }); } catch { return iso; }
    }

    async function openWorkspace(id: string) {
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

    onMount(() => { loadWorkspaces(); });
</script>

                <div class="c2-sh">
                    <h1 class="c2-sh-title">Workspaces</h1>
                    <p class="c2-sh-sub">Persistent project folders with file access and terminal integration.</p>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Command approval</div>
                        <div class="c2-row-desc">Require your confirmation before the AI runs each shell command. Applies to all workspaces.</div>
                    </div>
                    <div class="c2-row-control">
                        <button
                            class="c2-switch"
                            class:c2-switch-on={$preferences.requireCommandApproval}
                            onclick={() => preferences.update(p => ({ ...p, requireCommandApproval: !p.requireCommandApproval }))}
                            role="switch"
                            aria-checked={$preferences.requireCommandApproval}
                            aria-label="Toggle command approval"
                        >
                            <span class="c2-switch-knob"></span>
                        </button>
                    </div>
                </div>

                <div class="c2-ws-toolbar">
                    <button class="c2-btn-primary" onclick={startWsCreate}>New workspace</button>
                </div>

                {#if wsCreating}
                    <div class="c2-ws-create-row">
                        <input
                            class="c2-ws-create-input"
                            bind:this={wsNewInput}
                            bind:value={wsNewName}
                            placeholder="Project name"
                            onkeydown={handleWsCreateKeydown}
                        />
                        <button class="c2-btn-primary" onmousedown={(e) => e.preventDefault()} onclick={submitWsCreate}>Create</button>
                        <button class="c2-btn-ghost" style="margin-top:0" onclick={cancelWsCreate}>Cancel</button>
                    </div>
                {/if}

                {#if workspaces.length === 0 && !wsCreating}
                    <div class="c2-empty-state">No workspaces yet.</div>
                {:else}
                    {#each workspaces as ws}
                        <div class="c2-ws-row">
                            <div class="c2-ws-info">
                                <span class="c2-ws-name">{ws.name || ws.id}</span>
                                <span class="c2-ws-meta">{ws.file_count} file{ws.file_count !== 1 ? 's' : ''}{ws.created_at ? ' · ' + fmtWsDate(ws.created_at) : ''}</span>
                            </div>
                            <div style="display:inline-flex;gap:8px;">
                                <button class="c2-btn-primary" onclick={() => openWorkspace(ws.id)}>Open</button>
                                <button
                                    class="c2-btn-outline c2-btn-err"
                                    onclick={() => deleteWorkspace(ws.id)}
                                    disabled={deletingWs === ws.id}
                                >{deletingWs === ws.id ? 'Deleting…' : 'Delete'}</button>
                            </div>
                        </div>
                    {/each}
                {/if}
