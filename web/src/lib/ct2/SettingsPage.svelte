<script lang="ts">
    import { onMount } from 'svelte';
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
    import PromptsSection from './settings/PromptsSection.svelte';
    import GenerationSection from './settings/GenerationSection.svelte';
    import TuningSection from './settings/TuningSection.svelte';
    import DesignSection from './settings/DesignSection.svelte';
    import AtlasSection from './settings/AtlasSection.svelte';
    import InterfaceSection from './settings/InterfaceSection.svelte';

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

    async function saveParam(key: string, value: number | boolean) {
        try {
            await fetch('/api/config', {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ [key]: value }),
            });
        } catch {}
    }

    let _mounted = $state(false);

    onMount(async () => {
        await Promise.all([loadData(), refreshAuthStatus()]);
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
                <GenerationSection {config} {saveParam} />

            <!-- ── RESPONSE TUNING ── -->
            {:else if activeSection === 'tuning'}
                <TuningSection />

            <!-- ── DESIGN MODE ── -->
            {:else if activeSection === 'design'}
                <DesignSection />

            <!-- ── ATLAS MODE ── -->
            {:else if activeSection === 'atlas'}
                <AtlasSection />

            <!-- ── SYSTEM PROMPTS ── -->
            {:else if activeSection === 'prompts'}
                <PromptsSection {switching} {restartModel} />

            <!-- ── INTERFACE ── -->
            {:else if activeSection === 'interface'}
                <InterfaceSection />

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
