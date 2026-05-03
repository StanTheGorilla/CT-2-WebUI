<script lang="ts">
    import { onMount } from 'svelte';

    interface HFFile { name: string; size_gb: number; }
    interface HFResult { id: string; name: string; pipeline: string; downloads: number; likes: number; last_modified: string; }

    interface Props {
        show?: boolean;
        onDownloaded?: () => void;
    }
    let { show = true, onDownloaded }: Props = $props();

    // ── Quality labels ──────────────────────────────────────────────────────
    const QUANT_QUALITY: Record<string, string> = {
        IQ1_S:  'Tiny',       IQ1_M:  'Tiny',
        IQ2_XS: 'Very small', IQ2_S:  'Very small', IQ2_M: 'Very small', Q2_K: 'Very small',
        IQ3_XS: 'Small',      Q3_K_S: 'Small',      Q3_K_M: 'Small',     Q3_K_L: 'Small',
        IQ4_XS: 'Balanced',   Q4_0:   'Balanced',   Q4_K_S: 'Balanced',
        Q4_K_M: 'Recommended',
        Q5_K_S: 'High quality', Q5_K_M: 'High quality',
        Q6_K:   'Very high quality',
        Q8_0:   'Near-lossless',
        F16:    'Full precision', BF16: 'Full precision',
    };

    // ── State ──────────────────────────────────────────────────────────────
    let vramGb       = $state<number | null>(null);
    let modalOpen    = $state(false);
    let searchQuery  = $state('');
    let searching    = $state(false);
    let searchResults = $state<HFResult[]>([]);
    let searchError  = $state('');
    let hasSearched  = $state(false);

    let selectedRepo  = $state('');
    let selectedModel = $state<HFResult | null>(null);

    let hfFiles      = $state<HFFile[]>([]);
    let filesLoading = $state(false);
    let filesError   = $state('');
    let selectedFile  = $state('');

    let downloading  = $state(false);
    let percent      = $state(0);
    let speedMb      = $state(0);
    let doneGb       = $state(0);
    let totalGb      = $state(0);
    let dlError      = $state('');
    let dlDone       = $state('');

    function fmtGb(n: number) {
        return n >= 1 ? n.toFixed(1) + ' GB' : Math.round(n * 1024) + ' MB';
    }
    function extractQuant(filename: string): string {
        const base = filename.split('/').pop() ?? filename;
        const m = base.match(/[.\-_]((?:IQ|BF?)\d[_A-Za-z0-9]*|Q\d[_A-Za-z0-9]*|F\d+)\.gguf$/i);
        return m ? m[1].toUpperCase() : base.replace(/\.gguf$/i, '');
    }
    function repoLabel(repo: string): string {
        return (repo.split('/')[1] ?? repo).replace(/[-_]?gguf$/i, '');
    }
    function fmtDownloads(n: number): string {
        if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
        if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
        return String(n);
    }

    onMount(async () => {
        try {
            const r = await fetch('/api/system/vram');
            if (r.ok) vramGb = (await r.json()).vram_gb ?? null;
        } catch {}
    });

    let searchTimer: ReturnType<typeof setTimeout> | undefined;

    function onSearchInput() {
        clearTimeout(searchTimer);
        const q = searchQuery.trim();
        if (q.length < 2) { searchResults = []; searchError = ''; hasSearched = false; return; }
        searchTimer = setTimeout(doSearch, 350);
    }

    async function doSearch() {
        const q = searchQuery.trim();
        if (q.length < 2) return;
        searching = true; searchError = ''; searchResults = []; hasSearched = true;
        try {
            const r = await fetch(`/api/models/hf/search?q=${encodeURIComponent(q)}&limit=30`);
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || 'Search failed');
            searchResults = d.results ?? [];
            if (searchResults.length === 0) searchError = 'No GGUF models found. Try broadening your search.';
        } catch (e: any) {
            searchError = e.message || 'Search failed';
        } finally {
            searching = false;
        }
    }

    function onSearchKeydown(e: KeyboardEvent) {
        if (e.key === 'Enter') { clearTimeout(searchTimer); doSearch(); }
    }

    function pickModel(m: HFResult) {
        selectedRepo = m.id; selectedModel = m;
        hfFiles = []; selectedFile = ''; filesError = ''; dlDone = ''; dlError = '';
        fetchFiles(m.id);
    }

    async function fetchFiles(repo: string) {
        filesLoading = true; filesError = ''; hfFiles = []; selectedFile = '';
        try {
            const r = await fetch(`/api/models/hf/files?repo=${encodeURIComponent(repo)}`);
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || 'Failed to load files');
            hfFiles = d.files ?? [];
            const q4 = hfFiles.find(f => f.name.includes('Q4_K_M'));
            selectedFile = q4?.name ?? hfFiles[0]?.name ?? '';
        } catch (e: any) {
            filesError = e.message || 'Could not load files';
        } finally { filesLoading = false; }
    }

    async function startDownload() {
        if (!selectedRepo || !selectedFile || downloading) return;
        downloading = true; dlError = ''; dlDone = '';
        percent = 0; speedMb = 0; doneGb = 0; totalGb = 0;
        const url = `/api/models/download?repo=${encodeURIComponent(selectedRepo)}&filename=${encodeURIComponent(selectedFile)}`;
        try {
            const resp = await fetch(url);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const reader = resp.body!.getReader();
            const dec = new TextDecoder(); let buf = '';
            for (;;) {
                const { done, value } = await reader.read();
                if (done) break;
                buf += dec.decode(value, { stream: true });
                const parts = buf.split('\n\n'); buf = parts.pop() ?? '';
                for (const part of parts) {
                    if (!part.startsWith('data: ')) continue;
                    const ev = JSON.parse(part.slice(6));
                    if (ev.status === 'progress') {
                        percent = ev.percent; speedMb = ev.speed_mb;
                        doneGb = ev.downloaded_gb; totalGb = ev.total_gb;
                    } else if (ev.status === 'done') {
                        dlDone = ev.filename; downloading = false; onDownloaded?.();
                    } else if (ev.status === 'error') {
                        throw new Error(ev.message);
                    } else if (ev.status === 'cancelled') {
                        downloading = false;
                    }
                }
            }
        } catch (e: any) { dlError = e.message || 'Download failed'; downloading = false; }
    }

    async function cancelDownload() {
        try { await fetch('/api/models/download', { method: 'DELETE' }); } catch {}
        downloading = false;
    }

    function openModal() {
        modalOpen = true;
        searchQuery = ''; searchResults = []; selectedRepo = ''; selectedModel = null;
        hfFiles = []; selectedFile = ''; searchError = ''; filesError = '';
        dlError = ''; dlDone = ''; hasSearched = false;
    }

    function closeModal() {
        if (downloading) return;
        modalOpen = false;
        document.body.style.overflow = '';
    }

    function goBackToSearch() {
        hfFiles = []; selectedRepo = ''; selectedModel = null;
        selectedFile = ''; filesError = ''; dlError = ''; dlDone = '';
    }

    $effect(() => {
        if (modalOpen) document.body.style.overflow = 'hidden';
        return () => { document.body.style.overflow = ''; };
    });
</script>

{#if show}
<!-- ═══════════════════════════════════════════════════════════════════════════
     ROOT — CSS variable scope applies to BOTH the button and the modal
     ═══════════════════════════════════════════════════════════════════════ -->
<div class="mdc-root">
    <!-- ── Inline button ──────────────────────────────────────────────────── -->
    <button class="mdc-open-btn" onclick={openModal} type="button">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/>
            <line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        Download from Hugging Face
        {#if vramGb !== null}
            <span class="mdc-vram-chip">{vramGb} GB VRAM</span>
        {/if}
    </button>

    <!-- ── Modal ──────────────────────────────────────────────────────────── -->
    {#if modalOpen}
    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
    <div class="mdc-overlay" onclick={closeModal}>
        <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
        <div class="mdc-modal" onclick={(e) => e.stopPropagation()} role="dialog" aria-label="Download a model from Hugging Face">

            <!-- ── Header ────────────────────────────────────────────────── -->
            <div class="mdc-modal-header">
                <span class="mdc-modal-title">
                    {#if selectedRepo}
                        <button class="mdc-icon-btn" onclick={goBackToSearch} title="Back to search" type="button">
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>
                            </svg>
                        </button>
                        {repoLabel(selectedRepo)}
                    {:else}
                        Download a model
                    {/if}
                </span>
                <button class="mdc-icon-btn" onclick={closeModal} title="Close" type="button">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                    </svg>
                </button>
            </div>

            <div class="mdc-modal-body">
                {#if !selectedRepo}
                    <!-- ── Search view ────────────────────────────────────── -->
                    <div class="mdc-search-row">
                        <svg class="mdc-search-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                        </svg>
                        <input
                            class="mdc-search-input"
                            type="text"
                            bind:value={searchQuery}
                            oninput={onSearchInput}
                            onkeydown={onSearchKeydown}
                            placeholder="Search any GGUF model… (e.g. Qwen, Mistral, Gemma)"
                            autofocus
                        />
                        {#if searching}
                            <span class="mdc-spinner"></span>
                        {/if}
                    </div>

                    {#if searchError}
                        <div class="mdc-err">{searchError}</div>
                    {/if}

                    {#if searchResults.length > 0}
                        <div class="mdc-results">
                            {#each searchResults as m}
                                <button class="mdc-result" onclick={() => pickModel(m)} type="button">
                                    <div class="mdc-result-main">
                                        <span class="mdc-result-name">{m.name}</span>
                                        <span class="mdc-result-owner">{m.id.split('/')[0]}</span>
                                    </div>
                                    <div class="mdc-result-meta">
                                        {#if m.downloads > 0}
                                            <span class="mdc-result-dl">{fmtDownloads(m.downloads)}</span>
                                        {/if}
                                        <svg class="mdc-result-arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                            <polyline points="9 18 15 12 9 6"/>
                                        </svg>
                                    </div>
                                </button>
                            {/each}
                        </div>
                    {:else if hasSearched && !searching}
                        <div class="mdc-empty">No results. Try a different search term.</div>
                    {:else if !hasSearched && !searching}
                        <div class="mdc-hint">
                            Search for any model by name — official releases and community fine-tunes are all available.
                        </div>
                    {/if}

                {:else}
                    <!-- ── Quant picker view ───────────────────────────────── -->
                    {#if filesLoading}
                        <div class="mdc-loading">Loading available quants…</div>
                    {:else if filesError}
                        <div class="mdc-err">{filesError}</div>
                        <button class="mdc-btn-ghost" onclick={goBackToSearch} type="button">Back to search</button>
                    {:else if hfFiles.length > 0}
                        <div class="mdc-model-meta-row">
                            <span class="mdc-model-owner">{selectedModel?.id.split('/')[0]}</span>
                        </div>
                        <div class="mdc-quants">
                            {#each hfFiles as f}
                                {@const quant = extractQuant(f.name)}
                                {@const quality = QUANT_QUALITY[quant] ?? ''}
                                <button
                                    class="mdc-quant"
                                    class:mdc-quant-sel={selectedFile === f.name}
                                    onclick={() => selectedFile = f.name}
                                    disabled={downloading}
                                    type="button"
                                >
                                    <span class="mdc-quant-tag">{quant}</span>
                                    {#if quality}
                                        <span class="mdc-quant-quality"
                                            class:mdc-quality-rec={quality === 'Recommended'}
                                        >{quality}</span>
                                    {:else}
                                        <span class="mdc-quant-quality"></span>
                                    {/if}
                                    <span class="mdc-quant-size">{fmtGb(f.size_gb)}</span>
                                </button>
                            {/each}
                        </div>

                        {#if !downloading}
                            <button class="mdc-btn-download" onclick={startDownload} disabled={!selectedFile} type="button">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
                                    <polyline points="7 10 12 15 17 10"/>
                                    <line x1="12" y1="15" x2="12" y2="3"/>
                                </svg>
                                Download {extractQuant(selectedFile)}
                            </button>
                        {/if}
                    {:else}
                        <div class="mdc-empty">No GGUF files found in this repository.</div>
                        <button class="mdc-btn-ghost" onclick={goBackToSearch} type="button">Back to search</button>
                    {/if}

                    <!-- Progress -->
                    {#if downloading}
                        <div class="mdc-progress">
                            <div class="mdc-bar"><div class="mdc-fill" style="width:{percent}%"></div></div>
                            <div class="mdc-stats">
                                <span>{percent.toFixed(0)}%</span>
                                <span>{doneGb.toFixed(1)} / {totalGb.toFixed(1)} GB</span>
                                <span>{speedMb.toFixed(0)} MB/s</span>
                                <button class="mdc-cancel-btn" onclick={cancelDownload} type="button">Cancel</button>
                            </div>
                        </div>
                    {/if}

                    {#if dlDone}<div class="mdc-done">✓ Downloaded: {dlDone}</div>{/if}
                    {#if dlError}<div class="mdc-err">{dlError}</div>{/if}
                {/if}
            </div>
        </div>
    </div>
    {/if}
</div>
{/if}

<style>
    /* ═════════════════════════════════════════════════════════════════════════
       CSS variables — defined on .mdc-root so BOTH button and modal inherit
       CT-2 theme vars take priority; Classic UI falls through to :root vars
       ═══════════════════════════════════════════════════════════════════════ */
    .mdc-root {
        --mdc-fg0:     var(--c2-fg-0,   var(--text,             #1A1A1A));
        --mdc-fg1:     var(--c2-fg-1,   var(--text-secondary,   #555550));
        --mdc-fg2:     var(--c2-fg-2,   var(--text-secondary,   #777));
        --mdc-fg3:     var(--c2-fg-3,   var(--text-muted,       #9E9E96));
        --mdc-bg0:     var(--c2-bg-0,   var(--bg,               #F5F3F0));
        --mdc-bg1:     var(--c2-bg-1,   var(--surface,          rgba(255,255,255,0.55)));
        --mdc-bg2:     var(--c2-bg-2,   var(--surface-hover,    rgba(255,255,255,0.75)));
        --mdc-bg3:     var(--c2-bg-3,   rgba(0,0,0,0.08));
        --mdc-bd1:     var(--c2-border-1, var(--border-subtle,  rgba(0,0,0,0.05)));
        --mdc-bd2:     var(--c2-border-2, var(--border,         rgba(0,0,0,0.10)));
        --mdc-acc:     var(--c2-accent,     #6B6B6B);
        --mdc-acc-dim: var(--c2-accent-dim, rgba(0,0,0,0.06));
        --mdc-acc-fg:  var(--c2-accent-fg,  #fff);
        --mdc-ok:      var(--c2-ok,      var(--success,         #2DA44E));
        --mdc-err-c:   var(--c2-err,     var(--error,           #CF222E));

        /* Button spacing — collapsed when no modal, wider when open */
        margin: 14px 0 16px;
    }

    /* ═══════════════════════════════════════════════════════════════════════
       INLINE BUTTON
       ═══════════════════════════════════════════════════════════════════════ */
    .mdc-open-btn {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        height: 33px;
        padding: 0 14px;
        border-radius: 8px;
        border: 1px solid var(--mdc-bd2);
        background: var(--mdc-bg1);
        color: var(--mdc-fg1);
        font-size: 12.5px;
        font-weight: 450;
        font-family: inherit;
        cursor: pointer;
        white-space: nowrap;
        transition: background 140ms, color 140ms, border-color 140ms;
    }
    .mdc-open-btn:hover {
        background: var(--mdc-bg2);
        color: var(--mdc-fg0);
        border-color: var(--mdc-acc);
    }
    .mdc-vram-chip {
        font-size: 10.5px;
        color: var(--mdc-fg3);
        background: var(--mdc-bg3);
        padding: 2px 7px;
        border-radius: 4px;
        font-family: 'Geist Mono', 'JetBrains Mono', monospace;
        letter-spacing: 0.02em;
    }

    /* ═══════════════════════════════════════════════════════════════════════
       MODAL OVERLAY
       ═══════════════════════════════════════════════════════════════════════ */
    .mdc-overlay {
        position: fixed;
        inset: 0; z-index: 10000;
        display: flex;
        align-items: flex-start; justify-content: center;
        padding: 64px 16px;
        background: oklch(0 0 0 / 0.58);
        backdrop-filter: blur(5px);
        -webkit-backdrop-filter: blur(5px);
        overflow-y: auto;
    }

    .mdc-modal {
        width: 100%;
        max-width: 550px;
        max-height: calc(100vh - 128px);
        display: flex;
        flex-direction: column;
        background: var(--mdc-bg1);
        border: 1px solid var(--mdc-bd2);
        border-radius: 14px;
        box-shadow:
            0 0 0 1px var(--mdc-bd1),
            0 4px 8px oklch(0 0 0 / 0.06),
            0 16px 56px oklch(0 0 0 / 0.18);
        overflow: hidden;
        animation: mdc-in 200ms var(--c2-spring, cubic-bezier(0.22, 1.2, 0.36, 1));
    }
    @keyframes mdc-in {
        from { opacity: 0; transform: translateY(16px) scale(0.96); }
        to   { opacity: 1; transform: translateY(0) scale(1); }
    }

    /* ── Header ────────────────────────────────────────────────────────── */
    .mdc-modal-header {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 15px 20px;
        border-bottom: 1px solid var(--mdc-bd1);
        flex-shrink: 0;
    }
    .mdc-modal-title {
        flex: 1; min-width: 0;
        font-size: 14px;
        font-weight: 600;
        color: var(--mdc-fg0);
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .mdc-icon-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 30px; height: 30px;
        border-radius: 7px;
        border: none;
        background: transparent;
        color: var(--mdc-fg2);
        cursor: pointer;
        flex-shrink: 0;
        transition: background 120ms, color 120ms;
    }
    .mdc-icon-btn:hover { background: var(--mdc-bg2); color: var(--mdc-fg0); }
    .mdc-icon-btn:disabled { opacity: 0.4; cursor: not-allowed; }

    /* ── Body ───────────────────────────────────────────────────────────── */
    .mdc-modal-body {
        flex: 1; min-height: 0;
        overflow-y: auto;
        padding: 18px 20px;
        display: flex;
        flex-direction: column;
        gap: 12px;
        scrollbar-width: thin;
        scrollbar-color: var(--mdc-bd2) transparent;
    }

    /* ═══════════════════════════════════════════════════════════════════════
       SEARCH
       ═══════════════════════════════════════════════════════════════════════ */
    .mdc-search-row {
        display: flex;
        align-items: center;
        gap: 10px;
        height: 42px;
        padding: 0 15px;
        border-radius: 10px;
        background: var(--mdc-bg0);
        border: 1px solid var(--mdc-bd2);
        transition: border-color 140ms, box-shadow 140ms;
    }
    .mdc-search-row:focus-within {
        border-color: var(--mdc-acc);
        box-shadow: 0 0 0 3px var(--mdc-acc-dim);
    }
    .mdc-search-icon { flex-shrink: 0; color: var(--mdc-fg3); }
    .mdc-search-input {
        flex: 1; min-width: 0; height: 100%;
        background: none; border: none; outline: none;
        font-size: 13.5px; font-family: inherit;
        color: var(--mdc-fg0);
    }
    .mdc-search-input::placeholder { color: var(--mdc-fg3); }
    .mdc-spinner {
        width: 16px; height: 16px; border-radius: 50%;
        border: 2px solid var(--mdc-bd2);
        border-top-color: var(--mdc-acc);
        animation: mdc-spin 600ms linear infinite;
        flex-shrink: 0;
    }
    @keyframes mdc-spin { to { transform: rotate(360deg); } }

    /* ═══════════════════════════════════════════════════════════════════════
       RESULTS
       ═══════════════════════════════════════════════════════════════════════ */
    .mdc-results {
        display: flex;
        flex-direction: column;
        gap: 2px;
        max-height: 380px;
        overflow-y: auto;
        scrollbar-width: thin;
        scrollbar-color: var(--mdc-bd2) transparent;
        margin: -4px 0;
    }
    .mdc-result {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 11px 13px;
        border-radius: 9px;
        border: 1px solid transparent;
        background: transparent;
        cursor: pointer;
        text-align: left;
        width: 100%;
        font-family: inherit;
        transition: background 100ms, border-color 100ms;
    }
    .mdc-result:hover { background: var(--mdc-bg0); border-color: var(--mdc-bd1); }
    .mdc-result-main {
        flex: 1; min-width: 0;
        display: flex; flex-direction: column; gap: 2px;
    }
    .mdc-result-name {
        font-size: 13.5px; font-weight: 500; color: var(--mdc-fg0);
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .mdc-result-owner {
        font-size: 11px; color: var(--mdc-fg3);
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .mdc-result-meta {
        display: flex; align-items: center; gap: 8px; flex-shrink: 0;
    }
    .mdc-result-dl { font-size: 11px; color: var(--mdc-fg3); font-weight: 450; }
    .mdc-result-arrow { color: var(--mdc-fg3); flex-shrink: 0; opacity: 0.6; }

    .mdc-hint {
        font-size: 13px; color: var(--mdc-fg3); text-align: center;
        padding: 28px 20px; line-height: 1.6;
    }
    .mdc-empty {
        font-size: 13px; color: var(--mdc-fg3); text-align: center; padding: 20px 0;
    }
    .mdc-loading {
        font-size: 13px; color: var(--mdc-fg2); text-align: center; padding: 24px 0;
    }
    .mdc-err { font-size: 12.5px; color: var(--mdc-err-c); padding: 4px 0; }

    /* ═══════════════════════════════════════════════════════════════════════
       QUANT PICKER
       ═══════════════════════════════════════════════════════════════════════ */
    .mdc-model-meta-row { margin-bottom: -4px; }
    .mdc-model-owner {
        font-size: 11px; color: var(--mdc-fg3);
        font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em;
    }

    .mdc-quants {
        display: flex; flex-direction: column; gap: 4px;
        margin: 2px 0;
    }
    .mdc-quant {
        display: flex; align-items: center; gap: 10px;
        padding: 10px 14px; border-radius: 8px;
        border: 1px solid var(--mdc-bd1);
        background: var(--mdc-bg0);
        cursor: pointer; text-align: left;
        font-family: inherit;
        transition: background 100ms, border-color 100ms, box-shadow 100ms;
        width: 100%;
    }
    .mdc-quant:hover:not(:disabled) {
        background: var(--mdc-bg2); border-color: var(--mdc-bd2);
    }
    .mdc-quant.mdc-quant-sel {
        border-color: var(--mdc-acc);
        background: var(--mdc-acc-dim);
        box-shadow: 0 0 0 1px var(--mdc-acc-dim);
    }
    .mdc-quant:disabled { opacity: 0.5; cursor: not-allowed; }

    .mdc-quant-tag {
        font-family: 'Geist Mono', 'JetBrains Mono', monospace;
        font-size: 12.5px; font-weight: 600;
        color: var(--mdc-fg0);
        min-width: 82px; flex-shrink: 0;
    }
    .mdc-quant-sel .mdc-quant-tag { color: var(--mdc-acc); }

    .mdc-quant-quality {
        font-size: 12px; color: var(--mdc-fg2); flex: 1; font-weight: 450;
    }
    .mdc-quality-rec { color: var(--mdc-ok); font-weight: 550; }
    .mdc-quant-sel .mdc-quant-quality { color: var(--mdc-fg1); }

    .mdc-quant-size {
        font-family: 'Geist Mono', 'JetBrains Mono', monospace;
        font-size: 11.5px; color: var(--mdc-fg3);
        flex-shrink: 0; margin-left: auto;
        font-weight: 450;
    }
    .mdc-quant-sel .mdc-quant-size { color: var(--mdc-fg2); }

    /* ═══════════════════════════════════════════════════════════════════════
       BUTTONS
       ═══════════════════════════════════════════════════════════════════════ */
    .mdc-btn-download {
        display: inline-flex; align-items: center; gap: 7px;
        height: 35px; padding: 0 18px; border-radius: 8px;
        background: var(--mdc-acc);
        color: var(--mdc-acc-fg);
        border: none;
        font-size: 13px; font-weight: 500;
        font-family: inherit; cursor: pointer;
        white-space: nowrap;
        transition: opacity 120ms, transform 80ms;
        align-self: flex-start; margin-top: 6px;
    }
    .mdc-btn-download:disabled { opacity: 0.40; cursor: not-allowed; }
    .mdc-btn-download:hover:not(:disabled) { opacity: 0.92; }
    .mdc-btn-download:active:not(:disabled) { transform: scale(0.98); }

    .mdc-btn-ghost {
        display: inline-flex; align-items: center; gap: 5px;
        height: 31px; padding: 0 12px; border-radius: 8px;
        background: transparent;
        color: var(--mdc-fg1);
        border: 1px solid var(--mdc-bd2);
        font-size: 12.5px; font-family: inherit; cursor: pointer;
        white-space: nowrap;
        transition: background 120ms, color 120ms;
        align-self: flex-start;
    }
    .mdc-btn-ghost:hover { background: var(--mdc-bg0); color: var(--mdc-fg0); }

    /* ═══════════════════════════════════════════════════════════════════════
       PROGRESS
       ═══════════════════════════════════════════════════════════════════════ */
    .mdc-progress {
        display: flex; flex-direction: column; gap: 8px;
        margin-top: 6px;
    }
    .mdc-bar {
        height: 6px; border-radius: 999px;
        background: var(--mdc-bg3); overflow: hidden;
    }
    .mdc-fill {
        height: 100%;
        background: var(--mdc-acc);
        border-radius: 999px;
        transition: width 200ms linear;
    }
    .mdc-stats {
        display: flex; align-items: center; gap: 12px;
        font-family: 'Geist Mono', 'JetBrains Mono', monospace;
        font-size: 11.5px; color: var(--mdc-fg2);
    }
    .mdc-cancel-btn {
        margin-left: auto;
        background: none; border: none;
        color: var(--mdc-err-c);
        font-size: 11.5px; font-weight: 500;
        font-family: inherit; cursor: pointer; padding: 0;
        transition: opacity 120ms;
    }
    .mdc-cancel-btn:hover { opacity: 0.65; }

    /* ═══════════════════════════════════════════════════════════════════════
       STATUS
       ═══════════════════════════════════════════════════════════════════════ */
    .mdc-done {
        font-size: 12px; color: var(--mdc-ok); font-weight: 500;
        padding: 9px 13px; border-radius: 8px;
        background: var(--mdc-acc-dim);
        border: 1px solid var(--mdc-ok);
        margin-top: 4px;
    }
</style>
