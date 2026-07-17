import { writable } from 'svelte/store';

export type ToastVariant = 'info' | 'error' | 'success' | 'warning';

export interface Toast {
    id: number;
    variant: ToastVariant;
    title?: string;
    message: string;
}

export const toasts = writable<Toast[]>([]);

let nextId = 1;

export function showToast(message: string, opts: { variant?: ToastVariant; title?: string; duration?: number } = {}) {
    const id = nextId++;
    const variant = opts.variant ?? 'info';
    const t: Toast = { id, variant, title: opts.title, message };
    toasts.update((arr) => [...arr, t]);
    const dur = opts.duration ?? (variant === 'error' ? 6000 : 4000);
    if (dur > 0) setTimeout(() => dismissToast(id), dur);
    return id;
}

export function dismissToast(id: number) {
    toasts.update((arr) => arr.filter((t) => t.id !== id));
}
