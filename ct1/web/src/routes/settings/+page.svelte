<script lang="ts">
    import { onMount } from 'svelte';
    import StatusIndicator from '$lib/components/StatusIndicator.svelte';
    import { preferences, toggleWebSearch, setUiStyle, setClassicBg, type UiStyle, type ClassicBg } from '$lib/stores/preferences';
    import { serverUpdate, startUpdate, isUpdating } from '$lib/stores/serverUpdate';
    import { modelSwitchCount, notifyModelSwitch } from '$lib/stores/model';
    import { setModelSwapping, clearModelSwapping } from '$lib/stores/backgroundTasks';
    import Ct2Settings from '$lib/ct2/SettingsPage.svelte';
    import ModelDownloader from '$lib/components/ModelDownloader.svelte';

    const CONTEXT_MIN_FLOOR = 2048;

    let modelStatus = $state<Record<string, any>>({});
    let config = $state<Record<string, any>>({});
    let loading = $state(true);

    /* ── Model state ── */
    interface ModelFile {
        name: string;
        size_gb: number;
        thinking: boolean;
        vision: boolean;
        context_length: number | null;
    }
    let availableModels = $state<ModelFile[]>([]);
    let activeModel = $state('');
    let modelFound = $state(false);
    let modelThinking = $state(false);
    let modelVision = $state(false);
    let scanning = $state(false);
    let switching = $state(false);
    let switchError = $state('');
    let pickerOpen = $state(false);

    /* ── Backend state ── */
    let activeBackend = $state<'vulkan' | 'cuda'>('vulkan');
    let switchingBackend = $state(false);
    let backendError = $state('');

    /* ── llama-server update — state lives in serverUpdate store (persists across navigation) ── */
    const updateStatus = $derived($serverUpdate);
    const isMac = $derived(
        typeof navigator !== 'undefined' && navigator.platform.toLowerCase().includes('mac')
    );

    function isUiStyle(style: UiStyle) {
        return $preferences.uiStyle === style;
    }

    function isClassicBg(bg: ClassicBg) {
        return ($preferences.classicBg ?? 'default') === bg;
    }

    let contextSize = $state(0);
    let maxContextSize = $state(0);
    let runningContextSize = $state(0);

    let gpuLayers = $state(99);
    let runningGpuLayers = $state(99);
    let flashAttn = $state(false);
    let runningFlashAttn = $state(false);
    let contBatching = $state(false);
    let runningContBatching = $state(false);

    let planCacheStats = $state<{entries:number;avg_score:number;recent:Array<{sig:string;task_type:string;complexity:string;count:number;score:number}>}>({entries:0,avg_score:0,recent:[]});
    let planCacheClearing = $state(false);
    let planCacheMsg = $state('');

    /* ── RAG state ── */
    let ragStatus = $state<Record<string, any>>({});
    let ragFiles = $state<any[]>([]);
    let ragDataFiles = $state<any[]>([]);
    let ragLoading = $state(false);
    let ragReindexing = $state(false);
    let ragUploading = $state(false);
    let ragMsg = $state('');
    let ragDragOver = $state(false);
    let ragFileInput = $state<HTMLInputElement | undefined>(undefined);
    let ragEnabling = $state(false);
    let ragNeedsRestart = $state(false);

    let needsRestart = $derived(
        contextSize !== runningContextSize
        || gpuLayers !== runningGpuLayers
        || flashAttn !== runningFlashAttn
        || contBatching !== runningContBatching
    );

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

            gpuLayers = config.gpu_layers ?? 99;
            flashAttn = config.flash_attn ?? false;
            contBatching = config.cont_batching ?? false;
            runningGpuLayers = gpuLayers;
            runningFlashAttn = flashAttn;
            runningContBatching = contBatching;

            const modelData = await modelRes.json();
            activeModel = modelData.active_model || '';
            modelFound = modelData.model_found ?? false;
            modelThinking = modelData.enable_thinking ?? false;
            modelVision = modelData.vision_supported ?? false;

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

    async function fetchPlanCache() {
        try {
            planCacheStats = await (await fetch('/api/plan-cache/stats')).json();
        } catch { /* plan cache may not be available */ }
    }

    async function clearPlanCache() {
        planCacheClearing = true; planCacheMsg = '';
        try {
            const d = await (await fetch('/api/plan-cache', { method: 'DELETE' })).json();
            planCacheMsg = d.ok ? `Cleared ${d.removed} cached plan(s).` : (d.error || 'Failed');
            await fetchPlanCache();
        } catch (e: any) {
            planCacheMsg = e.message || 'Failed';
        } finally { planCacheClearing = false; }
    }

    /* ── RAG functions ── */
    async function fetchRag() {
        ragLoading = true; ragMsg = '';
        try {
            const [statusRes, filesRes, dataRes] = await Promise.all([
                fetch('/api/rag/status'),
                fetch('/api/rag/files'),
                fetch('/api/rag/data-files'),
            ]);
            ragStatus = await statusRes.json();
            ragFiles = (await filesRes.json()).files ?? [];
            ragDataFiles = (await dataRes.json()).files ?? [];
        } catch (e: any) { ragMsg = e.message || 'Failed to load RAG status'; }
        finally { ragLoading = false; }
    }

    async function ragUpload(file: File) {
        ragUploading = true; ragMsg = '';
        try {
            const fd = new FormData();
            fd.append('file', file);
            const res = await fetch('/api/rag/upload', { method: 'POST', body: fd });
            const d = await res.json();
            if (!res.ok) { ragMsg = d.detail || 'Upload failed'; return; }
            ragMsg = `Uploaded: ${file.name}`;
            await fetchRag();
        } catch (e: any) { ragMsg = e.message || 'Upload failed'; }
        finally { ragUploading = false; }
    }

    async function ragDelete(name: string) {
        ragMsg = '';
        try {
            const res = await fetch(`/api/rag/files/${encodeURIComponent(name)}`, { method: 'DELETE' });
            if (res.ok) { ragMsg = `Removed: ${name}`; await fetchRag(); }
            else { ragMsg = 'Delete failed'; }
        } catch (e: any) { ragMsg = e.message || 'Delete failed'; }
    }

    async function ragDeleteFile(name: string) {
        ragMsg = '';
        try {
            const res = await fetch(`/api/rag/data-files/${encodeURIComponent(name)}`, { method: 'DELETE' });
            if (res.ok) { ragMsg = `Deleted: ${name}`; await fetchRag(); }
            else { ragMsg = 'Delete failed'; }
        } catch (e: any) { ragMsg = e.message || 'Delete failed'; }
    }

    async function ragReindex() {
        ragReindexing = true; ragMsg = '';
        try {
            const res = await fetch('/api/rag/reindex', { method: 'POST' });
            const d = await res.json();
            ragMsg = d.ok ? `Re-indexed: ${d.files_added} added, ${d.files_updated} updated, ${d.files_skipped} skipped` : (d.detail || 'Re-index failed');
            await fetchRag();
        } catch (e: any) { ragMsg = e.message || 'Re-index failed'; }
        finally { ragReindexing = false; }
    }

    function handleRagDrop(e: DragEvent) {
        e.preventDefault(); ragDragOver = false;
        const file = e.dataTransfer?.files?.[0];
        if (file) ragUpload(file);
    }

    function handleRagFilePick() {
        const file = ragFileInput?.files?.[0];
        if (file) { ragUpload(file); if (ragFileInput) ragFileInput.value = ''; }
    }

    async function toggleRagEnabled() {
        ragEnabling = true; ragMsg = '';
        try {
            const newVal = !ragStatus.enabled;
            const res = await fetch('/api/config', {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ rag_enabled: newVal }),
            });
            const d = await res.json();
            if (d.ok) {
                ragStatus = { ...ragStatus, enabled: newVal };
                ragNeedsRestart = true;
            } else {
                ragMsg = 'Failed to save setting.';
            }
        } catch (e: any) { ragMsg = e.message || 'Failed'; }
        finally { ragEnabling = false; }
    }

    async function restartForRag() {
        await restartModel();
        ragNeedsRestart = false;
        ragMsg = '';
        await fetchRag();
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
        const swapTarget = modelName.replace(/\.gguf$/i, '').replace(/[._-][Qq]\d+[_A-Za-z0-9]*$/, '');
        setModelSwapping(swapTarget);
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
                notifyModelSwitch();
            }
        } catch (e: any) {
            switchError = e.message || 'Failed to select model';
        } finally {
            switching = false;
            clearModelSwapping();
        }
    }

    async function restartModel() {
        switching = true;
        switchError = '';
        serverUpdate.set({});
        promptsSaved = {};
        try {
            const res = await fetch('/api/restart', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ context_size: contextSize, n_gpu_layers: gpuLayers, flash_attn: flashAttn, cont_batching: contBatching }),
            });
            const data = await res.json();
            if (data.error) {
                switchError = data.error;
            } else {
                runningContextSize = contextSize;
                runningGpuLayers = gpuLayers;
                runningFlashAttn = flashAttn;
                runningContBatching = contBatching;
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
            // Initialize edits: MODE_DEFAULTS as base so all 3 sliders always show,
            // then task_overrides on top to preserve any saved values
            modeEdits = Object.fromEntries(
                modes.map(m => [m.name, { ...(MODE_DEFAULTS[m.name] ?? {}), ...m.task_overrides }])
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

    // Shipped defaults — what each mode's task_overrides were at install time.
    // Used by the reset button so users can always recover a known-good baseline.
    const MODE_DEFAULTS: Record<string, Record<string, number>> = {
        computer: { temperature: 0.25, top_p: 0.8,  presence_penalty: 1.3 },
        design:   { temperature: 0.1,  top_p: 0.9,  presence_penalty: 0.0 },
        code:     { temperature: 0,    top_p: 1.0,  presence_penalty: 1.3 },
        direct:   { temperature: 0.5,  top_p: 0.9,  presence_penalty: 0.6 },
    };

    function resetModeToDefault(name: string) {
        const defaults = MODE_DEFAULTS[name];
        if (!defaults) return;
        modeEdits[name] = { ...defaults };
        modesDirty[name] = true;
    }

    /* ── Prompts state ── */
    const PROMPT_LABELS: Record<string, string> = {
        generator_text:              'Chat & Direct Answers',
        generator_code:              'Code Generator',
        generator_design:            'Design Generator',
        generator_computer:          'Computer Mode',
        generator_text_base:         'Chat — Core Instructions',
        generator_code_base:         'Code — Core Instructions',
        generator_design_base:       'Design — Core Instructions',
        generator_computer_base:     'Computer — Core Instructions',
        generator_edit:              'Code Editor',
        generator_discuss:           'Code Discussion',
        generator_patch:             'Patch Editor',
        generator_section_edit:      'Section Editor',
        code_fewshot:                'Code Examples',
        design_fewshot:              'Design Examples',
        design_toolkit:              'Design Toolkit',
        complexity_brief:            'Brief Response Style',
        complexity_moderate:         'Moderate Response Style',
        complexity_deep:             'Detailed Response Style',
        inline_planning_suffix:      'Planning Instructions',
        inline_verify_suffix:        'Verification Instructions',
        refine:                      'Design Refiner',
        refine_css:                  'CSS Refiner',
        refine_targeted:             'Targeted Refiner',
        reflection_prompt:           'Self-Reflection',
        solo_plan:                   'Task Planner',
        spec_generator:              'Design — Phase 0: Visual Spec Generator',
        task_plan:                   'Task Planning',
        tension_prompt:              'Design Tension',
        brain_system:                'Brain System',
        mind_system:                 'Mind System',
    };

    const BEHAVIOR_KEYS = ['generator_text', 'generator_code', 'generator_design', 'generator_computer'];
    const PIPELINE_KEYS = ['generator_text_base', 'generator_code_base', 'generator_design_base', 'generator_computer_base', 'spec_generator'];
    const PROMPT_DANGER = new Set(['spec_generator']);
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
        generator_edit:          'How the AI rewrites a selected block of code.',
        generator_discuss:       'Behavior when reviewing or discussing code.',
        generator_patch:         'How the AI applies targeted text patches.',
        generator_section_edit:  'How the AI edits a specific section of a file.',
        code_fewshot:            'Example conversations shown to the AI in code mode.',
        design_fewshot:          'Example conversations shown to the AI in design mode.',
        design_toolkit:          'Additional design components and patterns available in design mode.',
        complexity_brief:        'Instructions for short, to-the-point responses.',
        complexity_moderate:     'Instructions for normal-length responses.',
        complexity_deep:         'Instructions for thorough, in-depth responses.',
        inline_planning_suffix:  'What the AI does when planning a multi-step task inline.',
        inline_verify_suffix:    'What the AI does when verifying its own work inline.',
        refine:                  'How the AI reviews and polishes a generated design.',
        refine_css:              'How the AI polishes CSS styling.',
        refine_targeted:         'How the AI makes targeted design improvements.',
        reflection_prompt:       'Prompts the AI to review its own reasoning before responding.',
        solo_plan:               'How the AI breaks down and plans complex tasks.',
        task_plan:               'Planning instructions for computer-mode tasks.',
        tension_prompt:          'Design tension and contrast guidance.',
        brain_system:            'Core reasoning system instructions.',
        mind_system:             'Memory and context management instructions.',
    };

    let advancedPromptsOpen = $state(false);

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

    let promptsOpen = $state(true);

    /* ── Workspace management ── */
    interface Workspace { id: string; name: string; created_at: string; file_count: number; }
    let workspaces = $state<Workspace[]>([]);
    let deletingWs = $state<string | null>(null);
    let wsCreating = $state(false);
    let wsNewName = $state('');
    let wsNewInput = $state<HTMLInputElement | null>(null);

    async function loadWorkspaces() {
        try {
            const res = await fetch('/api/workspaces');
            workspaces = await res.json();
        } catch {}
    }

    function startWsCreate() {
        wsCreating = true;
        wsNewName = '';
        requestAnimationFrame(() => wsNewInput?.focus());
    }

    async function submitWsCreate() {
        const trimmed = wsNewName.trim();
        wsCreating = false;
        wsNewName = '';
        if (!trimmed) return;
        try {
            const res = await fetch('/api/workspaces', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: trimmed }),
            });
            const ws: Workspace = await res.json();
            workspaces = [ws, ...workspaces];
        } catch {}
    }

    function cancelWsCreate() { wsCreating = false; wsNewName = ''; }

    function handleWsCreateKeydown(e: KeyboardEvent) {
        if (e.key === 'Enter') submitWsCreate();
        else if (e.key === 'Escape') cancelWsCreate();
    }

    async function deleteWorkspace(id: string) {
        deletingWs = id;
        try {
            await fetch(`/api/workspaces/${id}`, { method: 'DELETE' });
            workspaces = workspaces.filter(w => w.id !== id);
            // If deleted workspace was the active one, clear from localStorage
            try {
                if (localStorage.getItem('ct2_workspace_id') === id) {
                    localStorage.removeItem('ct2_workspace_id');
                }
            } catch {}
        } finally {
            deletingWs = null;
        }
    }

    function formatWsDate(iso: string): string {
        if (!iso) return '';
        try { return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); }
        catch { return iso; }
    }

    function handleWindowClick(e: MouseEvent) {
        const target = e.target as HTMLElement | null;
        if (target?.closest('.model-selector')) return;
        if (pickerOpen) pickerOpen = false;
    }

    let _settingsMounted = $state(false);

    onMount(async () => {
        await Promise.all([loadData(), loadModes(), loadPrompts(), loadWorkspaces(), fetchPlanCache()]);
        fetchRag();
        _settingsMounted = true;
    });

    $effect(() => {
        $modelSwitchCount;
        if (_settingsMounted) { loadData(); fetchPlanCache(); fetchRag(); }
    });
</script>

<svelte:window onclick={handleWindowClick} />

{#if $preferences.uiStyle === 'ct2'}
    <Ct2Settings />
{:else}
<div class="settings-page">
<div class="settings-content">

    <!-- ═══════════════════════════════════════════════
         SECTION 1 — AI Model
         ═══════════════════════════════════════════════ -->
    <section class="section">
        <div class="section-head">
            <div class="section-head-text">
                <h2 class="section-title">AI Model</h2>
                <p class="section-desc">Choose which AI model runs on your computer. Larger models are smarter but need more memory.</p>
            </div>
            <div class="section-head-btns">
                <button class="scan-btn" onclick={(e) => { e.stopPropagation(); scanModels(); }} disabled={scanning}>
                    {scanning ? 'Scanning...' : 'Scan for models'}
                </button>
                <button class="scan-btn scan-btn-warn" onclick={restartModel} disabled={switching}>
                    {switching ? 'Restarting…' : 'Reset server'}
                </button>
            </div>
        </div>

        <ModelDownloader show={!loading && !config.external_connected} onDownloaded={scanModels} />

        {#if loading}
            <div class="skeleton-card"></div>
        {:else}
            <div class="model-selector">
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
                    {#if activeModel && modelVision}
                        <span class="cap-badge vision">vision</span>
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
                    <div class="model-dropdown">
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
                                            {#if m.vision}
                                                <span class="drop-sep"></span>
                                                <span class="drop-vision">vision</span>
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

                <div class="card-item">
                    <div class="card-item-info">
                        <span class="card-item-name">Update llama-server</span>
                        <span class="card-item-hint">Download the latest llama.cpp release for each backend. The new version is used next time you restart.</span>
                    </div>
                    <div class="backend-picker">
                        <button
                            class="backend-btn update-btn"
                            onclick={() => startUpdate('vulkan')}
                            disabled={updateStatus['vulkan']?.status === 'downloading'}
                        >
                            {#if updateStatus['vulkan']?.status === 'downloading'}
                                Updating Vulkan...
                            {:else if updateStatus['vulkan']?.status === 'done'}
                                ✓ Vulkan updated
                            {:else}
                                Update Vulkan (AMD)
                            {/if}
                        </button>
                        <button
                            class="backend-btn update-btn"
                            onclick={() => startUpdate('cuda')}
                            disabled={updateStatus['cuda']?.status === 'downloading'}
                        >
                            {#if updateStatus['cuda']?.status === 'downloading'}
                                Updating CUDA...
                            {:else if updateStatus['cuda']?.status === 'done'}
                                ✓ CUDA updated
                            {:else}
                                Update CUDA (NVIDIA)
                            {/if}
                        </button>
                    </div>
                    {#if updateStatus['vulkan']?.message || updateStatus['cuda']?.message}
                        <p class="inline-info update-msg">
                            {updateStatus['vulkan']?.message || updateStatus['cuda']?.message}
                        </p>
                    {/if}
                    {#if updateStatus['vulkan']?.status === 'done' || updateStatus['cuda']?.status === 'done'}
                        <button onclick={restartModel} class="restart-btn update-restart-btn" disabled={switching}>
                            {switching ? 'Restarting...' : 'Restart Server Now'}
                        </button>
                    {/if}
                    {#if updateStatus['vulkan']?.status === 'error' || updateStatus['cuda']?.status === 'error'}
                        <p class="inline-error">
                            {updateStatus['vulkan']?.status === 'error' ? updateStatus['vulkan'].message : updateStatus['cuda']?.message}
                        </p>
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

        <div class="card-group" style="margin-top: 8px;">
        <div class="card-item">
            <div class="card-item-info">
                <span class="card-item-name">GPU offload</span>
                <span class="card-item-hint">How many model layers run on your GPU. Drag all the way right for fully GPU-accelerated, left for CPU only.</span>
            </div>
            <div class="slider-row">
                <input type="range" min="0" max="99" bind:value={gpuLayers} />
                <span class="slider-value">{gpuLayers === 99 ? 'All on GPU' : gpuLayers === 0 ? 'CPU only' : `${gpuLayers} layers`}</span>
            </div>
        </div>

        <div class="card-item" style="flex-direction: row; align-items: center; justify-content: space-between;">
            <div class="card-item-info">
                <span class="card-item-name">Flash attention</span>
                <span class="card-item-hint">Faster GPU attention. Reduces VRAM usage and improves speed on most cards.</span>
            </div>
            <button class="toggle-switch" class:on={flashAttn} onclick={() => flashAttn = !flashAttn} type="button">
                <span class="toggle-knob"></span>
            </button>
        </div>

        <div class="card-item" style="flex-direction: row; align-items: center; justify-content: space-between;">
            <div class="card-item-info">
                <span class="card-item-name">Continuous batching</span>
                <span class="card-item-hint">Start processing the next message before fully finishing the current one. Improves responsiveness.</span>
            </div>
            <button class="toggle-switch" class:on={contBatching} onclick={() => contBatching = !contBatching} type="button">
                <span class="toggle-knob"></span>
            </button>
        </div>
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
         SECTION 2.5 — Plan Cache
    ══════════════════════════════════════════════════ -->
    {#if !(config.external_connected ?? false)}
    <section class="section">
        <div class="section-head">
            <div class="section-head-text">
                <h2 class="section-title">Plan Cache</h2>
                <p class="section-desc">Learned task signatures skip AI deliberation — the model accelerates over time.</p>
            </div>
            <span class="plan-count-badge">{planCacheStats.entries ?? '—'}</span>
        </div>

        {#if planCacheStats.recent?.length > 0}
            <div class="plan-list">
                {#each planCacheStats.recent as p}
                    <div class="plan-item">
                        <div class="plan-item-main">
                            <span class="plan-sig" title={p.sig}>{p.sig.length > 44 ? p.sig.slice(0, 42) + '…' : p.sig}</span>
                            <span class="plan-meta">{p.task_type} · {p.complexity} · ×{p.count}</span>
                        </div>
                        <span class="plan-score" style="--score:{p.score}">{p.score.toFixed(1)}</span>
                    </div>
                {/each}
            </div>
        {:else if planCacheStats.entries === 0}
            <p class="plan-empty">No cached plans yet. Each new task type the AI learns will appear here.</p>
        {/if}

        <div style="display:flex;align-items:center;gap:12px;margin-top:12px;">
            <button class="plan-clear-btn" onclick={clearPlanCache} disabled={planCacheClearing}>
                {planCacheClearing ? 'Clearing…' : 'Clear cache'}
            </button>
            {#if planCacheMsg}<span class="plan-msg">{planCacheMsg}</span>{/if}
        </div>
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
                        <div class="mode-header-text">
                            <span class="mode-name">{mode.name}</span>
                            {#if mode.description}
                                <span class="mode-desc">{mode.description}</span>
                            {/if}
                        </div>
                        {#if MODE_DEFAULTS[mode.name]}
                        <button
                            class="mode-reset-btn"
                            class:active={modesDirty[mode.name]}
                            onclick={() => resetModeToDefault(mode.name)}
                            title="Reset to defaults"
                            aria-label="Reset {mode.name} settings to defaults"
                            type="button"
                        >
                            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                                <path d="M2.5 8a5.5 5.5 0 1 0 1.1-3.3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
                                <path d="M2.5 4v4h4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
                            </svg>
                        </button>
                        {/if}
                    </div>

                    <div class="mode-sliders">
                        {#each [['temperature', 0, 2, 0.05, 'Creativity', 'More predictable responses on the left, more surprising and original on the right.'], ['top_p', 0, 1, 0.05, 'Focus', 'Narrow, precise word choices on the left, broader and more diverse on the right.'], ['presence_penalty', -2, 2, 0.05, 'Variety', 'Lower values may repeat phrases. Higher values push the AI to use different words.']] as [key, min, max, step, label, desc]}
                            {@const val = (modeEdits[mode.name]?.[key as string] ?? mode.task_overrides[key as string] ?? MODE_DEFAULTS[mode.name]?.[key as string])}
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
                    <span class="toggle-name">Web Search</span>
                    <span class="toggle-hint">Allow the AI to search the web during a response and fetch pages it decides are relevant.</span>
                </span>
                <button
                    class="toggle-switch"
                    class:on={$preferences.webSearchEnabled}
                    onclick={toggleWebSearch}
                    role="switch"
                    aria-checked={$preferences.webSearchEnabled}
                    aria-label="Toggle web search capability"
                    title="Toggle web search capability"
                >
                    <span class="toggle-knob"></span>
                </button>
            </label>

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
                    aria-label="Toggle design refinement"
                    title="Toggle design refinement"
                >
                    <span class="toggle-knob"></span>
                </button>
            </label>

            <label class="toggle-card atlas-master">
                <span class="toggle-info">
                    <span class="toggle-name">Atlas Mode</span>
                    <span class="toggle-hint">The AI generates multiple answers and picks the best one. Significantly improves quality for complex tasks, but takes longer.</span>
                </span>
                <button
                    class="toggle-switch"
                    class:on={$preferences.atlasMode}
                    onclick={() => preferences.update(p => ({ ...p, atlasMode: !p.atlasMode }))}
                    role="switch"
                    aria-checked={$preferences.atlasMode}
                    aria-label="Toggle Atlas mode"
                    title="Toggle Atlas mode"
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
                            aria-label="Toggle Atlas self verification"
                            title="Toggle Atlas self verification"
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
                            aria-label="Toggle Atlas multi perspective"
                            title="Toggle Atlas multi perspective"
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
                            aria-label="Toggle Atlas iterative refinement"
                            title="Toggle Atlas iterative refinement"
                        >
                            <span class="toggle-knob"></span>
                        </button>
                    </label>
                </div>
            {/if}
        </div>
    </section>

    <!-- ═══════════════════════════════════════════════
         SECTION 5 — System Prompts
         ═══════════════════════════════════════════════ -->
    {#if Object.keys(prompts).length > 0}
    <section class="section">
        <div class="section-head">
            <div class="section-head-text">
                <h2 class="section-title">System Prompts</h2>
                <p class="section-desc">Instructions that guide the AI in each mode. Everything is editable. Prompts marked with a warning affect how the server processes output — edit those carefully. Changes require a model restart.</p>
            </div>
            <div class="prompts-head-actions">
                <button class="scan-btn" onclick={restartModel} disabled={switching}>
                    {switching ? 'Restarting...' : 'Restart server'}
                </button>
                <button class="collapse-btn" onclick={() => promptsOpen = !promptsOpen}>
                    {promptsOpen ? 'Hide' : 'Show'}
                    <span class="collapse-chevron" class:open={promptsOpen}></span>
                </button>
            </div>
        </div>

        {#if promptsOpen}

        <!-- ── Behavior group ── -->
        <div class="prompt-group">
            <div class="prompt-group-header">
                <span class="prompt-group-title">Behavior</span>
                <span class="prompt-group-desc">How the AI talks and responds in each mode. These layer on top of the core pipeline below. Edit freely.</span>
            </div>
            <div class="prompts-list">
                {#each BEHAVIOR_KEYS.filter(k => k in prompts) as name}
                    <div class="prompt-row" class:expanded={promptsExpanded[name]}>
                        <button class="prompt-header" onclick={() => togglePrompt(name)}>
                            <span class="prompt-name">
                                <span class="prompt-label">{PROMPT_LABELS[name] ?? name}</span>
                                <span class="prompt-key">{name}</span>
                            </span>
                            <span class="prompt-chars">{(promptEdits[name] ?? prompts[name]).length} chars</span>
                            <span class="prompt-chevron" class:open={promptsExpanded[name]}></span>
                        </button>
                        {#if promptsExpanded[name]}
                            <div class="prompt-body">
                                {#if PROMPT_DESCRIPTIONS[name]}
                                    <p class="prompt-desc">{PROMPT_DESCRIPTIONS[name]}</p>
                                {/if}
                                <textarea
                                    class="prompt-textarea"
                                    rows="12"
                                    value={promptEdits[name] ?? prompts[name]}
                                    oninput={(e) => editPrompt(name, (e.target as HTMLTextAreaElement).value)}
                                    spellcheck={false}
                                    placeholder="Enter custom instructions..."
                                ></textarea>
                                {#if promptsSaved[name]}
                                    <div class="prompt-restart-notice">
                                    Saved — restart the server to apply changes.
                                    <button class="prompt-restart-inline" onclick={restartModel} disabled={switching}>{switching ? 'Restarting...' : 'Restart now'}</button>
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
        </div>

        <!-- ── Pipeline group ── -->
        <div class="prompt-group">
            <div class="prompt-group-header">
                <span class="prompt-group-title">Pipeline</span>
                <span class="prompt-group-desc">Core instructions always active in each mode, plus the design planner. Edit only if you understand how the pipeline works.</span>
            </div>
            <div class="prompts-list">
                {#each PIPELINE_KEYS.filter(k => k in prompts) as name}
                    {@const isDanger = PROMPT_DANGER.has(name)}
                    <div class="prompt-row" class:expanded={promptsExpanded[name]}>
                        <button class="prompt-header" onclick={() => togglePrompt(name)}>
                            <span class="prompt-name">
                                <span class="prompt-label">
                                    {PROMPT_LABELS[name] ?? name}
                                    {#if isDanger}<span class="prompt-danger-badge">⚠ breaking if changed</span>{/if}
                                </span>
                                <span class="prompt-key">{name}</span>
                            </span>
                            <span class="prompt-chars">{(promptEdits[name] ?? prompts[name]).length} chars</span>
                            <span class="prompt-chevron" class:open={promptsExpanded[name]}></span>
                        </button>
                        {#if promptsExpanded[name]}
                            <div class="prompt-body">
                                {#if PROMPT_DESCRIPTIONS[name]}
                                    <p class="prompt-desc">{PROMPT_DESCRIPTIONS[name]}</p>
                                {/if}
                                {#if isDanger}
                                    <div class="prompt-danger-notice">
                                        ⚠ Warning: This prompt's output is read by the server as JSON. You can change the wording, but do not rename, add, or remove any output field names — that will break design mode generation.
                                    </div>
                                {/if}
                                <textarea
                                    class="prompt-textarea"
                                    rows="12"
                                    value={promptEdits[name] ?? prompts[name]}
                                    oninput={(e) => editPrompt(name, (e.target as HTMLTextAreaElement).value)}
                                    spellcheck={false}
                                ></textarea>
                                {#if promptsSaved[name]}
                                    <div class="prompt-restart-notice">
                                    Saved — restart the server to apply changes.
                                    <button class="prompt-restart-inline" onclick={restartModel} disabled={switching}>{switching ? 'Restarting...' : 'Restart now'}</button>
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
        </div>

        <!-- ── Internal / Advanced ── -->
        {@const internalKeys = Object.keys(prompts)
            .filter(k => !BEHAVIOR_KEYS.includes(k) && !PIPELINE_KEYS.includes(k))
            .sort()}
        {#if internalKeys.length > 0}
        <div class="advanced-prompts-section">
            <button class="collapse-btn advanced-prompts-toggle" onclick={() => advancedPromptsOpen = !advancedPromptsOpen}>
                Internal / Advanced ({internalKeys.length})
                <span class="collapse-chevron" class:open={advancedPromptsOpen}></span>
            </button>
            {#if advancedPromptsOpen}
            <div class="prompts-list" style="margin-top:8px;">
                {#each internalKeys as name}
                    <div class="prompt-row" class:expanded={promptsExpanded[name]}>
                        <button class="prompt-header" onclick={() => togglePrompt(name)}>
                            <span class="prompt-name">
                                <span class="prompt-label">{PROMPT_LABELS[name] ?? name}</span>
                                <span class="prompt-key">{name}</span>
                            </span>
                            <span class="prompt-chars">{(promptEdits[name] ?? prompts[name]).length} chars</span>
                            <span class="prompt-chevron" class:open={promptsExpanded[name]}></span>
                        </button>
                        {#if promptsExpanded[name]}
                            <div class="prompt-body">
                                {#if PROMPT_DESCRIPTIONS[name]}
                                    <p class="prompt-desc">{PROMPT_DESCRIPTIONS[name]}</p>
                                {/if}
                                <textarea
                                    class="prompt-textarea"
                                    rows="10"
                                    value={promptEdits[name] ?? prompts[name]}
                                    oninput={(e) => editPrompt(name, (e.target as HTMLTextAreaElement).value)}
                                    spellcheck={false}
                                ></textarea>
                                {#if promptsSaved[name]}
                                    <div class="prompt-restart-notice">
                                    Saved — restart the server to apply changes.
                                    <button class="prompt-restart-inline" onclick={restartModel} disabled={switching}>{switching ? 'Restarting...' : 'Restart now'}</button>
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
        </div>
        {/if}

        {/if}
    </section>
    {/if}

    <!-- ═══════════════════════════════════════════════
         SECTION 6 — Computer Mode Workspaces
         ═══════════════════════════════════════════════ -->
    <section class="section">
        <div class="section-head">
            <div class="section-head-text">
                <h2 class="section-title">Workspaces</h2>
                <p class="section-desc">Project folders for computer mode. Delete old ones to free up space.</p>
            </div>
            <button class="scan-btn" onclick={startWsCreate}>New workspace</button>
        </div>
        {#if wsCreating}
            <div class="ws-create-row">
                <input
                    class="ws-create-input"
                    bind:this={wsNewInput}
                    bind:value={wsNewName}
                    placeholder="Project name"
                    onkeydown={handleWsCreateKeydown}
                />
                <button class="save-btn" onmousedown={(e) => e.preventDefault()} onclick={submitWsCreate}>Create</button>
                <button class="btn-outline" onclick={cancelWsCreate}>Cancel</button>
            </div>
        {/if}
        {#if workspaces.length === 0 && !wsCreating}
            <p class="ws-empty">No workspaces yet.</p>
        {:else}
            <div class="ws-list">
                {#each workspaces as ws (ws.id)}
                    <div class="ws-row">
                        <div class="ws-info">
                            <span class="ws-name">{ws.name || ws.id}</span>
                            <span class="ws-meta">{ws.file_count} file{ws.file_count !== 1 ? 's' : ''}{ws.created_at ? ' · ' + formatWsDate(ws.created_at) : ''}</span>
                        </div>
                        <button
                            class="ws-delete"
                            onclick={() => deleteWorkspace(ws.id)}
                            disabled={deletingWs === ws.id}
                            title="Delete workspace"
                        >{deletingWs === ws.id ? 'Deleting…' : 'Delete'}</button>
                    </div>
                {/each}
            </div>
        {/if}
    </section>

    <!-- ═══════════════════════════════════════════════
         SECTION 7 — Appearance
         ═══════════════════════════════════════════════ -->
    <section class="section">
        <div class="section-head">
            <div class="section-head-text">
                <h2 class="section-title">Appearance</h2>
                <p class="section-desc">Interface layout and visual style.</p>
            </div>
        </div>

        <div class="card-group">
            <div class="toggle-card" style="align-items: flex-start; flex-direction: column; gap: 12px;">
                <span class="toggle-info" style="width: 100%;">
                    <span class="toggle-name">Interface style <span style="font-size:10px; font-weight:500; opacity:0.45; letter-spacing:0.06em; text-transform:uppercase; margin-left:6px;">uiStyle</span></span>
                    <span class="toggle-hint">
                        {#if isUiStyle('ct2')}
                            Geist font · ambient gradient background · OKLCH colors · phase progress track
                        {:else}
                            Inter font · spinning ASCII donut · glass-surface color tokens
                        {/if}
                    </span>
                </span>
                <div class="seg-group" role="group" aria-label="Interface style">
                    <button
                        class="seg-btn"
                        class:active={isUiStyle('classic')}
                        onclick={() => setUiStyle('classic')}
                    >Classic</button>
                    <button
                        class="seg-btn"
                        class:active={isUiStyle('ct2')}
                        onclick={() => setUiStyle('ct2')}
                    >Modern</button>
                </div>
            </div>

            {#if isUiStyle('classic')}
            <div class="toggle-card" style="align-items: flex-start; flex-direction: column; gap: 12px;">
                <span class="toggle-info" style="width: 100%;">
                    <span class="toggle-name">Background</span>
                    <span class="toggle-hint">
                        {#if isClassicBg('image')}
                            Static ASCII artwork image
                        {:else}
                            Spinning ASCII donut (animated)
                        {/if}
                    </span>
                </span>
                <div class="seg-group" role="group" aria-label="Classic background">
                    <button
                        class="seg-btn"
                        class:active={isClassicBg('default')}
                        onclick={() => setClassicBg('default')}
                    >Donut</button>
                    <button
                        class="seg-btn"
                        class:active={isClassicBg('image')}
                        onclick={() => setClassicBg('image')}
                    >Image</button>
                </div>
            </div>
            {/if}
        </div>
    </section>

    <!-- ═══════════════════════════════════════════════
         SECTION 8 — RAG (Retrieval-Augmented Generation)
         ═══════════════════════════════════════════════ -->
    <section class="section">
        <div class="section-head">
            <div class="section-head-text">
                <h2 class="section-title">RAG</h2>
                <p class="section-desc">Index your documents so the AI can pull in the most relevant passages before every reply — PDFs, notes, code, data files.</p>
            </div>
        </div>

        {#if ragLoading}
            <div class="skeleton-row"></div>
        {:else}
            <!-- Enable toggle -->
            <div class="card-group">
                <label class="toggle-card">
                    <span class="toggle-info">
                        <span class="toggle-name">Document indexing</span>
                        <span class="toggle-hint">When on, the AI searches your indexed documents before every reply and injects the most relevant passages as context. Requires a server restart when changed.</span>
                    </span>
                    <button
                        class="toggle-switch"
                        class:on={ragStatus.enabled}
                        onclick={toggleRagEnabled}
                        disabled={ragEnabling}
                        role="switch"
                        aria-checked={ragStatus.enabled}
                        aria-label="Toggle document indexing"
                    >
                        <span class="toggle-knob"></span>
                    </button>
                </label>
            </div>

            <!-- Restart required notice -->
            {#if ragNeedsRestart}
                <div class="rag-restart">
                    <span>Server restart required to apply this change.</span>
                    <button class="restart-btn" onclick={restartForRag} disabled={switching}>
                        {switching ? 'Restarting…' : 'Restart now'}
                    </button>
                </div>
            {/if}

            {#if ragStatus.enabled && !ragNeedsRestart}
                <!-- Upload drop zone -->
                <div
                    class="rag-drop"
                    class:rag-drop-over={ragDragOver}
                    ondragover={(e) => { e.preventDefault(); ragDragOver = true; }}
                    ondragleave={() => ragDragOver = false}
                    ondrop={handleRagDrop}
                    onclick={() => ragFileInput?.click()}
                    role="button"
                    tabindex="0"
                >
                    <input
                        bind:this={ragFileInput}
                        type="file"
                        accept=".pdf,.txt,.md,.markdown,.rst,.py,.js,.ts,.jsx,.tsx,.java,.go,.rs,.c,.cpp,.h,.hpp,.cs,.rb,.php,.html,.htm,.css,.scss,.less,.json,.yaml,.yml,.toml,.ini,.cfg,.xml,.csv,.tsv,.log,.sh,.bat,.ps1,.sql,.svg"
                        onchange={handleRagFilePick}
                        style="display:none"
                    />
                    <span class="rag-drop-icon">
                        {#if ragUploading}
                            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" class="rag-spin">
                                <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.8" stroke-dasharray="18 38" stroke-linecap="round"/>
                            </svg>
                        {:else}
                            <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                                <path d="M12 15V5M12 5L8 9M12 5l4 4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
                                <path d="M4 17v1a2 2 0 002 2h12a2 2 0 002-2v-1" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
                            </svg>
                        {/if}
                    </span>
                    <span class="rag-drop-text">{ragUploading ? 'Uploading…' : 'Drop a file here or click to browse'}</span>
                    <span class="rag-drop-hint">PDF · Markdown · Text · Code · CSV · JSON · HTML{ragStatus.max_file_mb ? ` · Max ${ragStatus.max_file_mb}MB` : ''}</span>
                </div>

                <!-- Feedback message -->
                {#if ragMsg}
                    <div class="rag-msg" class:rag-msg-err={ragMsg.toLowerCase().includes('fail') || ragMsg.toLowerCase().includes('error')}>{ragMsg}</div>
                {/if}

                <!-- Files on disk -->
                {#if ragDataFiles.length > 0}
                    <div class="subsection-label" style="margin-top:20px;">Files in ct1/data/rag_uploads/</div>
                    {#each ragDataFiles as df (df.name)}
                        <div class="rag-file">
                            <div class="rag-file-info">
                                <span class="rag-file-name">{df.name}</span>
                                <span class="rag-file-meta">
                                    {df.size_mb} MB
                                    {#if ragFiles.some((f: any) => f.name === df.name)}
                                        · indexed → {ragFiles.find((f: any) => f.name === df.name)?.chunk_count ?? 0} chunk{ragFiles.find((f: any) => f.name === df.name)?.chunk_count !== 1 ? 's' : ''}
                                    {:else}
                                        · not indexed
                                    {/if}
                                </span>
                            </div>
                            <button class="rag-delete-btn" onclick={() => ragDeleteFile(df.name)} title="Delete file from disk">🗑</button>
                        </div>
                    {/each}
                {:else}
                    <p class="rag-empty">No documents indexed yet. Drop a file above to get started, or place files in the <code>ct1/data/rag_uploads/</code> folder and click Re-index.</p>
                {/if}

                <!-- Indexed files (de-index only) -->
                {#if ragFiles.length > 0}
                    <div class="subsection-label" style="margin-top:20px;">Indexed files</div>
                    {#each ragFiles as f}
                        <div class="rag-file">
                            <div class="rag-file-info">
                                <span class="rag-file-name">{f.name}</span>
                                <span class="rag-file-meta">{f.size_mb} MB · {f.chunk_count} chunk{f.chunk_count !== 1 ? 's' : ''}</span>
                            </div>
                            <button class="rag-delete-btn" onclick={() => ragDelete(f.name)} title="Remove from index">✕</button>
                        </div>
                    {/each}
                {/if}

                <!-- Actions + stats -->
                <div class="rag-actions">
                    <button class="btn btn-secondary" onclick={ragReindex} disabled={ragReindexing}>
                        {ragReindexing ? 'Re-indexing…' : 'Re-index folder'}
                    </button>
                    {#if (ragStatus.files ?? 0) > 0}
                        <span class="rag-stats">
                            {ragStatus.files} file{ragStatus.files !== 1 ? 's' : ''}
                            · {ragStatus.chunks} chunks
                            {#if (ragStatus.context_cost ?? 0) > 0}· ~{ragStatus.context_cost} tokens/msg{/if}
                        </span>
                    {/if}
                </div>

                {#if (ragStatus.context_cost ?? 0) > 0}
                    <div class="rag-budget">
                        Each message injects ~{ragStatus.context_cost} tokens of document context.
                        With a {config.context_size ? Math.round(config.context_size / 1024) + 'K' : '?'} context window, ~{Math.max(0, (config.context_size ?? 4096) / 3.5 - (ragStatus.context_cost ?? 2000)) | 0} tokens remain for conversation per turn.
                        CT-2 compacts history automatically when the window fills.
                    </div>
                {/if}
            {/if}
        {/if}
    </section>

    <!-- ═══════════════════════════════════════════════
         SECTION 9 — Server Status
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
{/if}

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
        transition: background 220ms ease, box-shadow 220ms ease;
        padding: 0;
    }
    .toggle-switch.on {
        background: oklch(0.58 0.17 145);
        box-shadow: 0 0 0 3px oklch(0.58 0.17 145 / 0.18);
    }
    .toggle-knob {
        position: absolute;
        top: 3px;
        left: 3px;
        width: 18px;
        height: 18px;
        border-radius: 50%;
        background: white;
        transition: transform 260ms cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 220ms ease;
        box-shadow: 0 1px 4px rgba(0,0,0,0.28), 0 0 0 1px rgba(0,0,0,0.06);
    }
    .toggle-switch.on .toggle-knob {
        transform: translateX(20px);
        box-shadow: 0 1px 4px rgba(0,0,0,0.22), 0 0 0 1px rgba(0,0,0,0.04);
    }

    /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       SEGMENT CONTROL
       ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
    .seg-group {
        display: flex;
        align-items: center;
        background: var(--accent-subtle);
        border: 1px solid var(--border);
        border-radius: var(--radius-sm);
        padding: 3px;
        gap: 2px;
    }
    .seg-btn {
        padding: 5px 14px;
        border-radius: calc(var(--radius-sm) - 2px);
        border: none;
        background: none;
        font-size: 12.5px;
        font-weight: 500;
        color: var(--text-muted);
        cursor: pointer;
        transition: background 150ms ease, color 150ms ease;
        white-space: nowrap;
    }
    .seg-btn:hover:not(.active) {
        color: var(--text-secondary);
        background: var(--surface-hover);
    }
    .seg-btn.active {
        background: var(--surface-solid);
        color: var(--text);
        box-shadow: var(--shadow-sm);
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
    .cap-badge.vision {
        color: #0f766e;
        background: rgba(20, 184, 166, 0.12);
        border: 1px solid rgba(20, 184, 166, 0.24);
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
    .drop-vision { color: rgba(13, 148, 136, 0.85); font-weight: 500; }
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
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 18px;
    }
    .mode-header-text {
        display: flex;
        flex-direction: column;
        gap: 2px;
        min-width: 0;
    }
    .mode-reset-btn {
        flex-shrink: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        width: 28px;
        height: 28px;
        border-radius: 7px;
        border: 1px solid transparent;
        background: transparent;
        color: var(--text-secondary);
        cursor: pointer;
        transition: color 0.15s, background 0.15s, border-color 0.15s;
        margin-top: 1px;
    }
    .mode-reset-btn:hover {
        color: var(--text);
        background: var(--bubble-strong);
        border-color: var(--border);
    }
    .mode-reset-btn.active {
        color: var(--accent, #7c6fe0);
        background: color-mix(in srgb, var(--accent, #7c6fe0) 12%, transparent);
        border-color: color-mix(in srgb, var(--accent, #7c6fe0) 30%, transparent);
    }
    .mode-reset-btn svg {
        display: block;
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
    .update-btn { color: var(--text-secondary); }
    .update-btn:disabled { cursor: wait; opacity: 0.6; }
    .update-msg { font-size: 11px; color: var(--text-muted); margin-top: 4px; font-family: var(--font-mono, monospace); }
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
    .update-restart-btn { margin-top: 10px; width: 100%; }

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
    .scan-btn-warn { color: var(--warn, #d29922); border-color: rgba(210, 153, 34, 0.35); }
    .scan-btn-warn:hover:not(:disabled) { background: rgba(210, 153, 34, 0.08); color: var(--warn, #d29922); }
    .section-head-btns { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }

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
    .prompts-head-actions {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-shrink: 0;
    }
    .prompt-restart-notice {
        font-size: 12px;
        color: rgba(210, 153, 34, 0.9);
        background: rgba(210, 153, 34, 0.07);
        border: 1px solid rgba(210, 153, 34, 0.18);
        border-radius: var(--radius-sm);
        padding: 8px 14px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
    }
    .prompt-restart-inline {
        flex-shrink: 0;
        padding: 4px 12px;
        font-size: 11px;
        font-weight: 600;
        font-family: inherit;
        color: rgba(210, 153, 34, 0.95);
        background: rgba(210, 153, 34, 0.12);
        border: 1px solid rgba(210, 153, 34, 0.3);
        border-radius: 9999px;
        cursor: pointer;
        transition: opacity 0.15s;
    }
    .prompt-restart-inline:hover:not(:disabled) { opacity: 0.8; }
    .prompt-restart-inline:disabled { opacity: 0.5; cursor: wait; }
    .prompt-actions {
        display: flex;
        justify-content: flex-end;
        gap: 8px;
    }

    .prompt-group {
        margin-bottom: 16px;
    }
    .prompt-group-header {
        display: flex;
        flex-direction: column;
        gap: 2px;
        margin-bottom: 8px;
        padding: 0 2px;
    }
    .prompt-group-title {
        font-size: 11px;
        font-weight: 650;
        color: var(--text-secondary);
        text-transform: uppercase;
        letter-spacing: 0.07em;
    }
    .prompt-group-desc {
        font-size: 12px;
        color: var(--text-muted);
        line-height: 1.4;
    }
    .prompt-desc {
        font-size: 12.5px;
        color: var(--text-secondary);
        line-height: 1.5;
        margin: 0 0 10px;
    }
    .prompt-danger-badge {
        display: inline-flex;
        align-items: center;
        margin-left: 8px;
        font-size: 10px;
        font-weight: 600;
        font-family: inherit;
        padding: 2px 7px;
        border-radius: 4px;
        background: rgba(210, 100, 34, 0.1);
        border: 1px solid rgba(210, 100, 34, 0.25);
        color: rgba(200, 85, 15, 0.95);
        text-transform: uppercase;
        letter-spacing: 0.04em;
        vertical-align: middle;
    }
    .prompt-danger-notice {
        font-size: 12.5px;
        line-height: 1.5;
        color: rgba(180, 75, 10, 0.95);
        background: rgba(210, 100, 34, 0.07);
        border: 1px solid rgba(210, 100, 34, 0.22);
        border-radius: var(--radius-sm);
        padding: 10px 14px;
        margin-bottom: 10px;
    }
    .advanced-prompts-section {
        margin-top: 16px;
        padding-top: 16px;
        border-top: 1px solid var(--border-subtle);
    }
    .advanced-prompts-toggle {
        font-size: 12px;
        color: var(--text-muted);
    }

    /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       WORKSPACES
       ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
    .ws-empty {
        font-size: 13px;
        color: var(--text-muted);
        padding: 8px 0;
    }
    .ws-create-row {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 14px;
    }
    .ws-create-input {
        flex: 1;
        padding: 8px 14px;
        font-size: 13px;
        font-family: inherit;
        color: var(--text);
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: var(--radius-sm);
        outline: none;
        min-width: 0;
        transition: border-color 0.15s;
    }
    .ws-create-input:focus { border-color: var(--text-muted); }
    .ws-create-input::placeholder { color: var(--text-muted); }
    .ws-list {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }
    .ws-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 10px 14px;
        background: var(--accent-subtle);
        border: 1px solid var(--border);
        border-radius: var(--radius-sm);
    }
    .ws-info { display: flex; flex-direction: column; gap: 2px; }
    .ws-name { font-size: 13px; font-weight: 500; color: var(--text); font-family: var(--font-mono); }
    .ws-meta { font-size: 11px; color: var(--text-muted); }
    .ws-delete {
        font-size: 12px;
        font-weight: 500;
        padding: 5px 14px;
        border: 1px solid var(--border);
        border-radius: var(--radius-pill);
        background: transparent;
        color: var(--text-secondary);
        cursor: pointer;
        transition: all var(--transition);
        font-family: var(--font-body);
    }
    .ws-delete:hover { background: rgba(239,68,68,0.1); border-color: rgba(239,68,68,0.4); color: #ef4444; }
    .ws-delete:disabled { opacity: 0.4; cursor: not-allowed; }

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

    /* ── Compact slider row ───────────────────────────────────── */
    .slider-row.compact {
        min-width: 160px;
    }

    /* ── Plan cache section ─────────────────────────────────────── */
    .plan-count-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 32px;
        height: 26px;
        padding: 0 10px;
        border-radius: 13px;
        background: var(--accent-dim);
        color: var(--accent);
        font-family: var(--font-mono);
        font-size: 13px;
        font-weight: 600;
    }
    .plan-list {
        display: flex;
        flex-direction: column;
        gap: 3px;
        margin-top: 8px;
        max-height: 220px;
        overflow-y: auto;
    }
    .plan-item {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        padding: 6px 12px;
        border-radius: 8px;
        background: var(--bg);
        border: 1px solid var(--border);
        font-size: 12px;
    }
    .plan-item-main {
        display: flex;
        flex-direction: column;
        gap: 1px;
        min-width: 0;
    }
    .plan-sig {
        font-family: var(--font-mono);
        font-size: 11px;
        color: var(--text);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .plan-meta {
        font-family: var(--font-mono);
        font-size: 10px;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.3px;
    }
    .plan-score {
        flex-shrink: 0;
        width: 28px;
        height: 18px;
        border-radius: 9px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-family: var(--font-mono);
        font-size: 10px;
        font-weight: 600;
        background: color-mix(in srgb, var(--accent) calc(var(--score, 0.5) * 100%), var(--bg));
        color: white;
    }
    .plan-empty {
        color: var(--text-muted);
        font-size: 13px;
        margin-top: 6px;
    }
    .plan-clear-btn {
        background: transparent;
        border: 1px solid var(--border);
        color: var(--text-secondary);
        font-size: 12px;
        padding: 5px 14px;
        border-radius: 6px;
        cursor: pointer;
        transition: all 150ms;
    }
    .plan-clear-btn:hover {
        border-color: var(--text-muted);
        color: var(--text);
    }
    .plan-clear-btn:disabled {
        opacity: 0.5;
        cursor: wait;
    }
    .plan-msg {
        display: block;
        color: var(--text-muted);
        font-size: 12px;
        margin-top: 6px;
    }

    /* ── Subsection label ── */
    .subsection-label {
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: var(--text-muted);
        margin: 20px 0 8px;
    }

    /* ── Generic buttons ── */
    .btn {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px 14px;
        font-size: 12px;
        font-weight: 600;
        font-family: inherit;
        border-radius: 9999px;
        cursor: pointer;
        transition: color 0.15s, background 0.15s, opacity 0.15s;
        white-space: nowrap;
        flex-shrink: 0;
    }
    .btn:disabled { opacity: 0.4; cursor: default; }
    .btn-secondary {
        border: 1px solid var(--border);
        background: var(--surface);
        color: var(--text-muted);
    }
    .btn-secondary:hover:not(:disabled) { background: var(--bubble-strong); color: var(--text); }

    /* ── RAG ── */
    .rag-restart {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin-top: 10px;
        padding: 10px 14px;
        border-radius: 8px;
        border: 1px solid rgba(210, 153, 34, 0.3);
        background: rgba(210, 153, 34, 0.06);
        font-size: 13px;
        color: var(--warn, #d29922);
    }
    .rag-empty {
        padding: 20px 0 8px;
        font-size: 13px;
        color: var(--text-muted);
        line-height: 1.55;
    }
    .rag-actions {
        display: flex;
        align-items: center;
        gap: 14px;
        margin-top: 14px;
    }
    .rag-stats {
        font-size: 11.5px;
        color: var(--text-muted);
        font-variant-numeric: tabular-nums;
    }
    .rag-drop {
        margin-top: 14px;
        border: 2px dashed var(--border);
        border-radius: 10px;
        padding: 24px 16px;
        text-align: center;
        cursor: pointer;
        transition: border-color 0.15s, background 0.15s;
        user-select: none;
    }
    .rag-drop:hover,
    .rag-drop-over {
        border-color: var(--text-muted);
        background: var(--hover);
    }
    .rag-drop-icon {
        display: flex;
        align-items: center;
        justify-content: center;
        margin-bottom: 6px;
        color: var(--text-muted);
        transition: color 0.15s;
    }
    .rag-drop:hover .rag-drop-icon,
    .rag-drop-over .rag-drop-icon { color: var(--accent, #4a9eff); }
    .rag-spin { animation: rag-spin 1s linear infinite; }
    @keyframes rag-spin { to { transform: rotate(360deg); } }
    .rag-drop-text { display: block; font-size: 13px; font-weight: 500; }
    .rag-drop-hint { display: block; font-size: 11px; color: var(--text-muted); margin-top: 3px; }

    .rag-msg {
        margin-top: 10px;
        font-size: 12px;
        color: var(--success, #4caf50);
        padding: 6px 10px;
        border-radius: 6px;
        background: color-mix(in srgb, var(--success, #4caf50) 8%, transparent);
    }
    .rag-msg-err {
        color: var(--danger, #f44336);
        background: color-mix(in srgb, var(--danger, #f44336) 8%, transparent);
    }

    .rag-file {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 8px 10px;
        border: 1px solid var(--border);
        border-radius: 6px;
        margin-top: 6px;
    }
    .rag-file-info { display: flex; flex-direction: column; min-width: 0; }
    .rag-file-name {
        font-size: 13px; font-weight: 500;
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .rag-file-meta { font-size: 11px; color: var(--text-muted); margin-top: 1px; }

    .rag-delete-btn {
        background: none; border: none; color: var(--text-muted);
        cursor: pointer; font-size: 14px; padding: 4px 8px; border-radius: 4px;
        transition: color 0.1s, background 0.1s;
        flex-shrink: 0;
    }
    .rag-delete-btn:hover { color: var(--danger, #f44336); background: var(--hover); }

    .rag-budget {
        margin-top: 14px;
        font-size: 11.5px;
        color: var(--text-muted);
        line-height: 1.5;
        padding: 10px 12px;
        border: 1px solid var(--border);
        border-radius: 6px;
        background: var(--surface);
    }
</style>
