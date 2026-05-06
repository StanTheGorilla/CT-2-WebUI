import { writable } from 'svelte/store';

/** Incremented whenever any component switches the active model.
 *  Settings pages watch this to refresh their display. */
export const modelSwitchCount = writable(0);

export function notifyModelSwitch() {
    modelSwitchCount.update(n => n + 1);
}

/** Target model name while a swap is in progress (anywhere in the app); null when idle.
 *  Top-bar switchers read this to show "Loading X…" even when the swap was initiated
 *  from the Settings page. Set/cleared via setModelSwapping/clearModelSwapping. */
export const modelSwapping = writable<string | null>(null);
