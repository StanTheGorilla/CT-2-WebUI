import { writable } from 'svelte/store';
import { browser } from '$app/environment';

export type Theme = 'light' | 'dark';
export type Ct2Bg = 'image' | 'none';

interface Preferences {
    theme: Theme;
    ct2Bg: Ct2Bg;
    showThinking: boolean;
    designRefinement: boolean;
    webSearchEnabled: boolean;
    requireCommandApproval: boolean;
    notifyOnDone: boolean;
    // Atlas Mode
    atlasMode: boolean;
    atlasEffortMode: 'auto' | 'manual';
    atlasEffortLevel: number;
    atlasSelfVerification: boolean;
    atlasMultiPerspective: boolean;
    atlasIterativeRefinement: boolean;
}

const defaults: Preferences = {
    theme: 'light',
    ct2Bg: 'image',
    showThinking: false,
    designRefinement: true,
    webSearchEnabled: false,
    requireCommandApproval: false,
    notifyOnDone: true,
    // Atlas defaults
    atlasMode: false,
    atlasEffortMode: 'auto',
    atlasEffortLevel: 3,
    atlasSelfVerification: true,
    atlasMultiPerspective: true,
    atlasIterativeRefinement: true,
};

function loadPrefs(): Preferences {
    if (!browser) return defaults;
    try {
        const raw = localStorage.getItem('ct2-preferences');
        if (raw) {
            const parsed = { ...defaults, ...JSON.parse(raw) };
            // Migrate 'system' to 'light'
            if (parsed.theme !== 'light' && parsed.theme !== 'dark') {
                parsed.theme = 'light';
            }
            return parsed;
        }
        return defaults;
    } catch {
        return defaults;
    }
}

function createPreferencesStore() {
    const { subscribe, set, update } = writable<Preferences>(loadPrefs());

    if (browser) {
        subscribe((prefs) => {
            localStorage.setItem('ct2-preferences', JSON.stringify(prefs));
            applyTheme(prefs.theme);
        });
    }

    return { subscribe, set, update };
}

export const preferences = createPreferencesStore();

function applyTheme(theme: Theme) {
    if (!browser) return;
    document.documentElement.setAttribute('data-theme', theme);
}

// How long the theme cross-fade lasts. Must match `.theme-transitioning` in app.css.
const THEME_TRANSITION_MS = 320;

function flipTheme() {
    preferences.update((p) => ({ ...p, theme: p.theme === 'light' ? 'dark' : 'light' }));
}

export function toggleTheme() {
    if (!browser) {
        flipTheme();
        return;
    }

    // Modern Chromium: snapshot-and-fade between old + new states. Smoothest path.
    const startView = (document as Document & {
        startViewTransition?: (cb: () => void) => unknown;
    }).startViewTransition;
    if (typeof startView === 'function') {
        startView.call(document, flipTheme);
        return;
    }

    // Fallback: enable a global color/shadow/border transition for the duration
    // of the swap, then strip it so it doesn't interfere with hover/active anims.
    const root = document.documentElement;
    root.classList.add('theme-transitioning');
    flipTheme();
    setTimeout(() => root.classList.remove('theme-transitioning'), THEME_TRANSITION_MS);
}

export function setCt2Bg(bg: Ct2Bg) {
    preferences.update((p) => ({ ...p, ct2Bg: bg }));
}

export function toggleWebSearch() {
    preferences.update((p) => {
        return { ...p, webSearchEnabled: !p.webSearchEnabled };
    });
}
