import { writable } from 'svelte/store';
import { browser } from '$app/environment';

export type Theme = 'light' | 'dark';
export type UiStyle = 'classic' | 'ct2';
export type ClassicBg = 'default' | 'image';
export type Ct2Bg = 'image' | 'none';

interface Preferences {
    theme: Theme;
    uiStyle: UiStyle;
    classicBg: ClassicBg;
    ct2Bg: Ct2Bg;
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
    classicBg: 'default',
    ct2Bg: 'image',
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
            // Migrate old 'video' classicBg to 'image'
            if ((parsed.classicBg as string) === 'video') {
                parsed.classicBg = 'image';
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
            applyClassicBg(prefs.classicBg ?? 'default');
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

export function setClassicBg(bg: ClassicBg) {
    preferences.update((p) => ({ ...p, classicBg: bg }));
}

export function setCt2Bg(bg: Ct2Bg) {
    preferences.update((p) => ({ ...p, ct2Bg: bg }));
}

function applyClassicBg(bg: ClassicBg) {
    if (!browser) return;
    document.documentElement.setAttribute('data-classic-bg', bg);
}

export function toggleWebSearch() {
    preferences.update((p) => {
        return { ...p, webSearchEnabled: !p.webSearchEnabled };
    });
}
