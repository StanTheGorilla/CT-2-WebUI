<script lang="ts">
    import { onMount } from 'svelte';
    import StatusIndicator from '$lib/components/StatusIndicator.svelte';
    import { preferences } from '$lib/stores/preferences';

    const CONTEXT_MIN_FLOOR = 2048;
    const PRESET_SETTINGS_KEY = 'ct2-preset-settings';

    let modelStatus = $state<Record<string, any>>({});
    let config = $state<Record<string, any>>({});
    let loading = $state(true);

    let presets = $state<Record<string, any>>({});
    let activePreset = $state('');
    let switching = $state(false);
    let switchError = $state('');

    let contextSize = $state(0);
    let maxContextSize = $state(0);
    let runningContextSize = $state(0);
    let needsRestart = $derived(contextSize !== runningContextSize);

    /* ── Per-preset settings persistence ── */

    function loadPresetSettings(preset: string): Record<string, any> {
        try {
            const all = JSON.parse(localStorage.getItem(PRESET_SETTINGS_KEY) || '{}');
            return all[preset] || {};
        } catch { return {}; }
    }

    function savePresetSettings(preset: string, settings: Record<string, any>) {
        try {
            const all = JSON.parse(localStorage.getItem(PRESET_SETTINGS_KEY) || '{}');
            all[preset] = settings;
            localStorage.setItem(PRESET_SETTINGS_KEY, JSON.stringify(all));
        } catch {}
    }

    function applyPresetContext(preset: string) {
        const info = presets[preset];
        maxContextSize = info?.context_size ?? 4096;
        const saved = loadPresetSettings(preset);
        const initial = saved.context_size ?? maxContextSize;
        contextSize = Math.max(CONTEXT_MIN_FLOOR, Math.min(initial, maxContextSize));
        runningContextSize = contextSize;
    }

    function onContextChange() {
        if (!activePreset) return;
        savePresetSettings(activePreset, { context_size: contextSize });
    }

    /* ── Data loading ── */

    async function loadData() {
        loading = true;
        try {
            const [statusRes, configRes, presetsRes] = await Promise.all([
                fetch('/api/status'),
                fetch('/api/config'),
                fetch('/api/presets'),
            ]);
            const statusData = await statusRes.json();
            modelStatus = statusData.director ?? {};
            config = await configRes.json();
            const presetsData = await presetsRes.json();
            presets = presetsData.presets ?? {};
            activePreset = presetsData.active ?? '';
            applyPresetContext(activePreset);
        } finally {
            loading = false;
        }
    }

    onMount(loadData);

    async function switchPreset(name: string) {
        if (name === activePreset || switching) return;
        switching = true;
        switchError = '';
        try {
            const res = await fetch('/api/preset', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ preset: name }),
            });
            const data = await res.json();
            if (data.error) {
                switchError = data.error;
            } else {
                activePreset = name;
                applyPresetContext(name);
                await loadData();
            }
        } catch (e: any) {
            switchError = e.message || 'Failed to switch preset';
        } finally {
            switching = false;
        }
    }

    async function restartModel() {
        switching = true;
        switchError = '';
        try {
            const res = await fetch('/api/preset', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ preset: activePreset, context_size: contextSize }),
            });
            const data = await res.json();
            if (data.error) {
                switchError = data.error;
            } else {
                runningContextSize = contextSize;
                await loadData();
            }
        } catch (e: any) {
            switchError = e.message || 'Failed to restart model';
        } finally {
            switching = false;
        }
    }

    function formatCtx(n: number): string {
        return n >= 1024 ? `${Math.round(n / 1024)}K` : `${n}`;
    }
</script>

<div class="settings-page">

    <!-- ─── Preset Selector ─── -->
    <section class="section">
        <h2 class="section-title">Model Preset</h2>
        {#if loading}
            <div class="skeleton-card"></div>
            <div class="skeleton-card"></div>
        {:else}
            <div class="preset-grid">
                {#each Object.entries(presets) as [name, info]}
                    <button
                        class="preset-card"
                        class:active={name === activePreset}
                        disabled={switching}
                        onclick={() => switchPreset(name)}
                    >
                        <!-- Radio dot -->
                        <div class="radio-col">
                            <span class="radio" class:checked={name === activePreset}>
                                {#if name === activePreset}
                                    <span class="radio-dot"></span>
                                {/if}
                            </span>
                        </div>

                        <div class="preset-body">
                            <div class="preset-top">
                                <span class="preset-name">{info.name}</span>
                                <span class="preset-arch">{info.solo ? 'Solo' : 'Cooperative'}</span>
                            </div>

                            <p class="preset-desc">{info.description}</p>

                            <!-- Best for / Not for -->
                            {#if info.best_for?.length}
                                <div class="use-case-row">
                                    <div class="use-case-col">
                                        <span class="use-case-label good">Best for</span>
                                        <ul class="use-case-list">
                                            {#each info.best_for as item}
                                                <li>{item}</li>
                                            {/each}
                                        </ul>
                                    </div>
                                    {#if info.not_for?.length}
                                        <div class="use-case-col">
                                            <span class="use-case-label avoid">Not ideal for</span>
                                            <ul class="use-case-list muted">
                                                {#each info.not_for as item}
                                                    <li>{item}</li>
                                                {/each}
                                            </ul>
                                        </div>
                                    {/if}
                                </div>
                            {/if}

                            <!-- Technical specs -->
                            <div class="preset-footer">
                                <div class="preset-specs">
                                    <span class="spec">{info.director_model?.replace('.gguf', '')}</span>
                                    {#if info.context_size}
                                        <span class="spec-sep"></span>
                                        <span class="spec">{formatCtx(info.context_size)} context</span>
                                    {/if}
                                </div>
                                {#if info.adaptive && info.task_modes?.length}
                                    <div class="preset-modes">
                                        {#each info.task_modes as mode}
                                            <span class="mode-pill">{mode}</span>
                                        {/each}
                                    </div>
                                {/if}
                            </div>
                        </div>
                    </button>
                {/each}
            </div>

            {#if switching}
                <div class="switch-banner">
                    <div class="switch-spinner"></div>
                    <span>Restarting servers with new model...</span>
                </div>
            {/if}
            {#if switchError}
                <div class="switch-banner error">
                    <span>{switchError}</span>
                </div>
            {/if}
        {/if}
    </section>

    <!-- ─── Pipeline ─── -->
    <section class="section">
        <h2 class="section-title">Pipeline</h2>
        <label class="toggle-row">
            <span class="toggle-label">
                <span class="toggle-name">Design refinement</span>
                <span class="toggle-desc">Second pass that reviews and polishes generated websites. Doubles generation time.</span>
            </span>
            <button
                class="toggle-switch"
                class:on={$preferences.designRefinement}
                onclick={() => preferences.update(p => ({ ...p, designRefinement: !p.designRefinement }))}
                role="switch"
                aria-checked={$preferences.designRefinement}
            >
                <span class="toggle-knob"></span>
            </button>
        </label>
    </section>

    <!-- ─── Server Status ─── -->
    <section class="section">
        <h2 class="section-title">Server Status</h2>
        {#if loading}
            <div class="skeleton-row"></div>
        {:else}
            <div class="status-grid">
                <StatusIndicator label="Model" status={modelStatus} />
            </div>
        {/if}
    </section>

    <!-- ─── Context Size ─── -->
    {#if maxContextSize > 0}
        <section class="section">
            <h2 class="section-title">Context Size</h2>
            <div class="config-card">
                <div class="config-row">
                    <label>Context Size</label>
                    <div class="slider-container">
                        <input type="range"
                            min={CONTEXT_MIN_FLOOR}
                            max={maxContextSize}
                            bind:value={contextSize}
                            oninput={onContextChange}
                        />
                        <span class="slider-value">{Math.round(contextSize / 1024)}K</span>
                    </div>
                </div>
            </div>
            {#if needsRestart}
                <div class="restart-notice">
                    <span>Restart required to apply changes.</span>
                    <button onclick={restartModel} class="restart-btn" disabled={switching}>Restart Model</button>
                </div>
            {/if}
        </section>
    {/if}

    <!-- ─── Configuration ─── -->
    {#if config.servers}
        <section class="section">
            <h2 class="section-title">Configuration</h2>
            {#each Object.entries(config.servers) as [name, info]}
                <div class="config-card">
                    <div class="config-card-title">{name}</div>
                    {#each Object.entries(info as Record<string, any>) as [key, value]}
                        <div class="config-row">
                            <span class="config-key">{key.replace(/_/g, ' ')}</span>
                            <span class="config-val">{value}</span>
                        </div>
                    {/each}
                </div>
            {/each}

            {#if config.models}
                {#each Object.entries(config.models) as [name, params]}
                    <div class="config-card">
                        <div class="config-card-title">{name} parameters</div>
                        {#each Object.entries(params as Record<string, any>) as [key, value]}
                            <div class="config-row">
                                <span class="config-key">{key.replace(/_/g, ' ')}</span>
                                <span class="config-val">{value}</span>
                            </div>
                        {/each}
                    </div>
                {/each}
            {/if}
        </section>
    {/if}
</div>

<style>
    .settings-page {
        max-width: 620px;
        margin: 0 auto;
        padding: 28px 28px 48px;
        height: 100%;
        overflow-y: auto;
        scrollbar-width: none;
    }
    .settings-page::-webkit-scrollbar { display: none; }

    /* ── Sections ── */
    .section { margin-bottom: 32px; }
    .section-title {
        font-size: 13px;
        font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin-bottom: 12px;
    }

    /* ── Skeleton loading ── */
    .skeleton-card {
        height: 110px;
        border-radius: var(--radius);
        background: var(--bubble);
        margin-bottom: 8px;
        animation: breathe 3s ease-in-out infinite;
    }
    .skeleton-row {
        height: 44px;
        border-radius: var(--radius-sm);
        background: var(--bubble);
        animation: breathe 3s ease-in-out infinite;
    }

    /* ── Preset Grid ── */
    .preset-grid {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .preset-card {
        display: flex;
        align-items: flex-start;
        gap: 14px;
        text-align: left;
        cursor: pointer;
        width: 100%;
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: var(--radius);
        padding: 16px 20px;
        box-shadow: var(--shadow-sm);
        transition:
            box-shadow var(--transition),
            background var(--transition),
            border-color var(--transition);
        font-family: inherit;
        color: inherit;
    }
    .preset-card:hover:not(:disabled) {
        background: var(--bubble-strong);
        box-shadow: var(--shadow-md);
    }
    .preset-card.active {
        background: var(--bubble-strong);
        border-color: var(--border);
        box-shadow: var(--bubble-glow);
    }
    .preset-card:disabled {
        opacity: 0.55;
        cursor: wait;
    }

    /* ── Radio ── */
    .radio-col {
        padding-top: 2px;
        flex-shrink: 0;
    }
    .radio {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 18px;
        height: 18px;
        border-radius: 50%;
        border: 2px solid var(--text-muted);
        transition: border-color var(--transition);
    }
    .radio.checked {
        border-color: var(--text);
    }
    .radio-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: var(--text);
    }

    /* ── Preset Content ── */
    .preset-body {
        flex: 1;
        min-width: 0;
    }
    .preset-top {
        display: flex;
        align-items: baseline;
        gap: 8px;
        margin-bottom: 4px;
    }
    .preset-name {
        font-size: 15px;
        font-weight: 600;
        color: var(--text);
    }
    .preset-arch {
        font-size: 12px;
        font-weight: 500;
        color: var(--text-muted);
    }
    .preset-desc {
        font-size: 13px;
        color: var(--text-secondary);
        line-height: 1.45;
        margin: 0 0 10px;
    }

    /* ── Use-case columns ── */
    .use-case-row {
        display: flex;
        gap: 20px;
        margin-bottom: 12px;
    }
    .use-case-col {
        flex: 1;
        min-width: 0;
    }
    .use-case-label {
        display: block;
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 4px;
    }
    .use-case-label.good { color: var(--text-secondary); }
    .use-case-label.avoid { color: var(--text-muted); }
    .use-case-list {
        list-style: none;
        padding: 0;
        margin: 0;
        font-size: 12.5px;
        line-height: 1.55;
        color: var(--text-secondary);
    }
    .use-case-list.muted { color: var(--text-muted); }
    .use-case-list li::before {
        content: '';
        display: inline-block;
        width: 4px;
        height: 4px;
        border-radius: 50%;
        background: currentColor;
        opacity: 0.4;
        margin-right: 7px;
        vertical-align: middle;
        position: relative;
        top: -1px;
    }

    /* ── Footer: specs + mode pills ── */
    .preset-footer {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding-top: 10px;
        border-top: 1px solid var(--border-subtle);
    }
    .preset-specs {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 11.5px;
        font-family: var(--font-mono);
        color: var(--text-muted);
    }
    .spec-sep {
        width: 3px;
        height: 3px;
        border-radius: 50%;
        background: var(--text-muted);
        opacity: 0.4;
    }
    .preset-modes {
        display: flex;
        align-items: center;
        gap: 4px;
        flex-shrink: 0;
    }
    .mode-pill {
        font-size: 10.5px;
        font-weight: 500;
        color: var(--text-muted);
        background: var(--accent-subtle);
        padding: 2px 8px;
        border-radius: var(--radius-pill);
        text-transform: capitalize;
    }

    /* ── Switch feedback ── */
    .switch-banner {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-top: 10px;
        padding: 10px 16px;
        border-radius: var(--radius-sm);
        background: var(--accent-subtle);
        font-size: 13px;
        color: var(--text-secondary);
    }
    .switch-banner.error {
        color: var(--error);
        background: rgba(207, 34, 46, 0.05);
    }
    .switch-spinner {
        width: 14px;
        height: 14px;
        border: 2px solid var(--border);
        border-top-color: var(--text-secondary);
        border-radius: 50%;
        animation: spin 0.7s linear infinite;
        flex-shrink: 0;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    /* ── Status ── */
    .status-grid { display: flex; flex-direction: column; gap: 6px; }
    .solo-note {
        font-size: 13px;
        color: var(--text-muted);
        padding: 10px 16px;
        background: var(--bubble);
        border: var(--bubble-border);
        border-radius: var(--radius-sm);
    }

    /* ── Config cards ── */
    .config-card {
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: var(--radius);
        padding: 14px 18px;
        box-shadow: var(--shadow-xs);
        margin-bottom: 8px;
    }
    .config-card-title {
        font-size: 12px;
        font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 6px;
    }
    .config-row {
        display: flex;
        justify-content: space-between;
        padding: 4px 0;
        font-size: 13px;
    }
    .config-key {
        color: var(--text-secondary);
        text-transform: capitalize;
    }
    .config-val {
        color: var(--text);
        font-family: var(--font-mono);
        font-size: 12px;
    }

    /* ── Toggle rows ── */
    .toggle-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        padding: 14px 18px;
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: var(--radius);
        box-shadow: var(--shadow-xs);
        cursor: pointer;
    }
    .toggle-label { flex: 1; min-width: 0; }
    .toggle-name {
        display: block;
        font-size: 14px;
        font-weight: 550;
        color: var(--text);
        margin-bottom: 2px;
    }
    .toggle-desc {
        display: block;
        font-size: 12.5px;
        color: var(--text-muted);
        line-height: 1.4;
    }
    .toggle-switch {
        position: relative;
        width: 40px;
        height: 22px;
        border-radius: 999px;
        border: none;
        background: var(--border);
        cursor: pointer;
        flex-shrink: 0;
        transition: background var(--transition);
        padding: 0;
    }
    .toggle-switch.on {
        background: var(--text-secondary);
    }
    .toggle-knob {
        position: absolute;
        top: 2px;
        left: 2px;
        width: 18px;
        height: 18px;
        border-radius: 50%;
        background: var(--bg);
        transition: transform var(--transition);
        box-shadow: 0 1px 3px rgba(0,0,0,0.15);
    }
    .toggle-switch.on .toggle-knob {
        transform: translateX(18px);
    }

    /* ── Context Size Slider ── */
    .slider-container {
        display: flex;
        align-items: center;
        gap: 10px;
        flex: 1;
        max-width: 280px;
    }
    .slider-container input[type="range"] {
        flex: 1;
        height: 4px;
        appearance: none;
        -webkit-appearance: none;
        background: var(--border);
        border-radius: 2px;
        outline: none;
        cursor: pointer;
    }
    .slider-container input[type="range"]::-webkit-slider-thumb {
        appearance: none;
        -webkit-appearance: none;
        width: 16px;
        height: 16px;
        border-radius: 50%;
        background: var(--text);
        border: 2px solid var(--bg);
        box-shadow: 0 1px 3px rgba(0,0,0,0.2);
        cursor: pointer;
    }
    .slider-container input[type="range"]::-moz-range-thumb {
        width: 16px;
        height: 16px;
        border-radius: 50%;
        background: var(--text);
        border: 2px solid var(--bg);
        box-shadow: 0 1px 3px rgba(0,0,0,0.2);
        cursor: pointer;
    }
    .slider-value {
        font-family: var(--font-mono);
        font-size: 13px;
        font-weight: 600;
        color: var(--text);
        min-width: 36px;
        text-align: right;
    }

    /* ── Restart Notice ── */
    .restart-notice {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin-top: 8px;
        padding: 10px 16px;
        border-radius: var(--radius-sm);
        background: rgba(210, 153, 34, 0.08);
        border: 1px solid rgba(210, 153, 34, 0.2);
        font-size: 13px;
        color: var(--text-secondary);
    }
    .restart-btn {
        flex-shrink: 0;
        padding: 5px 14px;
        font-size: 12px;
        font-weight: 600;
        font-family: inherit;
        color: var(--bg);
        background: var(--text-secondary);
        border: none;
        border-radius: var(--radius-sm);
        cursor: pointer;
        transition: opacity var(--transition);
    }
    .restart-btn:hover:not(:disabled) {
        opacity: 0.85;
    }
    .restart-btn:disabled {
        opacity: 0.5;
        cursor: wait;
    }
</style>
