<script lang="ts">
    let { workspaceId, onFileSelect, activeFile = '' }:
        { workspaceId: string; onFileSelect?: (path: string) => void; activeFile?: string } = $props();

    interface FileEntry {
        path: string;
        is_dir: boolean;
        size: number;
    }

    let files = $state<FileEntry[]>([]);
    let loading = $state(false);
    let collapsedDirs = $state<Set<string>>(new Set());

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
            cpp: '#5B8DEF', c: '#5B8DEF', h: '#5B8DEF',
        };
        return map[ext] || 'var(--text-muted)';
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

    function fileDir(path: string): string {
        const parts = path.split('/');
        return parts.length > 1 ? parts.slice(0, -1).join('/') : '';
    }

    function toggleDir(dir: string) {
        const next = new Set(collapsedDirs);
        if (next.has(dir)) next.delete(dir);
        else next.add(dir);
        collapsedDirs = next;
    }

    interface TreeNode {
        type: 'dir' | 'file';
        name: string;
        path: string;
        depth: number;
        size: number;
        ext: string;
    }

    let treeNodes = $derived.by(() => {
        const nodes: TreeNode[] = [];
        const seenDirs = new Set<string>();
        const sorted = [...files].filter(f => !f.is_dir).sort((a, b) => a.path.localeCompare(b.path));

        for (const file of sorted) {
            const dir = fileDir(file.path);
            if (dir && !seenDirs.has(dir)) {
                seenDirs.add(dir);
                const parts = dir.split('/');
                // Add each level of the directory path
                let accumulated = '';
                for (let i = 0; i < parts.length; i++) {
                    accumulated = accumulated ? accumulated + '/' + parts[i] : parts[i];
                    if (!seenDirs.has('__dir__' + accumulated)) {
                        seenDirs.add('__dir__' + accumulated);
                        nodes.push({ type: 'dir', name: parts[i], path: accumulated, depth: i, size: 0, ext: '' });
                    }
                }
            }
            const depth = dir ? dir.split('/').length : 0;
            // Skip if parent dir is collapsed
            if (dir) {
                const dirParts = dir.split('/');
                let skip = false;
                let acc = '';
                for (const part of dirParts) {
                    acc = acc ? acc + '/' + part : part;
                    if (collapsedDirs.has(acc)) { skip = true; break; }
                }
                if (skip) continue;
            }
            const ext = extOf(file.path);
            nodes.push({ type: 'file', name: fileName(file.path), path: file.path, depth, size: file.size, ext });
        }
        // Filter out dir nodes whose parent is collapsed
        return nodes.filter(n => {
            if (n.type === 'dir') {
                const parentDir = fileDir(n.path);
                if (parentDir) {
                    const parts = parentDir.split('/');
                    let acc = '';
                    for (const part of parts) {
                        acc = acc ? acc + '/' + part : part;
                        if (collapsedDirs.has(acc)) return false;
                    }
                }
            }
            return true;
        });
    });

    let fileCount = $derived(files.filter(f => !f.is_dir).length);
</script>

<div class="file-tree">
    <div class="tree-header">
        <div class="tree-header-left">
            <svg class="tree-icon" width="14" height="14" viewBox="0 0 16 16" fill="none">
                <path d="M2 4.5A1.5 1.5 0 013.5 3h3.379a1.5 1.5 0 011.06.44l.622.62a1.5 1.5 0 001.06.44H12.5A1.5 1.5 0 0114 6v5.5a1.5 1.5 0 01-1.5 1.5h-9A1.5 1.5 0 012 11.5v-7z" stroke="currentColor" stroke-width="1.2"/>
            </svg>
            <span class="tree-title">Explorer</span>
            <span class="tree-count">{fileCount}</span>
        </div>
        <button class="tree-refresh" onclick={loadFiles} title="Refresh">
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                <path d="M1 8a7 7 0 0112.3-4.5M15 8a7 7 0 01-12.3 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                <path d="M13 1v3h-3M3 15v-3h3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
        </button>
    </div>

    {#if loading}
        <div class="tree-loading">
            <span class="loading-dot"></span>
            Loading workspace...
        </div>
    {:else if files.length === 0}
        <div class="tree-empty">
            <svg width="28" height="28" viewBox="0 0 16 16" fill="none" opacity="0.3">
                <path d="M2 4.5A1.5 1.5 0 013.5 3h3.379a1.5 1.5 0 011.06.44l.622.62a1.5 1.5 0 001.06.44H12.5A1.5 1.5 0 0114 6v5.5a1.5 1.5 0 01-1.5 1.5h-9A1.5 1.5 0 012 11.5v-7z" stroke="currentColor" stroke-width="1.2"/>
            </svg>
            <span>No files yet</span>
            <span class="tree-hint">Files will appear here after generation</span>
        </div>
    {:else}
        <div class="tree-list">
            {#each treeNodes as node}
                {#if node.type === 'dir'}
                    <button
                        class="tree-dir"
                        style="padding-left: {12 + node.depth * 16}px"
                        onclick={() => toggleDir(node.path)}
                    >
                        <svg class="dir-chevron" class:collapsed={collapsedDirs.has(node.path)} width="10" height="10" viewBox="0 0 10 10" fill="none">
                            <path d="M3 2l4 3-4 3" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                        <svg class="dir-icon" width="14" height="14" viewBox="0 0 16 16" fill="none">
                            <path d="M2 4.5A1.5 1.5 0 013.5 3h3.379a1.5 1.5 0 011.06.44l.622.62a1.5 1.5 0 001.06.44H12.5A1.5 1.5 0 0114 6v5.5a1.5 1.5 0 01-1.5 1.5h-9A1.5 1.5 0 012 11.5v-7z" stroke="currentColor" stroke-width="1.1" fill="rgba(232,133,12,0.12)"/>
                        </svg>
                        <span class="dir-name">{node.name}</span>
                    </button>
                {:else}
                    <button
                        class="tree-file"
                        class:active={activeFile === node.path}
                        style="padding-left: {12 + node.depth * 16}px"
                        onclick={() => onFileSelect?.(node.path)}
                    >
                        <span class="file-icon" style="--fc: {extColor(node.ext)}">{node.ext.toUpperCase().slice(0, 3) || '?'}</span>
                        <span class="file-name">{node.name}</span>
                        <span class="file-size">{formatSize(node.size)}</span>
                    </button>
                {/if}
            {/each}
        </div>
    {/if}
</div>

<style>
    .file-tree {
        display: flex;
        flex-direction: column;
        height: 100%;
        overflow: hidden;
    }
    .tree-header {
        height: 38px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 12px;
        border-bottom: 1px solid var(--border-subtle);
        flex-shrink: 0;
    }
    .tree-header-left {
        display: flex;
        align-items: center;
        gap: 7px;
    }
    .tree-icon {
        color: var(--brain);
        opacity: 0.7;
    }
    .tree-title {
        font-family: var(--font-body);
        font-size: 11px;
        font-weight: 600;
        color: var(--text-secondary);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .tree-count {
        font-family: var(--font-mono);
        font-size: 10px;
        color: var(--text-muted);
        background: var(--accent-subtle);
        padding: 1px 6px;
        border-radius: var(--radius-pill);
    }
    .tree-refresh {
        width: 26px;
        height: 26px;
        border: none;
        background: none;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--text-muted);
        border-radius: 8px;
        transition: all var(--transition);
    }
    .tree-refresh:hover {
        background: var(--accent-subtle);
        color: var(--text);
    }
    .tree-loading {
        padding: 20px 14px;
        font-family: var(--font-body);
        font-size: 11.5px;
        color: var(--text-muted);
        text-align: center;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
    }
    .loading-dot {
        width: 7px; height: 7px;
        border-radius: 50%;
        background: var(--brain);
        animation: pulse 6s ease-in-out infinite;
    }
    .tree-empty {
        padding: 32px 14px;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 6px;
        font-family: var(--font-body);
        font-size: 12px;
        color: var(--text-muted);
    }
    .tree-hint {
        font-size: 10.5px;
        opacity: 0.5;
    }
    .tree-list {
        overflow-y: auto;
        flex: 1;
        padding: 4px 0;
        scrollbar-width: thin;
    }
    .tree-dir {
        display: flex;
        align-items: center;
        gap: 4px;
        width: 100%;
        padding: 4px 14px;
        border: none;
        background: none;
        cursor: pointer;
        font-family: var(--font-body);
        font-size: 11.5px;
        font-weight: 600;
        color: var(--text-secondary);
        text-align: left;
        transition: background var(--transition);
    }
    .tree-dir:hover {
        background: var(--accent-subtle);
    }
    .dir-chevron {
        flex-shrink: 0;
        transition: transform 150ms ease;
        transform: rotate(90deg);
        color: var(--text-muted);
    }
    .dir-chevron.collapsed {
        transform: rotate(0deg);
    }
    .dir-icon {
        flex-shrink: 0;
    }
    .dir-name {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .tree-file {
        display: flex;
        align-items: center;
        gap: 8px;
        width: 100%;
        padding: 5px 14px;
        border: none;
        background: none;
        cursor: pointer;
        font-family: var(--font-mono);
        font-size: 11.5px;
        color: var(--text);
        text-align: left;
        transition: all var(--transition);
    }
    .tree-file:hover {
        background: var(--accent-subtle);
    }
    .tree-file.active {
        background: var(--surface);
    }
    .file-icon {
        font-family: var(--font-mono);
        font-size: 8px;
        font-weight: 700;
        letter-spacing: 0.02em;
        color: var(--fc);
        background: color-mix(in srgb, var(--fc) 10%, transparent);
        padding: 2px 4px;
        border-radius: 4px;
        min-width: 24px;
        text-align: center;
        flex-shrink: 0;
    }
    .file-name {
        flex: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .file-size {
        color: var(--text-muted);
        font-size: 10px;
        flex-shrink: 0;
        opacity: 0.5;
    }
</style>
