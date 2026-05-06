<script lang="ts">
    import { onMount } from 'svelte';
    import { modelSwitchCount, notifyModelSwitch, modelSwapping } from '$lib/stores/model';

    interface ModelFile {
        name: string;
        size_gb: number;
        thinking: boolean;
        vision: boolean;
        context_length: number | null;
    }

    let activeModel  = $state('');
    let modelThinking = $state(false);
    let switching    = $state(false);
    let pickerOpen   = $state(false);
    let models       = $state<ModelFile[]>([]);
    let modelsLoaded = $state(false);
    let error        = $state('');

    /** Strip .gguf + trailing quantization suffix (.Q4_K_S, -Q4_K_M, etc.) */
    function shortName(name: string): string {
        return name
            .replace(/\.gguf$/i, '')
            .replace(/[._-][Qq]\d+[_A-Za-z0-9]*$/, '');
    }

    onMount(async () => {
        await fetchActiveModel();
    });

    async function fetchActiveModel() {
        try {
            const res  = await fetch('/api/model');
            const data = await res.json();
            activeModel   = data.active_model   || '';
            modelThinking = data.enable_thinking ?? false;
        } catch { /* silent — no model yet */ }
    }

    // Sync when settings changes the model
    $effect(() => {
        $modelSwitchCount;
        fetchActiveModel();
    });

    async function openPicker() {
        pickerOpen = !pickerOpen;
        if (pickerOpen && !modelsLoaded) {
            try {
                const res  = await fetch('/api/models');
                models       = (await res.json()).models ?? [];
                modelsLoaded = true;
            } catch { /* silent */ }
        }
    }

    async function selectModel(name: string) {
        if (name === activeModel) { pickerOpen = false; return; }
        pickerOpen = false;
        switching  = true;
        error      = '';
        try {
            const res  = await fetch('/api/model/select', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ model: name }),
            });
            const data = await res.json();
            if (data.error) throw new Error(data.error);
            activeModel   = name;
            modelThinking = data.enable_thinking ?? false;
            modelsLoaded  = false; // refresh list next open
            notifyModelSwitch();
        } catch (e: any) {
            error = e?.message || 'Switch failed';
        } finally {
            switching = false;
        }
    }

    function closeOnOutside(e: MouseEvent) {
        const t = e.target as Element;
        if (!t?.closest?.('.model-switcher')) pickerOpen = false;
    }
</script>

<svelte:window onclick={closeOnOutside} />

<div class="model-switcher">
    <button
        class="switcher-btn"
        class:open={pickerOpen}
        onclick={openPicker}
        disabled={switching}
        title="Switch model"
    >
        {#if switching || $modelSwapping}
            <span class="ms-spinner"></span>
            <span class="ms-label">Loading {$modelSwapping ?? 'model'}…</span>
        {:else if activeModel}
            <span class="ms-label">{shortName(activeModel)}</span>
            {#if modelThinking}
                <span class="ms-badge think">Thinking</span>
            {/if}
            <svg class="ms-chevron" width="10" height="10" viewBox="0 0 24 24" fill="none">
                <path d="M6 9l6 6 6-6" stroke="currentColor" stroke-width="2.2"
                      stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
        {:else}
            <span class="ms-label muted">No model selected</span>
            <svg class="ms-chevron" width="10" height="10" viewBox="0 0 24 24" fill="none">
                <path d="M6 9l6 6 6-6" stroke="currentColor" stroke-width="2.2"
                      stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
        {/if}
    </button>

    {#if error}
        <span class="ms-error">{error}</span>
    {/if}

    {#if pickerOpen}
        <div class="ms-dropdown">
            {#if models.length === 0}
                <div class="drop-empty">No models found in models folder</div>
            {:else}
                {#each models as m}
                    <button
                        class="drop-item"
                        class:active={m.name === activeModel}
                        onclick={() => selectModel(m.name)}
                    >
                        <div class="drop-info">
                            <span class="drop-name">{shortName(m.name)}</span>
                            <div class="drop-meta">
                                <span class="drop-badge">{m.size_gb} GB</span>
                                {#if m.thinking}
                                    <span class="drop-badge think">Thinking</span>
                                {/if}
                                {#if m.vision}
                                    <span class="drop-badge">Vision</span>
                                {/if}
                            </div>
                        </div>
                        {#if m.name === activeModel}
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                                <path d="M20 6L9 17l-5-5" stroke="currentColor" stroke-width="2.5"
                                      stroke-linecap="round" stroke-linejoin="round"/>
                            </svg>
                        {/if}
                    </button>
                {/each}
            {/if}
        </div>
    {/if}
</div>

<style>
    /* ── Wrapper ─────────────────────────────────────────────── */
    .model-switcher {
        position: relative;
        display: inline-flex;
        align-items: center;
        gap: 8px;
    }

    /* ── Trigger button ──────────────────────────────────────── */
    .switcher-btn {
        display: flex;
        align-items: center;
        gap: 7px;
        padding: 6px 12px 6px 14px;
        border-radius: 999px;
        border: 1px solid var(--border);
        background: var(--surface);
        color: var(--text-secondary);
        font-size: 12.5px;
        font-weight: 500;
        letter-spacing: 0.01em;
        cursor: pointer;
        transition: color 150ms ease, border-color 150ms ease, background 150ms ease;
        white-space: nowrap;
    }
    .switcher-btn:hover:not(:disabled) {
        color: var(--text);
        border-color: var(--accent);
        background: var(--surface-hover);
    }
    .switcher-btn.open {
        color: var(--text);
        border-color: var(--accent);
    }
    .switcher-btn:disabled {
        opacity: 0.7;
        cursor: not-allowed;
    }

    /* ── Label inside button ─────────────────────────────────── */
    .ms-label {
        max-width: 180px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .ms-label.muted { color: var(--text-muted); }

    /* ── Thinking badge ─────────────────────────────────────── */
    .ms-badge {
        font-size: 10px;
        font-weight: 600;
        padding: 1px 6px;
        border-radius: 4px;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        background: var(--surface-hover);
        color: var(--text-muted);
    }
    .ms-badge.think {
        background: rgba(232, 133, 12, 0.12);
        color: var(--brain);
    }

    /* ── Chevron ─────────────────────────────────────────────── */
    .ms-chevron {
        opacity: 0.45;
        flex-shrink: 0;
        transition: transform 180ms ease;
    }
    .switcher-btn.open .ms-chevron {
        transform: rotate(180deg);
    }

    /* ── Loading spinner ────────────────────────────────────── */
    .ms-spinner {
        width: 11px;
        height: 11px;
        border-radius: 50%;
        border: 1.5px solid var(--border-strong);
        border-top-color: var(--accent);
        animation: msSpin 600ms linear infinite;
        flex-shrink: 0;
    }

    /* ── Inline error ───────────────────────────────────────── */
    .ms-error {
        font-size: 11px;
        color: #E05252;
        white-space: nowrap;
    }

    /* ── Dropdown panel ─────────────────────────────────────── */
    .ms-dropdown {
        position: absolute;
        top: calc(100% + 8px);
        left: 50%;
        transform: translateX(-50%);
        min-width: 260px;
        max-width: 340px;
        max-height: 320px;
        overflow-y: auto;
        background: var(--surface-solid);
        border: 1px solid var(--border-strong);
        border-radius: 14px;
        box-shadow: 0 10px 36px rgba(0, 0, 0, 0.18), 0 2px 8px rgba(0, 0, 0, 0.10);
        z-index: 500;
        padding: 6px;
        animation: msDropIn 180ms var(--spring-soft) both;
    }
    .ms-dropdown::-webkit-scrollbar { width: 4px; }
    .ms-dropdown::-webkit-scrollbar-thumb {
        background: var(--border);
        border-radius: 2px;
    }

    .drop-empty {
        padding: 16px;
        text-align: center;
        font-size: 12.5px;
        color: var(--text-muted);
    }

    /* ── Dropdown items ─────────────────────────────────────── */
    .drop-item {
        display: flex;
        align-items: center;
        justify-content: space-between;
        width: 100%;
        padding: 9px 10px;
        border-radius: 8px;
        border: none;
        background: none;
        text-align: left;
        cursor: pointer;
        transition: background 120ms ease;
        gap: 10px;
        color: var(--text);
    }
    .drop-item:hover { background: var(--surface-hover); }
    .drop-item.active { background: var(--surface-hover); }

    .drop-info {
        display: flex;
        flex-direction: column;
        gap: 4px;
        min-width: 0;
    }
    .drop-name {
        font-size: 13px;
        font-weight: 500;
        color: var(--text);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .drop-meta {
        display: flex;
        flex-wrap: wrap;
        gap: 4px;
    }
    .drop-badge {
        font-size: 10px;
        font-weight: 600;
        padding: 1px 5px;
        border-radius: 4px;
        background: var(--surface-hover);
        color: var(--text-muted);
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }
    .drop-badge.think {
        background: rgba(232, 133, 12, 0.12);
        color: var(--brain);
    }

    /* ── Animations ─────────────────────────────────────────── */
    @keyframes msSpin {
        to { transform: rotate(360deg); }
    }
    @keyframes msDropIn {
        from {
            opacity: 0;
            transform: translateX(-50%) translateY(-6px) scale(0.97);
        }
        to {
            opacity: 1;
            transform: translateX(-50%) translateY(0) scale(1);
        }
    }
</style>
