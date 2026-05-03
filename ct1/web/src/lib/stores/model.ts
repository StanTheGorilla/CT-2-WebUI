import { writable } from 'svelte/store';

/** Incremented whenever any component switches the active model.
 *  Settings pages watch this to refresh their display. */
export const modelSwitchCount = writable(0);

export function notifyModelSwitch() {
    modelSwitchCount.update(n => n + 1);
}
