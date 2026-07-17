<script lang="ts">
    import { onMount } from 'svelte';
    import { preferences, toggleTheme, setCt2Bg } from '$lib/stores/preferences';
    import { serverUpdate, startUpdate, isUpdating } from '$lib/stores/serverUpdate';
    import { modelSwitchCount, notifyModelSwitch } from '$lib/stores/model';
    import { setModelSwapping, clearModelSwapping } from '$lib/stores/backgroundTasks';
    import { refreshAuthStatus } from '$lib/stores/auth';
    import { showToast } from '$lib/stores/toasts';
    import StatusIndicator from '$lib/components/StatusIndicator.svelte';
    import ModelDownloader from '$lib/components/ModelDownloader.svelte';
    import './settings.css';
    import RagSection from './settings/RagSection.svelte';
    import SecuritySection from './settings/SecuritySection.svelte';
    import PlanCacheSection from './settings/PlanCacheSection.svelte';
    import WorkspacesSection from './settings/WorkspacesSection.svelte';

    const CONTEXT_MIN_FLOOR = 2048;

    let modelStatus = $state<Record<string, any>>({});
    let config = $state<Record<string, any>>({});
    let loading = $state(false);
    let activeSection = $state('model');

    interface ModelFile { name: string; size_gb: number; thinking: boolean; vision: boolean; context_length: number | null; }
    let availableModels = $state<ModelFile[]>([]);
    let activeModel = $state('');
    let modelFound = $state(false);
    let modelThinking = $state(false);
    let modelVision = $state(false);
    let scanning = $state(false);
    let modelsLoading = $state(true);
    let switching = $state(false);
    let switchError = $state('');
    let pickerOpen = $state(false);

    let activeBackend = $state<'vulkan' | 'cuda'>('vulkan');
    let switchingBackend = $state(false);
    let backendError = $state('');

    let inferenceBackend = $state<'local' | 'ollama' | 'lm_studio'>('local');
    let switchingInference = $state(false);
    let inferenceMsg = $state('');

    let gpuLayers = $state(99);
    let runningGpuLayers = $state(99);
    let flashAttn = $state(false);
    let runningFlashAttn = $state(false);
    let contBatching = $state(false);
    let runningContBatching = $state(false);
    let mtpNDraft = $state(0);
    let runningMtpNDraft = $state(0);

    const updateStatus = $derived($serverUpdate);

    let contextSize = $state(0);
    let maxContextSize = $state(0);
    let runningContextSize = $state(0);
    let needsRestart = $derived(
        contextSize !== runningContextSize
        || gpuLayers !== runningGpuLayers
        || flashAttn !== runningFlashAttn
        || contBatching !== runningContBatching
        || mtpNDraft !== runningMtpNDraft
    );

    function shortName(name: string) {
        return name.replace(/\.gguf$/i, '').replace(/[._-][Qq]\d+[_A-Za-z0-9]*$/, '');
    }
    function formatSize(gb: number) {
        return gb >= 1 ? gb.toFixed(1) + ' GB' : Math.round(gb * 1024) + ' MB';
    }
    function formatCtx(n: number | null) {
        if (!n) return '—';
        return n >= 1024 ? `${Math.round(n / 1024)}K` : `${n}`;
    }

    async function loadData() {
        loading = true;
        try {
            const [statusRes, configRes, modelRes] = await Promise.all([
                fetch('/api/status'), fetch('/api/config'), fetch('/api/model'),
            ]);
            modelStatus = (await statusRes.json()).model ?? {};
            config = await configRes.json();
            activeBackend = (config.backend as 'vulkan' | 'cuda') ?? 'vulkan';
            inferenceBackend = (config.inference_backend_preference as 'local' | 'ollama' | 'lm_studio') ?? 'local';
            flashAttn = config.flash_attn ?? false;
            contBatching = config.cont_batching ?? false;
            mtpNDraft = config.mtp_n_draft ?? 0;
            gpuLayers = config.gpu_layers ?? 99;
            runningFlashAttn = flashAttn;
            runningContBatching = contBatching;
            runningMtpNDraft = mtpNDraft;
            runningGpuLayers = gpuLayers;
            const md = await modelRes.json();
            activeModel = md.active_model || '';
            modelFound = md.model_found ?? false;
            modelThinking = md.enable_thinking ?? false;
            modelVision = md.vision_supported ?? false;
            const ggufCtx = md.gguf_context_length, yamlCtx = md.context_size;
            maxContextSize = ggufCtx ?? yamlCtx ?? 4096;
            contextSize = Math.max(CONTEXT_MIN_FLOOR, Math.min(yamlCtx ?? maxContextSize, maxContextSize));
            runningContextSize = contextSize;
        } finally { loading = false; }
        // Load model list separately — can be slow (filesystem scan)
        modelsLoading = true;
        try {
            availableModels = ((await (await fetch('/api/models')).json()).models ?? []);
        } finally { modelsLoading = false; }
    }

    async function scanModels() {
        scanning = true; modelsLoading = true;
        try { availableModels = (await (await fetch('/api/models')).json()).models ?? []; }
        finally { scanning = false; modelsLoading = false; }
    }

    // After a model load, llama-server reports `offloaded N/M layers`.
    // If N < M, the model partially fell back to CPU — usually because
    // VRAM fragmentation from prior restarts left no clean block. The
    // user sees this as throughput crashing from ~40 to a few tok/s.
    async function checkLoadHealth() {
        try {
            const res = await fetch('/api/system/gpu-status');
            const d = await res.json();
            const layers = d?.layers;
            if (layers && layers.degraded) {
                showToast(
                    `Only ${layers.offloaded}/${layers.total} layers loaded on the GPU — the rest will run on CPU and slow generation a lot. Try Hard reset (Settings → Status) to clear VRAM fragmentation.`,
                    { variant: 'warning', title: 'Degraded model load', duration: 12000 }
                );
            }
        } catch {}
    }

    async function selectModel(name: string) {
        if (name === activeModel) { pickerOpen = false; return; }
        pickerOpen = false; switching = true; switchError = '';
        setModelSwapping(shortName(name));
        try {
            const res = await fetch('/api/model/select', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: name }) });
            const d = await res.json();
            if (d.error) { switchError = d.error; } else { await loadData(); notifyModelSwitch(); await checkLoadHealth(); }
        } catch (e: any) { switchError = e.message || 'Failed'; }
        finally { switching = false; clearModelSwapping(); }
    }

    async function restartModel() {
        switching = true; switchError = '';
        serverUpdate.set({});
        promptsSaved = {};
        try {
            const res = await fetch('/api/restart', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ context_size: contextSize, n_gpu_layers: gpuLayers, flash_attn: flashAttn, cont_batching: contBatching, mtp_n_draft: mtpNDraft }) });
            const d = await res.json();
            if (d.error) { switchError = d.error; } else { runningContextSize = contextSize; runningGpuLayers = gpuLayers; runningFlashAttn = flashAttn; runningContBatching = contBatching; runningMtpNDraft = mtpNDraft; await loadData(); await checkLoadHealth(); }
        } catch (e: any) { switchError = e.message || 'Failed'; }
        finally { switching = false; }
    }

    let hardResetting = $state(false);
    async function hardResetServer() {
        if (hardResetting) return;
        hardResetting = true;
        switching = true; switchError = '';
        try {
            const res = await fetch('/api/server/hard-reset', { method: 'POST' });
            const d = await res.json();
            if (d.error) { switchError = d.error; }
            else {
                await loadData();
                const layers = d.layers;
                if (layers && layers.degraded) {
                    showToast(
                        `Hard reset complete but ${layers.offloaded}/${layers.total} layers still on GPU — driver may need a full system restart to clear VRAM.`,
                        { variant: 'warning', title: 'Still degraded', duration: 12000 }
                    );
                } else if (layers) {
                    showToast(
                        `Hard reset complete — all ${layers.total} layers on GPU.`,
                        { variant: 'success', duration: 5000 }
                    );
                }
            }
        } catch (e: any) { switchError = e.message || 'Failed'; }
        finally { hardResetting = false; switching = false; }
    }

    async function switchBackend(backend: 'vulkan' | 'cuda') {
        if (backend === activeBackend) return;
        switchingBackend = true; backendError = '';
        try {
            const res = await fetch('/api/backend/select', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ backend }) });
            const d = await res.json();
            if (d.error) throw new Error(d.error);
            activeBackend = backend; await loadData();
        } catch (e: any) { backendError = e.message || 'Failed'; }
        finally { switchingBackend = false; }
    }

    async function switchInferenceBackend(pref: 'local' | 'ollama' | 'lm_studio') {
        if (pref === inferenceBackend || switchingInference) return;
        switchingInference = true; inferenceMsg = '';
        try {
            const res = await fetch('/api/backend/preference', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ preference: pref }),
            });
            const d = await res.json();
            if (d.warning) inferenceMsg = d.warning;
            await loadData();
        } catch (e: any) {
            inferenceMsg = e.message || 'Failed to switch';
        } finally {
            switchingInference = false;
        }
    }

    // ── Generation params ──────────────────────────────────────────
    let temperature = $state(0.7);
    let topP = $state(0.9);
    let topK = $state(40);
    let presencePenalty = $state(0.2);
    let repeatPenalty = $state(1.10);

    $effect(() => {
        if (!loading && config.temperature !== undefined) {
            temperature = config.temperature ?? 0.7;
            topP = config.top_p ?? 0.9;
            topK = config.top_k ?? 40;
            presencePenalty = config.presence_penalty ?? 0.2;
            repeatPenalty = config.repeat_penalty ?? 1.10;
        }
    });

    async function saveParam(key: string, value: number | boolean) {
        try {
            await fetch('/api/config', {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ [key]: value }),
            });
        } catch {}
    }

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

    // ── System prompts ────────────────────────────────────────────
    const BEHAVIOR_KEYS = ['generator_text', 'generator_code', 'generator_design', 'generator_computer'];
    const PIPELINE_KEYS = ['generator_text_base', 'generator_code_base', 'generator_design_base', 'generator_computer_base', 'spec_generator'];
    const PROMPT_DANGER = new Set(['spec_generator']);
    const PROMPT_LABELS: Record<string, string> = {
        generator_text:          'Chat & Direct Answers',
        generator_code:          'Code Generator',
        generator_design:        'Design Generator',
        generator_computer:      'Computer Mode',
        generator_text_base:     'Chat — Core Instructions',
        generator_code_base:     'Code — Core Instructions',
        generator_design_base:   'Design — Core Instructions',
        generator_computer_base: 'Computer — Core Instructions',
        spec_generator:          'Design — Visual Spec Generator',
    };
    const PROMPT_DESCRIPTIONS: Record<string, string> = {
        generator_text:          'Tone, format, and response style for chat and direct answers.',
        generator_code:          'Instructions for writing, explaining, and editing code.',
        generator_design:        'Appearance and style guidance layered on top of the core pipeline for website and UI generation.',
        generator_computer:      'How the AI behaves when using tools to control your computer.',
        generator_text_base:     'Core pipeline instructions for chat mode. Always applied before your custom instructions.',
        generator_code_base:     'Core pipeline instructions for code mode. Always applied before your custom instructions.',
        generator_design_base:   'Core pipeline instructions for design mode. Always applied before your custom instructions.',
        generator_computer_base: 'Core pipeline instructions for computer mode. Always applied before your custom instructions.',
        spec_generator:          'Generates the visual plan — colors, fonts, and layout — before building a design. The server reads specific JSON field names from its output.',
    };

    let prompts = $state<Record<string, string>>({});
    let promptEdits = $state<Record<string, string>>({});
    let promptsDirty = $state<Record<string, boolean>>({});
    let promptsSaving = $state<Record<string, boolean>>({});
    let promptsSaved = $state<Record<string, boolean>>({});
    let promptsResetting = $state<Record<string, boolean>>({});
    let promptsSaveError = $state<Record<string, string>>({});

    async function loadPrompts() {
        try {
            const res = await fetch('/api/prompts');
            if (!res.ok) return;
            const data = await res.json();
            prompts = data.prompts ?? {};
            promptEdits = { ...prompts };
        } catch {}
    }

    function editPrompt(key: string, val: string) {
        promptEdits[key] = val;
        promptsDirty[key] = promptEdits[key] !== prompts[key];
        promptsSaved[key] = false;
        promptsSaveError[key] = '';
    }

    async function savePrompt(key: string) {
        promptsSaving[key] = true;
        promptsSaveError[key] = '';
        try {
            const res = await fetch(`/api/prompts/${key}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: promptEdits[key] }),
            });
            const d = await res.json();
            if (d.error) throw new Error(d.error);
            prompts[key] = promptEdits[key];
            promptsDirty[key] = false;
            promptsSaved[key] = true;
        } catch (e: any) {
            promptsSaveError[key] = e.message || 'Failed to save';
        } finally {
            promptsSaving[key] = false;
        }
    }

    async function resetPrompt(key: string) {
        promptsResetting[key] = true;
        promptsSaveError[key] = '';
        try {
            const res = await fetch(`/api/prompts/${key}/reset`, { method: 'POST' });
            const d = await res.json();
            if (!res.ok) throw new Error(d.detail || 'Failed to reset');
            prompts[key] = d.content;
            promptEdits[key] = d.content;
            promptsDirty[key] = false;
            promptsSaved[key] = true;
        } catch (e: any) {
            promptsSaveError[key] = e.message || 'Failed to reset';
        } finally {
            promptsResetting[key] = false;
        }
    }

    // ── Confirm reset ─────────────────────────────────────────────
    let confirmReset = $state(false);

    let _mounted = $state(false);

    onMount(async () => {
        await Promise.all([loadData(), loadModes(), loadPrompts(), refreshAuthStatus()]);
        _mounted = true;
    });

    // Keep in-sync when model is switched from the topbar quick-pick
    $effect(() => {
        $modelSwitchCount; // reactive dependency — re-fetches on every switch
        if (_mounted) loadData();
    });

    const SECTIONS = [
        { id: 'model',      label: 'Model' },
        { id: 'generation', label: 'Generation' },
        { id: 'tuning',     label: 'Response tuning' },
        { id: 'design',     label: 'Design mode' },
        { id: 'atlas',      label: 'Atlas mode' },
        { id: 'prompts',    label: 'System prompts' },
        { id: 'interface',  label: 'Interface' },
        { id: 'security',   label: 'Security' },
        { id: 'rag',        label: 'RAG' },
        { id: 'plancache',  label: 'Plan cache' },
        { id: 'workspaces', label: 'Workspaces' },
        { id: 'status',     label: 'Status' },
    ];
</script>

<div class="c2-settings">
    <!-- Left nav -->
    <nav class="c2-settings-nav">
        <div class="c2-nav-label">Settings</div>
        {#each SECTIONS as s}
            <button
                class="c2-nav-item"
                class:c2-nav-item-active={activeSection === s.id}
                onclick={() => activeSection = s.id}
            >{s.label}</button>
        {/each}
    </nav>

    <!-- Content -->
    <div class="c2-settings-content">
        <div class="c2-settings-inner">

            <!-- ── MODEL ── -->
            {#if activeSection === 'model'}
                <div class="c2-sh">
                    <h1 class="c2-sh-title">Model</h1>
                    <p class="c2-sh-sub">Choose where models come from, then pick which one to load.</p>
                </div>

                <!-- Inference source / provider -->
                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Model provider <span class="c2-param">/ inference_backend</span></div>
                        <div class="c2-row-desc">Local runs GGUF files from your <code>models</code> folder using llama.cpp (built in). Ollama and LM Studio connect to those apps if they're running on this computer — install and start them first.</div>
                    </div>
                    <div class="c2-row-control">
                        <div class="c2-seg">
                            <button
                                class="c2-seg-btn"
                                class:c2-seg-active={inferenceBackend === 'local'}
                                onclick={() => switchInferenceBackend('local')}
                                disabled={switchingInference}
                            >Local llama.cpp</button>
                            <button
                                class="c2-seg-btn"
                                class:c2-seg-active={inferenceBackend === 'ollama'}
                                onclick={() => switchInferenceBackend('ollama')}
                                disabled={switchingInference}
                            >Ollama</button>
                            <button
                                class="c2-seg-btn"
                                class:c2-seg-active={inferenceBackend === 'lm_studio'}
                                onclick={() => switchInferenceBackend('lm_studio')}
                                disabled={switchingInference}
                            >LM Studio</button>
                        </div>
                        {#if inferenceMsg}<span class="c2-inline-err">{inferenceMsg}</span>{/if}
                    </div>
                </div>

                <div class="c2-model-toolbar">
                    <button class="c2-btn-outline c2-btn-warn" onclick={restartModel} disabled={switching}>
                        {switching ? 'Restarting…' : 'Reset server'}
                    </button>
                </div>

                {#if loading}
                    <div class="c2-skeleton"></div>
                {:else}
                    <!-- Active model card -->
                    {#if activeModel}
                        <div class="c2-model-card">
                            <div class="c2-model-icon">
                                {#if switching}
                                    <span class="c2-spinner" style="width:16px;height:16px;border-width:2px;"></span>
                                {:else}
                                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                                        <rect x="2" y="2" width="20" height="20" rx="4" stroke="currentColor" stroke-width="1.6"/>
                                        <path d="M8 8h8M8 12h8M8 16h5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
                                    </svg>
                                {/if}
                            </div>
                            <div class="c2-model-info">
                                <div class="c2-model-name">{shortName(activeModel)}</div>
                                <div class="c2-model-meta">
                                    {formatSize(availableModels.find(m => m.name === activeModel)?.size_gb ?? 0)}
                                    · {formatCtx(availableModels.find(m => m.name === activeModel)?.context_length ?? null)} context
                                </div>
                            </div>
                            {#if switching}
                                <span class="c2-badge c2-badge-yellow">SWITCHING…</span>
                            {:else}
                                <span class="c2-badge c2-badge-green">LOADED</span>
                            {/if}
                        </div>
                    {/if}

                    {#if switchError}
                        <div class="c2-error-row">{switchError}</div>
                    {/if}

                    <!-- Context size row -->
                    <div class="c2-row">
                        <div class="c2-row-label">
                            <div class="c2-row-name">Context size <span class="c2-param">/ n_ctx</span></div>
                            <div class="c2-row-desc">Active window for this session. Larger values use more VRAM.</div>
                        </div>
                        <div class="c2-row-control">
                            <div class="c2-slider-wrap">
                                <input
                                    type="range"
                                    min={CONTEXT_MIN_FLOOR}
                                    max={maxContextSize}
                                    step={1024}
                                    bind:value={contextSize}
                                    class="c2-slider"
                                />
                                <div class="c2-slider-val">{formatCtx(contextSize)}</div>
                            </div>
                            {#if needsRestart}
                                <button class="c2-btn-outline c2-btn-warn" onclick={restartModel} disabled={switching}>
                                    {switching ? 'Restarting…' : 'Apply & restart'}
                                </button>
                            {/if}
                        </div>
                    </div>

                    <!-- ── Hardware ── -->
                    <div class="c2-subsection-label" style="margin-top:24px;">Hardware</div>

                    <div class="c2-row">
                        <div class="c2-row-label">
                            <div class="c2-row-name">GPU offload <span class="c2-param">/ n_gpu_layers</span></div>
                            <div class="c2-row-desc">How many model layers run on your GPU. All the way right = fully GPU-accelerated. All the way left = CPU only.</div>
                        </div>
                        <div class="c2-row-control">
                            <div class="c2-slider-wrap">
                                <input type="range" min="0" max="99" step="1" bind:value={gpuLayers} class="c2-slider" />
                                <div class="c2-slider-val">{gpuLayers === 99 ? 'All' : gpuLayers === 0 ? 'CPU' : gpuLayers}</div>
                            </div>
                        </div>
                    </div>

                    <div class="c2-row">
                        <div class="c2-row-label">
                            <div class="c2-row-name">Flash attention <span class="c2-param">/ flash_attn</span></div>
                            <div class="c2-row-desc">Faster GPU attention. Reduces VRAM usage and improves speed on most cards.</div>
                        </div>
                        <div class="c2-row-control">
                            <button class="c2-switch" class:c2-switch-on={flashAttn} onclick={() => flashAttn = !flashAttn} role="switch" aria-checked={flashAttn} aria-label="Toggle flash attention">
                                <span class="c2-switch-knob"></span>
                            </button>
                        </div>
                    </div>

                    <div class="c2-row">
                        <div class="c2-row-label">
                            <div class="c2-row-name">Continuous batching <span class="c2-param">/ cont_batching</span></div>
                            <div class="c2-row-desc">Start processing the next message before fully finishing the current one. Improves responsiveness.</div>
                        </div>
                        <div class="c2-row-control">
                            <button class="c2-switch" class:c2-switch-on={contBatching} onclick={() => contBatching = !contBatching} role="switch" aria-checked={contBatching} aria-label="Toggle continuous batching">
                                <span class="c2-switch-knob"></span>
                            </button>
                        </div>
                    </div>

                    <div class="c2-row">
                        <div class="c2-row-label">
                            <div class="c2-row-name">Multi-token prediction <span class="c2-param">/ --spec-type draft-mtp</span></div>
                            <div class="c2-row-desc">Predict 1–3 extra tokens per step using draft heads baked into the model. Speeds up generation by ~1.5–2×. Only works with MTP-variant GGUFs (e.g. Qwen3-MTP). Set to Off for standard models.</div>
                        </div>
                        <div class="c2-row-control">
                            <div class="c2-seg">
                                {#each ([0, 1, 2, 3] as const) as n}
                                    <button
                                        class="c2-seg-btn"
                                        class:c2-seg-active={mtpNDraft === n}
                                        onclick={() => mtpNDraft = n}
                                    >{n === 0 ? 'Off' : `${n}`}</button>
                                {/each}
                            </div>
                        </div>
                    </div>

                    <!-- Backend row -->
                    <div class="c2-row">
                        <div class="c2-row-label">
                            <div class="c2-row-name">GPU backend</div>
                            <div class="c2-row-desc">Vulkan works on all GPUs. CUDA requires NVIDIA.</div>
                        </div>
                        <div class="c2-row-control">
                            <div class="c2-seg">
                                {#each (['vulkan', 'cuda'] as const) as b}
                                    <button
                                        class="c2-seg-btn"
                                        class:c2-seg-active={activeBackend === b}
                                        onclick={() => switchBackend(b)}
                                        disabled={switchingBackend}
                                    >{b.charAt(0).toUpperCase() + b.slice(1)}</button>
                                {/each}
                            </div>
                            {#if backendError}<span class="c2-inline-err">{backendError}</span>{/if}
                        </div>
                    </div>

                    <!-- Other models -->
                    <div class="c2-subsection-label">Other models</div>
                    {#if modelsLoading}
                        <div class="c2-skeleton" style="height:48px;margin-bottom:6px;"></div>
                        <div class="c2-skeleton" style="height:48px;margin-bottom:6px;"></div>
                    {:else}
                        {#each availableModels.filter(m => m.name !== activeModel) as m}
                            <button class="c2-model-row" onclick={() => selectModel(m.name)} disabled={switching}>
                                <span class="c2-radio"></span>
                                <span class="c2-mr-name">{shortName(m.name)}</span>
                                {#if m.vision}<span class="c2-badge">VISION</span>{/if}
                                <span class="c2-mr-size">{formatSize(m.size_gb)}</span>
                            </button>
                        {/each}
                    {/if}
                    <div style="display:inline-flex;gap:8px;align-items:center;flex-wrap:wrap;">
                        <button class="c2-btn-ghost" onclick={scanModels} disabled={scanning || modelsLoading}>
                            {scanning ? 'Scanning…' : 'Rescan models folder'}
                        </button>
                        <ModelDownloader show={!loading && !config.external_connected} onDownloaded={scanModels} />
                    </div>

                    <div class="c2-row" style="margin-top:16px;">
                        <div class="c2-row-label">
                            <div class="c2-row-name">Update llama-server</div>
                            <div class="c2-row-desc">Download the latest llama.cpp release for the currently selected backend. The new version is used after restart.</div>
                        </div>
                        <div class="c2-row-control">
                            <button class="c2-btn-primary" onclick={() => startUpdate(activeBackend)} disabled={$isUpdating}>
                                {#if $isUpdating}
                                    Updating…
                                {:else}
                                    Update {activeBackend.charAt(0).toUpperCase() + activeBackend.slice(1)}
                                {/if}
                            </button>
                            {#if updateStatus[activeBackend]?.status === 'done'}
                                <button class="c2-btn-outline c2-btn-warn" onclick={restartModel} disabled={switching}>
                                    {switching ? 'Restarting…' : 'Restart server'}
                                </button>
                            {/if}
                            {#if updateStatus[activeBackend]?.message}
                                <span class={updateStatus[activeBackend]?.status === 'error' ? 'c2-inline-err' : 'c2-row-desc'}>
                                    {updateStatus[activeBackend]?.message}
                                </span>
                            {/if}
                        </div>
                    </div>
                {/if}

            <!-- ── GENERATION ── -->
            {:else if activeSection === 'generation'}
                <div class="c2-sh">
                    <h1 class="c2-sh-title">Generation parameters</h1>
                    <p class="c2-sh-sub">Control how the model samples tokens. Friendly labels shown alongside their technical names.</p>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Creativity <span class="c2-param">/ temperature</span></div>
                        <div class="c2-row-desc">Higher values produce more varied output. 0.7 is a balanced default.</div>
                    </div>
                    <div class="c2-row-control">
                        <div class="c2-slider-wrap">
                            <input type="range" min="0" max="2" step="0.01" bind:value={temperature} onchange={() => saveParam('temperature', temperature)} class="c2-slider" />
                            <div class="c2-slider-val">{temperature.toFixed(2)}</div>
                        </div>
                    </div>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Nucleus sampling <span class="c2-param">/ top_p</span></div>
                        <div class="c2-row-desc">Keep the smallest set of tokens whose cumulative probability meets this threshold.</div>
                    </div>
                    <div class="c2-row-control">
                        <div class="c2-slider-wrap">
                            <input type="range" min="0" max="1" step="0.01" bind:value={topP} onchange={() => saveParam('top_p', topP)} class="c2-slider" />
                            <div class="c2-slider-val">{topP.toFixed(2)}</div>
                        </div>
                    </div>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Top-K <span class="c2-param">/ top_k</span></div>
                        <div class="c2-row-desc">Restrict sampling to the K most likely tokens at each step.</div>
                    </div>
                    <div class="c2-row-control">
                        <div class="c2-slider-wrap">
                            <input type="range" min="0" max="200" step="1" bind:value={topK} onchange={() => saveParam('top_k', topK)} class="c2-slider" />
                            <div class="c2-slider-val">{topK}</div>
                        </div>
                    </div>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Presence penalty <span class="c2-param">/ presence_penalty</span></div>
                        <div class="c2-row-desc">Discourages the model from repeating tokens that already appear in the context.</div>
                    </div>
                    <div class="c2-row-control">
                        <div class="c2-slider-wrap">
                            <input type="range" min="0" max="2" step="0.01" bind:value={presencePenalty} onchange={() => saveParam('presence_penalty', presencePenalty)} class="c2-slider" />
                            <div class="c2-slider-val">{presencePenalty.toFixed(2)}</div>
                        </div>
                    </div>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Repeat penalty <span class="c2-param">/ repeat_penalty</span></div>
                        <div class="c2-row-desc">Penalizes tokens that appear repeatedly in the output. Higher values reduce looping and repetition.</div>
                    </div>
                    <div class="c2-row-control">
                        <div class="c2-slider-wrap">
                            <input type="range" min="1.0" max="1.5" step="0.01" bind:value={repeatPenalty} onchange={() => saveParam('repeat_penalty', repeatPenalty)} class="c2-slider" />
                            <div class="c2-slider-val">{repeatPenalty.toFixed(2)}</div>
                        </div>
                    </div>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Context size</div>
                        <div class="c2-row-desc">Set by the loaded model. Read-only.</div>
                    </div>
                    <div class="c2-row-control">
                        <span class="c2-readonly-val">{formatCtx(runningContextSize)} tokens</span>
                    </div>
                </div>

            <!-- ── RESPONSE TUNING ── -->
            {:else if activeSection === 'tuning'}
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

            <!-- ── DESIGN MODE ── -->
            {:else if activeSection === 'design'}
                <div class="c2-sh">
                    <h1 class="c2-sh-title">Design mode</h1>
                    <p class="c2-sh-sub">A second pass that re-reads generated HTML and refines CSS, spacing, and visual hierarchy before finalizing.</p>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">CSS refinement pass</div>
                        <div class="c2-row-desc">Adds 4–12s to design-mode responses, and meaningfully improves visual quality.</div>
                    </div>
                    <div class="c2-row-control">
                        <button
                            class="c2-switch"
                            class:c2-switch-on={$preferences.designRefinement}
                            onclick={() => preferences.update(p => ({ ...p, designRefinement: !p.designRefinement }))}
                            role="switch"
                            aria-checked={$preferences.designRefinement}
                            aria-label="Toggle CSS refinement pass"
                        >
                            <span class="c2-switch-knob"></span>
                        </button>
                    </div>
                </div>

            <!-- ── ATLAS MODE ── -->
            {:else if activeSection === 'atlas'}
                <div class="c2-sh">
                    <h1 class="c2-sh-title">Atlas mode</h1>
                    <p class="c2-sh-sub">An extended reasoning layer that runs additional exploration, verification, and perspective-taking passes.</p>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Enable Atlas</div>
                        <div class="c2-row-desc">Master toggle. When off, all sub-options are disabled.</div>
                    </div>
                    <div class="c2-row-control">
                        <button
                            class="c2-switch"
                            class:c2-switch-on={$preferences.atlasMode}
                            onclick={() => preferences.update(p => ({ ...p, atlasMode: !p.atlasMode }))}
                            role="switch"
                            aria-checked={$preferences.atlasMode}
                            aria-label="Toggle Atlas mode"
                        >
                            <span class="c2-switch-knob"></span>
                        </button>
                    </div>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Effort mode</div>
                    </div>
                    <div class="c2-row-control">
                        <div class="c2-seg">
                            {#each (['auto', 'manual'] as const) as v}
                                <button
                                    class="c2-seg-btn"
                                    class:c2-seg-active={$preferences.atlasEffortMode === v}
                                    onclick={() => preferences.update(p => ({ ...p, atlasEffortMode: v }))}
                                    disabled={!$preferences.atlasMode}
                                >{v.charAt(0).toUpperCase() + v.slice(1)}</button>
                            {/each}
                        </div>
                    </div>
                </div>

                {#if $preferences.atlasEffortMode === 'manual'}
                    <div class="c2-row">
                        <div class="c2-row-label">
                            <div class="c2-row-name">Effort level <span class="c2-param">/ atlas_effort</span></div>
                            <div class="c2-row-desc">How aggressively Atlas explores alternatives before committing.</div>
                        </div>
                        <div class="c2-row-control">
                            <div class="c2-slider-wrap">
                                <input type="range" min="1" max="5" step="1"
                                    value={$preferences.atlasEffortLevel}
                                    onchange={(e) => preferences.update(p => ({ ...p, atlasEffortLevel: Number((e.target as HTMLInputElement).value) }))}
                                    class="c2-slider"
                                    disabled={!$preferences.atlasMode}
                                />
                                <div class="c2-slider-val">{$preferences.atlasEffortLevel}</div>
                            </div>
                        </div>
                    </div>
                    <div class="c2-row">
                        <div class="c2-row-label">
                            <div class="c2-row-name">Self-verification</div>
                            <div class="c2-row-desc">Re-read the output and flag contradictions.</div>
                        </div>
                        <div class="c2-row-control">
                            <button class="c2-switch" class:c2-switch-on={$preferences.atlasSelfVerification}
                                onclick={() => preferences.update(p => ({ ...p, atlasSelfVerification: !p.atlasSelfVerification }))}
                                disabled={!$preferences.atlasMode} role="switch" aria-checked={$preferences.atlasSelfVerification}
                                aria-label="Toggle Atlas self-verification">
                                <span class="c2-switch-knob"></span>
                            </button>
                        </div>
                    </div>
                    <div class="c2-row">
                        <div class="c2-row-label">
                            <div class="c2-row-name">Multi-perspective</div>
                            <div class="c2-row-desc">Consider the problem from 3 distinct viewpoints before answering.</div>
                        </div>
                        <div class="c2-row-control">
                            <button class="c2-switch" class:c2-switch-on={$preferences.atlasMultiPerspective}
                                onclick={() => preferences.update(p => ({ ...p, atlasMultiPerspective: !p.atlasMultiPerspective }))}
                                disabled={!$preferences.atlasMode} role="switch" aria-checked={$preferences.atlasMultiPerspective}
                                aria-label="Toggle Atlas multi-perspective mode">
                                <span class="c2-switch-knob"></span>
                            </button>
                        </div>
                    </div>
                    <div class="c2-row">
                        <div class="c2-row-label">
                            <div class="c2-row-name">Iterative refinement</div>
                            <div class="c2-row-desc">Run additional polishing passes until no more changes are proposed.</div>
                        </div>
                        <div class="c2-row-control">
                            <button class="c2-switch" class:c2-switch-on={$preferences.atlasIterativeRefinement}
                                onclick={() => preferences.update(p => ({ ...p, atlasIterativeRefinement: !p.atlasIterativeRefinement }))}
                                disabled={!$preferences.atlasMode} role="switch" aria-checked={$preferences.atlasIterativeRefinement}
                                aria-label="Toggle Atlas iterative refinement">
                                <span class="c2-switch-knob"></span>
                            </button>
                        </div>
                    </div>
                {/if}

            <!-- ── SYSTEM PROMPTS ── -->
            {:else if activeSection === 'prompts'}
                <div class="c2-sh">
                    <h1 class="c2-sh-title">System prompts</h1>
                    <p class="c2-sh-sub">Instructions that guide the AI in each mode. Everything is editable. Prompts marked with a warning affect how the server processes output — edit those carefully.</p>
                </div>
                <div class="c2-prompts-restart-row">
                    <span>Changes take effect after restarting the server.</span>
                    <button class="c2-btn-outline c2-btn-warn" onclick={restartModel} disabled={switching}>
                        {switching ? 'Restarting…' : 'Restart server'}
                    </button>
                </div>

                <!-- Behavior group -->
                <div class="c2-prompt-group-header">
                    <span class="c2-prompt-group-label">Behavior</span>
                    <span class="c2-prompt-group-desc">How the AI talks and responds in each mode. Edit freely.</span>
                </div>
                {#each BEHAVIOR_KEYS.filter(k => k in prompts) as key}
                    <div class="c2-prompt-card">
                        <div class="c2-prompt-card-header">
                            <span class="c2-prompt-card-name">{PROMPT_LABELS[key] ?? key}</span>
                            {#if PROMPT_DESCRIPTIONS[key]}
                                <span class="c2-prompt-card-desc">{PROMPT_DESCRIPTIONS[key]}</span>
                            {/if}
                            <span class="c2-prompt-card-key">{key}</span>
                        </div>
                        <textarea
                            class="c2-prompt-textarea"
                            rows="10"
                            value={promptEdits[key] ?? ''}
                            oninput={(e) => editPrompt(key, (e.target as HTMLTextAreaElement).value)}
                            spellcheck={false}
                            placeholder="Enter custom instructions..."
                        ></textarea>
                        {#if promptsSaved[key]}
                            <div class="c2-prompt-saved-notice">
                                Saved — restart the server to apply changes.
                                <button class="c2-prompt-restart-inline" onclick={restartModel} disabled={switching}>{switching ? 'Restarting…' : 'Restart now'}</button>
                            </div>
                        {/if}
                        {#if promptsSaveError[key]}
                            <div class="c2-inline-err">{promptsSaveError[key]}</div>
                        {/if}
                        <div class="c2-prompt-footer">
                            <button
                                class="c2-btn-ghost"
                                onclick={() => resetPrompt(key)}
                                disabled={promptsResetting[key] || promptsSaving[key]}
                            >{promptsResetting[key] ? 'Resetting…' : 'Reset to default'}</button>
                            {#if promptsDirty[key] || promptsSaveError[key]}
                                <button
                                    class="c2-btn-primary"
                                    onclick={() => savePrompt(key)}
                                    disabled={promptsSaving[key]}
                                >{promptsSaving[key] ? 'Saving…' : 'Save'}</button>
                            {/if}
                        </div>
                    </div>
                {/each}

                <!-- Pipeline group -->
                <div class="c2-prompt-group-header" style="margin-top:8px;">
                    <span class="c2-prompt-group-label">Pipeline</span>
                    <span class="c2-prompt-group-desc">Core instructions always active in each mode, plus the design planner. Edit only if you understand how the pipeline works.</span>
                </div>
                {#each PIPELINE_KEYS.filter(k => k in prompts) as key}
                    {@const isDanger = PROMPT_DANGER.has(key)}
                    <div class="c2-prompt-card">
                        <div class="c2-prompt-card-header">
                            <span class="c2-prompt-card-name">
                                {PROMPT_LABELS[key] ?? key}
                                {#if isDanger}<span class="c2-prompt-danger-badge">⚠ breaking if changed</span>{/if}
                            </span>
                            {#if PROMPT_DESCRIPTIONS[key]}
                                <span class="c2-prompt-card-desc">{PROMPT_DESCRIPTIONS[key]}</span>
                            {/if}
                            <span class="c2-prompt-card-key">{key}</span>
                        </div>
                        {#if isDanger}
                            <div class="c2-prompt-danger-notice">
                                ⚠ Warning: This prompt's output is read by the server as JSON. You can change the wording, but do not rename, add, or remove any output field names — that will break design mode generation.
                            </div>
                        {/if}
                        <textarea
                            class="c2-prompt-textarea"
                            rows="10"
                            value={promptEdits[key] ?? ''}
                            oninput={(e) => editPrompt(key, (e.target as HTMLTextAreaElement).value)}
                            spellcheck={false}
                        ></textarea>
                        {#if promptsSaved[key]}
                            <div class="c2-prompt-saved-notice">
                                Saved — restart the server to apply changes.
                                <button class="c2-prompt-restart-inline" onclick={restartModel} disabled={switching}>{switching ? 'Restarting…' : 'Restart now'}</button>
                            </div>
                        {/if}
                        {#if promptsSaveError[key]}
                            <div class="c2-inline-err">{promptsSaveError[key]}</div>
                        {/if}
                        <div class="c2-prompt-footer">
                            <button
                                class="c2-btn-ghost"
                                onclick={() => resetPrompt(key)}
                                disabled={promptsResetting[key] || promptsSaving[key]}
                            >{promptsResetting[key] ? 'Resetting…' : 'Reset to default'}</button>
                            {#if promptsDirty[key] || promptsSaveError[key]}
                                <button
                                    class="c2-btn-primary"
                                    onclick={() => savePrompt(key)}
                                    disabled={promptsSaving[key]}
                                >{promptsSaving[key] ? 'Saving…' : 'Save'}</button>
                            {/if}
                        </div>
                    </div>
                {/each}

            <!-- ── INTERFACE ── -->
            {:else if activeSection === 'interface'}
                <div class="c2-sh">
                    <h1 class="c2-sh-title">Interface</h1>
                    <p class="c2-sh-sub">Appearance and app-level preferences.</p>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Theme</div>
                    </div>
                    <div class="c2-row-control">
                        <div class="c2-seg">
                            {#each (['dark', 'light'] as const) as v}
                                <button
                                    class="c2-seg-btn"
                                    class:c2-seg-active={$preferences.theme === v}
                                    onclick={toggleTheme}
                                >{v.charAt(0).toUpperCase() + v.slice(1)}</button>
                            {/each}
                        </div>
                    </div>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Background <span class="c2-param">/ ct2Bg</span></div>
                        <div class="c2-row-desc">The ambient art image behind the interface. Flat gives a cleaner, fully dark surface.</div>
                    </div>
                    <div class="c2-row-control">
                        <div class="c2-seg">
                            <button
                                class="c2-seg-btn"
                                class:c2-seg-active={($preferences.ct2Bg ?? 'image') !== 'none'}
                                onclick={() => setCt2Bg('image')}
                            >Nature</button>
                            <button
                                class="c2-seg-btn"
                                class:c2-seg-active={($preferences.ct2Bg ?? 'image') === 'none'}
                                onclick={() => setCt2Bg('none')}
                            >Flat</button>
                        </div>
                    </div>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Web search</div>
                        <div class="c2-row-desc">Allow the model to query the web when the search pill is active.</div>
                    </div>
                    <div class="c2-row-control">
                        <button
                            class="c2-switch"
                            class:c2-switch-on={$preferences.webSearchEnabled}
                            onclick={() => preferences.update(p => ({ ...p, webSearchEnabled: !p.webSearchEnabled }))}
                            role="switch"
                            aria-checked={$preferences.webSearchEnabled}
                            aria-label="Toggle web search"
                        >
                            <span class="c2-switch-knob"></span>
                        </button>
                    </div>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Reset all settings</div>
                        <div class="c2-row-desc">Restores all generation, Atlas, and interface preferences to their defaults.</div>
                    </div>
                    <div class="c2-row-control">
                        {#if confirmReset}
                            <div style="display:inline-flex;gap:8px;">
                                <button class="c2-btn-ghost" onclick={() => confirmReset = false}>Cancel</button>
                                <button class="c2-btn-danger" onclick={() => { preferences.set({ theme: 'light', ct2Bg: 'image', showThinking: false, designRefinement: true, webSearchEnabled: false, requireCommandApproval: false, notifyOnDone: true, atlasMode: false, atlasEffortMode: 'auto', atlasEffortLevel: 3, atlasSelfVerification: true, atlasMultiPerspective: true, atlasIterativeRefinement: true }); confirmReset = false; }}>Yes, reset</button>
                            </div>
                        {:else}
                            <button class="c2-btn-outline c2-btn-err" onclick={() => confirmReset = true}>Reset…</button>
                        {/if}
                    </div>
                </div>

            <!-- ── Security ── -->
            {:else if activeSection === 'security'}
                <SecuritySection />

            <!-- ── RAG ── -->
            {:else if activeSection === 'rag'}
                <RagSection {config} {switching} {restartModel} />

            <!-- ── WORKSPACES ── -->
            <!-- ── PLAN CACHE ── -->
            {:else if activeSection === 'plancache'}
                <PlanCacheSection {config} {saveParam} />

            <!-- ── WORKSPACES ── -->
            {:else if activeSection === 'workspaces'}
                <WorkspacesSection />

            <!-- ── STATUS ── -->
            {:else if activeSection === 'status'}
                <div class="c2-sh">
                    <h1 class="c2-sh-title">Status</h1>
                </div>
                {#if loading}
                    <div class="c2-skeleton"></div>
                {:else}
                    <StatusIndicator label="Model" status={modelStatus} />

                    <div class="c2-row" style="margin-top:18px; flex-direction:column; align-items:stretch; gap:12px;">
                        <div class="c2-row-label">
                            <div class="c2-row-name">Hard reset llama-server</div>
                            <div class="c2-row-desc">If generation has slowed dramatically after a few normal restarts, the AMD Vulkan driver may be holding fragmented VRAM that prevents the model from fully loading on the GPU. Hard reset waits much longer for the driver to release memory before relaunching, then reports how many layers ended up on GPU.</div>
                        </div>
                        <button class="c2-btn-outline c2-btn-warn" style="align-self:flex-start;" onclick={hardResetServer} disabled={hardResetting}>
                            {hardResetting ? 'Hard resetting…' : 'Hard reset'}
                        </button>
                    </div>
                {/if}
            {/if}

        </div>
    </div>
</div>
