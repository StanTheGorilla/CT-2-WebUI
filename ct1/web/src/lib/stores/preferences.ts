import { writable } from 'svelte/store';
import { browser } from '$app/environment';

export type Theme = 'light' | 'dark';
export type UiStyle = 'classic' | 'ct2';

interface Preferences {
    theme: Theme;
    uiStyle: UiStyle;
    showThinking: boolean;
    designRefinement: boolean;
    webSearchEnabled: boolean;
    requireCommandApproval: boolean;
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
    uiStyle: 'classic',
    showThinking: false,
    designRefinement: true,
    webSearchEnabled: false,
    requireCommandApproval: false,
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
            applyUiStyle(prefs.uiStyle);
        });
    }

    return { subscribe, set, update };
}

export const preferences = createPreferencesStore();

function applyTheme(theme: Theme) {
    if (!browser) return;
    document.documentElement.setAttribute('data-theme', theme);
}

function applyUiStyle(style: UiStyle) {
    if (!browser) return;
    document.documentElement.setAttribute('data-ui-style', style);
}

export function toggleTheme() {
    preferences.update((p) => {
        return { ...p, theme: p.theme === 'light' ? 'dark' : 'light' };
    });
}

export function setUiStyle(style: UiStyle) {
    preferences.update((p) => ({ ...p, uiStyle: style }));
}

export function toggleWebSearch() {
    preferences.update((p) => {
        return { ...p, webSearchEnabled: !p.webSearchEnabled };
    });
}
