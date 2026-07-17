<script lang="ts">
    import { onMount } from 'svelte';
    import { startRagPolling } from '$lib/stores/backgroundTasks';

    let { config, switching, restartModel }: {
        config: Record<string, any>;
        switching: boolean;
        restartModel: () => Promise<void>;
    } = $props();

    let ragStatus = $state<Record<string, any>>({});
    let ragFiles = $state<any[]>([]);
    let ragDataFiles = $state<any[]>([]);
    let ragLoading = $state(false);
    let ragReindexing = $state(false);
    let ragProgress = $state<Record<string, any>>({running: false, current: 0, total: 0, file: '', stage: ''});
    let ragMsg = $state('');
    let ragUploading = $state(false);
    let ragDragOver = $state(false);
    let ragFileInput = $state<HTMLInputElement | undefined>(undefined);
    let ragEnabling = $state(false);
    let ragNeedsRestart = $state(false);
    let _ragPollTimer: ReturnType<typeof setInterval> | undefined = undefined;


    async function fetchRag() {
        ragLoading = true; ragMsg = '';
        try {
            const [statusRes, filesRes, dataRes] = await Promise.all([
                fetch('/api/rag/status'),
                fetch('/api/rag/files'),
                fetch('/api/rag/data-files'),
            ]);
            ragStatus = await statusRes.json();
            ragFiles = (await filesRes.json()).files ?? [];
            ragDataFiles = (await dataRes.json()).files ?? [];
        } catch (e: any) { ragMsg = e.message || 'Failed to load RAG status'; }
        finally { ragLoading = false; }
    }

    async function ragUpload(file: File) {
        ragUploading = true; ragMsg = '';
        try {
            const fd = new FormData();
            fd.append('file', file);
            const res = await fetch('/api/rag/upload', { method: 'POST', body: fd });
            const d = await res.json();
            if (!res.ok) { ragMsg = d.detail || 'Upload failed'; return; }
            ragMsg = d.error ? `Indexing error: ${d.error}` : `Uploaded: ${file.name}`;
            await fetchRag();
        } catch (e: any) { ragMsg = e.message || 'Upload failed'; }
        finally { ragUploading = false; }
    }

    async function ragDelete(name: string) {
        ragMsg = '';
        try {
            const res = await fetch(`/api/rag/files/${encodeURIComponent(name)}`, { method: 'DELETE' });
            if (res.ok) { ragMsg = `Removed: ${name}`; await fetchRag(); }
            else { ragMsg = 'Delete failed'; }
        } catch (e: any) { ragMsg = e.message || 'Delete failed'; }
    }

    async function ragDeleteFile(name: string) {
        ragMsg = '';
        try {
            const res = await fetch(`/api/rag/data-files/${encodeURIComponent(name)}`, { method: 'DELETE' });
            if (res.ok) { ragMsg = `Deleted: ${name}`; await fetchRag(); }
            else { ragMsg = 'Delete failed'; }
        } catch (e: any) { ragMsg = e.message || 'Delete failed'; }
    }

    async function ragReindex() {
        ragReindexing = true; ragMsg = '';
        ragProgress = {running: true, current: 0, total: 0, file: '', stage: 'scanning'};
        // Start global polling for the persistent banner
        startRagPolling();
        // Start local polling for the inline progress bar (smoother at 200ms)
        if (_ragPollTimer) clearInterval(_ragPollTimer);
        _ragPollTimer = setInterval(async () => {
            try {
                const p = await (await fetch('/api/rag/reindex/progress')).json();
                ragProgress = p;
                if (!p.running && _ragPollTimer) {
                    clearInterval(_ragPollTimer);
                    _ragPollTimer = undefined;
                }
            } catch { /* ignore poll errors */ }
        }, 200);
        try {
            const res = await fetch('/api/rag/reindex', { method: 'POST' });
            const d = await res.json();
            // Final progress pull
            try { ragProgress = await (await fetch('/api/rag/reindex/progress')).json(); } catch {}
            if (_ragPollTimer) { clearInterval(_ragPollTimer); _ragPollTimer = undefined; }
            ragMsg = d.ok ? `Re-indexed: ${d.files_added} added, ${d.files_updated} updated, ${d.files_skipped} skipped, ${d.errors} errors` : (d.detail || 'Re-index failed');
            await fetchRag();
        } catch (e: any) {
            if (_ragPollTimer) { clearInterval(_ragPollTimer); _ragPollTimer = undefined; }
            ragMsg = e.message || 'Re-index failed';
        } finally {
            ragReindexing = false;
            ragProgress = {running: false, current: 0, total: 0, file: '', stage: 'idle'};
        }
    }

    function handleRagDrop(e: DragEvent) {
        e.preventDefault(); ragDragOver = false;
        const file = e.dataTransfer?.files?.[0];
        if (file) ragUpload(file);
    }

    function handleRagFilePick() {
        const file = ragFileInput?.files?.[0];
        if (file) { ragUpload(file); if (ragFileInput) ragFileInput.value = ''; }
    }

    async function toggleRagEnabled() {
        ragEnabling = true; ragMsg = '';
        try {
            const newVal = !ragStatus.enabled;
            const res = await fetch('/api/config', {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ rag_enabled: newVal }),
            });
            const d = await res.json();
            if (d.ok) {
                ragStatus = { ...ragStatus, enabled: newVal };
                ragNeedsRestart = true;
            } else {
                ragMsg = 'Failed to save setting.';
            }
        } catch (e: any) { ragMsg = e.message || 'Failed'; }
        finally { ragEnabling = false; }
    }

    async function restartForRag() {
        await restartModel();
        ragNeedsRestart = false;
        ragMsg = '';
        await fetchRag();
    }

    onMount(() => {
        fetchRag();
        return () => { if (_ragPollTimer) clearInterval(_ragPollTimer); };
    });
</script>

                <div class="c2-sh">
                    <h1 class="c2-sh-title">RAG</h1>
                    <p class="c2-sh-sub">Index your documents so the AI can pull in the most relevant passages before every reply — PDFs, notes, code, data files.</p>
                </div>

                {#if ragLoading}
                    <div class="c2-skeleton"></div>
                {:else}
                    <!-- Enable toggle -->
                    <div class="c2-row">
                        <div class="c2-row-label">
                            <div class="c2-row-name">Document indexing</div>
                            <div class="c2-row-desc">When on, the AI searches your indexed documents before every reply and injects the most relevant passages as context. Requires a server restart when changed.</div>
                        </div>
                        <div class="c2-row-control">
                            <button
                                class="c2-switch"
                                class:c2-switch-on={ragStatus.enabled}
                                onclick={toggleRagEnabled}
                                disabled={ragEnabling}
                                role="switch"
                                aria-checked={ragStatus.enabled}
                                aria-label="Toggle document indexing"
                            >
                                <span class="c2-switch-knob"></span>
                            </button>
                        </div>
                    </div>

                    <!-- Restart required notice -->
                    {#if ragNeedsRestart}
                        <div class="c2-rag-restart">
                            <div class="c2-rag-restart-left">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" style="flex-shrink:0">
                                    <path d="M12 9v4M12 17h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                                </svg>
                                <span>Server restart required to apply this change.</span>
                            </div>
                            <button class="c2-btn-outline c2-btn-warn" onclick={restartForRag} disabled={switching}>
                                {switching ? 'Restarting…' : 'Restart now'}
                            </button>
                        </div>
                    {/if}

                    {#if ragStatus.enabled && !ragNeedsRestart}
                        <!-- Upload drop zone -->
                        <div
                            class="c2-rag-drop"
                            class:c2-rag-drop-over={ragDragOver}
                            ondragover={(e) => { e.preventDefault(); ragDragOver = true; }}
                            ondragleave={() => ragDragOver = false}
                            ondrop={handleRagDrop}
                            onclick={() => ragFileInput?.click()}
                            role="button"
                            tabindex="0"
                        >
                            <input
                                bind:this={ragFileInput}
                                type="file"
                                accept=".pdf,.txt,.md,.markdown,.rst,.py,.js,.ts,.jsx,.tsx,.java,.go,.rs,.c,.cpp,.h,.hpp,.cs,.rb,.php,.html,.htm,.css,.scss,.less,.json,.yaml,.yml,.toml,.ini,.cfg,.xml,.csv,.tsv,.log,.sh,.bat,.ps1,.sql,.svg"
                                onchange={handleRagFilePick}
                                style="display:none"
                            />
                            <span class="c2-rag-drop-icon">
                                {#if ragUploading}
                                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" class="c2-rag-spin">
                                        <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.8" stroke-dasharray="18 38" stroke-linecap="round"/>
                                    </svg>
                                {:else}
                                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                                        <path d="M12 15V5M12 5L8 9M12 5l4 4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
                                        <path d="M4 17v1a2 2 0 002 2h12a2 2 0 002-2v-1" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
                                    </svg>
                                {/if}
                            </span>
                            <span class="c2-rag-drop-text">{ragUploading ? 'Uploading…' : 'Drop a file here or click to browse'}</span>
                            <span class="c2-rag-drop-hint">PDF · Markdown · Text · Code · CSV · JSON · HTML{ragStatus.max_file_mb ? ` · Max ${ragStatus.max_file_mb}MB` : ''}</span>
                        </div>

                        <!-- Feedback message -->
                        {#if ragMsg}
                            <div class="c2-rag-msg" class:c2-rag-msg-err={ragMsg.toLowerCase().includes('fail') || ragMsg.toLowerCase().includes('error')}>
                                {ragMsg}
                            </div>
                        {/if}

                        <!-- Reindex progress bar -->
                        {#if ragReindexing && ragProgress.total > 0}
                            <div class="c2-rag-progress-wrap">
                                <div class="c2-rag-progress-bar">
                                    <div
                                        class="c2-rag-progress-fill"
                                        style="width: {Math.round((ragProgress.current / ragProgress.total) * 100)}%"
                                    ></div>
                                </div>
                                <div class="c2-rag-progress-text">
                                    <span>{ragProgress.current} / {ragProgress.total} files</span>
                                    <span class="c2-rag-progress-pct">{Math.round((ragProgress.current / ragProgress.total) * 100)}%</span>
                                </div>
                                {#if ragProgress.file}
                                    <div class="c2-rag-progress-file" title={ragProgress.file}>{ragProgress.file}</div>
                                {/if}
                            </div>
                        {:else if ragReindexing}
                            <div class="c2-rag-progress-wrap">
                                <div class="c2-rag-progress-bar">
                                    <div class="c2-rag-progress-fill c2-rag-progress-indeterminate"></div>
                                </div>
                                <div class="c2-rag-progress-text">Scanning folder…</div>
                            </div>
                        {/if}

                        <!-- Files in rag uploads folder -->
                        {#if ragDataFiles.length > 0}
                            <div class="c2-subsection-label">
                                Files in <code class="c2-rag-path-label">ct2/data/rag_uploads/</code>
                                <span class="c2-rag-count-badge">{ragDataFiles.length}</span>
                            </div>
                            <div class="c2-rag-datafile-list">
                                {#each ragDataFiles as df (df.name)}
                                    <div class="c2-rag-datafile" class:c2-rag-datafile-idx={ragFiles.some((f: any) => f.name === df.name)}>
                                        <div class="c2-rag-datafile-info">
                                            <span class="c2-rag-datafile-name">{df.name}</span>
                                            <span class="c2-rag-datafile-meta">
                                                {df.size_mb} MB
                                                {#if ragFiles.some((f: any) => f.name === df.name)}
                                                    · indexed → {ragFiles.find((f: any) => f.name === df.name)?.chunk_count ?? 0} chunk{ragFiles.find((f: any) => f.name === df.name)?.chunk_count !== 1 ? 's' : ''}
                                                {:else}
                                                    · not indexed
                                                {/if}
                                            </span>
                                        </div>
                                        <div class="c2-rag-datafile-actions">
                                            <span class="c2-rag-datafile-dot" class:green={ragFiles.some((f: any) => f.name === df.name)}></span>
                                            <button class="c2-btn-ghost c2-btn-err-small" onclick={() => ragDeleteFile(df.name)} title="Delete file from disk">🗑</button>
                                        </div>
                                    </div>
                                {/each}
                            </div>
                        {:else}
                            <p class="c2-rag-empty">No files in <code>ct2/data/rag_uploads/</code> yet. Drop a file above to get started.</p>
                        {/if}

                        <!-- Indexed files summary -->
                        {#if ragFiles.length > 0}
                            <div class="c2-subsection-label">
                                Indexed files
                                <span class="c2-rag-count-badge">{ragFiles.length}</span>
                            </div>
                            {#each ragFiles as f}
                                <div class="c2-rag-file">
                                    <div class="c2-rag-file-info">
                                        <span class="c2-rag-file-name">{f.name}</span>
                                        <span class="c2-rag-file-meta">{f.size_mb} MB · {f.chunk_count} chunk{f.chunk_count !== 1 ? 's' : ''}</span>
                                    </div>
                                    <button class="c2-btn-ghost c2-btn-err-small" onclick={() => ragDelete(f.name)} title="Remove from index">✕</button>
                                </div>
                            {/each}
                        {:else if ragDataFiles.length > 0}
                            <p class="c2-rag-empty">Files exist in <code>ct2/data/rag_uploads/</code> but nothing is indexed yet. Click Re-index below.</p>
                        {:else}
                            <p class="c2-rag-empty">No documents indexed yet. Drop a file above to get started, or place files in the <code>ct2/data/rag_uploads/</code> folder and click Re-index.</p>
                        {/if}

                        <!-- Actions + stats -->
                        <div class="c2-rag-actions">
                            <button class="c2-btn-outline" onclick={ragReindex} disabled={ragReindexing}>
                                {ragReindexing ? 'Re-indexing…' : 'Re-index folder'}
                            </button>
                            {#if (ragStatus.files ?? 0) > 0}
                                <span class="c2-rag-stats">
                                    {ragStatus.files} file{ragStatus.files !== 1 ? 's' : ''}
                                    · {ragStatus.chunks} chunks
                                    {#if (ragStatus.context_cost ?? 0) > 0}· ~{ragStatus.context_cost} tokens/msg{/if}
                                </span>
                            {/if}
                        </div>

                        <!-- Context budget note -->
                        {#if (ragStatus.context_cost ?? 0) > 0}
                            <div class="c2-rag-budget">
                                Each message injects ~{ragStatus.context_cost} tokens of document context.
                                With a {config.context_size ? Math.round(config.context_size / 1024) + 'K' : '?'} context window, ~{Math.max(0, (config.context_size ?? 4096) / 3.5 - (ragStatus.context_cost ?? 2000)) | 0} tokens remain for conversation per turn.
                                CT-2 compacts history automatically when the window fills.
                            </div>
                        {/if}
                    {/if}
                {/if}
