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

    /* ── Modes state ── */
    interface ModeDefinition {
        name: string;
        route_id: string;
        description: string;
        detected_lang: string;
        priority: number;
        patterns: string[];
        negative_patterns: string[];
        task_overrides: Record<string, number>;
    }
    let modes = $state<ModeDefinition[]>([]);
    let modesDirty = $state<Record<string, boolean>>({});
    let modesSaving = $state<Record<string, boolean>>({});
    let modesSaveError = $state<Record<string, string>>({});
    let modeEdits = $state<Record<string, Record<string, number>>>({});

    async function loadModes() {
        try {
            const res = await fetch('/api/modes');
            const data = await res.json();
            modes = data.modes ?? [];
            // Initialize edits from current task_overrides
            modeEdits = Object.fromEntries(
                modes.map(m => [m.name, { ...m.task_overrides }])
            );
        } catch (e) {
            // silent — modes section just won't show
        }
    }

    async function saveMode(name: string) {
        modesSaving[name] = true;
        modesSaveError[name] = '';
        try {
            const res = await fetch(`/api/modes/${name}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task_overrides: modeEdits[name] }),
            });
            const data = await res.json();
            if (data.error) throw new Error(data.error);
            modesDirty[name] = false;
        } catch (e: any) {
            modesSaveError[name] = e.message || 'Failed to save';
        } finally {
            modesSaving[name] = false;
        }
    }

    function updateModeOverride(modeName: string, key: string, value: number) {
        if (!modeEdits[modeName]) modeEdits[modeName] = {};
        modeEdits[modeName][key] = value;
        modesDirty[modeName] = true;
    }

    /* ── Prompts state ── */
    const PROMPT_LABELS: Record<string, string> = {
        generator_text:        'Chat & Direct Answers',
        generator_code:        'Code Generator',
        generator_design:      'Design Generator',
        generator_computer:    'Computer Mode',
        generator_edit:        'Code Editor',
        generator_discuss:     'Code Discussion',
        generator_patch:       'Patch Editor',
        generator_section_edit:'Section Editor',
        code_fewshot:          'Code Examples',
        design_fewshot:        'Design Examples',
        design_toolkit:        'Design Toolkit',
        complexity_brief:      'Brief Response Style',
        complexity_moderate:   'Moderate Response Style',
        complexity_deep:       'Detailed Response Style',
        inline_planning_suffix:'Planning Instructions',
        inline_verify_suffix:  'Verification Instructions',
        refine:                'Design Refiner',
        refine_css:            'CSS Refiner',
        refine_targeted:       'Targeted Refiner',
        reflection_prompt:     'Self-Reflection',
        solo_plan:             'Task Planner',
        spec_generator:        'Spec Generator',
        task_plan:             'Task Planning',
        tension_prompt:        'Design Tension',
        brain_system:          'Brain System',
        mind_system:           'Mind System',
    };

    let prompts = $state<Record<string, string>>({});
    let promptsExpanded = $state<Record<string, boolean>>({});
    let promptEdits = $state<Record<string, string>>({});
    let promptsDirty = $state<Record<string, boolean>>({});
    let promptsSaving = $state<Record<string, boolean>>({});
    let promptsSaved = $state<Record<string, boolean>>({});  // shows "restart required" after save
    let promptsSaveError = $state<Record<string, string>>({});
    let promptsResetting = $state<Record<string, boolean>>({});

    async function loadPrompts() {
        try {
            const res = await fetch('/api/prompts');
            if (!res.ok) return;
            const data = await res.json();
            prompts = data.prompts ?? {};
            promptEdits = { ...prompts };
        } catch (e) {
            // silent
        }
    }

    function togglePrompt(name: string) {
        promptsExpanded[name] = !promptsExpanded[name];
    }

    function editPrompt(name: string, value: string) {
        promptEdits[name] = value;
        promptsDirty[name] = promptEdits[name] !== prompts[name];
        promptsSaved[name] = false;
        promptsSaveError[name] = '';
    }

    async function savePrompt(name: string) {
        promptsSaving[name] = true;
        promptsSaveError[name] = '';
        try {
            const res = await fetch(`/api/prompts/${name}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: promptEdits[name] }),
            });
            const data = await res.json();
            if (data.error) throw new Error(data.error);
            prompts[name] = promptEdits[name];
            promptsDirty[name] = false;
            promptsSaved[name] = true;  // trigger "restart required" notice
        } catch (e: any) {
            promptsSaveError[name] = e.message || 'Failed to save';
        } finally {
            promptsSaving[name] = false;
        }
    }

    async function resetPrompt(name: string) {
        promptsResetting[name] = true;
        promptsSaveError[name] = '';
        try {
            const res = await fetch(`/api/prompts/${name}/reset`, { method: 'POST' });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Failed to reset');
            prompts[name] = data.content;
            promptEdits[name] = data.content;
            promptsDirty[name] = false;
            promptsSaved[name] = true;
        } catch (e: any) {
            promptsSaveError[name] = e.message || 'Failed to reset';
        } finally {
            promptsResetting[name] = false;
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

    let promptsOpen = $state(false);

    onMount(async () => {
        await Promise.all([loadData(), loadModes(), loadPrompts()]);
    });
</script>

<div class="settings-page" onclick={() => { if (pickerOpen) pickerOpen = false; }}>
<div class="settings-content">

    <!-- ─── Page Header ─── -->
    <div class="page-header">
        <h1 class="page-title">Settings</h1>
        <p class="page-subtitle">Configure your local AI assistant</p>
    </div>

    <!-- ═══════════════════════════════════════════════
         SECTION 1 — AI Model
         ═══════════════════════════════════════════════ -->
    <section class="section">
        <div class="section-head">
            <div class="section-head-text">
                <h2 class="section-title">AI Model</h2>
                <p class="section-desc">Choose which AI model runs on your computer. Larger models are smarter but need more memory.</p>
            </div>
            <button class="scan-btn" onclick={(e) => { e.stopPropagation(); scanModels(); }} disabled={scanning}>
                {scanning ? 'Scanning...' : 'Scan for models'}
            </button>
        </div>

        {#if loading}
            <div class="skeleton-card"></div>
        {:else}
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
                            Loading model...
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
                                No model files found.<br>
                                Place <code>.gguf</code> files in the <code>models/</code> folder, then click "Scan for models".
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
                                                <span class="drop-ctx">{formatCtx(m.context_length)} context</span>
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
                    <span>Loading model — this may take a minute...</span>
                </div>
            {/if}
            {#if switchError}
                <div class="switch-banner error"><span>{switchError}</span></div>
            {/if}
        {/if}
    </section>

    <!-- ═══════════════════════════════════════════════
         SECTION 2 — Hardware
         ═══════════════════════════════════════════════ -->
    {#if !isMac || (maxContextSize > 0 && activeModel)}
    <section class="section">
        <div class="section-head">
            <div class="section-head-text">
                <h2 class="section-title">Hardware</h2>
                <p class="section-desc">Control how your GPU and memory are used. These settings affect performance and speed.</p>
            </div>
        </div>

        <div class="card-group">
            {#if !isMac}
                <div class="card-item">
                    <div class="card-item-info">
                        <span class="card-item-name">GPU Mode</span>
                        <span class="card-item-hint">Select your graphics card type. Use Vulkan for AMD, CUDA for NVIDIA.</span>
                    </div>
                    <div class="backend-picker">
                        <button
                            class="backend-btn"
                            class:active={activeBackend === 'vulkan'}
                            onclick={() => switchBackend('vulkan')}
                            disabled={switchingBackend}
                        >Vulkan (AMD)</button>
                        <button
                            class="backend-btn"
                            class:active={activeBackend === 'cuda'}
                            onclick={() => switchBackend('cuda')}
                            disabled={switchingBackend}
                        >CUDA (NVIDIA)</button>
                    </div>
                    {#if backendError}
                        <p class="inline-error">{backendError}</p>
                    {/if}
                    {#if switchingBackend}
                        <p class="inline-info">Switching...</p>
                    {/if}
                </div>
            {/if}

            {#if maxContextSize > 0 && activeModel}
                <div class="card-item">
                    <div class="card-item-info">
                        <span class="card-item-name">Memory Window</span>
                        <span class="card-item-hint">How much of the conversation the AI can see at once. Larger values let the AI remember more, but use more GPU memory.</span>
                    </div>
                    <div class="slider-row">
                        <input type="range"
                            min={CONTEXT_MIN_FLOOR}
                            max={maxContextSize}
                            bind:value={contextSize}
                        />
                        <span class="slider-value">{Math.round(contextSize / 1024)}K tokens</span>
                    </div>
                </div>
            {/if}
        </div>

        {#if needsRestart}
            <div class="restart-notice">
                <span>Restart the model to apply changes.</span>
                <button onclick={restartModel} class="restart-btn" disabled={switching}>Restart Now</button>
            </div>
        {/if}
    </section>
    {/if}

    <!-- ═══════════════════════════════════════════════
         SECTION 3 — Response Tuning (Modes)
         ═══════════════════════════════════════════════ -->
    {#if modes.length > 0}
    <section class="section">
        <div class="section-head">
            <div class="section-head-text">
                <h2 class="section-title">Response Tuning</h2>
                <p class="section-desc">Adjust how the AI behaves in each mode. Move the sliders to change its personality — more creative, more focused, or more varied.</p>
            </div>
        </div>

        <div class="modes-list">
            {#each modes as mode (mode.name)}
                <div class="mode-card">
                    <div class="mode-header">
                        <span class="mode-name">{mode.name}</span>
                        {#if mode.description}
                            <span class="mode-desc">{mode.description}</span>
                        {/if}
                    </div>

                    <div class="mode-sliders">
                        {#each [['temperature', 0, 2, 0.05, 'Creativity', 'More predictable responses on the left, more surprising and original on the right.'], ['top_p', 0, 1, 0.05, 'Focus', 'Narrow, precise word choices on the left, broader and more diverse on the right.'], ['presence_penalty', -2, 2, 0.05, 'Variety', 'Lower values may repeat phrases. Higher values push the AI to use different words.']] as [key, min, max, step, label, desc]}
                            {@const val = (modeEdits[mode.name]?.[key as string] ?? mode.task_overrides[key as string])}
                            {#if val !== undefined}
                            <div class="slider-block">
                                <div class="slider-label-row">
                                    <span class="slider-label">{label}</span>
                                    <span class="slider-tech">{key}</span>
                                    <span class="slider-value">{(modeEdits[mode.name]?.[key as string] ?? val).toFixed(2)}</span>
                                </div>
                                <p class="slider-hint">{desc}</p>
                                <input type="range"
                                    class="full-slider"
                                    min={min}
                                    max={max}
                                    step={step}
                                    value={val}
                                    oninput={(e) => updateModeOverride(mode.name, key as string, Number((e.target as HTMLInputElement).value))}
                                />
                            </div>
                            {/if}
                        {/each}
                    </div>

                    {#if modesDirty[mode.name] || modesSaveError[mode.name]}
                    <div class="mode-footer">
                        {#if modesSaveError[mode.name]}
                            <span class="inline-error">{modesSaveError[mode.name]}</span>
                        {/if}
                        <button
                            class="save-btn"
                            onclick={() => saveMode(mode.name)}
                            disabled={modesSaving[mode.name]}
                        >{modesSaving[mode.name] ? 'Saving...' : 'Save Changes'}</button>
                    </div>
                    {/if}
                </div>
            {/each}
        </div>
    </section>
    {/if}

    <!-- ═══════════════════════════════════════════════
         SECTION 4 — Quality Features
         ═══════════════════════════════════════════════ -->
    <section class="section">
        <div class="section-head">
            <div class="section-head-text">
                <h2 class="section-title">Quality Features</h2>
                <p class="section-desc">Optional features that can improve output quality. These may increase generation time.</p>
            </div>
        </div>

        <div class="card-group">
            <label class="toggle-card">
                <span class="toggle-info">
                    <span class="toggle-name">Design Refinement</span>
                    <span class="toggle-hint">When generating websites or designs, the AI will review and polish its output in a second pass. Takes longer, but produces higher quality results.</span>
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

            <label class="toggle-card atlas-master">
                <span class="toggle-info">
                    <span class="toggle-name">Atlas Mode <span class="beta-badge">Beta</span></span>
                    <span class="toggle-hint">The AI generates multiple answers and picks the best one. Significantly improves quality for complex tasks, but takes longer.</span>
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
                <div class="atlas-sub-group">
                    <div class="atlas-row">
                        <div class="card-item-info">
                            <span class="card-item-name">Quality vs Speed</span>
                            <span class="card-item-hint">Let the AI decide how much effort to spend, or set it manually.</span>
                        </div>
                        <select
                            class="atlas-select"
                            value={$preferences.atlasEffortMode}
                            onchange={(e) => preferences.update(p => ({ ...p, atlasEffortMode: (e.target as HTMLSelectElement).value as 'auto' | 'manual' }))}
                        >
                            <option value="auto">Automatic</option>
                            <option value="manual">Manual</option>
                        </select>
                    </div>

                    {#if $preferences.atlasEffortMode === 'manual'}
                        <div class="atlas-row">
                            <div class="card-item-info">
                                <span class="card-item-name">Quality Level</span>
                                <span class="card-item-hint">1 = fastest, 5 = highest quality.</span>
                            </div>
                            <div class="slider-row compact">
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

                    <label class="toggle-card sub">
                        <span class="toggle-info">
                            <span class="toggle-name">Auto-Check Output</span>
                            <span class="toggle-hint">Verify the answer meets your request before showing it.</span>
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

                    <label class="toggle-card sub">
                        <span class="toggle-info">
                            <span class="toggle-name">Compare Multiple Answers</span>
                            <span class="toggle-hint">Evaluate answers from different angles before picking the best one.</span>
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

                    <label class="toggle-card sub">
                        <span class="toggle-info">
                            <span class="toggle-name">Auto-Improve</span>
                            <span class="toggle-hint">Automatically fix and polish the output until it's ready.</span>
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
        </div>
    </section>

    <!-- ═══════════════════════════════════════════════
         SECTION 5 — System Prompts (Advanced)
         ═══════════════════════════════════════════════ -->
    {#if Object.keys(prompts).length > 0}
    <section class="section">
        <div class="section-head">
            <div class="section-head-text">
                <h2 class="section-title">System Prompts</h2>
                <p class="section-desc">Advanced: edit the built-in instructions that guide each mode. Changes require a model restart.</p>
            </div>
            <button class="collapse-btn" onclick={() => promptsOpen = !promptsOpen}>
                {promptsOpen ? 'Hide' : 'Show'}
                <span class="collapse-chevron" class:open={promptsOpen}></span>
            </button>
        </div>

        {#if promptsOpen}
        <div class="prompts-list">
            {#each Object.entries(prompts).sort(([a], [b]) => a.localeCompare(b)) as [name, _content]}
                <div class="prompt-row" class:expanded={promptsExpanded[name]}>
                    <button class="prompt-header" onclick={() => togglePrompt(name)}>
                        <span class="prompt-name">
                            <span class="prompt-label">{PROMPT_LABELS[name] ?? name}</span>
                            <span class="prompt-key">{name}</span>
                        </span>
                        <span class="prompt-chars">{(promptEdits[name] ?? _content).length} chars</span>
                        <span class="prompt-chevron" class:open={promptsExpanded[name]}></span>
                    </button>
                    {#if promptsExpanded[name]}
                        <div class="prompt-body">
                            <textarea
                                class="prompt-textarea"
                                rows="12"
                                value={promptEdits[name] ?? _content}
                                oninput={(e) => editPrompt(name, (e.target as HTMLTextAreaElement).value)}
                                spellcheck={false}
                            ></textarea>
                            {#if promptsSaved[name]}
                                <div class="prompt-restart-notice">
                                    Saved. Restart the model to apply changes.
                                </div>
                            {/if}
                            {#if promptsSaveError[name]}
                                <div class="inline-error">{promptsSaveError[name]}</div>
                            {/if}
                            <div class="prompt-actions">
                                <button
                                    class="btn-outline"
                                    onclick={() => resetPrompt(name)}
                                    disabled={promptsResetting[name] || promptsSaving[name]}
                                    title="Restore original default"
                                >{promptsResetting[name] ? 'Resetting...' : 'Reset to default'}</button>
                                {#if promptsDirty[name] || promptsSaveError[name]}
                                    <button
                                        class="save-btn"
                                        onclick={() => savePrompt(name)}
                                        disabled={promptsSaving[name]}
                                    >{promptsSaving[name] ? 'Saving...' : 'Save'}</button>
                                {/if}
                            </div>
                        </div>
                    {/if}
                </div>
            {/each}
        </div>
        {/if}
    </section>
    {/if}

    <!-- ═══════════════════════════════════════════════
         SECTION 6 — Server Status
         ═══════════════════════════════════════════════ -->
    <section class="section section-last">
        <div class="section-head">
            <div class="section-head-text">
                <h2 class="section-title">Status</h2>
            </div>
        </div>
        {#if loading}
            <div class="skeleton-row"></div>
        {:else}
            <div class="status-grid">
                <StatusIndicator label="Model" status={modelStatus} />
            </div>
        {/if}
    </section>

</div>
</div>

<style>
    /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       LAYOUT
       ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
    .settings-page {
        width: 100%;
        height: 100%;
        overflow-y: auto;
        scrollbar-width: thin;
        scrollbar-color: var(--border) transparent;
    }
    .settings-page::-webkit-scrollbar { width: 6px; }
    .settings-page::-webkit-scrollbar-track { background: transparent; }
    .settings-page::-webkit-scrollbar-thumb {
        background: var(--border);
        border-radius: 3px;
    }
    .settings-content {
        max-width: 680px;
        margin: 0 auto;
        padding: 20px 32px 64px;
    }

    /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       PAGE HEADER
       ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
    .page-header {
        margin-bottom: 36px;
    }
    .page-title {
        font-size: 22px;
        font-weight: 700;
        color: var(--text);
        margin: 0 0 4px;
        letter-spacing: -0.02em;
    }
    .page-subtitle {
        font-size: 14px;
        color: var(--text-secondary);
        margin: 0;
        line-height: 1.4;
    }

    /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       SECTIONS
       ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
    .section {
        margin-bottom: 40px;
        padding-bottom: 40px;
        border-bottom: 1px solid var(--border-subtle);
    }
    .section-last {
        border-bottom: none;
        margin-bottom: 0;
        padding-bottom: 0;
    }
    .section-head {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 16px;
        margin-bottom: 20px;
    }
    .section-head-text {
        flex: 1;
        min-width: 0;
    }
    .section-title {
        font-size: 16px;
        font-weight: 650;
        color: var(--text);
        margin: 0 0 4px;
        letter-spacing: -0.01em;
    }
    .section-desc {
        font-size: 13px;
        color: var(--text-secondary);
        margin: 0;
        line-height: 1.5;
    }

    /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       CARD GROUP — vertical stack of setting items
       ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
    .card-group {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }
    .card-item {
        display: flex;
        flex-direction: column;
        gap: 12px;
        padding: 18px 20px;
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: var(--radius);
        box-shadow: var(--shadow-xs);
    }
    .card-item-info {
        display: flex;
        flex-direction: column;
        gap: 3px;
    }
    .card-item-name {
        font-size: 14px;
        font-weight: 550;
        color: var(--text);
    }
    .card-item-hint {
        font-size: 12.5px;
        color: var(--text-secondary);
        line-height: 1.45;
    }

    /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       TOGGLE CARD — on/off switch with description
       ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
    .toggle-card {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 20px;
        padding: 18px 20px;
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: var(--radius);
        box-shadow: var(--shadow-xs);
        cursor: pointer;
    }
    .toggle-card.sub {
        padding: 14px 20px;
    }
    .toggle-info {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 4px;
    }
    .toggle-name {
        font-size: 14px;
        font-weight: 550;
        color: var(--text);
    }
    .toggle-card.sub .toggle-name {
        font-size: 13px;
    }
    .toggle-hint {
        font-size: 12.5px;
        color: var(--text-secondary);
        line-height: 1.45;
    }
    .toggle-card.sub .toggle-hint {
        font-size: 12px;
    }

    .toggle-switch {
        position: relative;
        width: 44px;
        height: 24px;
        border-radius: 999px;
        border: none;
        background: var(--border);
        cursor: pointer;
        flex-shrink: 0;
        transition: background 0.2s;
        padding: 0;
    }
    .toggle-switch.on {
        background: var(--success, #2da44e);
    }
    .toggle-knob {
        position: absolute;
        top: 3px;
        left: 3px;
        width: 18px;
        height: 18px;
        border-radius: 50%;
        background: white;
        transition: transform 0.2s;
        box-shadow: 0 1px 3px rgba(0,0,0,0.18);
    }
    .toggle-switch.on .toggle-knob {
        transform: translateX(20px);
    }

    /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       ATLAS SUB-GROUP
       ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
    .atlas-sub-group {
        display: flex;
        flex-direction: column;
        gap: 6px;
        margin-left: 16px;
        padding-left: 16px;
        border-left: 2px solid var(--border-subtle);
    }
    .atlas-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        padding: 14px 20px;
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: var(--radius);
        box-shadow: var(--shadow-xs);
    }
    .atlas-select {
        font-family: inherit;
        font-size: 13px;
        color: var(--text);
        background: var(--bg);
        border: 1px solid var(--border);
        border-radius: var(--radius-sm);
        padding: 6px 12px;
        cursor: pointer;
        outline: none;
    }
    .beta-badge {
        font-size: 10px;
        font-weight: 600;
        color: var(--text-muted);
        background: rgba(210, 153, 34, 0.12);
        border: 1px solid rgba(210, 153, 34, 0.25);
        padding: 1px 7px;
        border-radius: 9999px;
        vertical-align: middle;
        margin-left: 4px;
        text-transform: none;
        letter-spacing: 0;
    }

    /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       MODEL SELECTOR
       ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
    .model-selector { position: relative; }
    .model-box {
        display: flex;
        align-items: center;
        gap: 10px;
        width: 100%;
        padding: 14px 18px;
        background: var(--bubble);
        border: var(--bubble-border);
        border-radius: var(--radius);
        cursor: pointer;
        font-family: var(--font-mono);
        font-size: 13px;
        color: var(--text);
        text-align: left;
        box-shadow: var(--shadow-sm);
        transition: border-color 0.15s, background 0.15s, box-shadow 0.15s;
    }
    .model-box:hover:not(:disabled) {
        background: var(--bubble-strong);
        box-shadow: var(--shadow-md);
    }
    .model-box.open {
        border-color: var(--text-muted);
        box-shadow: var(--shadow-md);
    }
    .model-box:disabled { opacity: 0.55; cursor: wait; }
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
        max-height: 320px;
        overflow-y: auto;
        scrollbar-width: thin;
    }
    .drop-empty {
        padding: 20px;
        font-size: 13px;
        color: var(--text-muted);
        line-height: 1.6;
    }
    .drop-empty code {
        font-family: var(--font-mono);
        font-size: 12px;
        background: var(--surface);
        padding: 1px 5px;
        border-radius: 3px;
    }
    .drop-item {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        width: 100%;
        padding: 12px 16px;
        border: none;
        background: none;
        cursor: pointer;
        font-family: inherit;
        text-align: left;
        border-bottom: 1px solid var(--border-subtle);
        transition: background 0.15s;
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
        font-size: 13px;
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
    .drop-thinking { color: rgba(139, 92, 246, 0.75); font-weight: 500; }
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

    /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       SWITCH / LOADING FEEDBACK
       ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
    .switch-banner {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-top: 12px;
        padding: 12px 18px;
        border-radius: var(--radius);
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

    /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       MODE CARDS — Response Tuning
       ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
    .modes-list {
        display: flex;
        flex-direction: column;
        gap: 12px;
    }
    .mode-card {
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: var(--radius);
        padding: 22px 22px 18px;
        box-shadow: var(--shadow-xs);
    }
    .mode-header {
        margin-bottom: 18px;
    }
    .mode-name {
        font-size: 15px;
        font-weight: 600;
        color: var(--text);
        text-transform: capitalize;
        display: block;
        margin-bottom: 2px;
    }
    .mode-desc {
        font-size: 12.5px;
        color: var(--text-secondary);
        line-height: 1.4;
    }

    .mode-sliders {
        display: flex;
        flex-direction: column;
        gap: 18px;
    }
    .slider-block {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }
    .slider-label-row {
        display: flex;
        align-items: baseline;
        gap: 8px;
    }
    .slider-label {
        font-size: 13px;
        font-weight: 550;
        color: var(--text);
    }
    .slider-tech {
        font-size: 11px;
        font-family: var(--font-mono);
        color: var(--text-secondary);
        opacity: 0.7;
    }
    .slider-hint {
        font-size: 12px;
        color: var(--text-secondary);
        line-height: 1.4;
        margin: 0 0 4px;
    }
    .full-slider {
        width: 100%;
        height: 4px;
        appearance: none;
        -webkit-appearance: none;
        background: var(--border);
        border-radius: 2px;
        outline: none;
        cursor: pointer;
    }
    .full-slider::-webkit-slider-thumb {
        appearance: none;
        -webkit-appearance: none;
        width: 18px;
        height: 18px;
        border-radius: 50%;
        background: var(--text);
        border: 2px solid var(--bg);
        box-shadow: 0 1px 4px rgba(0,0,0,0.2);
        cursor: pointer;
    }
    .full-slider::-moz-range-thumb {
        width: 18px;
        height: 18px;
        border-radius: 50%;
        background: var(--text);
        border: 2px solid var(--bg);
        box-shadow: 0 1px 4px rgba(0,0,0,0.2);
        cursor: pointer;
    }

    .mode-footer {
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: 10px;
        margin-top: 18px;
        padding-top: 14px;
        border-top: 1px solid var(--border-subtle);
    }

    /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       SLIDERS — generic
       ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
    .slider-row {
        display: flex;
        align-items: center;
        gap: 12px;
        width: 100%;
    }
    .slider-row input[type="range"] {
        flex: 1;
        height: 4px;
        appearance: none;
        -webkit-appearance: none;
        background: var(--border);
        border-radius: 2px;
        outline: none;
        cursor: pointer;
    }
    .slider-row input[type="range"]::-webkit-slider-thumb {
        appearance: none;
        -webkit-appearance: none;
        width: 18px;
        height: 18px;
        border-radius: 50%;
        background: var(--text);
        border: 2px solid var(--bg);
        box-shadow: 0 1px 4px rgba(0,0,0,0.2);
        cursor: pointer;
    }
    .slider-row input[type="range"]::-moz-range-thumb {
        width: 18px;
        height: 18px;
        border-radius: 50%;
        background: var(--text);
        border: 2px solid var(--bg);
        box-shadow: 0 1px 4px rgba(0,0,0,0.2);
        cursor: pointer;
    }
    .slider-row.compact {
        max-width: 200px;
    }
    .slider-value {
        font-family: var(--font-mono);
        font-size: 13px;
        font-weight: 600;
        color: var(--text);
        min-width: 36px;
        text-align: right;
        flex-shrink: 0;
    }

    /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       HARDWARE
       ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
    .backend-picker {
        display: flex;
        gap: 8px;
    }
    .backend-btn {
        padding: 8px 16px;
        border: 1px solid var(--border);
        border-radius: var(--radius-sm);
        background: transparent;
        color: var(--text-muted);
        cursor: pointer;
        font-size: 13px;
        font-family: inherit;
        font-weight: 500;
        transition: all 0.15s;
    }
    .backend-btn.active {
        color: var(--text);
        border-color: var(--text-secondary);
        background: var(--surface);
        font-weight: 600;
    }
    .backend-btn:disabled { cursor: wait; opacity: 0.3; }

    .restart-notice {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin-top: 12px;
        padding: 12px 18px;
        border-radius: var(--radius);
        background: rgba(210, 153, 34, 0.08);
        border: 1px solid rgba(210, 153, 34, 0.2);
        font-size: 13px;
        color: var(--text-secondary);
    }
    .restart-btn {
        flex-shrink: 0;
        padding: 6px 16px;
        font-size: 12px;
        font-weight: 600;
        font-family: inherit;
        color: var(--bg);
        background: var(--text-secondary);
        border: none;
        border-radius: 9999px;
        cursor: pointer;
        transition: opacity 0.15s;
    }
    .restart-btn:hover:not(:disabled) { opacity: 0.85; }
    .restart-btn:disabled { opacity: 0.5; cursor: wait; }

    /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       BUTTONS — shared styles
       ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
    .scan-btn {
        font-size: 12px;
        font-weight: 600;
        padding: 6px 14px;
        border-radius: 9999px;
        border: 1px solid var(--border);
        background: var(--surface);
        color: var(--text-muted);
        cursor: pointer;
        font-family: inherit;
        transition: color 0.15s, background 0.15s;
        white-space: nowrap;
        flex-shrink: 0;
    }
    .scan-btn:hover:not(:disabled) { background: var(--bubble-strong); color: var(--text); }
    .scan-btn:disabled { opacity: 0.4; cursor: default; }

    .save-btn {
        padding: 6px 18px;
        font-size: 12px;
        font-weight: 600;
        font-family: inherit;
        color: var(--bg);
        background: var(--text-secondary);
        border: none;
        border-radius: 9999px;
        cursor: pointer;
        transition: opacity 0.15s;
    }
    .save-btn:hover:not(:disabled) { opacity: 0.85; }
    .save-btn:disabled { opacity: 0.5; cursor: wait; }

    .btn-outline {
        padding: 6px 14px;
        font-size: 12px;
        font-weight: 500;
        font-family: inherit;
        color: var(--text-secondary);
        background: transparent;
        border: 1px solid var(--border);
        border-radius: 9999px;
        cursor: pointer;
        transition: all 0.15s;
    }
    .btn-outline:hover:not(:disabled) {
        background: var(--surface);
        color: var(--text);
    }
    .btn-outline:disabled { opacity: 0.5; cursor: default; }

    .collapse-btn {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 12px;
        font-weight: 600;
        padding: 6px 14px;
        border-radius: 9999px;
        border: 1px solid var(--border);
        background: var(--surface);
        color: var(--text-muted);
        cursor: pointer;
        font-family: inherit;
        transition: color 0.15s, background 0.15s;
        white-space: nowrap;
        flex-shrink: 0;
    }
    .collapse-btn:hover { background: var(--bubble-strong); color: var(--text); }
    .collapse-chevron {
        width: 0; height: 0;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid currentColor;
        transition: transform 0.15s;
    }
    .collapse-chevron.open { transform: rotate(180deg); }

    /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       INLINE FEEDBACK
       ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
    .inline-error {
        font-size: 12px;
        color: var(--error, #e06c75);
        flex: 1;
    }
    .inline-info {
        font-size: 12px;
        color: var(--text-muted);
        margin: 4px 0 0;
    }

    /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       PROMPTS — accordion list
       ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
    .prompts-list {
        display: flex;
        flex-direction: column;
        gap: 2px;
        border: var(--bubble-border);
        border-radius: var(--radius);
        overflow: hidden;
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        box-shadow: var(--shadow-xs);
    }
    .prompt-row {
        border-bottom: 1px solid var(--border-subtle);
    }
    .prompt-row:last-child { border-bottom: none; }
    .prompt-header {
        display: flex;
        align-items: center;
        gap: 10px;
        width: 100%;
        padding: 12px 18px;
        background: none;
        border: none;
        cursor: pointer;
        font-family: inherit;
        text-align: left;
        transition: background 0.15s;
    }
    .prompt-header:hover { background: var(--bubble-strong); }
    .prompt-name {
        flex: 1;
        display: flex;
        flex-direction: column;
        gap: 2px;
        color: var(--text);
    }
    .prompt-label {
        font-size: 13px;
        font-weight: 500;
        color: var(--text);
    }
    .prompt-key {
        font-size: 11px;
        font-family: var(--font-mono);
        color: var(--text-muted);
    }
    .prompt-chars {
        font-size: 11px;
        color: var(--text-muted);
        flex-shrink: 0;
    }
    .prompt-chevron {
        flex-shrink: 0;
        width: 0; height: 0;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid var(--text-muted);
        transition: transform 0.15s;
    }
    .prompt-chevron.open { transform: rotate(180deg); }
    .prompt-body {
        padding: 0 18px 16px;
        display: flex;
        flex-direction: column;
        gap: 10px;
    }
    .prompt-textarea {
        width: 100%;
        font-family: var(--font-mono);
        font-size: 12px;
        line-height: 1.6;
        color: var(--text);
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: var(--radius-sm);
        padding: 12px 14px;
        resize: vertical;
        outline: none;
        transition: border-color 0.15s;
        box-sizing: border-box;
    }
    .prompt-textarea:focus { border-color: var(--text-muted); }
    .prompt-restart-notice {
        font-size: 12px;
        color: rgba(210, 153, 34, 0.9);
        background: rgba(210, 153, 34, 0.07);
        border: 1px solid rgba(210, 153, 34, 0.18);
        border-radius: var(--radius-sm);
        padding: 8px 14px;
    }
    .prompt-actions {
        display: flex;
        justify-content: flex-end;
        gap: 8px;
    }

    /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       LOADING / STATUS
       ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
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
    .status-grid {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }
</style>
