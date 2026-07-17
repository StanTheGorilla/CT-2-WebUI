import { writable, get } from 'svelte/store';
import { browser } from '$app/environment';

export type AuthMode = 'none' | 'password' | 'accounts';

export interface AuthStatus {
    mode: AuthMode;
    authenticated: boolean;
    needs_setup: boolean;
}

const initial: AuthStatus = {
    mode: 'none',
    authenticated: true,
    needs_setup: false,
};

export const authStatus = writable<AuthStatus>(initial);
// Whether we've completed at least one /api/auth/status call. The layout
// uses this to avoid flashing the chat UI while we're still figuring out
// whether a login screen needs to render.
export const authReady = writable<boolean>(false);

export async function refreshAuthStatus(): Promise<AuthStatus> {
    if (!browser) return initial;
    try {
        const res = await fetch('/api/auth/status', { credentials: 'same-origin' });
        if (!res.ok) throw new Error(`status ${res.status}`);
        const data = (await res.json()) as AuthStatus;
        authStatus.set(data);
        return data;
    } catch {
        // Server unreachable — assume single-user so the UI doesn't deadlock.
        const fallback: AuthStatus = { mode: 'none', authenticated: true, needs_setup: false };
        authStatus.set(fallback);
        return fallback;
    } finally {
        authReady.set(true);
    }
}

export async function login(password: string): Promise<{ ok: boolean; error?: string }> {
    try {
        const res = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ password }),
        });
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            return { ok: false, error: data.detail || 'Login failed.' };
        }
        await refreshAuthStatus();
        return { ok: true };
    } catch (e: any) {
        return { ok: false, error: e?.message || 'Network error.' };
    }
}

export async function logout(): Promise<void> {
    try {
        await fetch('/api/auth/logout', {
            method: 'POST',
            credentials: 'same-origin',
        });
    } catch { /* ignore — we'll fall through to the login screen anyway */ }
    await refreshAuthStatus();
}

/** First-time setup OR password change. */
export async function setPassword(args: {
    new_password: string;
    current_password?: string;
    enable?: boolean;
}): Promise<{ ok: boolean; error?: string; mode?: AuthMode }> {
    try {
        const res = await fetch('/api/auth/password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({
                new_password: args.new_password,
                current_password: args.current_password,
                enable: args.enable ?? true,
            }),
        });
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            return { ok: false, error: data.detail || 'Could not set password.' };
        }
        const data = await res.json();
        await refreshAuthStatus();
        return { ok: true, mode: data.mode };
    } catch (e: any) {
        return { ok: false, error: e?.message || 'Network error.' };
    }
}

export async function disableAuth(password: string): Promise<{ ok: boolean; error?: string }> {
    try {
        const res = await fetch('/api/auth/disable', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ password }),
        });
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            return { ok: false, error: data.detail || 'Could not disable auth.' };
        }
        await refreshAuthStatus();
        return { ok: true };
    } catch (e: any) {
        return { ok: false, error: e?.message || 'Network error.' };
    }
}

/** True iff the current state means the chat shell shouldn't render. */
export function needsLoginScreen(s: AuthStatus): boolean {
    return s.mode !== 'none' && (!s.authenticated || s.needs_setup);
}

/** Convenience for non-Svelte callers. */
export function getAuthSnapshot(): AuthStatus {
    return get(authStatus);
}
