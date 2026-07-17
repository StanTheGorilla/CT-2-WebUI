<script lang="ts">
    import { onMount } from 'svelte';

    // ── Response tuning (per-mode) ────────────────────────────────
    interface ModeConfig { name: string; description: string; task_overrides: Record<string, number>; }
    let modes = $state<ModeConfig[]>([]);
    let modeEdits = $state<Record<string, Record<string, number>>>({});
    let modesDirty = $state<Record<string, boolean>>({});
    let modesSaving = $state<Record<string, boolean>>({});
    let modesSaveError = $state<Record<string, string>>({});

    const MODE_DEFAULTS: Record<string, Record<string, number>> = {
        computer: { temperature: 0.25, top_p: 0.8,  presence_penalty: 1.3 },
        design:   { temperature: 0.1,  top_p: 0.9,  presence_penalty: 0.0 },
        code:     { temperature: 0,    top_p: 1.0,  presence_penalty: 1.3 },
        direct:   { temperature: 0.5,  top_p: 0.9,  presence_penalty: 0.6 },
    };

    async function loadModes() {
        try {
            const res = await fetch('/api/modes');
            modes = (await res.json()).modes ?? [];
        } catch {}
    }

    async function saveMode(name: string) {
        modesSaving[name] = true; modesSaveError[name] = '';
        try {
            const res = await fetch(`/api/modes/${name}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task_overrides: modeEdits[name] }),
            });
            const d = await res.json();
            if (d.error) throw new Error(d.error);
            modesDirty[name] = false;
        } catch (e: any) { modesSaveError[name] = e.message || 'Failed to save'; }
        finally { modesSaving[name] = false; }
    }

    function updateModeOverride(name: string, key: string, value: number) {
        if (!modeEdits[name]) modeEdits[name] = {};
        modeEdits[name][key] = value;
        modesDirty[name] = true;
    }

    function resetModeToDefault(name: string) {
        const d = MODE_DEFAULTS[name];
        if (!d) return;
        modeEdits[name] = { ...d };
        modesDirty[name] = true;
    }


    onMount(() => { loadModes(); });
</script>

                <div class="c2-sh">
                    <h1 class="c2-sh-title">Response tuning</h1>
                    <p class="c2-sh-sub">Per-mode overrides for temperature, sampling, and repetition. Each mode has independent defaults.</p>
                </div>

                {#if modes.length === 0}
                    <div class="c2-skeleton"></div>
                {:else}
                    {#each modes as mode}
                        <div class="c2-mode-card">
                            <div class="c2-mode-header">
                                <span class="c2-mode-name">{mode.name.charAt(0).toUpperCase() + mode.name.slice(1)}</span>
                                {#if mode.description}
                                    <span class="c2-mode-desc">{mode.description}</span>
                                {/if}
                                {#if MODE_DEFAULTS[mode.name]}
                                    <button
                                        class="c2-mode-reset"
                                        class:c2-mode-reset-active={modesDirty[mode.name]}
                                        onclick={() => resetModeToDefault(mode.name)}
                                        title="Reset to defaults"
                                    >
                                        <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                                            <path d="M2.5 8a5.5 5.5 0 1 0 1.1-3.3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
                                            <path d="M2.5 4v4h4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
                                        </svg>
                                        Reset
                                    </button>
                                {/if}
                            </div>

                            {#each [
                                { key: 'temperature',       min: 0, max: 2,  step: 0.05, label: 'Creativity',       param: 'temperature'       },
                                { key: 'top_p',             min: 0, max: 1,  step: 0.05, label: 'Nucleus sampling', param: 'top_p'             },
                                { key: 'presence_penalty',  min: -2, max: 2, step: 0.05, label: 'Presence penalty', param: 'presence_penalty'  },
                            ] as param}
                                {@const val = modeEdits[mode.name]?.[param.key] ?? mode.task_overrides[param.key] ?? MODE_DEFAULTS[mode.name]?.[param.key]}
                                {#if val !== undefined}
                                    <div class="c2-mode-param">
                                        <div class="c2-mode-param-header">
                                            <span class="c2-mode-param-label">{param.label}</span>
                                            <span class="c2-param">{param.param}</span>
                                            <span class="c2-slider-val" style="min-width:44px;">{(modeEdits[mode.name]?.[param.key] ?? val).toFixed(2)}</span>
                                        </div>
                                        <input
                                            type="range"
                                            min={param.min}
                                            max={param.max}
                                            step={param.step}
                                            value={modeEdits[mode.name]?.[param.key] ?? val}
                                            oninput={(e) => updateModeOverride(mode.name, param.key, Number((e.target as HTMLInputElement).value))}
                                            class="c2-slider"
                                            style="width:100%"
                                        />
                                    </div>
                                {/if}
                            {/each}

                            {#if modesDirty[mode.name] || modesSaveError[mode.name]}
                                <div class="c2-mode-footer">
                                    {#if modesSaveError[mode.name]}
                                        <span class="c2-inline-err">{modesSaveError[mode.name]}</span>
                                    {/if}
                                    <button
                                        class="c2-btn-primary"
                                        onclick={() => saveMode(mode.name)}
                                        disabled={modesSaving[mode.name]}
                                    >{modesSaving[mode.name] ? 'Saving…' : 'Save changes'}</button>
                                </div>
                            {/if}
                        </div>
                    {/each}
                {/if}
