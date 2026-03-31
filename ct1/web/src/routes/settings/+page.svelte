<script lang="ts">
    import { onMount } from 'svelte';
    import StatusIndicator from '$lib/components/StatusIndicator.svelte';
    import { preferences } from '$lib/stores/preferences';

    const CONTEXT_MIN_FLOOR = 2048;

    let modelStatus = $state<Record<string, any>>({});
    let config = $state<Record<string, any>>({});
    let loading = $state(true);

    /* ── Model state ── */
    interface ModelFile {
        name: string;
        size_gb: number;
        thinking: boolean;
        context_length: number | null;
    }
    let availableModels = $state<ModelFile[]>([]);
    let activeModel = $state('');
    let modelFound = $state(false);
    let modelThinking = $state(false);
    let scanning = $state(false);
    let switching = $state(false);
    let switchError = $state('');
    let pickerOpen = $state(false);

    /* ── Backend state ── */
    let activeBackend = $state<'vulkan' | 'cuda'>('vulkan');
    let switchingBackend = $state(false);
    let backendError = $state('');
    const isMac = $derived(
        typeof navigator !== 'undefined' && navigator.platform.toLowerCase().includes('mac')
    );

    let contextSize = $state(0);
    let maxContextSize = $state(0);
    let runningContextSize = $state(0);
    let needsRestart = $derived(contextSize !== runningContextSize);

    /* ── Data loading ── */

    async function loadData() {
        loading = true;
        try {
            const [statusRes, configRes, modelRes, modelsRes] = await Promise.all([
                fetch('/api/status'),
                fetch('/api/config'),
                fetch('/api/model'),
                fetch('/api/models'),
            ]);
            const statusData = await statusRes.json();
            modelStatus = statusData.model ?? statusData.director ?? {};
            config = await configRes.json();
            activeBackend = (config.backend as 'vulkan' | 'cuda') ?? 'vulkan';

            const modelData = await modelRes.json();
            activeModel = modelData.active_model || '';
            modelFound = modelData.model_found ?? false;
            modelThinking = modelData.enable_thinking ?? false;

            const ggufCtx = modelData.gguf_context_length;
            const yamlCtx = modelData.context_size;
            maxContextSize = ggufCtx ?? yamlCtx ?? 4096;
            const initial = yamlCtx ?? maxContextSize;
            contextSize = Math.max(CONTEXT_MIN_FLOOR, Math.min(initial, maxContextSize));
            runningContextSize = contextSize;

            const modelsData = await modelsRes.json();
            availableModels = modelsData.models ?? [];
        } finally {
            loading = false;
        }
    }

    async function scanModels() {
        scanning = true;
        try {
            const res = await fetch('/api/models');
            availableModels = (await res.json()).models ?? [];
        } finally {
            scanning = false;
        }
    }

    async function switchBackend(backend: 'vulkan' | 'cuda') {
        if (backend === activeBackend) return;
        switchingBackend = true;
        backendError = '';
        try {
            const res = await fetch('/api/backend/select', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ backend }),
            });
            const data = await res.json();
            if (data.error) throw new Error(data.error);
            activeBackend = backend;
            await loadData();
        } catch (e: any) {
            backendError = e.message || 'Failed to switch backend';
        } finally {
            switchingBackend = false;
        }
    }

    async function selectModel(modelName: string) {
        if (modelName === activeModel) {
            pickerOpen = false;
            return;
        }
        pickerOpen = false;
        switching = true;
        switchError = '';
        try {
            const res = await fetch('/api/model/select', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model: modelName }),
            });
            const data = await res.json();
            if (data.error) {
                switchError = data.error;
            } else {
                await loadData();
            }
        } catch (e: any) {
            switchError = e.message || 'Failed to select model';
        } finally {
            switching = false;
        }
    }

    async function restartModel() {
        switching = true;
        switchError = '';
        try {
            const res = await fetch('/api/restart', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ context_size: contextSize }),
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

    function formatSize(gb: number): string {
        if (gb >= 1) return gb.toFixed(1) + ' GB';
        return Math.round(gb * 1024) + ' MB';
    }

    function formatCtx(n: number | null): string {
        if (!n) return '—';
        return n >= 1024 ? `${Math.round(n / 1024)}K` : `${n}`;
    }

    function extractParams(name: string): string {
        const m = name.match(/(\d+\.?\d*)[Bb]/);
        return m ? m[1] + 'B' : '';
    }

    onMount(loadData);
</script>

<div class="settings-page" onclick={() => { if (pickerOpen) pickerOpen = false; }}>

    <!-- ─── Model Selection ─── -->
    <section class="section">
        <div class="section-header">
            <h2 class="section-title">Model</h2>
            <button class="scan-btn" onclick={(e) => { e.stopPropagation(); scanModels(); }} disabled={scanning}>
                {scanning ? 'Scanning…' : 'Scan models'}
            </button>
        </div>

        {#if loading}
            <div class="skeleton-card"></div>
        {:else}
            <!-- Active model display -->
            <div class="model-selector" onclick={(e) => e.stopPropagation()}>
                <button
                    class="model-box"
                    class:open={pickerOpen}
                    class:assigned={modelFound}
                    onclick={() => { pickerOpen = !pickerOpen; }}
                    disabled={switching}
                >
                    <span class="model-dot" class:found={modelFound} class:empty={!activeModel}></span>
                    <span class="model-box-label">
                        {#if switching}
                            Loading model…
                        {:else if activeModel}
                            {activeModel}
                        {:else}
                            No model selected — click to choose
                        {/if}
                    </span>
                    {#if activeModel && modelThinking}
                        <span class="cap-badge thinking">thinking</span>
                    {/if}
                    {#if activeModel}
                        {@const params = extractParams(activeModel)}
                        {#if params}
                            <span class="cap-badge params">{params}</span>
                        {/if}
                    {/if}
                    <span class="box-chevron" class:open={pickerOpen}></span>
                </button>

                {#if pickerOpen}
                    <div class="model-dropdown" onclick={(e) => e.stopPropagation()}>
                        {#if availableModels.length === 0}
                            <div class="drop-empty">
                                No .gguf files found in <code>models/</code>.<br>
                                Add model files there and click "Scan models".
                            </div>
                        {:else}
                            {#each availableModels as m}
                                <button
                                    class="drop-item"
                                    class:active={activeModel === m.name}
                                    onclick={() => selectModel(m.name)}
                                >
                                    <div class="drop-main">
                                        <span class="drop-name">{m.name}</span>
                                        <div class="drop-meta">
                                            <span class="drop-size">{formatSize(m.size_gb)}</span>
                                            {#if m.context_length}
                                                <span class="drop-sep"></span>
                                                <span class="drop-ctx">{formatCtx(m.context_length)} ctx</span>
                                            {/if}
                                            {#if m.thinking}
                                                <span class="drop-sep"></span>
                                                <span class="drop-thinking">thinking</span>
                                            {/if}
                                        </div>
                                    </div>
                                    {#if activeModel === m.name}
                                        <span class="drop-check">✓</span>
                                    {/if}
                                </button>
                            {/each}
                        {/if}
                    </div>
                {/if}
            </div>

            {#if switching}
                <div class="switch-banner">
                    <div class="switch-spinner"></div>
                    <span>Loading model — this may take a minute…</span>
                </div>
            {/if}
            {#if switchError}
                <div class="switch-banner error"><span>{switchError}</span></div>
            {/if}
        {/if}
    </section>

    <!-- ─── Backend ─── -->
    {#if !isMac}
        <div class="setting-row">
            <label class="setting-label">Backend</label>
            <div class="backend-picker">
                <button
                    class="backend-btn"
                    class:active={activeBackend === 'vulkan'}
                    onclick={() => switchBackend('vulkan')}
                    disabled={switchingBackend}
                >Vulkan</button>
                <button
                    class="backend-btn"
                    class:active={activeBackend === 'cuda'}
                    onclick={() => switchBackend('cuda')}
                    disabled={switchingBackend}
                >CUDA</button>
            </div>
            {#if backendError}
                <p class="error-text">{backendError}</p>
            {/if}
            {#if switchingBackend}
                <p class="switching-text">Switching backend…</p>
            {/if}
        </div>
    {/if}

    <!-- ─── Context Size ─── -->
    {#if maxContextSize > 0 && activeModel}
        <section class="section">
            <h2 class="section-title">Context Size</h2>
            <div class="config-card">
                <div class="config-row">
                    <label>Context Window</label>
                    <div class="slider-container">
                        <input type="range"
                            min={CONTEXT_MIN_FLOOR}
                            max={maxContextSize}
                            bind:value={contextSize}
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

    <!-- ─── Atlas Mode ─── -->
    <section class="section">
        <h2 class="section-title">Atlas Mode <span class="beta-badge">Beta</span></h2>
        <label class="toggle-row">
            <span class="toggle-label">
                <span class="toggle-name">Atlas Mode</span>
                <span class="toggle-desc">Adaptive test-time compute: generates multiple candidates, selects the best, repairs failures automatically.</span>
            </span>
            <button
                class="toggle-switch"
                class:on={$preferences.atlasMode}
                onclick={() => preferences.update(p => ({ ...p, atlasMode: !p.atlasMode }))}
                role="switch"
                aria-checked={$preferences.atlasMode}
            >
                <span class="toggle-knob"></span>
            </button>
        </label>

        {#if $preferences.atlasMode}
            <div class="atlas-settings">
                <div class="atlas-row">
                    <span class="atlas-label">Effort Mode</span>
                    <select
                        class="atlas-select"
                        value={$preferences.atlasEffortMode}
                        onchange={(e) => preferences.update(p => ({ ...p, atlasEffortMode: (e.target as HTMLSelectElement).value as 'auto' | 'manual' }))}
                    >
                        <option value="auto">Auto</option>
                        <option value="manual">Manual</option>
                    </select>
                </div>

                {#if $preferences.atlasEffortMode === 'manual'}
                    <div class="atlas-row">
                        <span class="atlas-label">Effort Level</span>
                        <div class="slider-container">
                            <input type="range"
                                min="1"
                                max="5"
                                value={$preferences.atlasEffortLevel}
                                oninput={(e) => preferences.update(p => ({ ...p, atlasEffortLevel: Number((e.target as HTMLInputElement).value) }))}
                            />
                            <span class="slider-value">{$preferences.atlasEffortLevel}</span>
                        </div>
                    </div>
                {/if}

                <label class="toggle-row sub-toggle">
                    <span class="toggle-label">
                        <span class="toggle-name">Self-Verification</span>
                        <span class="toggle-desc">Automatically verify outputs against requirements before finalizing.</span>
                    </span>
                    <button
                        class="toggle-switch"
                        class:on={$preferences.atlasSelfVerification}
                        onclick={() => preferences.update(p => ({ ...p, atlasSelfVerification: !p.atlasSelfVerification }))}
                        role="switch"
                        aria-checked={$preferences.atlasSelfVerification}
                    >
                        <span class="toggle-knob"></span>
                    </button>
                </label>

                <label class="toggle-row sub-toggle">
                    <span class="toggle-label">
                        <span class="toggle-name">Multi-Perspective Review</span>
                        <span class="toggle-desc">Evaluate candidates from multiple angles before selecting the best.</span>
                    </span>
                    <button
                        class="toggle-switch"
                        class:on={$preferences.atlasMultiPerspective}
                        onclick={() => preferences.update(p => ({ ...p, atlasMultiPerspective: !p.atlasMultiPerspective }))}
                        role="switch"
                        aria-checked={$preferences.atlasMultiPerspective}
                    >
                        <span class="toggle-knob"></span>
                    </button>
                </label>

                <label class="toggle-row sub-toggle">
                    <span class="toggle-label">
                        <span class="toggle-name">Iterative Refinement</span>
                        <span class="toggle-desc">Automatically repair and refine outputs through successive iterations.</span>
                    </span>
                    <button
                        class="toggle-switch"
                        class:on={$preferences.atlasIterativeRefinement}
                        onclick={() => preferences.update(p => ({ ...p, atlasIterativeRefinement: !p.atlasIterativeRefinement }))}
                        role="switch"
                        aria-checked={$preferences.atlasIterativeRefinement}
                    >
                        <span class="toggle-knob"></span>
                    </button>
                </label>
            </div>
        {/if}
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

    <!-- ─── Configuration ─── -->
    {#if config.preset}
        <section class="section">
            <h2 class="section-title">Configuration</h2>
            <div class="config-card">
                <div class="config-row"><span class="config-key">model</span><span class="config-val">{config.model || '—'}</span></div>
                <div class="config-row"><span class="config-key">context size</span><span class="config-val">{formatCtx(config.context_size)}</span></div>
                <div class="config-row"><span class="config-key">thinking</span><span class="config-val">{config.enable_thinking ? 'enabled' : 'disabled'}</span></div>
                <div class="config-row"><span class="config-key">temperature</span><span class="config-val">{config.temperature}</span></div>
                <div class="config-row"><span class="config-key">top p</span><span class="config-val">{config.top_p}</span></div>
                <div class="config-row"><span class="config-key">presence penalty</span><span class="config-val">{config.presence_penalty}</span></div>
                <div class="config-row"><span class="config-key">port</span><span class="config-val">{config.port}</span></div>
            </div>
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

    /* ── Section header row ── */
    .section-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 12px;
    }
    .section-header .section-title { margin-bottom: 0; }
    .scan-btn {
        font-size: 11px;
        font-weight: 600;
        padding: 3px 11px;
        border-radius: 9999px;
        border: 1px solid var(--border);
        background: var(--surface);
        color: var(--text-muted);
        cursor: pointer;
        font-family: inherit;
        transition: color var(--transition), background var(--transition);
    }
    .scan-btn:hover:not(:disabled) { background: var(--bubble-strong); color: var(--text); }
    .scan-btn:disabled { opacity: 0.4; cursor: default; }

    /* ── Skeleton loading ── */
    .skeleton-card {
        height: 56px;
        border-radius: var(--radius);
        background: var(--bubble);
        animation: breathe 3s ease-in-out infinite;
    }
    .skeleton-row {
        height: 44px;
        border-radius: var(--radius-sm);
        background: var(--bubble);
        animation: breathe 3s ease-in-out infinite;
    }

    /* ── Model Selector ── */
    .model-selector { position: relative; }

    .model-box {
        display: flex;
        align-items: center;
        gap: 8px;
        width: 100%;
        padding: 12px 16px;
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: var(--radius);
        cursor: pointer;
        font-family: var(--font-mono);
        font-size: 13px;
        color: var(--text);
        text-align: left;
        box-shadow: var(--shadow-sm);
        transition:
            border-color var(--transition),
            background var(--transition),
            box-shadow var(--transition);
    }
    .model-box:hover:not(:disabled) {
        background: var(--bubble-strong);
        box-shadow: var(--shadow-md);
    }
    .model-box.open {
        border-color: var(--text-muted);
        box-shadow: var(--shadow-md);
    }
    .model-box:disabled {
        opacity: 0.55;
        cursor: wait;
    }
    .model-box-label {
        flex: 1;
        min-width: 0;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .box-chevron {
        flex-shrink: 0;
        width: 0; height: 0;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid var(--text-muted);
        transition: transform 0.15s;
    }
    .box-chevron.open { transform: rotate(180deg); }

    /* ── Capability badges ── */
    .cap-badge {
        font-size: 10px;
        font-weight: 600;
        font-family: inherit;
        padding: 2px 8px;
        border-radius: 9999px;
        flex-shrink: 0;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .cap-badge.thinking {
        color: var(--text-muted);
        background: rgba(139, 92, 246, 0.12);
        border: 1px solid rgba(139, 92, 246, 0.2);
    }
    .cap-badge.params {
        color: var(--text-muted);
        background: rgba(59, 130, 246, 0.1);
        border: 1px solid rgba(59, 130, 246, 0.18);
    }

    /* ── Model dot ── */
    .model-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        flex-shrink: 0;
    }
    .model-dot.found { background: #3fb950; }
    .model-dot.empty { background: var(--text-muted); opacity: 0.35; }

    /* ── Dropdown ── */
    .model-dropdown {
        position: absolute;
        top: calc(100% + 6px);
        left: 0;
        right: 0;
        z-index: 200;
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: var(--radius);
        box-shadow: var(--shadow-lg, var(--shadow-md));
        overflow: hidden;
        max-height: 300px;
        overflow-y: auto;
        scrollbar-width: thin;
    }
    .drop-empty {
        padding: 16px;
        font-size: 12.5px;
        color: var(--text-muted);
        line-height: 1.6;
        font-family: inherit;
    }
    .drop-empty code {
        font-family: var(--font-mono);
        font-size: 11.5px;
        background: var(--surface);
        padding: 1px 4px;
        border-radius: 3px;
    }
    .drop-item {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        width: 100%;
        padding: 10px 14px;
        border: none;
        background: none;
        cursor: pointer;
        font-family: inherit;
        text-align: left;
        border-bottom: 1px solid var(--border-subtle);
        transition: background var(--transition);
    }
    .drop-item:last-child { border-bottom: none; }
    .drop-item:hover { background: var(--bubble-strong); }
    .drop-item.active { background: rgba(63, 185, 80, 0.06); }
    .drop-main {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 3px;
    }
    .drop-name {
        font-family: var(--font-mono);
        font-size: 12.5px;
        color: var(--text);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .drop-meta {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 11px;
        color: var(--text-muted);
    }
    .drop-size { font-family: var(--font-mono); }
    .drop-ctx { font-family: var(--font-mono); }
    .drop-thinking {
        color: rgba(139, 92, 246, 0.75);
        font-weight: 500;
    }
    .drop-sep {
        width: 3px;
        height: 3px;
        border-radius: 50%;
        background: var(--text-muted);
        opacity: 0.35;
    }
    .drop-check {
        color: #3fb950;
        font-size: 14px;
        font-weight: 600;
        flex-shrink: 0;
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
        border-radius: 9999px;
        cursor: pointer;
        transition: opacity var(--transition);
    }
    .restart-btn:hover:not(:disabled) { opacity: 0.85; }
    .restart-btn:disabled { opacity: 0.5; cursor: wait; }

    /* ── Atlas Mode ── */
    .beta-badge {
        font-size: 10px;
        font-weight: 600;
        color: var(--text-muted);
        background: rgba(210, 153, 34, 0.12);
        border: 1px solid rgba(210, 153, 34, 0.25);
        padding: 1px 6px;
        border-radius: 9999px;
        vertical-align: middle;
        margin-left: 6px;
        text-transform: none;
        letter-spacing: 0;
    }
    .atlas-settings {
        display: flex;
        flex-direction: column;
        gap: 6px;
        margin-top: 8px;
    }
    .atlas-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        padding: 10px 18px;
        background: var(--bubble);
        border: var(--bubble-border);
        border-radius: var(--radius);
        box-shadow: var(--shadow-xs);
    }
    .atlas-label {
        font-size: 13px;
        font-weight: 550;
        color: var(--text);
    }
    .atlas-select {
        font-family: inherit;
        font-size: 12.5px;
        color: var(--text);
        background: var(--bg);
        border: 1px solid var(--border);
        border-radius: var(--radius-sm);
        padding: 4px 10px;
        cursor: pointer;
        outline: none;
    }
    .sub-toggle {
        padding: 10px 18px;
    }
    .sub-toggle .toggle-name {
        font-size: 13px;
    }
    .sub-toggle .toggle-desc {
        font-size: 11.5px;
    }

    /* ── Backend switcher ── */
    .setting-row {
        margin-bottom: 32px;
    }
    .setting-label {
        display: block;
        font-size: 13px;
        font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin-bottom: 12px;
    }
    .backend-picker {
        display: flex;
        gap: 0.5rem;
    }
    .backend-btn {
        padding: 0.35rem 0.9rem;
        border: 1px solid var(--border, #444);
        border-radius: 6px;
        background: transparent;
        color: inherit;
        cursor: pointer;
        font-size: 0.85rem;
        opacity: 0.6;
        transition: opacity 0.15s, border-color 0.15s;
    }
    .backend-btn.active {
        opacity: 1;
        border-color: var(--accent, #7c6af7);
    }
    .backend-btn:disabled { cursor: wait; opacity: 0.3; }
    .switching-text { font-size: 0.8rem; opacity: 0.6; margin: 0.25rem 0 0; }
</style>
