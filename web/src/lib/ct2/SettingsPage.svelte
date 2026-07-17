<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { preferences, toggleTheme, setCt2Bg } from '$lib/stores/preferences';
    import { newConversation, setWorkspaceId, setMode, loadFromHistory } from '$lib/stores/chat';
    import { serverUpdate, startUpdate, isUpdating } from '$lib/stores/serverUpdate';
    import { modelSwitchCount, notifyModelSwitch } from '$lib/stores/model';
    import { setModelSwapping, clearModelSwapping, startRagPolling } from '$lib/stores/backgroundTasks';
    import { authStatus, refreshAuthStatus, setPassword, disableAuth, logout } from '$lib/stores/auth';
    import { showToast } from '$lib/stores/toasts';
    import StatusIndicator from '$lib/components/StatusIndicator.svelte';
    import ModelDownloader from '$lib/components/ModelDownloader.svelte';

    const CONTEXT_MIN_FLOOR = 2048;

    let modelStatus = $state<Record<string, any>>({});
    let config = $state<Record<string, any>>({});
    let loading = $state(false);
    let activeSection = $state('model');

    // ── Security tab state ────────────────────────────────────────────
    let secCurrentPw = $state('');
    let secNewPw = $state('');
    let secConfirmPw = $state('');
    let secDisablePw = $state('');
    let secBusy = $state(false);
    let secShowDisable = $state(false);

    async function secEnableOrChangePassword() {
        if (secBusy) return;
        if (secNewPw.length < 6) { showToast('Password must be at least 6 characters.', { variant: 'error' }); return; }
        if (secNewPw !== secConfirmPw) { showToast('Passwords do not match.', { variant: 'error' }); return; }
        const isFirstTime = $authStatus.mode === 'none';
        if (!isFirstTime && !secCurrentPw) { showToast('Enter your current password.', { variant: 'error' }); return; }
        secBusy = true;
        const r = await setPassword({
            new_password: secNewPw,
            current_password: isFirstTime ? undefined : secCurrentPw,
            enable: true,
        });
        secBusy = false;
        if (!r.ok) { showToast(r.error || 'Could not save.', { variant: 'error', title: 'Password change failed' }); return; }
        secCurrentPw = ''; secNewPw = ''; secConfirmPw = '';
        showToast(isFirstTime ? 'Password set. Other devices need to sign in.' : 'Password changed. Other sessions are signed out.', {
            variant: 'success',
            title: isFirstTime ? 'Multi-user mode enabled' : 'Password updated',
        });
    }

    async function secDisablePassword() {
        if (secBusy) return;
        if (!secDisablePw) { showToast('Enter your current password to disable.', { variant: 'error' }); return; }
        secBusy = true;
        const r = await disableAuth(secDisablePw);
        secBusy = false;
        if (!r.ok) { showToast(r.error || 'Could not disable.', { variant: 'error' }); return; }
        secDisablePw = ''; secShowDisable = false;
        showToast('Multi-user mode disabled. Bind reverts to localhost on next start.', { variant: 'info' });
    }

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

    let planCacheStats = $state<{entries:number;avg_score:number;recent:Array<{sig:string;task_type:string;complexity:string;count:number;score:number}>}>({entries:0,avg_score:0,recent:[]});
    let planCacheClearing = $state(false);
    let planCacheMsg = $state('');
    let planCacheFast = $state(false);

    // ── RAG ───────────────────────────────────────────────────────
    let ragStatus = $state<Record<string, any>>({});
    let ragFiles = $state<any[]>([]);
    let ragDataFiles = $state<any[]>([]);
    let ragLoading = $state(false);
    let ragReindexing = $state(false);
    let ragProgress = $state<Record<string, any>>({running: false, current: 0, total: 0, file: '', stage: ''});
    let ragMsg = $state('');
    let ragUploading = $state(false);
    let ragDragOver = $state(false);
    let ragFileInput = $state<HTMLInputElement | undefined>(undefined);
    let ragEnabling = $state(false);
    let ragNeedsRestart = $state(false);
    let _ragPollTimer: ReturnType<typeof setInterval> | undefined = undefined;

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

    async function fetchPlanCache() {
        try {
            planCacheStats = await (await fetch('/api/plan-cache/stats')).json();
        } catch {}
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

    // ── RAG functions ─────────────────────────────────────────────
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
            ragMsg = d.error ? `Indexing error: ${d.error}` : `Uploaded: ${file.name}`;
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
        ragProgress = {running: true, current: 0, total: 0, file: '', stage: 'scanning'};
        // Start global polling for the persistent banner
        startRagPolling();
        // Start local polling for the inline progress bar (smoother at 200ms)
        if (_ragPollTimer) clearInterval(_ragPollTimer);
        _ragPollTimer = setInterval(async () => {
            try {
                const p = await (await fetch('/api/rag/reindex/progress')).json();
                ragProgress = p;
                if (!p.running && _ragPollTimer) {
                    clearInterval(_ragPollTimer);
                    _ragPollTimer = undefined;
                }
            } catch { /* ignore poll errors */ }
        }, 200);
        try {
            const res = await fetch('/api/rag/reindex', { method: 'POST' });
            const d = await res.json();
            // Final progress pull
            try { ragProgress = await (await fetch('/api/rag/reindex/progress')).json(); } catch {}
            if (_ragPollTimer) { clearInterval(_ragPollTimer); _ragPollTimer = undefined; }
            ragMsg = d.ok ? `Re-indexed: ${d.files_added} added, ${d.files_updated} updated, ${d.files_skipped} skipped, ${d.errors} errors` : (d.detail || 'Re-index failed');
            await fetchRag();
        } catch (e: any) {
            if (_ragPollTimer) { clearInterval(_ragPollTimer); _ragPollTimer = undefined; }
            ragMsg = e.message || 'Re-index failed';
        } finally {
            ragReindexing = false;
            ragProgress = {running: false, current: 0, total: 0, file: '', stage: 'idle'};
        }
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

    // ── Workspaces ────────────────────────────────────────────────
    interface Workspace { id: string; name: string; created_at: string; file_count: number; }
    let workspaces = $state<Workspace[]>([]);
    let deletingWs = $state<string | null>(null);
    let wsCreating = $state(false);
    let wsNewName = $state('');
    let wsNewInput = $state<HTMLInputElement | null>(null);

    async function loadWorkspaces() {
        try { workspaces = await (await fetch('/api/workspaces')).json(); } catch {}
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
            try { if (localStorage.getItem('ct2_workspace_id') === id) localStorage.removeItem('ct2_workspace_id'); } catch {}
        } finally { deletingWs = null; }
    }
    function fmtWsDate(iso: string) {
        try { return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }); } catch { return iso; }
    }

    async function openWorkspace(id: string) {
        try {
            const conv = await fetch(`/api/workspaces/${id}/conversation`).then(r => r.json());
            if (conv?.id) {
                loadFromHistory(conv);
            } else {
                newConversation();
            }
        } catch {
            newConversation();
        }
        setWorkspaceId(id);
        setMode('computer');
        goto('/');
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
        await Promise.all([loadData(), loadModes(), loadWorkspaces(), loadPrompts(), fetchPlanCache(), refreshAuthStatus()]);
        fetchRag();
        _mounted = true;
    });

    // Keep in-sync when model is switched from the topbar quick-pick
    $effect(() => {
        $modelSwitchCount; // reactive dependency — re-fetches on every switch
        if (_mounted) { loadData(); fetchPlanCache(); }
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
                <div class="c2-sh">
                    <h1 class="c2-sh-title">Security</h1>
                    <p class="c2-sh-sub">By default CT-2 WebUI runs single-user and binds to <code>localhost</code> only. Enable a shared password to let other devices on your home network reach it — they'll all use the same password.</p>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Current mode</div>
                        <div class="c2-row-desc">
                            {#if $authStatus.mode === 'none'}
                                <span class="c2-tag">Single-user (none)</span> &nbsp; Bind: <code>127.0.0.1:8000</code>. Only your machine can connect. Web search and RAG still work.
                            {:else if $authStatus.mode === 'password'}
                                <span class="c2-tag c2-tag-active">Shared password</span> &nbsp; Bind: <code>0.0.0.0:8000</code>. Devices on your network can sign in with the password below. Sessions last 30 days.
                            {:else}
                                <span class="c2-tag">{$authStatus.mode}</span>
                            {/if}
                        </div>
                    </div>
                </div>

                {#if $authStatus.mode === 'none'}
                    <div class="c2-row" style="flex-direction:column;align-items:stretch;gap:12px;">
                        <div class="c2-row-label">
                            <div class="c2-row-name">Enable shared password</div>
                            <div class="c2-row-desc">Pick a password and turn on multi-user mode. After saving, restart CT-2 — the bind will widen to <code>0.0.0.0</code> so other devices can reach it. Pair this with a reverse proxy (Caddy, Tailscale) if you expose it beyond the home network.</div>
                        </div>
                        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                            <input type="password" class="c2-input" placeholder="New password" bind:value={secNewPw} autocomplete="new-password" disabled={secBusy} />
                            <input type="password" class="c2-input" placeholder="Confirm" bind:value={secConfirmPw} autocomplete="new-password" disabled={secBusy} />
                        </div>
                        <button class="c2-btn-primary" style="align-self:flex-start;" onclick={secEnableOrChangePassword} disabled={secBusy || !secNewPw}>
                            {secBusy ? 'Saving…' : 'Enable password'}
                        </button>
                    </div>
                {:else if $authStatus.mode === 'password'}
                    <div class="c2-row" style="flex-direction:column;align-items:stretch;gap:12px;">
                        <div class="c2-row-label">
                            <div class="c2-row-name">Change password</div>
                            <div class="c2-row-desc">All other devices will be signed out — they'll need to enter the new password.</div>
                        </div>
                        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;">
                            <input type="password" class="c2-input" placeholder="Current password" bind:value={secCurrentPw} autocomplete="current-password" disabled={secBusy} />
                            <input type="password" class="c2-input" placeholder="New password" bind:value={secNewPw} autocomplete="new-password" disabled={secBusy} />
                            <input type="password" class="c2-input" placeholder="Confirm" bind:value={secConfirmPw} autocomplete="new-password" disabled={secBusy} />
                        </div>
                        <button class="c2-btn-primary" style="align-self:flex-start;" onclick={secEnableOrChangePassword} disabled={secBusy || !secCurrentPw || !secNewPw}>
                            {secBusy ? 'Saving…' : 'Change password'}
                        </button>
                    </div>

                    <div class="c2-row" style="flex-direction:column;align-items:stretch;gap:12px;">
                        <div class="c2-row-label">
                            <div class="c2-row-name">Sign out this device</div>
                            <div class="c2-row-desc">Clears the session cookie on this browser. You'll be sent to the login screen.</div>
                        </div>
                        <button class="c2-btn-outline" style="align-self:flex-start;" onclick={() => logout()}>Sign out</button>
                    </div>

                    <div class="c2-row" style="flex-direction:column;align-items:stretch;gap:12px;">
                        <div class="c2-row-label">
                            <div class="c2-row-name">Disable multi-user mode</div>
                            <div class="c2-row-desc">Switch back to single-user. The bind reverts to <code>localhost</code> on next start; everyone else loses access.</div>
                        </div>
                        {#if !secShowDisable}
                            <button class="c2-btn-outline c2-btn-err" style="align-self:flex-start;" onclick={() => secShowDisable = true}>Disable…</button>
                        {:else}
                            <div style="display:grid;grid-template-columns:1fr auto auto;gap:10px;align-items:center;">
                                <input type="password" class="c2-input" placeholder="Current password to confirm" bind:value={secDisablePw} autocomplete="current-password" disabled={secBusy} />
                                <button class="c2-btn-ghost" onclick={() => { secShowDisable = false; secDisablePw = ''; }}>Cancel</button>
                                <button class="c2-btn-danger" onclick={secDisablePassword} disabled={secBusy || !secDisablePw}>
                                    {secBusy ? 'Disabling…' : 'Yes, disable'}
                                </button>
                            </div>
                        {/if}
                    </div>
                {/if}

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Per-user accounts</div>
                        <div class="c2-row-desc">Coming in a future release: each family member gets their own login and isolated chat history. Today everyone shares one account in password mode.</div>
                    </div>
                    <div class="c2-row-control">
                        <span class="c2-tag">Roadmap</span>
                    </div>
                </div>

            <!-- ── RAG ── -->
            {:else if activeSection === 'rag'}
                <div class="c2-sh">
                    <h1 class="c2-sh-title">RAG</h1>
                    <p class="c2-sh-sub">Index your documents so the AI can pull in the most relevant passages before every reply — PDFs, notes, code, data files.</p>
                </div>

                {#if ragLoading}
                    <div class="c2-skeleton"></div>
                {:else}
                    <!-- Enable toggle -->
                    <div class="c2-row">
                        <div class="c2-row-label">
                            <div class="c2-row-name">Document indexing</div>
                            <div class="c2-row-desc">When on, the AI searches your indexed documents before every reply and injects the most relevant passages as context. Requires a server restart when changed.</div>
                        </div>
                        <div class="c2-row-control">
                            <button
                                class="c2-switch"
                                class:c2-switch-on={ragStatus.enabled}
                                onclick={toggleRagEnabled}
                                disabled={ragEnabling}
                                role="switch"
                                aria-checked={ragStatus.enabled}
                                aria-label="Toggle document indexing"
                            >
                                <span class="c2-switch-knob"></span>
                            </button>
                        </div>
                    </div>

                    <!-- Restart required notice -->
                    {#if ragNeedsRestart}
                        <div class="c2-rag-restart">
                            <div class="c2-rag-restart-left">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" style="flex-shrink:0">
                                    <path d="M12 9v4M12 17h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                                </svg>
                                <span>Server restart required to apply this change.</span>
                            </div>
                            <button class="c2-btn-outline c2-btn-warn" onclick={restartForRag} disabled={switching}>
                                {switching ? 'Restarting…' : 'Restart now'}
                            </button>
                        </div>
                    {/if}

                    {#if ragStatus.enabled && !ragNeedsRestart}
                        <!-- Upload drop zone -->
                        <div
                            class="c2-rag-drop"
                            class:c2-rag-drop-over={ragDragOver}
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
                            <span class="c2-rag-drop-icon">
                                {#if ragUploading}
                                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" class="c2-rag-spin">
                                        <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.8" stroke-dasharray="18 38" stroke-linecap="round"/>
                                    </svg>
                                {:else}
                                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                                        <path d="M12 15V5M12 5L8 9M12 5l4 4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
                                        <path d="M4 17v1a2 2 0 002 2h12a2 2 0 002-2v-1" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
                                    </svg>
                                {/if}
                            </span>
                            <span class="c2-rag-drop-text">{ragUploading ? 'Uploading…' : 'Drop a file here or click to browse'}</span>
                            <span class="c2-rag-drop-hint">PDF · Markdown · Text · Code · CSV · JSON · HTML{ragStatus.max_file_mb ? ` · Max ${ragStatus.max_file_mb}MB` : ''}</span>
                        </div>

                        <!-- Feedback message -->
                        {#if ragMsg}
                            <div class="c2-rag-msg" class:c2-rag-msg-err={ragMsg.toLowerCase().includes('fail') || ragMsg.toLowerCase().includes('error')}>
                                {ragMsg}
                            </div>
                        {/if}

                        <!-- Reindex progress bar -->
                        {#if ragReindexing && ragProgress.total > 0}
                            <div class="c2-rag-progress-wrap">
                                <div class="c2-rag-progress-bar">
                                    <div
                                        class="c2-rag-progress-fill"
                                        style="width: {Math.round((ragProgress.current / ragProgress.total) * 100)}%"
                                    ></div>
                                </div>
                                <div class="c2-rag-progress-text">
                                    <span>{ragProgress.current} / {ragProgress.total} files</span>
                                    <span class="c2-rag-progress-pct">{Math.round((ragProgress.current / ragProgress.total) * 100)}%</span>
                                </div>
                                {#if ragProgress.file}
                                    <div class="c2-rag-progress-file" title={ragProgress.file}>{ragProgress.file}</div>
                                {/if}
                            </div>
                        {:else if ragReindexing}
                            <div class="c2-rag-progress-wrap">
                                <div class="c2-rag-progress-bar">
                                    <div class="c2-rag-progress-fill c2-rag-progress-indeterminate"></div>
                                </div>
                                <div class="c2-rag-progress-text">Scanning folder…</div>
                            </div>
                        {/if}

                        <!-- Files in rag uploads folder -->
                        {#if ragDataFiles.length > 0}
                            <div class="c2-subsection-label">
                                Files in <code class="c2-rag-path-label">ct2/data/rag_uploads/</code>
                                <span class="c2-rag-count-badge">{ragDataFiles.length}</span>
                            </div>
                            <div class="c2-rag-datafile-list">
                                {#each ragDataFiles as df (df.name)}
                                    <div class="c2-rag-datafile" class:c2-rag-datafile-idx={ragFiles.some((f: any) => f.name === df.name)}>
                                        <div class="c2-rag-datafile-info">
                                            <span class="c2-rag-datafile-name">{df.name}</span>
                                            <span class="c2-rag-datafile-meta">
                                                {df.size_mb} MB
                                                {#if ragFiles.some((f: any) => f.name === df.name)}
                                                    · indexed → {ragFiles.find((f: any) => f.name === df.name)?.chunk_count ?? 0} chunk{ragFiles.find((f: any) => f.name === df.name)?.chunk_count !== 1 ? 's' : ''}
                                                {:else}
                                                    · not indexed
                                                {/if}
                                            </span>
                                        </div>
                                        <div class="c2-rag-datafile-actions">
                                            <span class="c2-rag-datafile-dot" class:green={ragFiles.some((f: any) => f.name === df.name)}></span>
                                            <button class="c2-btn-ghost c2-btn-err-small" onclick={() => ragDeleteFile(df.name)} title="Delete file from disk">🗑</button>
                                        </div>
                                    </div>
                                {/each}
                            </div>
                        {:else}
                            <p class="c2-rag-empty">No files in <code>ct2/data/rag_uploads/</code> yet. Drop a file above to get started.</p>
                        {/if}

                        <!-- Indexed files summary -->
                        {#if ragFiles.length > 0}
                            <div class="c2-subsection-label">
                                Indexed files
                                <span class="c2-rag-count-badge">{ragFiles.length}</span>
                            </div>
                            {#each ragFiles as f}
                                <div class="c2-rag-file">
                                    <div class="c2-rag-file-info">
                                        <span class="c2-rag-file-name">{f.name}</span>
                                        <span class="c2-rag-file-meta">{f.size_mb} MB · {f.chunk_count} chunk{f.chunk_count !== 1 ? 's' : ''}</span>
                                    </div>
                                    <button class="c2-btn-ghost c2-btn-err-small" onclick={() => ragDelete(f.name)} title="Remove from index">✕</button>
                                </div>
                            {/each}
                        {:else if ragDataFiles.length > 0}
                            <p class="c2-rag-empty">Files exist in <code>ct2/data/rag_uploads/</code> but nothing is indexed yet. Click Re-index below.</p>
                        {:else}
                            <p class="c2-rag-empty">No documents indexed yet. Drop a file above to get started, or place files in the <code>ct2/data/rag_uploads/</code> folder and click Re-index.</p>
                        {/if}

                        <!-- Actions + stats -->
                        <div class="c2-rag-actions">
                            <button class="c2-btn-outline" onclick={ragReindex} disabled={ragReindexing}>
                                {ragReindexing ? 'Re-indexing…' : 'Re-index folder'}
                            </button>
                            {#if (ragStatus.files ?? 0) > 0}
                                <span class="c2-rag-stats">
                                    {ragStatus.files} file{ragStatus.files !== 1 ? 's' : ''}
                                    · {ragStatus.chunks} chunks
                                    {#if (ragStatus.context_cost ?? 0) > 0}· ~{ragStatus.context_cost} tokens/msg{/if}
                                </span>
                            {/if}
                        </div>

                        <!-- Context budget note -->
                        {#if (ragStatus.context_cost ?? 0) > 0}
                            <div class="c2-rag-budget">
                                Each message injects ~{ragStatus.context_cost} tokens of document context.
                                With a {config.context_size ? Math.round(config.context_size / 1024) + 'K' : '?'} context window, ~{Math.max(0, (config.context_size ?? 4096) / 3.5 - (ragStatus.context_cost ?? 2000)) | 0} tokens remain for conversation per turn.
                                CT-2 compacts history automatically when the window fills.
                            </div>
                        {/if}
                    {/if}
                {/if}

            <!-- ── WORKSPACES ── -->
            <!-- ── PLAN CACHE ── -->
            {:else if activeSection === 'plancache'}
                <div class="c2-sh">
                    <h1 class="c2-sh-title">Plan cache</h1>
                    <p class="c2-sh-sub">Learned task signatures let the AI skip deliberation and respond faster over time.</p>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Cached entries</div>
                        <div class="c2-row-desc">Each entry maps a task pattern to a fast execution path. Grows automatically as you use the AI.</div>
                    </div>
                    <div class="c2-row-control">
                        <span class="c2-badge-big">{planCacheStats.entries ?? '—'}</span>
                    </div>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Fast-path acceleration</div>
                        <div class="c2-row-desc">When enabled, reusing a cached pattern skips the AI routing and planning steps. Off by default — enable after the cache has entries for your common tasks.</div>
                    </div>
                    <div class="c2-row-control">
                        <button class="c2-toggle" class:c2-toggle-on={planCacheFast} onclick={() => { planCacheFast = !planCacheFast; saveParam('plan_cache_fast', planCacheFast); }} type="button">
                            <span class="c2-toggle-knob"></span>
                        </button>
                    </div>
                </div>

                {#if planCacheStats.recent?.length}
                    <div class="c2-subsection-label" style="margin-top:8px;">Recent entries</div>
                    <div class="c2-pc-list">
                        {#each planCacheStats.recent as p}
                            <div class="c2-pc-item">
                                <div class="c2-pc-item-left">
                                    <span class="c2-pc-sig" title={p.sig}>{p.sig.length > 40 ? p.sig.slice(0, 38) + '…' : p.sig}</span>
                                    <span class="c2-pc-meta">{p.task_type} · {p.complexity} · ×{p.count}</span>
                                </div>
                                <div class="c2-pc-score" style="--score:{p.score}">{p.score.toFixed(1)}</div>
                            </div>
                        {/each}
                    </div>
                {:else if planCacheStats.entries === 0}
                    <p class="c2-row-desc" style="padding-top:8px;">No cached plans yet. Each new task type the AI learns will appear here.</p>
                {/if}

                <div style="margin-top:20px;display:flex;align-items:center;gap:12px;">
                    <button class="c2-btn-outline c2-btn-err" onclick={clearPlanCache} disabled={planCacheClearing}>
                        {planCacheClearing ? 'Clearing…' : 'Clear cache'}
                    </button>
                    {#if planCacheMsg}<span class="c2-row-desc">{planCacheMsg}</span>{/if}
                </div>

            <!-- ── WORKSPACES ── -->
            {:else if activeSection === 'workspaces'}
                <div class="c2-sh">
                    <h1 class="c2-sh-title">Workspaces</h1>
                    <p class="c2-sh-sub">Persistent project folders with file access and terminal integration.</p>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Command approval</div>
                        <div class="c2-row-desc">Require your confirmation before the AI runs each shell command. Applies to all workspaces.</div>
                    </div>
                    <div class="c2-row-control">
                        <button
                            class="c2-switch"
                            class:c2-switch-on={$preferences.requireCommandApproval}
                            onclick={() => preferences.update(p => ({ ...p, requireCommandApproval: !p.requireCommandApproval }))}
                            role="switch"
                            aria-checked={$preferences.requireCommandApproval}
                            aria-label="Toggle command approval"
                        >
                            <span class="c2-switch-knob"></span>
                        </button>
                    </div>
                </div>

                <div class="c2-ws-toolbar">
                    <button class="c2-btn-primary" onclick={startWsCreate}>New workspace</button>
                </div>

                {#if wsCreating}
                    <div class="c2-ws-create-row">
                        <input
                            class="c2-ws-create-input"
                            bind:this={wsNewInput}
                            bind:value={wsNewName}
                            placeholder="Project name"
                            onkeydown={handleWsCreateKeydown}
                        />
                        <button class="c2-btn-primary" onmousedown={(e) => e.preventDefault()} onclick={submitWsCreate}>Create</button>
                        <button class="c2-btn-ghost" style="margin-top:0" onclick={cancelWsCreate}>Cancel</button>
                    </div>
                {/if}

                {#if workspaces.length === 0 && !wsCreating}
                    <div class="c2-empty-state">No workspaces yet.</div>
                {:else}
                    {#each workspaces as ws}
                        <div class="c2-ws-row">
                            <div class="c2-ws-info">
                                <span class="c2-ws-name">{ws.name || ws.id}</span>
                                <span class="c2-ws-meta">{ws.file_count} file{ws.file_count !== 1 ? 's' : ''}{ws.created_at ? ' · ' + fmtWsDate(ws.created_at) : ''}</span>
                            </div>
                            <div style="display:inline-flex;gap:8px;">
                                <button class="c2-btn-primary" onclick={() => openWorkspace(ws.id)}>Open</button>
                                <button
                                    class="c2-btn-outline c2-btn-err"
                                    onclick={() => deleteWorkspace(ws.id)}
                                    disabled={deletingWs === ws.id}
                                >{deletingWs === ws.id ? 'Deleting…' : 'Delete'}</button>
                            </div>
                        </div>
                    {/each}
                {/if}

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

<style>
    .c2-settings {
        position: absolute;
        inset: 0;
        display: grid;
        grid-template-columns: 220px 1fr;
        font-family: 'Geist', ui-sans-serif, system-ui, sans-serif;
        color: var(--c2-fg-0);
        min-height: 0;
    }

    /* Left nav */
    .c2-settings-nav {
        border-right: 1px solid var(--c2-border-1);
        padding: 18px 10px;
        background: oklch(0.165 0.004 260 / 0.6);
        overflow-y: auto;
    }
    :global([data-theme="light"]) .c2-settings-nav {
        background: oklch(0.97 0.002 90 / 0.7);
    }
    .c2-nav-label {
        font-family: 'Geist Mono', monospace;
        padding: 0 10px 10px;
        font-size: 10.5px;
        color: var(--c2-fg-3);
        letter-spacing: 0.5px;
        text-transform: uppercase;
    }
    .c2-nav-item {
        width: 100%;
        display: flex;
        align-items: center;
        padding: 9px 10px;
        margin-bottom: 2px;
        border-radius: 8px;
        background: transparent;
        border: 1px solid transparent;
        color: var(--c2-fg-1);
        font-size: 13px;
        font-family: inherit;
        cursor: pointer;
        transition: background 120ms, color 120ms, border-color 120ms;
        text-align: left;
    }
    .c2-nav-item:hover { background: var(--c2-bg-2); color: var(--c2-fg-0); }
    .c2-nav-item-active {
        background: var(--c2-bg-2);
        border-color: var(--c2-border-2);
        color: var(--c2-fg-0);
    }

    /* Content area */
    .c2-settings-content {
        overflow-y: auto;
        scrollbar-width: thin;
        scrollbar-color: var(--c2-border-2) transparent;
    }
    .c2-settings-inner {
        max-width: 860px;
        padding: 40px 52px 96px;
    }

    /* Section heading */
    .c2-sh { margin-bottom: 28px; }
    .c2-sh-title {
        font-family: 'Instrument Serif', 'Cormorant Garamond', Georgia, serif;
        font-size: 36px;
        font-weight: 400;
        letter-spacing: -0.6px;
        margin: 0;
        line-height: 1.05;
        color: var(--c2-fg-0);
    }
    .c2-sh-sub {
        font-size: 13.5px;
        color: var(--c2-fg-2);
        margin: 8px 0 0;
        max-width: 480px;
    }

    /* Row pattern */
    .c2-row {
        display: grid;
        grid-template-columns: 280px 1fr;
        gap: 36px;
        padding: 22px 0;
        border-top: 1px solid var(--c2-border-1);
        align-items: start;
    }
    .c2-row-name {
        font-size: 14px;
        color: var(--c2-fg-0);
        font-weight: 500;
    }
    .c2-param {
        font-family: 'Geist Mono', monospace;
        color: var(--c2-fg-3);
        font-weight: 400;
        font-size: 12px;
    }
    .c2-row-desc {
        font-size: 12.5px;
        color: var(--c2-fg-2);
        margin-top: 4px;
        line-height: 1.5;
    }
    .c2-row-control {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 8px;
    }

    /* Segment control */
    .c2-seg {
        display: inline-flex;
        padding: 3px;
        border-radius: 10px;
        background: var(--c2-bg-2);
        border: 1px solid var(--c2-border-1);
        gap: 2px;
    }
    .c2-seg-btn {
        height: 28px;
        padding: 0 12px;
        border-radius: 7px;
        font-size: 12px;
        font-weight: 500;
        font-family: inherit;
        color: var(--c2-fg-2);
        background: transparent;
        border: 1px solid transparent;
        cursor: pointer;
        transition: color var(--c2-dur-fast), background var(--c2-dur-fast), border-color var(--c2-dur-fast);
    }
    .c2-seg-btn:hover:not(:disabled):not(.c2-seg-active) { color: var(--c2-fg-0); }
    .c2-seg-active {
        background: var(--c2-bg-0);
        color: var(--c2-fg-0);
        border-color: var(--c2-border-2);
        box-shadow: 0 1px 0 var(--c2-border-2) inset;
    }
    .c2-seg-btn:disabled { opacity: 0.4; cursor: not-allowed; }

    /* Switch */
    .c2-switch {
        position: relative;
        width: 34px;
        height: 20px;
        border-radius: 999px;
        background: var(--c2-bg-3);
        border: 1px solid var(--c2-border-2);
        cursor: pointer;
        transition: background 160ms, border-color 160ms;
        flex-shrink: 0;
    }
    .c2-switch:disabled { opacity: 0.5; cursor: not-allowed; }
    .c2-switch-on {
        background: oklch(0.58 0.17 145);
        border-color: oklch(0.58 0.17 145);
        box-shadow: 0 0 0 3px oklch(0.58 0.17 145 / 0.18);
    }
    .c2-switch-knob {
        position: absolute;
        top: 2px;
        left: 2px;
        width: 14px;
        height: 14px;
        border-radius: 50%;
        background: var(--c2-fg-1);
        transition: left 260ms cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 220ms ease;
        box-shadow: 0 1px 3px rgba(0,0,0,0.3), 0 0 0 1px rgba(0,0,0,0.08);
    }
    .c2-switch-on .c2-switch-knob {
        left: 16px;
        background: white;
        box-shadow: 0 1px 3px rgba(0,0,0,0.2), 0 0 0 1px rgba(0,0,0,0.04);
    }

    /* Slider */
    .c2-slider-wrap {
        display: flex;
        align-items: center;
        gap: 14px;
        width: 100%;
    }
    .c2-slider {
        flex: 1;
        appearance: none;
        height: 4px;
        border-radius: 999px;
        background: var(--c2-bg-3);
        outline: none;
        cursor: pointer;
    }
    .c2-slider::-webkit-slider-thumb {
        appearance: none;
        width: 16px;
        height: 16px;
        border-radius: 50%;
        background: var(--c2-fg-0);
        border: 1px solid var(--c2-border-2);
        box-shadow: 0 2px 6px oklch(0 0 0 / 0.35);
        cursor: pointer;
    }
    .c2-slider:disabled { opacity: 0.4; cursor: not-allowed; }
    .c2-slider-val {
        font-family: 'Geist Mono', monospace;
        min-width: 56px;
        text-align: right;
        font-size: 13px;
        color: var(--c2-fg-0);
        padding: 4px 8px;
        border-radius: 6px;
        background: var(--c2-bg-2);
        border: 1px solid var(--c2-border-1);
    }

    /* Readonly value */
    .c2-readonly-val {
        font-family: 'Geist Mono', monospace;
        font-size: 13px;
        color: var(--c2-fg-0);
        padding: 4px 10px;
        border-radius: 6px;
        background: var(--c2-bg-2);
        border: 1px solid var(--c2-border-1);
    }

    /* Model card */
    .c2-model-card {
        display: flex;
        align-items: center;
        gap: 16px;
        padding: 18px 20px;
        border-radius: 14px;
        border: 1px solid var(--c2-border-2);
        background: var(--c2-bg-1);
        margin-bottom: 8px;
    }
    .c2-model-icon {
        width: 42px;
        height: 42px;
        border-radius: 10px;
        background: var(--c2-accent-dim);
        color: var(--c2-accent);
        display: inline-flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
    }
    .c2-model-info { flex: 1; }
    .c2-model-name { font-size: 15px; font-weight: 500; }
    .c2-model-meta {
        font-family: 'Geist Mono', monospace;
        font-size: 12px;
        color: var(--c2-fg-2);
        margin-top: 2px;
    }

    /* Model row (other models list) */
    .c2-model-row {
        display: flex;
        align-items: center;
        gap: 14px;
        padding: 12px 16px;
        border-radius: 10px;
        border: 1px solid var(--c2-border-1);
        margin-bottom: 6px;
        cursor: pointer;
        background: var(--c2-bg-1);
        width: 100%;
        text-align: left;
        font-family: inherit;
        font-size: 13.5px;
        color: var(--c2-fg-0);
        transition: background 120ms;
    }
    .c2-model-row:hover:not(:disabled) { background: var(--c2-bg-2); }
    .c2-model-row:disabled { opacity: 0.5; cursor: not-allowed; }
    .c2-radio {
        width: 16px;
        height: 16px;
        border-radius: 50%;
        border: 1.5px solid var(--c2-border-3);
        flex-shrink: 0;
    }
    .c2-mr-name { flex: 1; }
    .c2-mr-size {
        font-family: 'Geist Mono', monospace;
        font-size: 12px;
        color: var(--c2-fg-3);
    }

    /* Badges */
    .c2-badge {
        font-family: 'Geist Mono', monospace;
        display: inline-flex;
        align-items: center;
        height: 20px;
        padding: 0 7px;
        font-size: 10.5px;
        font-weight: 500;
        letter-spacing: 0.3px;
        text-transform: uppercase;
        background: var(--c2-bg-3);
        color: var(--c2-fg-1);
        border: 1px solid var(--c2-border-2);
        border-radius: 4px;
    }
    .c2-badge-green {
        background: oklch(0.32 0.07 150 / 0.28);
        color: var(--c2-ok);
        border-color: oklch(0.5 0.1 150 / 0.4);
    }
    :global([data-theme="light"]) .c2-badge-green {
        background: oklch(0.94 0.05 150 / 0.5);
        border-color: oklch(0.62 0.10 150 / 0.45);
    }
    .c2-badge-yellow {
        background: oklch(0.35 0.07 85 / 0.28);
        color: var(--c2-warn);
        border-color: oklch(0.55 0.10 85 / 0.4);
    }
    :global([data-theme="light"]) .c2-badge-yellow {
        background: oklch(0.94 0.05 85 / 0.5);
        border-color: oklch(0.65 0.10 85 / 0.45);
    }

    /* Subsection label */
    .c2-subsection-label {
        font-family: 'Geist Mono', monospace;
        font-size: 11px;
        color: var(--c2-fg-3);
        letter-spacing: 0.4px;
        text-transform: uppercase;
        margin: 24px 0 8px;
    }

    /* Buttons */
    .c2-btn-primary {
        height: 30px;
        padding: 0 12px;
        border-radius: 8px;
        background: var(--c2-accent);
        color: var(--c2-accent-fg);
        border: none;
        font-size: 12.5px;
        font-weight: 500;
        font-family: inherit;
        cursor: pointer;
        transition: opacity 120ms;
    }
    .c2-btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
    .c2-btn-ghost {
        height: 30px;
        padding: 0 12px;
        border-radius: 8px;
        background: transparent;
        color: var(--c2-fg-1);
        border: 1px solid var(--c2-border-1);
        font-size: 12.5px;
        font-family: inherit;
        cursor: pointer;
        transition: background 120ms;
        margin-top: 8px;
    }
    .c2-btn-ghost:hover:not(:disabled) { background: var(--c2-bg-2); }
    .c2-btn-ghost:disabled { opacity: 0.5; cursor: not-allowed; }
    .c2-btn-outline {
        height: 30px;
        padding: 0 12px;
        border-radius: 8px;
        background: transparent;
        font-size: 12.5px;
        font-family: inherit;
        cursor: pointer;
        transition: background 120ms;
        border: 1px solid var(--c2-border-2);
        color: var(--c2-fg-1);
    }
    .c2-btn-outline:hover:not(:disabled) { background: var(--c2-bg-2); }
    .c2-btn-warn { color: var(--c2-warn); border-color: oklch(0.68 0.10 80 / 0.4); }
    .c2-btn-err { color: var(--c2-err); border-color: oklch(0.55 0.15 25 / 0.4); }
    .c2-btn-outline:disabled { opacity: 0.5; cursor: not-allowed; }
    .c2-btn-danger {
        height: 30px;
        padding: 0 12px;
        border-radius: 8px;
        background: var(--c2-err);
        color: white;
        border: none;
        font-size: 12.5px;
        font-weight: 500;
        font-family: inherit;
        cursor: pointer;
    }

    /* Misc */
    .c2-error-row {
        font-size: 12.5px;
        color: var(--c2-err);
        padding: 8px 0;
    }
    .c2-inline-err {
        font-size: 12px;
        color: var(--c2-err);
    }
    .c2-skeleton {
        height: 80px;
        border-radius: 10px;
        background: var(--c2-bg-2);
        animation: c2-shimmer 1.4s ease-in-out infinite;
    }
    @keyframes c2-shimmer {
        0%, 100% { opacity: 0.6; }
        50% { opacity: 1; }
    }
    .c2-empty-state {
        font-size: 14px;
        color: var(--c2-fg-3);
        padding: 32px 0;
        text-align: center;
    }
    .c2-model-toolbar { margin-bottom: 16px; }
    .c2-ws-toolbar { margin-bottom: 16px; }

    .c2-ws-create-row {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 16px;
    }
    .c2-ws-create-input {
        flex: 1;
        height: 32px;
        padding: 0 12px;
        font-size: 13px;
        font-family: inherit;
        color: var(--c2-fg-0);
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-2);
        border-radius: 8px;
        outline: none;
        min-width: 0;
    }
    .c2-ws-create-input:focus { border-color: var(--c2-accent); }
    .c2-ws-create-input::placeholder { color: var(--c2-fg-3); }

    .c2-ws-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 14px 0;
        border-top: 1px solid var(--c2-border-1);
        gap: 16px;
    }
    .c2-ws-info { display: flex; flex-direction: column; gap: 2px; }
    .c2-ws-name { font-size: 13.5px; font-weight: 500; color: var(--c2-fg-0); }
    .c2-ws-meta { font-family: 'Geist Mono', monospace; font-size: 11.5px; color: var(--c2-fg-3); }

    /* ── Mode cards (response tuning) ──────────────────────────── */
    .c2-mode-card {
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-1);
        border-radius: 12px;
        padding: 20px 22px 16px;
        margin-bottom: 12px;
    }
    .c2-mode-header {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 16px;
    }
    .c2-mode-name {
        font-size: 14px;
        font-weight: 600;
        color: var(--c2-fg-0);
        flex: 1;
    }
    .c2-mode-desc {
        font-size: 12.5px;
        color: var(--c2-fg-2);
    }
    .c2-mode-reset {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        font-size: 11.5px;
        font-family: inherit;
        color: var(--c2-fg-3);
        background: none;
        border: 1px solid transparent;
        border-radius: 6px;
        padding: 3px 8px;
        cursor: pointer;
        transition: color 120ms, background 120ms, border-color 120ms;
    }
    .c2-mode-reset:hover { color: var(--c2-fg-1); background: var(--c2-bg-2); border-color: var(--c2-border-1); }
    .c2-mode-reset-active { color: var(--c2-warn); }

    .c2-mode-param {
        margin-bottom: 16px;
    }
    .c2-mode-param:last-of-type { margin-bottom: 0; }
    .c2-mode-param-header {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 8px;
    }
    .c2-mode-param-label {
        font-size: 13px;
        font-weight: 500;
        color: var(--c2-fg-0);
        flex: 1;
    }
    .c2-mode-footer {
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: 10px;
        padding-top: 14px;
        margin-top: 14px;
        border-top: 1px solid var(--c2-border-1);
    }

    /* ── Prompt cards ──────────────────────────────────────────── */
    .c2-prompt-card {
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-1);
        border-radius: 12px;
        padding: 20px 22px;
        margin-bottom: 12px;
        display: flex;
        flex-direction: column;
        gap: 12px;
    }
    .c2-prompt-card-header {
        display: flex;
        flex-direction: column;
        gap: 3px;
    }
    .c2-prompt-card-name {
        font-size: 14px;
        font-weight: 600;
        color: var(--c2-fg-0);
    }
    .c2-prompt-card-desc {
        font-size: 12.5px;
        color: var(--c2-fg-2);
        line-height: 1.4;
    }
    .c2-prompt-group-header {
        display: flex;
        flex-direction: column;
        gap: 2px;
        margin-bottom: 10px;
        padding: 0 2px;
    }
    .c2-prompt-group-label {
        font-size: 10.5px;
        font-weight: 650;
        color: var(--c2-fg-2);
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }
    .c2-prompt-group-desc {
        font-size: 12px;
        color: var(--c2-fg-3);
        line-height: 1.4;
    }
    .c2-prompt-card-key {
        font-family: 'Geist Mono', monospace;
        font-size: 11px;
        color: var(--c2-fg-3);
        margin-top: 1px;
    }
    .c2-prompt-danger-badge {
        display: inline-flex;
        align-items: center;
        margin-left: 8px;
        font-size: 9.5px;
        font-weight: 600;
        font-family: 'Geist Mono', monospace;
        padding: 2px 6px;
        border-radius: 4px;
        background: oklch(0.55 0.16 45 / 0.12);
        border: 1px solid oklch(0.55 0.16 45 / 0.28);
        color: oklch(0.55 0.16 45);
        text-transform: uppercase;
        letter-spacing: 0.04em;
        vertical-align: middle;
    }
    .c2-prompt-danger-notice {
        font-size: 12.5px;
        line-height: 1.5;
        color: oklch(0.52 0.14 45);
        background: oklch(0.55 0.16 45 / 0.07);
        border: 1px solid oklch(0.55 0.16 45 / 0.22);
        border-radius: 8px;
        padding: 10px 14px;
    }
    .c2-prompt-textarea {
        width: 100%;
        font-family: 'Geist Mono', monospace;
        font-size: 12.5px;
        line-height: 1.6;
        color: var(--c2-fg-0);
        background: var(--c2-bg-0);
        border: 1px solid var(--c2-border-2);
        border-radius: 8px;
        padding: 12px 14px;
        resize: vertical;
        outline: none;
        transition: border-color 120ms;
        box-sizing: border-box;
        min-height: 120px;
    }
    .c2-prompt-textarea:focus { border-color: var(--c2-accent); }
    .c2-prompt-textarea::placeholder { color: var(--c2-fg-3); }
    .c2-prompts-restart-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 10px 14px;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-1);
        border-radius: 10px;
        margin-bottom: 18px;
        font-size: 12.5px;
        color: var(--c2-fg-2);
    }
    .c2-prompt-saved-notice {
        font-size: 12px;
        color: var(--c2-warn);
        background: oklch(0.68 0.10 80 / 0.08);
        border: 1px solid oklch(0.68 0.10 80 / 0.2);
        border-radius: 6px;
        padding: 8px 12px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
    }
    .c2-prompt-restart-inline {
        flex-shrink: 0;
        padding: 4px 12px;
        font-size: 11px;
        font-weight: 600;
        font-family: inherit;
        color: var(--c2-warn);
        background: oklch(0.68 0.10 80 / 0.12);
        border: 1px solid oklch(0.68 0.10 80 / 0.3);
        border-radius: 6px;
        cursor: pointer;
        transition: opacity 120ms;
    }
    .c2-prompt-restart-inline:disabled { opacity: 0.5; cursor: wait; }
    .c2-prompt-footer {
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: 8px;
    }
    .c2-btn-ghost { margin-top: 0; }

    /* ── Expand chevron ───────────────────────────────────────── */
    .c2-expand-header {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background: none;
        border: none;
        color: var(--c2-fg-1);
        font-family: 'Geist Mono', monospace;
        font-size: 10.5px;
        letter-spacing: 0.5px;
        text-transform: uppercase;
        cursor: pointer;
        padding: 4px 0;
        transition: color 120ms;
    }
    .c2-expand-header:hover { color: var(--c2-fg-0); }
    .c2-expand-chevron {
        flex-shrink: 0;
        color: var(--c2-fg-2);
        transition: transform 180ms var(--c2-spring);
    }
    .c2-expand-chevron.c2-expand-open { transform: rotate(90deg); }

    /* ── Toggle switch ────────────────────────────────────────── */
    .c2-toggle {
        width: 40px;
        height: 22px;
        border-radius: 999px;
        border: 1px solid var(--c2-border-2);
        background: var(--c2-bg-3);
        cursor: pointer;
        position: relative;
        transition: background 180ms, border-color 180ms;
        flex-shrink: 0;
    }
    .c2-toggle.c2-toggle-on {
        background: var(--c2-accent);
        border-color: var(--c2-accent);
    }
    .c2-toggle-knob {
        position: absolute;
        top: 1px;
        left: 1px;
        width: 18px;
        height: 18px;
        border-radius: 50%;
        background: var(--c2-fg-0);
        transition: transform 180ms var(--c2-spring);
    }
    .c2-toggle-on .c2-toggle-knob {
        transform: translateX(18px);
        background: var(--c2-accent-fg);
    }

    /* ── Plan cache list ─────────────────────────────────────────── */
    .c2-badge-big {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 36px;
        height: 28px;
        padding: 0 10px;
        border-radius: 14px;
        background: var(--c2-accent-dim);
        color: var(--c2-accent);
        font-family: 'Geist Mono', monospace;
        font-size: 14px;
        font-weight: 600;
    }
    .c2-pc-list {
        display: flex;
        flex-direction: column;
        gap: 2px;
        margin-top: 6px;
        max-height: 200px;
        overflow-y: auto;
    }
    .c2-pc-item {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 5px 10px;
        border-radius: 6px;
        background: var(--c2-bg-2);
        border: 1px solid var(--c2-border-2);
        font-size: 11.5px;
    }
    .c2-pc-item-left {
        display: flex;
        flex-direction: column;
        gap: 1px;
        min-width: 0;
    }
    .c2-pc-sig {
        font-family: 'Geist Mono', monospace;
        font-size: 11px;
        color: var(--c2-fg-0);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .c2-pc-meta {
        font-family: 'Geist Mono', monospace;
        font-size: 10px;
        color: var(--c2-fg-3);
    }
    .c2-pc-score {
        flex-shrink: 0;
        width: 30px;
        height: 20px;
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-family: 'Geist Mono', monospace;
        font-size: 10.5px;
        font-weight: 600;
        background: color-mix(in srgb, var(--c2-accent) calc(var(--score, 0.5) * 100%), var(--c2-bg-3));
        color: var(--c2-accent-fg);
    }

    /* RAG */
    .c2-rag-restart {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        margin-top: 4px;
        padding: 11px 16px;
        border-radius: 10px;
        border: 1px solid oklch(0.68 0.10 80 / 0.3);
        background: oklch(0.68 0.10 80 / 0.07);
    }
    .c2-rag-restart-left {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 13px;
        color: var(--c2-warn);
    }
    .c2-rag-empty {
        padding: 28px 0 12px;
        font-size: 13px;
        color: var(--c2-fg-3);
        line-height: 1.55;
    }
    .c2-rag-actions {
        display: flex;
        align-items: center;
        gap: 16px;
        margin-top: 16px;
    }
    .c2-rag-stats {
        font-family: 'Geist Mono', monospace;
        font-size: 11.5px;
        color: var(--c2-fg-3);
    }
    .c2-rag-drop {
        margin-top: 16px;
        border: 1.5px dashed var(--c2-border-2);
        border-radius: 12px;
        padding: 32px 20px;
        text-align: center;
        cursor: pointer;
        background: var(--c2-bg-1);
        transition: border-color var(--c2-transition), background var(--c2-transition);
        user-select: none;
    }
    .c2-rag-drop:hover,
    .c2-rag-drop-over {
        border-color: var(--c2-accent);
        background: var(--c2-accent-dim);
    }
    .c2-rag-drop-icon {
        display: flex;
        align-items: center;
        justify-content: center;
        margin-bottom: 10px;
        color: var(--c2-fg-3);
        transition: color var(--c2-transition);
    }
    .c2-rag-drop:hover .c2-rag-drop-icon,
    .c2-rag-drop-over .c2-rag-drop-icon {
        color: var(--c2-accent);
    }
    .c2-rag-spin {
        animation: rag-spin 1s linear infinite;
    }
    @keyframes rag-spin {
        to { transform: rotate(360deg); }
    }
    .c2-rag-drop-text {
        display: block;
        font-size: 14px;
        font-weight: 500;
        color: var(--c2-fg-0);
    }
    .c2-rag-drop-hint {
        display: block;
        font-size: 11px;
        font-family: 'Geist Mono', monospace;
        letter-spacing: 0.2px;
        color: var(--c2-fg-3);
        margin-top: 6px;
    }
    .c2-rag-msg {
        margin-top: 10px;
        font-size: 12.5px;
        color: var(--c2-ok);
        padding: 8px 12px;
        border-radius: 8px;
        border: 1px solid var(--c2-border-1);
        background: var(--c2-bg-2);
    }
    .c2-rag-msg-err {
        color: var(--c2-err);
    }
    .c2-rag-file {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 11px 14px;
        border: 1px solid var(--c2-border-1);
        border-radius: 10px;
        background: var(--c2-bg-1);
        margin-top: 6px;
        transition: background var(--c2-transition);
    }
    .c2-rag-file:hover {
        background: var(--c2-bg-2);
    }
    .c2-rag-file-info {
        display: flex;
        flex-direction: column;
        min-width: 0;
    }
    .c2-rag-file-name {
        font-size: 13px;
        font-weight: 500;
        color: var(--c2-fg-0);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .c2-rag-file-meta {
        font-family: 'Geist Mono', monospace;
        font-size: 11px;
        color: var(--c2-fg-3);
        margin-top: 3px;
    }
    .c2-rag-budget {
        margin-top: 16px;
        font-size: 12px;
        color: var(--c2-fg-2);
        line-height: 1.6;
        padding: 12px 14px;
        border: 1px solid var(--c2-border-1);
        border-radius: 10px;
        background: var(--c2-bg-1);
    }

    /* ── RAG progress bar ────────────────────────────────────────── */
    .c2-rag-progress-wrap {
        margin-top: 14px;
        padding: 14px 16px;
        border: 1px solid var(--c2-border-1);
        border-radius: 10px;
        background: var(--c2-bg-1);
    }
    .c2-rag-progress-bar {
        width: 100%;
        height: 6px;
        border-radius: 3px;
        background: var(--c2-bg-3);
        overflow: hidden;
    }
    .c2-rag-progress-fill {
        height: 100%;
        border-radius: 3px;
        background: var(--c2-accent);
        transition: width 250ms ease-out;
    }
    .c2-rag-progress-indeterminate {
        width: 30%;
        animation: rag-indeterminate 1.4s ease-in-out infinite;
    }
    @keyframes rag-indeterminate {
        0% { transform: translateX(-100%); }
        100% { transform: translateX(400%); }
    }
    .c2-rag-progress-text {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-top: 8px;
        font-family: 'Geist Mono', monospace;
        font-size: 11.5px;
        color: var(--c2-fg-2);
    }
    .c2-rag-progress-pct {
        font-weight: 600;
        color: var(--c2-accent);
    }
    .c2-rag-progress-file {
        margin-top: 4px;
        font-size: 11px;
        color: var(--c2-fg-3);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    /* ── RAG data files list ─────────────────────────────────────── */
    .c2-rag-path-label {
        font-family: 'Geist Mono', monospace;
        font-size: 11px;
        padding: 1px 6px;
        border-radius: 4px;
        background: var(--c2-bg-3);
        color: var(--c2-fg-2);
    }
    .c2-rag-count-badge {
        font-family: 'Geist Mono', monospace;
        font-size: 10.5px;
        font-weight: 600;
        padding: 1px 7px;
        border-radius: 10px;
        background: var(--c2-accent-dim);
        color: var(--c2-accent);
        margin-left: 6px;
        vertical-align: middle;
    }
    .c2-rag-datafile-list {
        display: flex;
        flex-direction: column;
        gap: 3px;
        margin-top: 6px;
    }
    .c2-rag-datafile {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        padding: 9px 14px;
        border: 1px solid var(--c2-border-1);
        border-radius: 8px;
        background: var(--c2-bg-1);
        transition: background var(--c2-transition);
    }
    .c2-rag-datafile:hover {
        background: var(--c2-bg-2);
    }
    .c2-rag-datafile-idx {
        border-left: 3px solid var(--c2-ok);
    }
    .c2-rag-datafile-info {
        display: flex;
        flex-direction: column;
        min-width: 0;
    }
    .c2-rag-datafile-name {
        font-size: 12.5px;
        font-weight: 500;
        color: var(--c2-fg-0);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .c2-rag-datafile-meta {
        font-family: 'Geist Mono', monospace;
        font-size: 10.5px;
        color: var(--c2-fg-3);
        margin-top: 2px;
    }
    .c2-rag-datafile-actions {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-shrink: 0;
    }
    .c2-rag-datafile-dot {
        flex-shrink: 0;
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: var(--c2-fg-4);
        transition: background var(--c2-transition);
    }
    .c2-rag-datafile-dot.green {
        background: var(--c2-ok);
    }

    /* ── Security tab: text input + status tag ─────────────────── */
    .c2-input {
        height: 36px;
        padding: 0 12px;
        background: var(--c2-bg-2);
        border: 1px solid var(--c2-border-2);
        border-radius: 8px;
        color: var(--c2-fg-0);
        font: inherit;
        font-size: 13px;
        outline: none;
        transition: border-color 140ms, background 140ms;
    }
    .c2-input:focus {
        border-color: var(--c2-accent);
        background: var(--c2-bg-1);
    }
    .c2-input:disabled { opacity: 0.6; cursor: not-allowed; }

    .c2-tag {
        display: inline-block;
        padding: 2px 9px;
        background: var(--c2-bg-2);
        border: 1px solid var(--c2-border-2);
        border-radius: 999px;
        font-size: 11px;
        font-weight: 600;
        color: var(--c2-fg-2);
        letter-spacing: 0.02em;
    }
    .c2-tag.c2-tag-active {
        background: oklch(0.78 0.10 70 / 0.14);
        border-color: oklch(0.78 0.10 70 / 0.45);
        color: var(--c2-accent);
    }
</style>
