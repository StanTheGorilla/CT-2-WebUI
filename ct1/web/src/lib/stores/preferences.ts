import { writable } from 'svelte/store';
import { browser } from '$app/environment';

export type Theme = 'light' | 'dark';

interface Preferences {
    theme: Theme;
    showThinking: boolean;
    designRefinement: boolean;
    // Atlas Mode (beta)
    atlasMode: boolean;
    atlasEffortMode: 'auto' | 'manual';
    atlasEffortLevel: number;
    atlasSelfVerification: boolean;
    atlasMultiPerspective: boolean;
    atlasIterativeRefinement: boolean;
}

const defaults: Preferences = {
    theme: 'light',
    showThinking: false,
    designRefinement: true,
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

export function toggleTheme() {
    preferences.update((p) => {
        return { ...p, theme: p.theme === 'light' ? 'dark' : 'light' };
    });
}
