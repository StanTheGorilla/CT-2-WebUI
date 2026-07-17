import { writable, derived, get } from 'svelte/store';
import { serverUpdate, isUpdating } from './serverUpdate';
import { modelSwapping } from './model';

export interface BgTask {
    id: string;
    type: 'download' | 'swap' | 'index' | 'install';
    label: string;          // e.g. "Downloading llama-server (Vulkan)…"
    detail: string;         // e.g. "45%" or "file 3 of 12"
    progress: number;       // 0-100, or -1 if indeterminate
    variant: 'info' | 'progress' | 'pulse';
}

const _tasks = writable<BgTask[]>([]);

export const backgroundTasks = derived(_tasks, $t => $t);
export const hasBackgroundTasks = derived(_tasks, $t => $t.length > 0);

// ── Model download tracking (from serverUpdate store) ────────────
let _downloadUnsub: (() => void) | null = null;

function _syncDownloadTasks() {
    const current = get(serverUpdate);
    const tasks: BgTask[] = [];

    for (const [backend, status] of Object.entries(current)) {
        if (status.status === 'downloading') {
            const label = backend === 'cuda' ? 'CUDA' : 'Vulkan';
            tasks.push({
                id: `download-${backend}`,
                type: 'download',
                label: `Downloading llama-server (${label})`,
                detail: status.message || 'Downloading…',
                progress: -1,
                variant: 'pulse',
            });
        } else if (status.status === 'done') {
            // Flash "done" briefly then remove
            const label = backend === 'cuda' ? 'CUDA' : 'Vulkan';
            tasks.push({
                id: `download-${backend}`,
                type: 'download',
                label: `llama-server (${label}) ready`,
                detail: 'Download complete — restart to apply',
                progress: 100,
                variant: 'info',
            });
        } else if (status.status === 'error') {
            const label = backend === 'cuda' ? 'CUDA' : 'Vulkan';
            tasks.push({
                id: `download-${backend}`,
                type: 'download',
                label: `Download failed (${label})`,
                detail: status.message || 'Unknown error',
                progress: -1,
                variant: 'info',
            });
        }
    }

    _tasks.update(t => {
        const without = t.filter(t => !t.id.startsWith('download-'));
        return [...without, ...tasks];
    });
}

// Subscribe to serverUpdate changes
if (typeof window !== 'undefined') {
    _downloadUnsub = serverUpdate.subscribe(() => _syncDownloadTasks());
}

// ── RAG indexing progress (global polling) ───────────────────────
let _ragPollTimer: ReturnType<typeof setInterval> | null = null;

export function startRagPolling() {
    if (_ragPollTimer) return;
    _ragPollTimer = setInterval(async () => {
        try {
            const r = await fetch('/api/rag/reindex/progress');
            const d = await r.json();
            if (d.running) {
                const pct = d.total > 0 ? Math.round((d.current / d.total) * 100) : -1;
                _tasks.update(t => {
                    const without = t.filter(t => t.id !== 'rag-index');
                    return [...without, {
                        id: 'rag-index',
                        type: 'index',
                        label: 'Indexing documents',
                        detail: d.file
                            ? `${d.file} (${d.current}/${d.total})`
                            : `${d.current}/${d.total} files`,
                        progress: pct >= 0 ? pct : -1,
                        variant: 'progress',
                    }];
                });
            } else {
                // Not running — remove from list, maybe show "done"
                _tasks.update(t => {
                    const existing = t.find(x => x.id === 'rag-index');
                    if (existing) {
                        // Flash done briefly (5s), then auto-remove
                        setTimeout(() => _tasks.update(t2 => t2.filter(x => x.id !== 'rag-index')), 5000);
                        return t.map(x => x.id === 'rag-index'
                            ? { ...x, label: 'Indexing complete', progress: 100, variant: 'info' as const }
                            : x);
                    }
                    return t;
                });
                // Stop polling when not running
                if (_ragPollTimer) {
                    clearInterval(_ragPollTimer);
                    _ragPollTimer = null;
                }
            }
        } catch {
            // Endpoint may not exist yet — stop polling
            if (_ragPollTimer) {
                clearInterval(_ragPollTimer);
                _ragPollTimer = null;
            }
        }
    }, 1000);
    // Also fire immediately
    _ragPollTimer && setTimeout(() => {
        // trigger first poll
    }, 50);
}

export function stopRagPolling() {
    if (_ragPollTimer) {
        clearInterval(_ragPollTimer);
        _ragPollTimer = null;
    }
    _tasks.update(t => t.filter(x => x.id !== 'rag-index'));
}

// ── Model swap tracking ──────────────────────────────────────────
let _swapDismissTimer: ReturnType<typeof setTimeout> | null = null;

export function setModelSwapping(target: string) {
    if (_swapDismissTimer) clearTimeout(_swapDismissTimer);
    modelSwapping.set(target);
    _tasks.update(t => {
        const without = t.filter(x => x.id !== 'model-swap');
        return [...without, {
            id: 'model-swap',
            type: 'swap',
            label: `Switching to ${target}`,
            detail: 'Model is loading — large models may take 30–90 seconds',
            progress: -1,
            variant: 'pulse',
        }];
    });
}

export function clearModelSwapping() {
    modelSwapping.set(null);
    _tasks.update(t => {
        const existing = t.find(x => x.id === 'model-swap');
        if (existing) {
            // Show "ready" briefly
            _swapDismissTimer = setTimeout(() => {
                _tasks.update(t2 => t2.filter(x => x.id !== 'model-swap'));
            }, 3000);
            return t.map(x => x.id === 'model-swap'
                ? { ...x, label: 'Model ready', detail: '', progress: 100, variant: 'info' as const }
                : x);
        }
        return t;
    });
}

// Mark download "done" tasks for auto-removal after a few seconds
let _doneTimers: Record<string, ReturnType<typeof setTimeout>> = {};
serverUpdate.subscribe(s => {
    for (const [backend, status] of Object.entries(s)) {
        const id = `download-${backend}`;
        if (status.status === 'done' && !_doneTimers[id]) {
            _doneTimers[id] = setTimeout(() => {
                _tasks.update(t => t.filter(x => x.id !== id));
                delete _doneTimers[id];
            }, 8000);
        }
    }
});

// ── Model file download tracking ────────────────────────────────
export function setModelDownload(filename: string, pct: number, speedMb: number, doneGb: number, totalGb: number) {
    const short = filename.split('/').pop() ?? filename;
    const detail = totalGb > 0
        ? `${speedMb.toFixed(1)} MB/s · ${doneGb.toFixed(1)}/${totalGb.toFixed(1)} GB`
        : `${speedMb.toFixed(1)} MB/s`;
    _tasks.update(t => {
        const without = t.filter(x => x.id !== 'model-dl');
        return [...without, {
            id: 'model-dl',
            type: 'download',
            label: `Downloading ${short}`,
            detail,
            progress: Math.round(pct),
            variant: 'progress',
        }];
    });
}

export function clearModelDownload() {
    _tasks.update(t => {
        const existing = t.find(x => x.id === 'model-dl');
        if (existing) {
            setTimeout(() => _tasks.update(t2 => t2.filter(x => x.id !== 'model-dl')), 5000);
            return t.map(x => x.id === 'model-dl'
                ? { ...x, label: x.label.replace('Downloading', 'Download complete'), progress: 100, variant: 'info' as const }
                : x);
        }
        return t;
    });
}
