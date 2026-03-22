<script lang="ts">
    let { workspaceId, onFileSelect }:
        { workspaceId: string; onFileSelect?: (path: string) => void } = $props();

    interface FileEntry {
        path: string;
        is_dir: boolean;
        size: number;
    }

    let files = $state<FileEntry[]>([]);
    let loading = $state(false);

    $effect(() => {
        if (workspaceId) loadFiles();
    });

    async function loadFiles() {
        loading = true;
        try {
            const res = await fetch(`/api/workspaces/${workspaceId}/files`);
            const data = await res.json();
            if (Array.isArray(data)) files = data;
        } catch (e) {
            console.error('FileTree load error:', e);
        }
        loading = false;
    }

    export function refresh() {
        loadFiles();
    }

    function extOf(name: string): string {
        const i = name.lastIndexOf('.');
        return i >= 0 ? name.slice(i + 1).toLowerCase() : '';
    }

    function extColor(ext: string): string {
        const map: Record<string, string> = {
            html: '#E8850C', htm: '#E8850C', css: '#5B8DEF',
            js: '#D4AA00', ts: '#3178C6', jsx: '#D4AA00', tsx: '#3178C6',
            py: '#2DA44E', json: '#9E9E96', md: '#9E9E96', txt: '#9E9E96',
            svg: '#E8850C', sql: '#5B8DEF', go: '#00ADD8', rs: '#CE422B',
        };
        return map[ext] || '#777';
    }

    function formatSize(n: number): string {
        if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
        if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
        return `${n}B`;
    }

    function fileName(path: string): string {
        const parts = path.split('/');
        return parts[parts.length - 1];
    }

    function fileDepth(path: string): number {
        return path.split('/').length - 1;
    }
</script>

<div class="file-tree">
    <div class="tree-header">
        <span class="tree-title">Files</span>
        <button class="tree-refresh" onclick={loadFiles} title="Refresh">
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                <path d="M1 8a7 7 0 0112.3-4.5M15 8a7 7 0 01-12.3 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                <path d="M13 1v3h-3M3 15v-3h3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
        </button>
    </div>

    {#if loading}
        <div class="tree-loading">Loading...</div>
    {:else if files.length === 0}
        <div class="tree-empty">No files yet</div>
    {:else}
        <div class="tree-list">
            {#each files.filter(f => !f.is_dir) as file}
                {@const ext = extOf(file.path)}
                {@const name = fileName(file.path)}
                {@const depth = fileDepth(file.path)}
                <button
                    class="tree-file"
                    style="padding-left: {12 + depth * 16}px"
                    onclick={() => onFileSelect?.(file.path)}
                >
                    <span class="file-dot" style="background: {extColor(ext)}"></span>
                    <span class="file-name">{name}</span>
                    <span class="file-size">{formatSize(file.size)}</span>
                </button>
            {/each}
        </div>
    {/if}
</div>

<style>
    .file-tree {
        display: flex;
        flex-direction: column;
        height: 100%;
        background: var(--surface-solid);
        overflow: hidden;
    }
    .tree-header {
        height: 44px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 16px;
        background: var(--surface);
        border-bottom: 1px solid var(--border);
        flex-shrink: 0;
    }
    .tree-title {
        font-family: var(--font-body);
        font-size: 12px;
        font-weight: 600;
        color: var(--text-secondary);
        letter-spacing: 0.02em;
    }
    .tree-refresh {
        width: 28px;
        height: 28px;
        border: 1px solid var(--border);
        background: var(--accent-subtle);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--text-muted);
        border-radius: var(--radius-pill);
        transition: all var(--transition);
    }
    .tree-refresh:hover {
        background: var(--surface);
        color: var(--text);
        border-color: var(--border-strong);
    }
    .tree-loading, .tree-empty {
        padding: 24px 16px;
        font-family: var(--font-body);
        font-size: 12px;
        color: var(--text-muted);
        text-align: center;
    }
    .tree-list {
        overflow-y: auto;
        flex: 1;
        padding: 4px 0;
        scrollbar-width: thin;
    }
    .tree-file {
        display: flex;
        align-items: center;
        gap: 10px;
        width: 100%;
        padding: 6px 16px;
        border: none;
        background: none;
        cursor: pointer;
        font-family: var(--font-mono);
        font-size: 12px;
        color: var(--text);
        text-align: left;
        transition: all var(--transition);
        border-radius: 0;
    }
    .tree-file:hover {
        background: var(--accent-subtle);
    }
    .file-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        flex-shrink: 0;
        box-shadow: 0 0 4px rgba(0, 0, 0, 0.08);
    }
    .file-name {
        flex: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .file-size {
        color: var(--text-muted);
        font-size: 11px;
        flex-shrink: 0;
        opacity: 0.7;
    }
</style>
