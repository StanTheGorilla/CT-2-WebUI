<script lang="ts">
    import { tick, onMount } from 'svelte';
    import { chat, sendThink, stopGeneration, setMode, revertToTurn, editTurn, setFeedback, regenerate, setContextSize, clearPendingCommands, clearPendingApproval, toggleRag, cancelCompaction, toggleContextFile, clearContextFiles, pendingInputPrompt, type Attachment } from '$lib/stores/chat';
    import { preferences } from '$lib/stores/preferences';
    import { showToast } from '$lib/stores/toasts';
    import { render } from '$lib/markdown';
    import PreviewPanel from './PreviewPanel.svelte';
    import './chat.css';
    import ContextSummaryBlock from '$lib/components/ContextSummaryBlock.svelte';
    import FileTree from '$lib/components/FileTree.svelte';
    import TerminalPanel from '$lib/components/TerminalPanel.svelte';
    import {
        CHAT_MODE_ITEMS,
        CHAT_MODE_LABELS,
        copyText,
        getPhaseLabel,
        getRouteLabel,
        getTurnOutputExt,
        getTurnOutputFilename,
        stripCodeFences,
        stripFileMarkers,
    } from '$lib/chatUi';

    // ── Composer state ───────────────────────────────────────────
    let text = $state('');
    let attachments = $state<Attachment[]>([]);
    let fileInput = $state<HTMLInputElement | null>(null);
    let visionSupported = $state(false);
    let dragOver = $state(false);
    let wsCtxOpen = $state(false);
    let wsFileList = $state<string[]>([]);
    let wsFileLoading = $state(false);
    let wsFileReq = 0;
    const TEXT_FILE_ACCEPT = '.txt,.html,.htm,.css,.js,.ts,.py,.json,.md,.csv,.xml,.yaml,.yml,.svg,.sh,.bat,.sql,.rb,.go,.rs,.java,.c,.cpp,.h,.hpp,.toml,.ini,.cfg';
    const TEXT_EXTENSIONS = new Set([
        'txt', 'html', 'htm', 'css', 'js', 'ts', 'py', 'json', 'md',
        'csv', 'xml', 'yaml', 'yml', 'svg', 'sh', 'bat', 'sql', 'rb',
        'go', 'rs', 'java', 'c', 'cpp', 'h', 'hpp', 'toml', 'ini', 'cfg',
    ]);
    const IMAGE_MAX_PX = 1536;
    let feedEl = $state<HTMLDivElement | null>(null);
    let userNearBottom = $state(true);

    function onFeedScroll() {
        if (!feedEl) return;
        const gap = feedEl.scrollHeight - feedEl.scrollTop - feedEl.clientHeight;
        userNearBottom = gap < 120;
    }
    let taEl   = $state<HTMLTextAreaElement | null>(null);
    let hoveredTurn = $state<number | null>(null);
    let contextSize = $state(0);
    let ragCost = $state(0);
    let expandedThinking = $state(new Set<number>());
    let expandedSearches = $state(new Set<number>());
    let latestCompactionOpen = $state(false);
    let latestCompactionKey = $state('');
    let liveThinkingOpen = $state(false);
    let editingTurn = $state<number | null>(null);
    let editText = $state('');
    let editTaEl = $state<HTMLTextAreaElement | null>(null);

    function startEdit(idx: number, content: string) {
        editingTurn = idx;
        editText = content;
        tick().then(() => {
            if (editTaEl) {
                editTaEl.focus();
                editTaEl.setSelectionRange(editTaEl.value.length, editTaEl.value.length);
                autosizeEditTa();
            }
        });
    }

    function cancelEdit() {
        editingTurn = null;
        editText = '';
    }

    function saveEdit() {
        if (editingTurn === null) return;
        const trimmed = editText.trim();
        if (!trimmed) return;
        const idx = editingTurn;
        editingTurn = null;
        editText = '';
        editTurn(idx, trimmed);
    }

    function autosizeEditTa() {
        if (!editTaEl) return;
        editTaEl.style.height = 'auto';
        editTaEl.style.height = Math.min(editTaEl.scrollHeight, 320) + 'px';
    }

    function handleEditKey(e: KeyboardEvent) {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveEdit(); }
        else if (e.key === 'Escape') { e.preventDefault(); cancelEdit(); }
    }

    onMount(async () => {
        try {
            const [cfg, mdl, rag] = await Promise.all([
                fetch('/api/config').then(r => r.json()),
                fetch('/api/model').then(r => r.json()),
                fetch('/api/rag/status').then(r => r.json()),
            ]);
            const sz = mdl.context_size ?? cfg.context_size ?? 0;
            contextSize = sz;
            setContextSize(sz);
            ragCost = rag.enabled ? (rag.context_cost ?? 0) : 0;
            visionSupported = mdl.vision_supported ?? false;
        } catch {}
    });

    // ── Attachment helpers ───────────────────────────────────────
    const attachAccept = $derived(`${visionSupported ? 'image/*,' : ''}${TEXT_FILE_ACCEPT}`);
    const attachLabel = $derived(visionSupported ? 'Attach file or image' : 'Attach file (current model has no vision)');

    function getExtension(name: string): string {
        const i = name.lastIndexOf('.');
        return i >= 0 ? name.slice(i + 1).toLowerCase() : '';
    }

    function _resizeAndAttach(srcUrl: string, name: string) {
        const img = new Image();
        img.onload = () => {
            const w = img.naturalWidth, h = img.naturalHeight;
            if (w <= IMAGE_MAX_PX && h <= IMAGE_MAX_PX) {
                attachments = [...attachments, { type: 'image', name, dataUrl: srcUrl }];
                return;
            }
            const scale = IMAGE_MAX_PX / Math.max(w, h);
            const canvas = document.createElement('canvas');
            canvas.width  = Math.round(w * scale);
            canvas.height = Math.round(h * scale);
            canvas.getContext('2d')!.drawImage(img, 0, 0, canvas.width, canvas.height);
            attachments = [...attachments, { type: 'image', name, dataUrl: canvas.toDataURL('image/png') }];
        };
        img.src = srcUrl;
    }

    function readFiles(files: FileList | File[]) {
        const remainingSlots = Math.max(0, 4 - attachments.length);
        if (remainingSlots === 0) {
            showToast('Up to 4 attachments per message', { variant: 'info' });
            return;
        }
        let acceptedCount = 0;
        let skippedVision = 0;
        let skippedType = 0;
        for (const file of Array.from(files)) {
            if (acceptedCount >= remainingSlots) break;
            const ext = getExtension(file.name);
            if (file.type.startsWith('image/')) {
                if (!visionSupported) { skippedVision += 1; continue; }
                const reader = new FileReader();
                const fileName = file.name || 'image.png';
                reader.onload = () => _resizeAndAttach(reader.result as string, fileName);
                reader.readAsDataURL(file);
                acceptedCount += 1;
            } else if (TEXT_EXTENSIONS.has(ext) || file.type.startsWith('text/')) {
                const reader = new FileReader();
                reader.onload = () => {
                    const txt = reader.result as string;
                    const truncated = txt.length > 8000
                        ? txt.slice(0, 8000) + '\n\n[... truncated, file too large ...]'
                        : txt;
                    attachments = [...attachments, {
                        type: 'file',
                        name: file.name,
                        dataUrl: '',
                        textContent: truncated,
                    }];
                };
                reader.readAsText(file);
                acceptedCount += 1;
            } else {
                skippedType += 1;
            }
        }
        if (skippedVision > 0) {
            showToast('Switch to a vision model to attach images', {
                variant: 'info',
                title: 'Image skipped',
            });
        }
        if (skippedType > 0 && acceptedCount === 0) {
            showToast('Only text files and images are supported', { variant: 'info' });
        }
    }

    function onAttachInput(e: Event) {
        const target = e.target as HTMLInputElement;
        if (target.files) readFiles(target.files);
        target.value = '';
    }

    function onDrop(e: DragEvent) {
        e.preventDefault();
        dragOver = false;
        if (e.dataTransfer?.files) readFiles(e.dataTransfer.files);
    }
    function onDragOver(e: DragEvent) { e.preventDefault(); dragOver = true; }
    function onDragLeave() { dragOver = false; }

    function onPaste(e: ClipboardEvent) {
        const items = e.clipboardData?.items;
        if (!items) return;
        const images: File[] = [];
        for (const item of items) {
            if (item.type.startsWith('image/')) {
                const file = item.getAsFile();
                if (file) images.push(file);
            }
        }
        if (images.length > 0 && visionSupported) {
            e.preventDefault();
            readFiles(images);
        }
    }

    function removeAttachment(idx: number) {
        attachments = attachments.filter((_, i) => i !== idx);
    }

    // ── Workspace context popover ────────────────────────────────
    async function openWsCtx() {
        const wsId = $chat.workspaceId;
        if (!wsId) return;
        wsCtxOpen = !wsCtxOpen;
        if (!wsCtxOpen) return;
        const reqId = ++wsFileReq;
        wsFileList = [];
        wsFileLoading = true;
        try {
            const res = await fetch(`/api/workspaces/${wsId}/files`);
            const data = await res.json();
            if (reqId !== wsFileReq || wsId !== $chat.workspaceId || !wsCtxOpen) return;
            wsFileList = (data as Array<{ path: string; is_dir: boolean }>)
                .filter(f => !f.is_dir).map(f => f.path);
        } catch {
            if (reqId === wsFileReq) wsFileList = [];
        } finally {
            if (reqId === wsFileReq) wsFileLoading = false;
        }
    }

    function handleOutsideClick(e: MouseEvent) {
        const target = e.target as HTMLElement;
        if (!target.closest('.c2-ctx-popover') && !target.closest('.c2-ws-ctx-badge')) {
            wsCtxOpen = false;
        }
    }
    function handleGlobalKey(e: KeyboardEvent) {
        if (e.key === 'Escape' && wsCtxOpen) wsCtxOpen = false;
    }

    // Reset workspace popover when switching workspaces
    $effect(() => {
        void $chat.workspaceId;
        wsCtxOpen = false;
        wsFileList = [];
    });

    // Listen for prefill prompts (e.g., from "Try again" buttons)
    $effect(() => {
        const prompt = $pendingInputPrompt;
        if (prompt) {
            text = prompt;
            pendingInputPrompt.set('');
            tick().then(() => taEl?.focus());
        }
    });

    // ── Derived ──────────────────────────────────────────────────
    let isActive  = $derived($chat.phase !== 'idle' && $chat.phase !== 'done');

    // ── Long-generation notification ─────────────────────────────
    let genStartedAt = $state(0);
    let lastIsActive = $state(false);
    function playDoneChime() {
        try {
            const Ctx = (window.AudioContext || (window as any).webkitAudioContext);
            if (!Ctx) return;
            const ctx = new Ctx();
            const beep = (freq: number, when: number, dur = 0.12) => {
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.type = 'sine';
                osc.frequency.value = freq;
                gain.gain.setValueAtTime(0, ctx.currentTime + when);
                gain.gain.linearRampToValueAtTime(0.08, ctx.currentTime + when + 0.01);
                gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + when + dur);
                osc.connect(gain).connect(ctx.destination);
                osc.start(ctx.currentTime + when);
                osc.stop(ctx.currentTime + when + dur + 0.05);
            };
            beep(880, 0);
            beep(1175, 0.13);
            setTimeout(() => ctx.close().catch(() => {}), 600);
        } catch {}
    }
    function fireDoneNotification() {
        if (!('Notification' in window)) return;
        if (Notification.permission === 'granted') {
            try {
                const n = new Notification('CT-2 finished', { body: 'Your response is ready.', silent: true });
                setTimeout(() => n.close(), 6000);
            } catch {}
        } else if (Notification.permission === 'default') {
            // First time — request silently. Don't notify retroactively.
            Notification.requestPermission().catch(() => {});
        }
    }
    $effect(() => {
        const active = isActive;
        if (active && !lastIsActive) {
            genStartedAt = Date.now();
        } else if (!active && lastIsActive) {
            const elapsed = Date.now() - genStartedAt;
            if (elapsed > 15000 && $preferences.notifyOnDone) {
                playDoneChime();
                if (typeof document !== 'undefined' && !document.hasFocus()) {
                    fireDoneNotification();
                }
            }
        }
        lastIsActive = active;
    });

    function estimateConvTokens(conv: any[]): number {
        return Math.round(conv.reduce((acc, t) => {
            const c = t.content;
            if (typeof c === 'string') return acc + c.length / 3.5;
            if (Array.isArray(c)) return acc + c.reduce((a: number, p: any) => {
                if (p?.type === 'text') return a + (p.text?.length ?? 0) / 3.5;
                if (p?.type === 'image_url') return a + 85;
                return a + 16;
            }, 0);
            return acc + JSON.stringify(c ?? '').length / 3.5;
        }, 0));
    }

    // ── Context accounting ───────────────────────────────────────
    // System prompt overhead: base prompt + tier suffix + few-shot.
    // Conservative estimate — actual size varies by route and model tier.
    const SYSTEM_PROMPT_ESTIMATE = 1200;

    // Compaction uses effectiveCtx, not raw contextSize, to decide when to
    // compact. Align the bar with the same threshold so users see what matters.
    function getEffectiveCtx(raw: number): number {
        const overhead = Math.min(800, Math.round(raw * 0.4));
        return Math.max(512, raw - overhead);
    }

    // Total estimated tokens: conversation history (chars/3.5) +
    // streaming output tokens (exact from backend) + system prompt +
    // RAG injected content per message.
    let usedTokens = $derived(
        estimateConvTokens($chat.conversation) + $chat.tokenCount + ($chat.ragEnabled ? ragCost : 0) + SYSTEM_PROMPT_ESTIMATE
    );
    let effectiveCtx = $derived(contextSize > 0 ? getEffectiveCtx(contextSize) : 0);
    let ctxPct   = $derived(effectiveCtx > 0 ? Math.min(100, Math.round(usedTokens / effectiveCtx * 100)) : 0);
    let ctxLabel = $derived(usedTokens >= 1000 ? `${(usedTokens / 1000).toFixed(1)}K` : `${usedTokens}`);
    let ctxMax   = $derived(contextSize >= 1000 ? `${Math.round(contextSize / 1000)}K` : `${contextSize}`);
    let compactionZone = $derived(ctxPct >= 90);  // matches the 0.90 threshold in sendThink
    let showCtxBar = $derived(contextSize > 0 && $chat.conversation.length > 0);
    let ctxTooltip = $derived(
        `${usedTokens} est. tokens used / ${effectiveCtx} effective\n` +
        `(raw context: ${contextSize}, system: ~${SYSTEM_PROMPT_ESTIMATE}, RAG: ~${$chat.ragEnabled ? ragCost : 0})`
    );
    let latestCompactedTurn = $derived(
        [...$chat.conversation].reverse().find((turn) => !!turn.isCompacted) ?? null
    );
    let latestCompactionSummary = $derived(latestCompactedTurn?.content ?? '');
    let canSend   = $derived(!isActive && !$chat.isCompacting && (text.trim().length > 0 || attachments.length > 0));
    let isDesign  = $derived($chat.modeOverride === 'design');

    // ── Preview panel ────────────────────────────────────────────
    let showPreview = $state(false);
    let previewOverride = $state<string | null>(null);
    let previewWidth = $state(44);
    function _looksLikeHtml(text: string): boolean {
        const t = text.trim().toLowerCase();
        return t.startsWith('<!doctype') || t.startsWith('<html');
    }
    let isHtmlOutput = $derived(
        $chat.route === 'ROUTE_DESIGN'
        || _looksLikeHtml($chat.response)
        || _looksLikeHtml($chat.streamingText)
    );
    let previewCode = $derived(
        (isActive && isHtmlOutput && $chat.streamingText)
            ? stripCodeFences($chat.streamingText)
            : previewOverride ?? $chat.response ?? ''
    );
    let previewVisible = $derived(showPreview && !!previewCode);
    function previewHistoryCode(code: string) { previewOverride = code; showPreview = true; }

    // ── Workspace panel ──────────────────────────────────────────
    let isWorkspace = $derived(!!$chat.workspaceId);
    let wsTab = $state<'files' | 'terminal'>('files');
    let wsPanelWidth = $state(38); // percentage, like PreviewPanel
    let viewingFile = $state<{ path: string; content: string } | null>(null);
    let fileTreeRef = $state<FileTree | null>(null);
    let fileRequestId = $state(0);
    let lastWsId = $state<string | null>(null);

    $effect(() => {
        const wsId = $chat.workspaceId;
        if (wsId !== lastWsId) {
            lastWsId = wsId;
            viewingFile = null;
            wsTab = 'files';
            fileRequestId += 1;
        }
    });

    $effect(() => {
        if (($chat.pendingCommands.length > 0 || !!$chat.pendingApproval) && isWorkspace) wsTab = 'terminal';
    });

    $effect(() => {
        const lastEvent = $chat.events?.[$chat.events.length - 1];
        if (lastEvent?.event === 'file_saved') fileTreeRef?.refresh?.();
    });

    async function onFileSelect(path: string) {
        const wsId = $chat.workspaceId;
        if (!wsId) return;
        const reqId = ++fileRequestId;
        try {
            const data = await fetch(`/api/workspaces/${wsId}/files/${path}`).then(r => r.json());
            if (reqId !== fileRequestId || wsId !== $chat.workspaceId) return;
            if (data.content != null) viewingFile = { path, content: data.content };
        } catch {}
    }

    function startWsResize(e: PointerEvent) {
        e.preventDefault();
        const startX = e.clientX;
        const startW = wsPanelWidth;
        function onMove(mv: PointerEvent) {
            wsPanelWidth = Math.max(22, Math.min(65, startW + (startX - mv.clientX) / window.innerWidth * 100));
        }
        function onUp() {
            window.removeEventListener('pointermove', onMove);
            window.removeEventListener('pointerup', onUp);
        }
        window.addEventListener('pointermove', onMove);
        window.addEventListener('pointerup', onUp);
    }

    const generalSuggestions = [
        { label: 'Design a landing page',  hint: 'a landing page for a focus app called FlowState' },
        { label: 'Write a Python script',  hint: 'a Python script that deduplicates CSV rows by email' },
        { label: 'Explain a concept',      hint: 'how self-attention works, for a non-technical reader' },
        { label: 'Debug code',             hint: 'why my React effect fires twice on mount' },
    ] as const;
    const workspaceSuggestions = [
        { label: 'Explain this codebase',  hint: 'Walk me through what this project does and how the main pieces fit together.' },
        { label: 'Find bugs',              hint: 'Review the files in context and point out likely bugs or risky code paths.' },
        { label: 'Add a feature',          hint: 'I want to add ' },
        { label: 'Write a test',           hint: 'Write a test for the function I just attached.' },
    ] as const;
    let suggestions = $derived(isWorkspace ? workspaceSuggestions : generalSuggestions);

    // ── Auto scroll ───────────────────────────────────────────────
    $effect(() => {
        void $chat.conversation.length;
        void $chat.streamingText;
        tick().then(() => { if (feedEl && userNearBottom) feedEl.scrollTop = feedEl.scrollHeight; });
    });

    // Reset scroll-lock when a new generation begins
    $effect(() => {
        if ($chat.phase === 'routing') userNearBottom = true;
    });

    // ── Auto resize textarea ─────────────────────────────────────
    $effect(() => {
        void text;
        if (taEl) {
            taEl.style.height = 'auto';
            taEl.style.height = Math.min(220, taEl.scrollHeight) + 'px';
        }
    });

    // Auto-open live thinking panel when new thinking arrives; reset to open after generation
    $effect(() => { if (!isActive) liveThinkingOpen = true; });

    // Auto-open/close preview panel based on route and streaming progress
    $effect(() => {
        if (isActive && isHtmlOutput && $chat.streamingText.length > 300 && !showPreview) {
            showPreview = true; previewOverride = null;
        }
        if (isActive && !isHtmlOutput && showPreview) showPreview = false;
        if (!isActive && isHtmlOutput && $chat.response) previewOverride = null;
    });

    $effect(() => {
        const summary = latestCompactionSummary;
        const key = summary.slice(0, 160);
        if (!summary) {
            latestCompactionKey = '';
            latestCompactionOpen = false;
            return;
        }
        if (key !== latestCompactionKey) {
            latestCompactionKey = key;
            latestCompactionOpen = true;
        }
    });

    function send() {
        if (!canSend) return;
        const msg = text.trim();
        const atts = attachments;
        text = '';
        attachments = [];
        sendThink(msg || (atts.some(a => a.type === 'image') ? '(image attached)' : '(file attached)'), [...atts]);
    }

    function handleKey(e: KeyboardEvent) {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    }

    function pickSuggestion(hint: string) {
        text = hint;
        tick().then(() => taEl?.focus());
    }

</script>

<svelte:window onclick={handleOutsideClick} onkeydown={handleGlobalKey} />

<div class="c2-page-frame">
<div class="c2-chat"
    class:c2-chat-no-tr={isWorkspace}
    style:right={isWorkspace ? wsPanelWidth + '%' : previewVisible ? previewWidth + '%' : '0'}
>
    <!-- ── Feed ──────────────────────────────────────────────── -->
    <div class="c2-feed scroll" bind:this={feedEl} onscroll={onFeedScroll}>
        {#if $chat.conversation.length === 0 && !isActive}
            <!-- Welcome ─────────────────────────────────────────── -->
            <div class="c2-welcome">
                <div class="c2-welcome-logo">
                    <span class="c2-wl-text">ct</span>
                    <span class="c2-wl-dot"></span>
                    <span class="c2-wl-2">2</span>
                </div>
                <div class="c2-welcome-tagline">
                    <span class="c2-tag-line"></span>
                    Local · Private · GPU
                    <span class="c2-tag-line"></span>
                </div>
                <h2 class="c2-welcome-h2">What would you like to build today?</h2>
                <div class="c2-sug-wrap">
                    {#each suggestions as s, i}
                        <button
                            class="c2-sug-pill"
                            style="animation-delay: {i * 60}ms"
                            onclick={() => pickSuggestion(s.hint)}
                        >{s.label}</button>
                    {/each}
                </div>
            </div>
        {:else}
            <!-- Conversation ────────────────────────────────────── -->
            <div class="c2-feed-inner">
                {#each $chat.conversation as turn, i}
                    {#if turn.role === 'user'}
                        <!-- User message -->
                        <div class="c2-turn-user"
                            role="group"
                            aria-label="User message"
                            onmouseenter={() => hoveredTurn = i}
                            onmouseleave={() => hoveredTurn = null}
                        >
                            {#if editingTurn === i}
                                <div class="c2-user-edit">
                                    <textarea
                                        bind:this={editTaEl}
                                        bind:value={editText}
                                        class="c2-user-edit-ta"
                                        rows={1}
                                        oninput={autosizeEditTa}
                                        onkeydown={handleEditKey}
                                    ></textarea>
                                    <div class="c2-user-edit-foot">
                                        <button class="c2-edit-btn c2-edit-cancel" onclick={cancelEdit}>Cancel</button>
                                        <button class="c2-edit-btn c2-edit-save" onclick={saveEdit} disabled={!editText.trim()}>Send</button>
                                    </div>
                                </div>
                            {:else}
                                {#if turn.attachments && turn.attachments.length > 0}
                                    <div class="c2-user-atts">
                                        {#each turn.attachments as att}
                                            <div class="c2-att-island c2-att-island-msg">
                                                {#if att.type === 'image'}
                                                    <img src={att.dataUrl} alt={att.name} class="c2-att-thumb" />
                                                {:else}
                                                    <div class="c2-att-icon">
                                                        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                                                            <path d="M4 1h5.5L13 4.5V14a1 1 0 01-1 1H4a1 1 0 01-1-1V2a1 1 0 011-1z" stroke="currentColor" stroke-width="1.5"/>
                                                            <path d="M9 1v4h4" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
                                                        </svg>
                                                    </div>
                                                {/if}
                                                <span class="c2-att-name">{att.name.length > 22 ? att.name.slice(0, 19) + '…' : att.name}</span>
                                            </div>
                                        {/each}
                                    </div>
                                {/if}
                                <div class="c2-user-bubble">{turn.content}</div>
                                <div class="c2-user-foot" class:c2-visible={hoveredTurn === i}>
                                    <button class="c2-msg-btn" onclick={() => startEdit(i, turn.content)} title="Edit message">
                                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
                                            <path d="M16.5 3.5a2.121 2.121 0 113 3L7 19l-4 1 1-4L16.5 3.5z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                                        </svg>
                                        Edit
                                    </button>
                                    <button class="c2-msg-btn" onclick={() => revertToTurn(i)} title="Revert conversation to this point">
                                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
                                            <path d="M3 12a9 9 0 1 0 3-6.7L3 8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                                            <path d="M3 3v5h5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                                        </svg>
                                        Revert
                                    </button>
                                </div>
                            {/if}
                        </div>
                    {:else if turn.isCompacted}
                        <!-- Rendered below as an inline chat event near the latest turn -->
                    {:else}
                        <!-- Assistant turn -->
                        <div class="c2-turn-assistant"
                            role="group"
                            aria-label="Assistant response"
                            onmouseenter={() => hoveredTurn = i}
                            onmouseleave={() => hoveredTurn = null}
                        >
                            <span class="c2-rail"></span>
                            <span class="c2-rail-node">
                                <span class="c2-rail-inner"></span>
                            </span>

                            {#if turn.route}
                                <div class="c2-route-tag">
                                    <span class="c2-route-dot"></span>
                                    Routed → {getRouteLabel(turn.route)}
                                </div>
                            {/if}

                            <!-- Status line -->
                            {#if turn.stopped}
                                <div class="c2-status-line">
                                    <svg width="11" height="11" viewBox="0 0 10 10" fill="var(--c2-fg-3)">
                                        <rect width="10" height="10" rx="1.5"/>
                                    </svg>
                                    <span class="c2-stopped-label">Stopped</span>
                                    {#if turn.content}
                                        <span class="c2-sl-meta">{turn.content.length.toLocaleString()} chars</span>
                                    {:else}
                                        <span class="c2-sl-meta">nothing generated</span>
                                    {/if}
                                </div>
                            {:else}
                                <div class="c2-status-line">
                                    <svg class="c2-sl-check" width="12" height="12" viewBox="0 0 24 24" fill="none">
                                        <path d="M20 6L9 17l-5-5" stroke="var(--c2-ok)" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
                                    </svg>
                                    <span>Done</span>
                                    {#if turn.reflection?.self_score}
                                        <span class="c2-sl-meta">{turn.reflection.self_score}%</span>
                                    {/if}
                                </div>
                            {/if}

                            <!-- ── Thinking block ────────────────────────── -->
                            {#if turn.thinking}
                                {@const thOpen = expandedThinking.has(i)}
                                <div class="c2-think-block">
                                    <button
                                        class="c2-think-header"
                                        onclick={() => {
                                            const s = new Set(expandedThinking);
                                            thOpen ? s.delete(i) : s.add(i);
                                            expandedThinking = s;
                                        }}
                                    >
                                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" class="c2-think-chevron" class:c2-think-open={thOpen}>
                                            <path d="M9 18l6-6-6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                        </svg>
                                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                                            <path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3M12 17h.01" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                                            <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="1.4"/>
                                        </svg>
                                        <span>Thinking</span>
                                        <span class="c2-sl-meta">{turn.thinking.length.toLocaleString()} chars</span>
                                    </button>
                                    {#if thOpen}
                                        <pre class="c2-think-body scroll">{turn.thinking}</pre>
                                    {/if}
                                </div>
                            {/if}

                            <!-- ── Search results (completed) ─────────────── -->
                            {#if turn.activeSearches?.length}
                                {#each turn.activeSearches as search, si}
                                    {@const sKey = i * 1000 + si}
                                    {@const sOpen = expandedSearches.has(sKey)}
                                    <div class="c2-search-block">
                                        <button
                                            class="c2-search-header"
                                            onclick={() => {
                                                const s = new Set(expandedSearches);
                                                sOpen ? s.delete(sKey) : s.add(sKey);
                                                expandedSearches = s;
                                            }}
                                        >
                                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                                                <circle cx="11" cy="11" r="8" stroke="currentColor" stroke-width="1.8"/>
                                                <path d="M21 21l-4.35-4.35" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                                            </svg>
                                            <span>Web search</span>
                                            <span class="c2-sl-meta">"{search.query}"</span>
                                            {#if search.results.length > 0}
                                                <span class="c2-sl-meta">· {search.results.length} results</span>
                                            {/if}
                                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" class="c2-think-chevron" class:c2-think-open={sOpen} style="margin-left:auto">
                                                <path d="M9 18l6-6-6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                            </svg>
                                        </button>
                                        {#if sOpen && search.results.length > 0}
                                            <div class="c2-search-results">
                                                {#each search.results as r}
                                                    <a class="c2-search-result" href={r.url} target="_blank" rel="noopener noreferrer">
                                                        <div class="c2-sr-title">{r.title}</div>
                                                        <div class="c2-sr-snippet">{r.snippet}</div>
                                                        <div class="c2-sr-url">{r.url}</div>
                                                    </a>
                                                {/each}
                                            </div>
                                        {/if}
                                    </div>
                                {/each}
                            {/if}

                            <!-- Content -->
                            {#if turn.route === 'ROUTE_COMPUTER'}
                                <!-- Narrative explanation as markdown bubble -->
                                {#if turn.explanation}
                                    <div class="c2-ai-bubble">
                                        <div class="c2-ai-text">{@html render(turn.explanation)}</div>
                                        <div class="c2-ai-actions" class:c2-visible={hoveredTurn === i}>
                                            <button class="c2-icon-btn" onclick={() => setFeedback(i, 1)}
                                                class:c2-icon-active={turn.feedback === 1} title="Good response">
                                                <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
                                                    <path d="M7 22V11M2 13v7a2 2 0 002 2h13.4a2 2 0 001.98-1.72l1.2-9A2 2 0 0020.6 9H15V5a3 3 0 00-3-3 1 1 0 00-1 1v.5L9 9.07" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                                                </svg>
                                            </button>
                                            <button class="c2-icon-btn" onclick={() => setFeedback(i, -1)}
                                                class:c2-icon-active={turn.feedback === -1} title="Bad response">
                                                <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
                                                    <path d="M17 2v11M22 11V4a2 2 0 00-2-2H6.6a2 2 0 00-1.98 1.72l-1.2 9A2 2 0 003.4 15H9v4a3 3 0 003 3 1 1 0 001-1v-.5L15 14.93" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                                                </svg>
                                            </button>
                                            <button class="c2-icon-btn" onclick={() => regenerate(i)} title="Regenerate">
                                                <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
                                                    <path d="M1 4v6h6M23 20v-6h-6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                                                    <path d="M20.49 9A9 9 0 005.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 013.51 15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                                                </svg>
                                            </button>
                                            <button class="c2-icon-btn" onclick={() => copyText(turn.explanation || '')} title="Copy">
                                                <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
                                                    <rect x="9" y="9" width="13" height="13" rx="2" stroke="currentColor" stroke-width="1.8"/>
                                                    <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                                                </svg>
                                            </button>
                                        </div>
                                    </div>
                                {/if}
                                <!-- File cards — click to open in workspace panel -->
                                {#if turn.files?.length}
                                    <div class="c2-ws-file-list">
                                        {#each turn.files as file}
                                            <button
                                                class="c2-ws-file-card"
                                                onclick={() => { wsTab = 'files'; onFileSelect(file.path); }}
                                                title="View {file.path}"
                                            >
                                                <span class="c2-wsf-ext">{(file.lang || file.path.split('.').pop() || 'file').toUpperCase()}</span>
                                                <span class="c2-wsf-path">{file.path}</span>
                                                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" class="c2-wsf-open">
                                                    <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                                                    <path d="M15 3h6v6M10 14L21 3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                                                </svg>
                                            </button>
                                        {/each}
                                    </div>
                                {/if}
                                <!-- Backward compat: no explanation extracted — show content as markdown -->
                                {#if !turn.explanation && turn.content}
                                    <div class="c2-ai-bubble">
                                        <div class="c2-ai-text">{@html render(stripFileMarkers(turn.content))}</div>
                                        <div class="c2-ai-actions" class:c2-visible={hoveredTurn === i}>
                                            <button class="c2-icon-btn" onclick={() => copyText(turn.content)} title="Copy">
                                                <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
                                                    <rect x="9" y="9" width="13" height="13" rx="2" stroke="currentColor" stroke-width="1.8"/>
                                                    <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                                                </svg>
                                            </button>
                                        </div>
                                    </div>
                                {/if}
                            {:else if turn.isCode && turn.content}
                                {@const outputExt = getTurnOutputExt(turn)}
                                {@const outputName = getTurnOutputFilename(turn)}
                                <!-- Output card (ROUTE_CODE / ROUTE_DESIGN) -->
                                <div class="c2-output-card">
                                    <div class="c2-output-header">
                                        <span class="c2-output-ext">{outputExt}</span>
                                        <span class="c2-output-name">{outputName}</span>
                                        <span class="c2-output-chars">{turn.content.length.toLocaleString()} chars</span>
                                        <div style="flex:1"></div>
                                        <button class="c2-out-btn" onclick={() => copyText(turn.content)}>
                                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                                                <rect x="9" y="9" width="13" height="13" rx="2" stroke="currentColor" stroke-width="1.8"/>
                                                <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                                            </svg>
                                            Copy
                                        </button>
                                        <button class="c2-out-btn" onclick={() => {
                                            const b = new Blob([turn.content], { type: 'text/plain' });
                                            const a = document.createElement('a');
                                            a.href = URL.createObjectURL(b);
                                            a.download = outputName;
                                            a.click();
                                        }}>
                                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                                                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                                            </svg>
                                            Download
                                        </button>
                                        {#if turn.route === 'ROUTE_DESIGN' || _looksLikeHtml(turn.content)}
                                            <button class="c2-out-btn" onclick={() => previewHistoryCode(turn.content)}>
                                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                                                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" stroke="currentColor" stroke-width="1.8"/>
                                                    <circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="1.8"/>
                                                </svg>
                                                Preview
                                            </button>
                                        {/if}
                                    </div>
                                    <pre class="c2-output-pre scroll">{turn.content}</pre>
                                </div>
                            {:else if turn.content}
                                <!-- Chat bubble -->
                                <div class="c2-ai-bubble">
                                    <div class="c2-ai-text">{@html render(turn.content)}</div>
                                    <div class="c2-ai-actions" class:c2-visible={hoveredTurn === i}>
                                        <button class="c2-icon-btn" onclick={() => setFeedback(i, 1)}
                                            class:c2-icon-active={turn.feedback === 1} title="Good response">
                                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
                                                <path d="M7 22V11M2 13v7a2 2 0 002 2h13.4a2 2 0 001.98-1.72l1.2-9A2 2 0 0020.6 9H15V5a3 3 0 00-3-3 1 1 0 00-1 1v.5L9 9.07" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                                            </svg>
                                        </button>
                                        <button class="c2-icon-btn" onclick={() => setFeedback(i, -1)}
                                            class:c2-icon-active={turn.feedback === -1} title="Bad response">
                                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
                                                <path d="M17 2v11M22 11V4a2 2 0 00-2-2H6.6a2 2 0 00-1.98 1.72l-1.2 9A2 2 0 003.4 15H9v4a3 3 0 003 3 1 1 0 001-1v-.5L15 14.93" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                                            </svg>
                                        </button>
                                        <button class="c2-icon-btn" onclick={() => regenerate(i)} title="Regenerate">
                                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
                                                <path d="M1 4v6h6M23 20v-6h-6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                                                <path d="M20.49 9A9 9 0 005.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 013.51 15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                                            </svg>
                                        </button>
                                        <button class="c2-icon-btn" onclick={() => copyText(turn.content)} title="Copy">
                                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
                                                <rect x="9" y="9" width="13" height="13" rx="2" stroke="currentColor" stroke-width="1.8"/>
                                                <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                                            </svg>
                                        </button>
                                    </div>
                                </div>
                            {/if}
                        </div>
                    {/if}
                {/each}

                {#if latestCompactedTurn}
                    <div class="c2-turn-assistant">
                        <span class="c2-rail"></span>
                        <span class="c2-rail-node"><span class="c2-rail-inner"></span></span>
                        <ContextSummaryBlock
                            summary={latestCompactedTurn.content}
                            open={latestCompactionOpen}
                            onToggle={() => latestCompactionOpen = !latestCompactionOpen}
                            variant="ct2"
                        />
                    </div>
                {/if}

                <!-- ── Compacting indicator ──────────────────────── -->
                {#if $chat.isCompacting}
                    <div class="c2-turn-assistant">
                        <span class="c2-rail"></span>
                        <span class="c2-rail-node"><span class="c2-rail-inner"></span></span>
                        <div class="c2-status-line">
                            <span class="c2-pulse-dot"></span>
                            <span>Compacting context…</span>
                            <span class="c2-sl-meta">summarizing conversation history</span>
                        </div>
                    </div>
                {/if}

                <!-- ── Live generation turn ──────────────────────── -->
                {#if isActive}
                    <div class="c2-turn-assistant">
                        <span class="c2-rail"></span>
                        <span class="c2-rail-node">
                            <span class="c2-rail-inner"></span>
                        </span>

                        {#if $chat.route}
                            <div class="c2-route-tag">
                                <span class="c2-route-dot"></span>
                                Routed → {getRouteLabel($chat.route)}
                            </div>
                        {/if}

                        <!-- Active status line — shows Paused when waiting for command approval -->
                        {#if $chat.pendingApproval}
                            <div class="c2-status-line">
                                <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
                                    <rect x="6" y="4" width="4" height="16" rx="1" fill="var(--c2-fg-3)"/>
                                    <rect x="14" y="4" width="4" height="16" rx="1" fill="var(--c2-fg-3)"/>
                                </svg>
                                <span class="c2-paused-label">Paused</span>
                                <span class="c2-sl-meta">waiting for your decision in Terminal</span>
                            </div>
                        {:else}
                            <div class="c2-status-line">
                                <span class="c2-pulse-dot"></span>
                                <span>{getPhaseLabel($chat.phase)}</span>
                                {#if $chat.tokensPerSec > 0}
                                    <span class="c2-sl-meta">{$chat.tokensPerSec} tok/s</span>
                                {/if}
                            </div>
                        {/if}

                        <!-- Search activity -->
                        {#each $chat.activeSearches as search}
                            <div class="c2-search-row">
                                {#if !search.done}
                                    <span class="c2-pulse-dot"></span>
                                {:else}
                                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                                        <circle cx="11" cy="11" r="8" stroke="var(--c2-fg-2)" stroke-width="1.8"/>
                                        <path d="M21 21l-4.35-4.35" stroke="var(--c2-fg-2)" stroke-width="1.8" stroke-linecap="round"/>
                                    </svg>
                                {/if}
                                <span>Web search</span>
                                <span class="c2-sl-meta">"{search.query}"</span>
                                {#if search.results.length > 0}
                                    <span class="c2-sl-meta">· {search.results.length} results</span>
                                {/if}
                            </div>
                        {/each}

                        <!-- Live thinking block -->
                        {#if $chat.streamingThinking}
                            <div class="c2-think-block">
                                <button class="c2-think-header" onclick={() => { liveThinkingOpen = !liveThinkingOpen; }}>
                                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" class="c2-think-chevron" class:c2-think-open={liveThinkingOpen}>
                                        <path d="M9 18l6-6-6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                    </svg>
                                    <span class="c2-pulse-dot"></span>
                                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                                        <path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3M12 17h.01" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                                        <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="1.4"/>
                                    </svg>
                                    <span>Thinking</span>
                                    <span class="c2-sl-meta">{$chat.streamingThinking.length.toLocaleString()} chars</span>
                                </button>
                                {#if liveThinkingOpen}
                                    <pre class="c2-think-body scroll">{$chat.streamingThinking}<span class="c2-cursor" aria-hidden="true"></span></pre>
                                {/if}
                            </div>
                        {/if}

                        <!-- Streaming output card -->
                        {#if $chat.streamingText}
                            <div class="c2-gen-card">
                                <div class="c2-gen-header">
                                    <span class="c2-pulse-dot"></span>
                                    <span class="c2-gen-title">{getPhaseLabel($chat.phase)}</span>
                                    <span class="c2-sl-meta">{$chat.streamingText.length.toLocaleString()} chars</span>
                                    {#if $chat.tokensPerSec > 0}
                                        <span class="c2-sl-meta">· {$chat.tokensPerSec} tok/s</span>
                                    {/if}
                                    <div style="flex:1"></div>
                                    {#if !$chat.pendingApproval}
                                        <button class="c2-stop-btn" onclick={stopGeneration} title="Stop">
                                            <svg width="9" height="9" viewBox="0 0 10 10" fill="currentColor">
                                                <rect width="10" height="10" rx="1.5"/>
                                            </svg>
                                        </button>
                                    {/if}
                                </div>
                                <div class="c2-gen-body">
                                    {$chat.streamingText}<span class="c2-cursor" aria-hidden="true"></span>
                                </div>
                            </div>
                        {:else if !$chat.pendingApproval}
                            <!-- Phase-only (routing/planning) — show stop button -->
                            <div class="c2-phase-stop">
                                <button class="c2-revert-btn" onclick={stopGeneration}>Stop</button>
                            </div>
                        {/if}
                    </div>
                {/if}
            </div>
        {/if}
    </div>

    <!-- ── Composer ───────────────────────────────────────────── -->
    <div class="c2-composer-wrap"
        ondrop={onDrop}
        ondragover={onDragOver}
        ondragleave={onDragLeave}
        role="region"
    >
        <div class="c2-composer-inner">
            {#if attachments.length > 0}
                <div class="c2-att-bar">
                    {#each attachments as att, i}
                        <div class="c2-att-island">
                            {#if att.type === 'image'}
                                <img src={att.dataUrl} alt={att.name} class="c2-att-thumb" />
                            {:else}
                                <div class="c2-att-icon">
                                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                                        <path d="M4 1h5.5L13 4.5V14a1 1 0 01-1 1H4a1 1 0 01-1-1V2a1 1 0 011-1z" stroke="currentColor" stroke-width="1.5"/>
                                        <path d="M9 1v4h4" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
                                    </svg>
                                </div>
                            {/if}
                            <span class="c2-att-name">{att.name.length > 22 ? att.name.slice(0, 19) + '…' : att.name}</span>
                            {#if att.type === 'file' && att.textContent}
                                <span class="c2-att-size">{(att.textContent.length / 1000).toFixed(1)}k</span>
                            {/if}
                            <button class="c2-att-remove" onclick={() => removeAttachment(i)} aria-label="Remove {att.name}">
                                <svg width="9" height="9" viewBox="0 0 10 10" fill="none">
                                    <path d="M2 2l6 6M8 2l-6 6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
                                </svg>
                            </button>
                        </div>
                    {/each}
                </div>
            {/if}

            <div class="c2-composer-box" class:c2-drag-over={dragOver}>
                {#if dragOver}
                    <div class="c2-drop-overlay" aria-hidden="true">
                        <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                        <span>Drop {visionSupported ? 'image or file' : 'file'} to attach</span>
                    </div>
                {/if}
                <input
                    bind:this={fileInput}
                    type="file"
                    accept={attachAccept}
                    multiple
                    onchange={onAttachInput}
                    style="display:none"
                />
                <div class="c2-composer-ta-wrap">
                    <textarea
                        bind:this={taEl}
                        bind:value={text}
                        class="c2-ta"
                        placeholder="Ask CT-2 anything…"
                        rows={1}
                        onkeydown={handleKey}
                        onpaste={onPaste}
                        disabled={$chat.isCompacting}
                    ></textarea>
                </div>

                <div class="c2-composer-toolbar">
                    <div class="c2-mode-pills">
                        {#if !isWorkspace}
                            {#each CHAT_MODE_ITEMS as m}
                                <button
                                    class="c2-mode-pill"
                                    class:c2-mode-active={$chat.modeOverride === m}
                                    onclick={() => setMode(m)}
                                    disabled={isActive}
                                >{CHAT_MODE_LABELS[m]}</button>
                            {/each}
                            <div class="c2-pill-sep"></div>
                        {:else}
                            <div class="c2-ctx-anchor">
                                <button
                                    class="c2-mode-pill c2-ws-ctx-badge"
                                    class:c2-mode-active={$chat.contextFiles.length > 0}
                                    onclick={openWsCtx}
                                    type="button"
                                >
                                    <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                                        <path d="M2 5V3a1 1 0 011-1h4l2 2h4a1 1 0 011 1v7a1 1 0 01-1 1H3a1 1 0 01-1-1V5z" stroke="currentColor" stroke-width="1.5"/>
                                    </svg>
                                    {$chat.contextFiles.length > 0
                                        ? `${$chat.contextFiles.length} file${$chat.contextFiles.length === 1 ? '' : 's'} in context`
                                        : 'Attach files to context'}
                                </button>
                                {#if wsCtxOpen}
                                    <div class="c2-ctx-popover" role="dialog" aria-modal="true" aria-label="Workspace files">
                                        <div class="c2-ctx-popover-head">
                                            <span>Workspace files</span>
                                            {#if $chat.contextFiles.length > 0}
                                                <button class="c2-ctx-clear" onclick={clearContextFiles} type="button">Clear all</button>
                                            {/if}
                                        </div>
                                        {#if wsFileLoading}
                                            <div class="c2-ctx-empty">Loading…</div>
                                        {:else if wsFileList.length === 0}
                                            <div class="c2-ctx-empty">No files in workspace</div>
                                        {:else}
                                            <ul class="c2-ctx-file-list">
                                                {#each wsFileList as path}
                                                    <li>
                                                        <label class="c2-ctx-file-row">
                                                            <input
                                                                type="checkbox"
                                                                checked={$chat.contextFiles.includes(path)}
                                                                onchange={() => toggleContextFile(path)}
                                                            />
                                                            <span class="c2-ctx-file-path">{path}</span>
                                                        </label>
                                                    </li>
                                                {/each}
                                            </ul>
                                        {/if}
                                    </div>
                                {/if}
                            </div>
                            <div class="c2-pill-sep"></div>
                        {/if}

                        <button
                            class="c2-mode-pill"
                            class:c2-mode-active={$preferences.webSearchEnabled}
                            onclick={() => {
                                import('$lib/stores/preferences').then(m => m.toggleWebSearch());
                            }}
                            disabled={isActive}
                        >
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
                                <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.6"/>
                                <ellipse cx="12" cy="12" rx="4" ry="9" stroke="currentColor" stroke-width="1.6"/>
                                <path d="M3 12h18" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
                            </svg>
                            Search
                        </button>

                        <button
                            class="c2-mode-pill"
                            class:c2-mode-active={$chat.ragEnabled}
                            onclick={toggleRag}
                            disabled={isActive}
                            title={$chat.ragEnabled ? 'RAG on — documents injected into context' : 'RAG off — click to enable document context'}
                        >
                            <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                                <path d="M2 3h4l1 2h6a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
                                <path d="M6 9v3M10 9v3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                            </svg>
                            RAG
                        </button>
                    </div>

                    <div style="flex:1"></div>

                    {#if showCtxBar}
                        <div class="c2-ctx-bar" class:c2-ctx-compacting={$chat.isCompacting} title={ctxTooltip}>
                            <div class="c2-ctx-track">
                                <!-- compaction zone marker at 75% -->
                                <span class="c2-ctx-zone" class:c2-ctx-zonepass={compactionZone}></span>
                                <div
                                    class="c2-ctx-fill"
                                    class:c2-ctx-warn={ctxPct >= 50}
                                    class:c2-ctx-crit={ctxPct >= 75}
                                    class:c2-ctx-full={ctxPct >= 95}
                                    style="width: max(5px, {ctxPct}%)"
                                ></div>
                            </div>
                            <span class="c2-ctx-label" class:c2-ctx-labelwarn={compactionZone}>{ctxLabel} / {ctxMax}</span>
                            {#if $chat.isCompacting}
                                <span class="c2-ctx-badge compacting">
                                    Compacting…
                                    <button
                                        type="button"
                                        class="c2-ctx-cancel"
                                        onclick={cancelCompaction}
                                        title="Skip compaction and send the conversation as-is"
                                        aria-label="Skip compaction"
                                    >Skip</button>
                                </span>
                            {:else if compactionZone && !isActive}
                                <span class="c2-ctx-badge near-limit">Near limit</span>
                            {:else if latestCompactionSummary}
                                <span class="c2-ctx-badge compacted">Summary ready</span>
                            {/if}
                        </div>
                    {/if}

                    <button
                        class="c2-attach-btn"
                        onclick={() => fileInput?.click()}
                        disabled={isActive || $chat.isCompacting}
                        aria-label={attachLabel}
                        title={attachLabel}
                        type="button"
                    >
                        <svg width="16" height="16" viewBox="0 0 18 18" fill="none">
                            <path d="M15.5 8.5l-6.4 6.4a3.5 3.5 0 01-5-5l6.4-6.4a2.1 2.1 0 013 3L7.2 12.8a.7.7 0 01-1-1l5.3-5.3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    </button>

                    {#if isActive}
                        <button
                            class="c2-send-btn c2-send-stop"
                            onclick={stopGeneration}
                            aria-label="Stop generation"
                            title="Stop"
                            type="button"
                        >
                            <svg width="11" height="11" viewBox="0 0 10 10" fill="currentColor">
                                <rect width="10" height="10" rx="1.5"/>
                            </svg>
                        </button>
                    {:else}
                        <button
                            class="c2-send-btn"
                            class:c2-send-active={canSend}
                            onclick={send}
                            disabled={!canSend}
                            aria-label="Send"
                            type="button"
                        >
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
                                <path d="M12 19V5M5 12l7-7 7 7" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
                            </svg>
                        </button>
                    {/if}
                </div>
            </div>

            <div class="c2-composer-footer">
                <span class="c2-send-hint">Enter to send · Shift+Enter for newline</span>
                <span class="c2-footer-sep">·</span>
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                Runs locally on your GPU
            </div>
        </div>
    </div>
</div>
{#if isWorkspace}
<aside class="c2-ws-panel" style="width:{wsPanelWidth}%">
    <!-- Resize handle -->
    <button class="c2-ws-handle" onpointerdown={startWsResize} aria-label="Resize workspace panel">
        <svg class="c2-ws-grip" width="4" height="18" viewBox="0 0 4 18" fill="currentColor">
            <circle cx="2" cy="2" r="1.4"/><circle cx="2" cy="7" r="1.4"/>
            <circle cx="2" cy="12" r="1.4"/><circle cx="2" cy="17" r="1.4"/>
        </svg>
    </button>

    <!-- Header -->
    <div class="c2-ws-header">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" class="c2-ws-title-icon">
            <polyline points="4 17 10 11 4 5" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
            <line x1="12" y1="19" x2="20" y2="19" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>
        </svg>
        <span class="c2-ws-title">Computer</span>
        <div style="flex:1"></div>
        <div class="c2-ws-seg">
            <button class="c2-ws-seg-btn" class:c2-ws-seg-active={wsTab === 'files'} onclick={() => wsTab = 'files'}>Files</button>
            <button class="c2-ws-seg-btn" class:c2-ws-seg-active={wsTab === 'terminal'} onclick={() => wsTab = 'terminal'}>Terminal</button>
        </div>
    </div>

    <!-- Files tab: two-column grid -->
    {#if wsTab === 'files'}
        <div class="c2-ws-files-grid">
            <div class="c2-ws-tree-col scroll">
                <FileTree
                    workspaceId={$chat.workspaceId ?? ''}
                    onFileSelect={onFileSelect}
                    activeFile={viewingFile?.path ?? ''}
                    bind:this={fileTreeRef}
                />
            </div>
            <div class="c2-ws-content-col">
                {#if viewingFile}
                    <div class="c2-ws-file-header">
                        <span class="c2-ws-file-path">{viewingFile.path}</span>
                        <button class="c2-ws-close" onclick={() => viewingFile = null} aria-label="Close file" style="margin-left:auto">
                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
                                <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                            </svg>
                        </button>
                    </div>
                    <pre class="c2-ws-file-code scroll">{viewingFile.content}</pre>
                {:else}
                    <div class="c2-ws-no-file">Select a file to view</div>
                {/if}
            </div>
        </div>
    {:else}
        <!-- Terminal tab -->
        <div class="c2-ws-terminal">
            <TerminalPanel
                workspaceId={$chat.workspaceId ?? ''}
                onClose={() => wsTab = 'files'}
                externalOutput={$chat.terminalOutput}
                pendingCommands={$chat.pendingCommands}
                onCommandsConsumed={clearPendingCommands}
                pendingApproval={$chat.pendingApproval}
                onApprovalHandled={clearPendingApproval}
            />
        </div>
    {/if}
</aside>
{/if}

<PreviewPanel
    code={previewCode}
    open={previewVisible}
    width={previewWidth}
    isStreaming={isActive}
    onClose={() => showPreview = false}
    onWidthChange={(w) => previewWidth = w}
/>
</div>
