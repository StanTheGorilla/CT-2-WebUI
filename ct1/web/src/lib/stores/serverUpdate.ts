import { writable, derived } from 'svelte/store';

export interface UpdateStatus {
    status: 'idle' | 'downloading' | 'done' | 'error';
    message: string;
}

export const serverUpdate = writable<Record<string, UpdateStatus>>({});

const _pollers: Record<string, ReturnType<typeof setInterval>> = {};

export async function startUpdate(backend: 'vulkan' | 'cuda') {
    serverUpdate.update(s => ({ ...s, [backend]: { status: 'downloading', message: 'Starting...' } }));
    try {
        const res = await fetch(`/api/llama/update/${backend}`, { method: 'POST' });
        const data = await res.json();
        if (data.error) {
            serverUpdate.update(s => ({ ...s, [backend]: { status: 'error', message: data.error } }));
            return;
        }
    } catch {
        serverUpdate.update(s => ({ ...s, [backend]: { status: 'error', message: 'Request failed' } }));
        return;
    }

    if (_pollers[backend]) clearInterval(_pollers[backend]);
    _pollers[backend] = setInterval(async () => {
        try {
            const res = await fetch(`/api/llama/update/${backend}/status`);
            const data = await res.json();
            serverUpdate.update(s => ({ ...s, [backend]: data }));
            if (data.status === 'done' || data.status === 'error') {
                clearInterval(_pollers[backend]);
                delete _pollers[backend];
            }
        } catch { /* ignore */ }
    }, 1500);
}

export const isUpdating = derived(
    serverUpdate,
    $s => Object.values($s).some(v => v.status === 'downloading')
);
