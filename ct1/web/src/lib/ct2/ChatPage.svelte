<script lang="ts">
    import { tick, onMount } from 'svelte';
    import { chat, sendThink, stopGeneration, setMode, revertToTurn, editTurn, setFeedback, regenerate, setContextSize, clearPendingCommands, clearPendingApproval, toggleRag, cancelCompaction, toggleContextFile, clearContextFiles, pendingInputPrompt, type Attachment } from '$lib/stores/chat';
    import { preferences } from '$lib/stores/preferences';
    import { showToast } from '$lib/stores/toasts';
    import { render } from '$lib/markdown';
    import PreviewPanel from './PreviewPanel.svelte';
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
    let compactionZone = $derived(ctxPct >= 75);  // matches the 0.75 threshold in sendThink
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
                                        title="Cancel and use a quick fallback summary"
                                        aria-label="Cancel compaction"
                                    >Cancel</button>
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

<style>
    /* ── Page shell ────────────────────────────────────────────── */
    .c2-page-frame {
        position: absolute;
        inset: 0;
    }

    .c2-chat {
        position: absolute;
        top: 0; left: 0; bottom: 0; right: 0;
        transition: right 340ms cubic-bezier(.22,1.2,.36,1);
        display: flex;
        flex-direction: column;
        font-family: 'Geist', ui-sans-serif, system-ui, sans-serif;
        color: var(--c2-fg-0);
        overflow: hidden;
    }

    /* ── Feed ──────────────────────────────────────────────────── */
    .c2-feed {
        flex: 1;
        overflow-y: auto;
        scrollbar-width: thin;
        scrollbar-color: var(--c2-border-2) transparent;
    }

    .c2-feed-inner {
        max-width: var(--c2-feed-max, 860px);
        margin: 0 auto;
        padding: 32px 24px 16px;
        display: flex;
        flex-direction: column;
        gap: 28px;
    }

    /* ── Welcome ───────────────────────────────────────────────── */
    .c2-welcome {
        flex: 1;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 0 24px;
        min-height: calc(100vh - 200px);
        animation: c2-spring-up 320ms var(--c2-spring, cubic-bezier(.22,1.2,.36,1)) both;
    }

    .c2-welcome-logo {
        font-size: 84px;
        font-weight: 500;
        letter-spacing: -2.4px;
        color: var(--c2-fg-0);
        display: flex;
        align-items: center;
        gap: 6px;
        margin-bottom: 20px;
        line-height: 1;
    }

    .c2-wl-text { color: var(--c2-fg-0); }
    .c2-wl-2 { color: var(--c2-fg-1); }

    .c2-wl-dot {
        display: inline-block;
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: var(--c2-accent);
        opacity: 0.9;
        margin: 0 2px 10px;
        flex-shrink: 0;
    }

    .c2-welcome-tagline {
        font-family: 'Geist Mono', monospace;
        font-size: 10.5px;
        color: var(--c2-fg-3);
        letter-spacing: 1.2px;
        text-transform: uppercase;
        margin-bottom: 22px;
        display: inline-flex;
        align-items: center;
        gap: 10px;
    }

    .c2-tag-line {
        display: inline-block;
        width: 16px;
        height: 1px;
        background: var(--c2-border-2);
    }

    .c2-welcome-h2 {
        font-size: 25px;
        font-weight: 500;
        color: var(--c2-fg-1);
        margin: 0 0 28px;
        letter-spacing: -0.5px;
        line-height: 1.25;
        text-align: center;
    }

    .c2-sug-wrap {
        display: flex;
        flex-wrap: wrap;
        justify-content: center;
        gap: 8px;
        max-width: 680px;
    }

    .c2-sug-pill {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 9px 14px;
        border-radius: 999px;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-2);
        color: var(--c2-fg-1);
        font-size: 13px;
        cursor: pointer;
        transition: background 160ms, color 160ms, border-color 160ms;
        animation: c2-spring-up 320ms var(--c2-spring, cubic-bezier(.22,1.2,.36,1)) both;
    }
    .c2-sug-pill:hover {
        background: var(--c2-bg-2);
        color: var(--c2-fg-0);
        border-color: var(--c2-border-3);
        transform: translateY(-1px);
        box-shadow: 0 4px 14px oklch(0 0 0 / 0.18);
    }

    /* ── User message ──────────────────────────────────────────── */
    .c2-turn-user {
        display: flex;
        flex-direction: column;
        align-items: flex-end;
        gap: 4px;
        animation: c2-spring-up 320ms var(--c2-spring, cubic-bezier(.22,1.2,.36,1)) both;
    }

    .c2-user-bubble {
        max-width: 72%;
        background: var(--c2-bg-2);
        color: var(--c2-fg-0);
        padding: 10px 14px;
        border-radius: 14px 14px 4px 14px;
        font-size: 14px;
        line-height: 1.55;
        border: 1px solid var(--c2-border-1);
        white-space: pre-wrap;
        word-break: break-word;
    }

    .c2-user-foot {
        height: 22px;
        opacity: 0;
        transition: opacity 120ms;
        display: flex;
        align-items: center;
    }
    .c2-user-foot.c2-visible { opacity: 1; }

    /* ── Assistant turn ────────────────────────────────────────── */
    .c2-turn-assistant {
        position: relative;
        padding-left: 42px;
        display: flex;
        flex-direction: column;
        gap: 10px;
        animation: c2-spring-up 320ms var(--c2-spring, cubic-bezier(.22,1.2,.36,1)) both;
    }

    .c2-rail {
        position: absolute;
        left: 8px; top: 6px; bottom: 6px;
        width: 1.5px;
        border-radius: 999px;
        background: var(--c2-border-1);
    }

    .c2-rail-node {
        position: absolute;
        left: 2px; top: 2px;
        width: 14px; height: 14px;
        border-radius: 50%;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-2);
        display: inline-flex;
        align-items: center;
        justify-content: center;
    }

    .c2-rail-inner {
        width: 4px; height: 4px;
        border-radius: 50%;
        background: var(--c2-accent);
    }

    /* ── Route tag ─────────────────────────────────────────────── */
    .c2-route-tag {
        font-family: 'Geist Mono', monospace;
        align-self: flex-start;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        font-size: 11px;
        color: var(--c2-fg-2);
        letter-spacing: 0.6px;
        text-transform: uppercase;
        padding: 4px 10px;
        border-radius: 999px;
        background: var(--c2-bg-2);
        border: 1px solid var(--c2-border-1);
        animation: c2-slide-right 260ms var(--c2-spring, cubic-bezier(.22,1.2,.36,1)) both;
    }

    .c2-route-dot {
        width: 5px; height: 5px;
        border-radius: 50%;
        background: var(--c2-accent);
    }

    /* ── Status line ───────────────────────────────────────────── */
    .c2-status-line {
        display: inline-flex;
        align-items: center;
        gap: 10px;
        font-size: 12.5px;
        color: var(--c2-fg-2);
        padding: 2px 0;
    }

    .c2-sl-check { flex-shrink: 0; }

    .c2-stopped-label {
        color: var(--c2-fg-3);
        font-size: 12px;
    }

    .c2-paused-label {
        color: var(--c2-fg-2);
        font-size: 12.5px;
    }

    .c2-sl-meta {
        font-family: 'Geist Mono', monospace;
        font-size: 11px;
        color: var(--c2-fg-3);
    }

    /* ── Pulsing dot (live) ────────────────────────────────────── */
    .c2-pulse-dot {
        display: inline-block;
        width: 7px; height: 7px;
        border-radius: 50%;
        background: var(--c2-accent);
        flex-shrink: 0;
        animation: c2-pulse-radar 1.6s cubic-bezier(0.4, 0, 0.6, 1) infinite;
    }

    /* ── Search row ────────────────────────────────────────────── */
    .c2-search-row {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        font-size: 12px;
        color: var(--c2-fg-2);
        padding: 2px 0;
    }

    /* ── Generation card ───────────────────────────────────────── */
    .c2-gen-card {
        align-self: stretch;
        max-width: 820px;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-2);
        border-radius: 10px;
        overflow: hidden;
        position: relative;
    }

    .c2-gen-card::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 2px;
        background: linear-gradient(90deg, var(--c2-accent) 0%, oklch(0.78 0.10 70 / 0.12) 70%, transparent 100%);
        animation: c2-gen-sweep 2.4s ease-in-out infinite;
        transform-origin: left center;
        border-radius: 2px 2px 0 0;
    }

    @keyframes c2-gen-sweep {
        0%   { opacity: 0.6; transform: scaleX(0.15); }
        40%  { opacity: 1;   transform: scaleX(0.72); }
        80%  { opacity: 0.6; transform: scaleX(1);    }
        100% { opacity: 0.6; transform: scaleX(1);    }
    }

    .c2-gen-header {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 12px;
        border-bottom: 1px solid var(--c2-border-1);
    }

    .c2-gen-title {
        font-size: 12.5px;
        font-weight: 500;
        color: var(--c2-fg-0);
    }

    .c2-gen-body {
        padding: 12px 14px;
        font-size: 13.5px;
        line-height: 1.6;
        color: var(--c2-fg-0);
        white-space: pre-wrap;
        word-break: break-word;
        max-height: 400px;
        overflow: hidden;
    }

    /* ── Blinking cursor ───────────────────────────────────────── */
    .c2-cursor {
        display: inline-block;
        width: 2px;
        height: 0.88em;
        margin-left: 2px;
        vertical-align: text-bottom;
        background: var(--c2-accent);
        border-radius: 1px;
        animation: c2-cursor-blink 1s step-end infinite;
        opacity: 0.85;
    }

    /* ── Stop button ───────────────────────────────────────────── */
    .c2-stop-btn {
        width: 24px; height: 24px;
        border-radius: 6px;
        background: var(--c2-bg-2);
        color: var(--c2-err);
        border: 1px solid var(--c2-border-1);
        display: inline-flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        transition: background 120ms;
        flex-shrink: 0;
    }
    .c2-stop-btn:hover { background: var(--c2-bg-3); }

    /* ── Phase-only stop ───────────────────────────────────────── */
    .c2-phase-stop {
        display: flex;
        align-items: center;
    }

    /* ── Output card ───────────────────────────────────────────── */
    .c2-output-card {
        align-self: stretch;
        max-width: 820px;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-1);
        border-radius: 10px;
        overflow: hidden;
    }

    .c2-output-header {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 10px;
        border-bottom: 1px solid var(--c2-border-1);
        background: var(--c2-bg-2);
    }

    .c2-output-ext {
        font-family: 'Geist Mono', monospace;
        font-size: 10px;
        color: var(--c2-fg-3);
        text-transform: uppercase;
        letter-spacing: 0.4px;
        padding: 1px 5px;
        border-radius: 3px;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-1);
    }

    .c2-output-name {
        font-family: 'Geist Mono', monospace;
        font-size: 12.5px;
        color: var(--c2-fg-0);
    }

    .c2-output-chars {
        font-family: 'Geist Mono', monospace;
        font-size: 11px;
        color: var(--c2-fg-3);
    }

    .c2-output-pre {
        margin: 0;
        padding: 12px 14px;
        font-family: 'Geist Mono', monospace;
        font-size: 12.5px;
        line-height: 1.6;
        color: var(--c2-fg-0);
        overflow-x: auto;
        scrollbar-width: thin;
        scrollbar-color: var(--c2-border-2) transparent;
        max-height: 420px;
        white-space: pre;
        background: none;
        border: none;
        border-radius: 0;
    }

    .c2-out-btn {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        font-family: 'Geist Mono', monospace;
        font-size: 11px;
        color: var(--c2-fg-2);
        padding: 3px 8px;
        border-radius: 5px;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-1);
        cursor: pointer;
        transition: background 120ms, color 120ms;
    }
    .c2-out-btn:hover { background: var(--c2-bg-2); color: var(--c2-fg-0); }

    /* ── AI bubble ─────────────────────────────────────────────── */
    .c2-ai-bubble {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 6px;
    }

    .c2-ai-text {
        max-width: 100%;
        color: var(--c2-fg-0);
        font-size: 14px;
        line-height: 1.7;
    }

    /* Markdown content inside ai bubble */
    .c2-ai-text :global(p) { margin: 0 0 8px; }
    .c2-ai-text :global(p:last-child) { margin-bottom: 0; }
    .c2-ai-text :global(h1) { font-size: 20px; font-weight: 600; letter-spacing: -0.3px; margin: 12px 0 6px; }
    .c2-ai-text :global(h2) { font-size: 16px; font-weight: 600; margin: 12px 0 6px; }
    .c2-ai-text :global(h3) { font-size: 13.5px; font-weight: 600; color: var(--c2-fg-1); margin: 10px 0 4px; }
    .c2-ai-text :global(ul) { margin: 6px 0; padding-left: 18px; }
    .c2-ai-text :global(li) { margin-bottom: 3px; }
    .c2-ai-text :global(code) {
        font-family: 'Geist Mono', monospace;
        font-size: 0.84em;
        padding: 2px 7px;
        border-radius: 4px;
        background: var(--c2-bg-2);
        border: 1px solid var(--c2-border-1);
    }
    .c2-ai-text :global(pre) {
        margin: 10px 0;
        border-radius: 8px;
        border: 1px solid var(--c2-border-1);
        background: var(--c2-bg-2);
        overflow: hidden;
    }
    .c2-ai-text :global(pre code) {
        display: block;
        padding: 12px 14px;
        font-size: 12.5px;
        line-height: 1.6;
        background: none;
        border: none;
        border-radius: 0;
        overflow-x: auto;
    }
    .c2-ai-text :global(blockquote) {
        border-left: 3px solid var(--c2-border-2);
        margin: 8px 0;
        padding: 4px 12px;
        color: var(--c2-fg-2);
    }
    .c2-ai-text :global(a) { color: var(--c2-accent); text-decoration: none; }
    .c2-ai-text :global(a:hover) { text-decoration: underline; }
    .c2-ai-text :global(strong) { font-weight: 600; color: var(--c2-fg-0); }
    .c2-ai-text :global(em) { font-style: italic; color: var(--c2-fg-1); }
    .c2-ai-text :global(table) { border-collapse: collapse; margin: 8px 0; font-size: 13px; }
    .c2-ai-text :global(th), .c2-ai-text :global(td) {
        border: 1px solid var(--c2-border-1);
        padding: 6px 10px;
    }
    .c2-ai-text :global(th) { background: var(--c2-bg-2); font-weight: 600; }
    .c2-ai-text :global(hr) { border: none; border-top: 1px solid var(--c2-border-1); margin: 12px 0; }

    /* ── AI bubble hover actions ───────────────────────────────── */
    .c2-ai-actions {
        display: flex;
        align-items: center;
        gap: 4px;
        height: 30px;
        margin-top: 2px;
        opacity: 0;
        transition: opacity 120ms;
    }
    .c2-ai-actions.c2-visible { opacity: 1; }

    .c2-icon-btn {
        width: 28px; height: 28px;
        border-radius: 7px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        color: var(--c2-fg-2);
        background: none;
        border: 1px solid transparent;
        cursor: pointer;
        transition: background 120ms, color 120ms, border-color 120ms;
    }
    .c2-icon-btn:hover {
        background: var(--c2-bg-2);
        color: var(--c2-fg-0);
        border-color: var(--c2-border-1);
    }
    .c2-icon-btn.c2-icon-active {
        color: var(--c2-accent);
        background: oklch(0.78 0.10 70 / 0.10);
    }
    .c2-icon-btn svg {
        flex-shrink: 0;
    }

    /* ── Revert / Stop button ──────────────────────────────────── */
    .c2-revert-btn {
        font-family: 'Geist Mono', monospace;
        display: inline-flex;
        align-items: center;
        gap: 5px;
        font-size: 10.5px;
        color: var(--c2-fg-2);
        padding: 2px 7px;
        border-radius: 5px;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-1);
        cursor: pointer;
        transition: background 120ms, color 120ms;
    }
    .c2-revert-btn:hover { background: var(--c2-bg-2); color: var(--c2-fg-0); }

    /* ── User message action buttons (Edit / Revert) ───────────── */
    .c2-user-foot {
        gap: 4px;
    }
    .c2-msg-btn {
        font-family: 'Geist', ui-sans-serif, system-ui, sans-serif;
        display: inline-flex;
        align-items: center;
        gap: 5px;
        font-size: 11.5px;
        font-weight: 500;
        color: var(--c2-fg-2);
        padding: 3px 9px;
        border-radius: 6px;
        background: transparent;
        border: 1px solid transparent;
        cursor: pointer;
        transition: background 120ms, color 120ms, border-color 120ms;
    }
    .c2-msg-btn:hover {
        background: var(--c2-bg-2);
        color: var(--c2-fg-0);
        border-color: var(--c2-border-1);
    }
    .c2-msg-btn svg {
        flex-shrink: 0;
    }

    /* ── Inline edit ───────────────────────────────────────────── */
    .c2-user-edit {
        align-self: flex-end;
        width: 100%;
        max-width: 72%;
        background: var(--c2-bg-2);
        border: 1px solid var(--c2-border-2);
        border-radius: 14px;
        box-shadow: 0 4px 14px -6px oklch(0 0 0 / 0.18);
        overflow: hidden;
    }
    .c2-user-edit-ta {
        width: 100%;
        resize: none;
        font-family: 'Geist', ui-sans-serif, system-ui, sans-serif;
        font-size: 14px;
        line-height: 1.55;
        color: var(--c2-fg-0);
        background: transparent;
        border: none;
        outline: none;
        padding: 12px 14px 6px;
        min-height: 22px;
        max-height: 320px;
        overflow: auto;
        scrollbar-width: thin;
        scrollbar-color: var(--c2-border-2) transparent;
    }
    .c2-user-edit-foot {
        display: flex;
        justify-content: flex-end;
        gap: 6px;
        padding: 6px 8px 8px;
    }
    .c2-edit-btn {
        font-family: 'Geist', ui-sans-serif, system-ui, sans-serif;
        font-size: 12px;
        font-weight: 500;
        padding: 5px 12px;
        border-radius: 7px;
        border: 1px solid var(--c2-border-1);
        cursor: pointer;
        transition: background 120ms, color 120ms, border-color 120ms, opacity 120ms;
    }
    .c2-edit-cancel {
        color: var(--c2-fg-2);
        background: transparent;
    }
    .c2-edit-cancel:hover {
        color: var(--c2-fg-0);
        background: var(--c2-bg-1);
    }
    .c2-edit-save {
        color: var(--c2-accent-fg, oklch(0.20 0.03 70));
        background: var(--c2-accent);
        border-color: var(--c2-accent);
    }
    .c2-edit-save:hover:not(:disabled) {
        opacity: 0.88;
    }
    .c2-edit-save:disabled {
        opacity: 0.45;
        cursor: not-allowed;
    }

    /* ── Composer ──────────────────────────────────────────────── */
    .c2-composer-wrap {
        flex-shrink: 0;
        position: relative;
        z-index: 10;
    }

    .c2-composer-inner {
        max-width: var(--c2-feed-max, 860px);
        margin: 0 auto;
        padding: 0 24px 16px;
    }

    .c2-composer-box {
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-2);
        border-radius: 14px;
        box-shadow: var(--c2-shadow-card, 0 10px 28px -12px oklch(0 0 0 / 0.55));
        overflow: hidden;
        transition: border-color 140ms, box-shadow 140ms;
    }

    .c2-composer-box:focus-within {
        border-color: var(--c2-border-3);
        box-shadow:
            0 0 0 3px oklch(0.78 0.10 70 / 0.09),
            var(--c2-shadow-card, 0 10px 28px -12px oklch(0 0 0 / 0.55));
    }

    .c2-composer-ta-wrap {
        padding: 14px 16px 8px;
    }

    .c2-ta {
        width: 100%;
        resize: none;
        font-size: 14px;
        line-height: 1.5;
        color: var(--c2-fg-0);
        min-height: 22px;
        max-height: 220px;
        overflow: auto;
        background: transparent;
        border: none;
        outline: none;
        font-family: 'Geist', ui-sans-serif, system-ui, sans-serif;
        scrollbar-width: thin;
        scrollbar-color: var(--c2-border-2) transparent;
    }
    .c2-ta::placeholder { color: var(--c2-fg-3); }
    .c2-ta:disabled { opacity: 0.6; cursor: not-allowed; }

    .c2-composer-toolbar {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 6px 8px 6px 10px;
        border-top: 1px solid var(--c2-border-1);
    }

    .c2-mode-pills {
        display: flex;
        gap: 3px;
        align-items: center;
    }

    .c2-mode-pill {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        height: 24px;
        padding: 0 9px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 500;
        color: var(--c2-fg-2);
        background: none;
        border: 1px solid transparent;
        cursor: pointer;
        transition: background 120ms, color 120ms, border-color 120ms;
    }
    .c2-mode-pill:hover:not(:disabled) {
        background: var(--c2-bg-2);
        color: var(--c2-fg-1);
    }
    .c2-mode-pill.c2-mode-active {
        background: var(--c2-bg-2);
        color: var(--c2-fg-0);
        border-color: var(--c2-border-2);
    }
    .c2-mode-pill:disabled { opacity: 0.5; cursor: not-allowed; }

    .c2-pill-sep {
        width: 1px;
        height: 16px;
        background: var(--c2-border-1);
        margin: 0 4px;
    }

    .c2-send-btn {
        width: 30px; height: 30px;
        border-radius: 8px;
        background: var(--c2-bg-2);
        color: var(--c2-fg-3);
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border: 1px solid var(--c2-border-1);
        cursor: not-allowed;
        transition: background 140ms, color 140ms, border-color 140ms;
        flex-shrink: 0;
    }
    .c2-send-btn.c2-send-active {
        background: var(--c2-accent);
        color: var(--c2-accent-fg, oklch(0.20 0.03 70));
        border-color: var(--c2-accent);
        cursor: pointer;
    }
    .c2-send-btn.c2-send-active:hover {
        opacity: 0.88;
        transform: scale(1.06);
    }
    .c2-send-btn.c2-send-active:active {
        transform: scale(0.94);
        opacity: 1;
    }

    .c2-send-btn.c2-send-stop {
        background: oklch(0.68 0.20 25 / 0.12);
        color: oklch(0.68 0.20 25);
        border-color: oklch(0.68 0.20 25 / 0.35);
        cursor: pointer;
    }
    .c2-send-btn.c2-send-stop:hover {
        background: oklch(0.68 0.20 25 / 0.22);
        transform: scale(1.06);
    }
    .c2-send-btn.c2-send-stop:active {
        transform: scale(0.94);
    }

    /* ── Attach button ──────────────────────────────────────── */
    .c2-attach-btn {
        width: 30px; height: 30px;
        border-radius: 8px;
        background: transparent;
        color: var(--c2-fg-3);
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border: 1px solid transparent;
        cursor: pointer;
        transition: background 140ms, color 140ms, border-color 140ms;
        flex-shrink: 0;
    }
    .c2-attach-btn:hover:not(:disabled) {
        background: var(--c2-bg-2);
        color: var(--c2-fg-1);
        border-color: var(--c2-border-1);
    }
    .c2-attach-btn:disabled {
        opacity: 0.4;
        cursor: not-allowed;
    }

    /* ── Attachment preview strip ──────────────────────────── */
    .c2-att-bar {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin-bottom: 8px;
    }
    .c2-att-island {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-2);
        border-radius: 10px;
        padding: 4px 8px 4px 4px;
        font-size: 12px;
        color: var(--c2-fg-1);
        animation: c2-att-in 220ms cubic-bezier(0.34, 1.56, 0.64, 1) both;
    }
    @keyframes c2-att-in {
        from { opacity: 0; transform: scale(0.85) translateY(4px); }
        to   { opacity: 1; transform: scale(1) translateY(0); }
    }
    .c2-att-thumb {
        width: 30px; height: 30px;
        border-radius: 7px;
        object-fit: cover;
        flex-shrink: 0;
    }
    .c2-att-icon {
        width: 30px; height: 30px;
        border-radius: 7px;
        background: var(--c2-bg-2);
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--c2-fg-2);
        flex-shrink: 0;
    }
    .c2-att-name {
        max-width: 160px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        font-weight: 500;
    }
    .c2-att-size {
        font-size: 10.5px;
        color: var(--c2-fg-3);
    }
    .c2-att-remove {
        width: 18px; height: 18px;
        border: none;
        background: var(--c2-bg-2);
        color: var(--c2-fg-3);
        border-radius: 50%;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        transition: background 120ms, color 120ms;
    }
    .c2-att-remove:hover {
        background: var(--c2-bg-3);
        color: var(--c2-fg-0);
    }

    /* On a past user message — slightly lighter, no remove */
    .c2-user-atts {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin-bottom: 6px;
        justify-content: flex-end;
    }
    .c2-att-island-msg {
        background: var(--c2-bg-2);
    }

    /* Drag-over state */
    .c2-composer-box.c2-drag-over {
        border-color: var(--c2-accent);
        box-shadow:
            0 0 0 3px oklch(0.78 0.10 70 / 0.18),
            var(--c2-shadow-card, 0 10px 28px -12px oklch(0 0 0 / 0.55));
        position: relative;
    }
    .c2-drop-overlay {
        position: absolute;
        inset: 0;
        background: oklch(0.78 0.10 70 / 0.10);
        backdrop-filter: blur(2px);
        border-radius: 14px;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 6px;
        font-size: 13px;
        font-weight: 600;
        color: var(--c2-accent);
        letter-spacing: 0.01em;
        pointer-events: none;
        z-index: 4;
        animation: c2-fade-in 140ms ease both;
    }
    @keyframes c2-fade-in { from { opacity: 0; } to { opacity: 1; } }

    /* Send hint */
    .c2-send-hint {
        font-family: 'Geist', ui-sans-serif, sans-serif;
        font-size: 10.5px;
        color: var(--c2-fg-3);
        letter-spacing: 0.02em;
    }
    .c2-footer-sep { opacity: 0.4; }

    /* ── Narrow-width composer ──────────────────────────────── */
    @media (max-width: 720px) {
        .c2-composer-toolbar {
            flex-wrap: wrap;
        }
        .c2-mode-pills {
            flex-wrap: wrap;
            row-gap: 4px;
        }
        .c2-ctx-bar {
            order: 99;
            width: 100%;
            margin-top: 4px;
        }
    }
    @media (max-width: 520px) {
        .c2-ctx-bar { display: none; }
        .c2-pill-sep { display: none; }
        .c2-composer-footer {
            flex-wrap: wrap;
            justify-content: center;
            text-align: center;
        }
        .c2-att-name { max-width: 100px; }
    }

    /* ── Cancel-compaction chip ─────────────────────────────── */
    .c2-ctx-cancel {
        appearance: none;
        margin-left: 6px;
        padding: 0 8px;
        height: 16px;
        line-height: 16px;
        border-radius: 999px;
        font-size: 9.5px;
        font-weight: 600;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: inherit;
        background: transparent;
        border: 1px solid currentColor;
        cursor: pointer;
        opacity: 0.85;
        transition: opacity 120ms, background 120ms;
    }
    .c2-ctx-cancel:hover {
        opacity: 1;
        background: oklch(1 0 0 / 0.08);
    }

    /* ── Workspace context popover ──────────────────────────── */
    .c2-ctx-anchor {
        position: relative;
    }
    .c2-ws-ctx-badge {
        max-width: 220px;
    }
    .c2-ctx-popover {
        position: absolute;
        bottom: calc(100% + 8px);
        left: 0;
        min-width: 260px;
        max-width: 360px;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-2);
        border-radius: 12px;
        box-shadow: 0 10px 32px -8px oklch(0 0 0 / 0.45);
        z-index: 200;
        overflow: hidden;
    }
    .c2-ctx-popover-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 9px 12px;
        font-size: 10.5px;
        font-weight: 600;
        color: var(--c2-fg-2);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        border-bottom: 1px solid var(--c2-border-1);
    }
    .c2-ctx-clear {
        background: none;
        border: none;
        color: var(--c2-accent);
        font-size: 10.5px;
        cursor: pointer;
        padding: 0;
    }
    .c2-ctx-clear:hover { text-decoration: underline; }
    .c2-ctx-empty {
        padding: 14px;
        font-size: 12px;
        color: var(--c2-fg-2);
        text-align: center;
    }
    .c2-ctx-file-list {
        list-style: none;
        margin: 0;
        padding: 4px 0;
        max-height: 240px;
        overflow-y: auto;
    }
    .c2-ctx-file-row {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 12px;
        cursor: pointer;
        font-size: 12px;
        color: var(--c2-fg-1);
    }
    .c2-ctx-file-row:hover { background: var(--c2-bg-2); }
    .c2-ctx-file-path {
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        font-family: 'Geist Mono', monospace;
        font-size: 11px;
    }

    .c2-composer-footer {
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: 5px;
        padding: 6px 10px 0;
        font-family: 'Geist Mono', monospace;
        font-size: 10.5px;
        color: var(--c2-fg-3);
    }

    /* ── Context bar ──────────────────────────────────────────── */
    .c2-ctx-bar {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        flex-shrink: 0;
        transition: opacity 200ms;
    }
    .c2-ctx-bar.c2-ctx-compacting {
        opacity: 0.6;
    }
    .c2-ctx-track {
        position: relative;
        width: 72px;
        height: 4px;
        border-radius: 999px;
        background: var(--c2-bg-3);
        overflow: hidden;
    }
    /* Compaction threshold marker at 75% */
    .c2-ctx-zone {
        position: absolute;
        left: 75%; top: 0; bottom: 0;
        width: 1px;
        background: var(--c2-border-2);
        z-index: 1;
        transition: background 300ms;
    }
    .c2-ctx-zone.c2-ctx-zonepass {
        background: var(--c2-warn);
    }
    .c2-ctx-fill {
        position: relative;
        height: 100%;
        border-radius: 999px;
        background: var(--c2-fg-3);
        transition: width 400ms ease, background 400ms ease;
        min-width: 5px;
        z-index: 0;
    }
    .c2-ctx-fill.c2-ctx-warn { background: var(--c2-warn); }
    .c2-ctx-fill.c2-ctx-crit { background: var(--c2-err); }
    .c2-ctx-fill.c2-ctx-full { background: var(--c2-err); box-shadow: 0 0 6px var(--c2-err); }
    .c2-ctx-label {
        font-family: 'Geist Mono', monospace;
        font-size: 10.5px;
        color: var(--c2-fg-3);
        white-space: nowrap;
        transition: color 300ms;
    }
    .c2-ctx-label.c2-ctx-labelwarn { color: var(--c2-warn); }
    .c2-ctx-badge {
        display: inline-flex;
        align-items: center;
        height: 20px;
        padding: 0 8px;
        border-radius: 999px;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.03em;
        white-space: nowrap;
        border: 1px solid transparent;
    }
    .c2-ctx-badge.compacting {
        color: var(--c2-warn);
        background: color-mix(in srgb, var(--c2-warn) 12%, transparent);
        border-color: color-mix(in srgb, var(--c2-warn) 24%, transparent);
    }
    .c2-ctx-badge.near-limit {
        color: var(--c2-warn);
        background: color-mix(in srgb, var(--c2-warn) 8%, transparent);
        border-color: color-mix(in srgb, var(--c2-warn) 18%, transparent);
    }
    .c2-ctx-badge.compacted {
        color: var(--c2-fg-2);
        background: var(--c2-bg-1);
        border-color: var(--c2-border-1);
    }

    /* ── Thinking block ───────────────────────────────────────── */
    .c2-think-block {
        align-self: stretch;
        max-width: 820px;
        background: color-mix(in oklch, var(--c2-bg-1) 88%, oklch(0.78 0.10 70) 12%);
        border: 1px solid color-mix(in oklch, var(--c2-border-1) 60%, oklch(0.78 0.10 70) 40%);
        border-radius: 8px;
        overflow: hidden;
    }

    .c2-think-header {
        width: 100%;
        display: flex;
        align-items: center;
        gap: 7px;
        padding: 7px 10px;
        background: none;
        border: none;
        cursor: pointer;
        color: var(--c2-fg-2);
        font-size: 12px;
        font-family: 'Geist', ui-sans-serif, system-ui, sans-serif;
        text-align: left;
        transition: background 120ms;
    }
    .c2-think-header:hover { background: var(--c2-bg-2); }

    .c2-think-chevron {
        flex-shrink: 0;
        color: var(--c2-fg-3);
        transition: transform 160ms ease;
    }
    .c2-think-chevron.c2-think-open { transform: rotate(90deg); }

    .c2-think-body {
        margin: 0;
        padding: 8px 14px 12px;
        font-family: 'Geist Mono', monospace;
        font-size: 12px;
        line-height: 1.6;
        color: var(--c2-fg-2);
        white-space: pre-wrap;
        word-break: break-word;
        max-height: 220px;
        overflow-y: auto;
        border-top: 1px solid var(--c2-border-1);
        background: none;
        border-radius: 0;
        border-left: none;
        border-right: none;
        border-bottom: none;
        scrollbar-width: thin;
        scrollbar-color: var(--c2-border-2) transparent;
    }

    /* ── Search block (completed turns) ───────────────────────── */
    .c2-search-block {
        align-self: stretch;
        max-width: 820px;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-1);
        border-radius: 8px;
        overflow: hidden;
    }

    .c2-search-header {
        width: 100%;
        display: flex;
        align-items: center;
        gap: 7px;
        padding: 7px 10px;
        background: none;
        border: none;
        cursor: pointer;
        color: var(--c2-fg-2);
        font-size: 12px;
        font-family: 'Geist', ui-sans-serif, system-ui, sans-serif;
        text-align: left;
        transition: background 120ms;
    }
    .c2-search-header:hover { background: var(--c2-bg-2); }

    .c2-search-results {
        border-top: 1px solid var(--c2-border-1);
        display: flex;
        flex-direction: column;
    }

    .c2-search-result {
        display: flex;
        flex-direction: column;
        gap: 2px;
        padding: 8px 12px;
        border-bottom: 1px solid var(--c2-border-1);
        text-decoration: none;
        transition: background 120ms;
    }
    .c2-search-result:last-child { border-bottom: none; }
    .c2-search-result:hover { background: var(--c2-bg-2); }

    .c2-sr-title {
        font-size: 12.5px;
        font-weight: 500;
        color: var(--c2-fg-0);
        line-height: 1.4;
    }

    .c2-sr-snippet {
        font-size: 12px;
        color: var(--c2-fg-2);
        line-height: 1.5;
    }

    .c2-sr-url {
        font-family: 'Geist Mono', monospace;
        font-size: 10.5px;
        color: var(--c2-fg-3);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    /* ── Utility ───────────────────────────────────────────────── */
    .c2-visible { opacity: 1 !important; }

    /* ── No-transition override (workspace resize) ─────────────── */
    .c2-chat-no-tr { transition: none !important; }

    /* ── Workspace panel ───────────────────────────────────────── */
    .c2-ws-panel {
        position: absolute;
        top: 0; right: 0; bottom: 0;
        background: var(--c2-bg-1);
        border-left: 1px solid var(--c2-border-2);
        box-shadow: -8px 0 32px oklch(0 0 0 / 0.30);
        display: flex;
        flex-direction: column;
        overflow: hidden;
        z-index: 20;
    }

    .c2-ws-handle {
        position: absolute;
        left: -4px; top: 0; bottom: 0;
        width: 8px;
        cursor: col-resize;
        background: transparent;
        border: none;
        padding: 0;
        z-index: 2;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .c2-ws-grip {
        color: var(--c2-fg-3);
        opacity: 0;
        transition: opacity 150ms;
        pointer-events: none;
    }
    .c2-ws-handle:hover .c2-ws-grip { opacity: 1; }

    /* Header bar */
    .c2-ws-header {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 10px 14px;
        border-bottom: 1px solid var(--c2-border-1);
        flex-shrink: 0;
        background: var(--c2-bg-1);
    }
    .c2-ws-title-icon { color: oklch(0.72 0.14 55); flex-shrink: 0; }
    .c2-ws-title { font-size: 13px; font-weight: 500; color: var(--c2-fg-0); }

    /* Segment control */
    .c2-ws-seg {
        display: inline-flex;
        padding: 2px;
        border-radius: 8px;
        background: var(--c2-bg-2);
        border: 1px solid var(--c2-border-1);
        gap: 1px;
    }
    .c2-ws-seg-btn {
        height: 24px;
        padding: 0 10px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 500;
        font-family: inherit;
        color: var(--c2-fg-2);
        background: transparent;
        border: 1px solid transparent;
        cursor: pointer;
        transition: all 120ms;
    }
    .c2-ws-seg-btn:hover:not(.c2-ws-seg-active) { color: var(--c2-fg-0); }
    .c2-ws-seg-active {
        background: var(--c2-bg-0);
        color: var(--c2-fg-0);
        border-color: var(--c2-border-2);
        box-shadow: 0 1px 0 var(--c2-border-2) inset;
    }

    .c2-ws-close {
        width: 28px;
        height: 28px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 7px;
        background: none;
        border: none;
        color: var(--c2-fg-2);
        cursor: pointer;
        flex-shrink: 0;
        transition: color 120ms, background 120ms;
    }
    .c2-ws-close:hover { color: var(--c2-fg-0); background: var(--c2-bg-2); }

    /* Files tab: two-column grid */
    .c2-ws-files-grid {
        flex: 1;
        display: grid;
        grid-template-columns: 220px 1fr;
        min-height: 0;
        overflow: hidden;
    }

    .c2-ws-tree-col {
        border-right: 1px solid var(--c2-border-1);
        padding: 8px 4px;
        overflow-y: auto;
        scrollbar-width: thin;
        scrollbar-color: var(--c2-border-2) transparent;
    }

    .c2-ws-content-col {
        display: flex;
        flex-direction: column;
        overflow: hidden;
        min-width: 0;
        background: var(--c2-bg-0);
    }

    .c2-ws-file-header {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 7px 14px;
        border-bottom: 1px solid var(--c2-border-1);
        flex-shrink: 0;
        background: var(--c2-bg-1);
    }
    .c2-ws-file-path {
        flex: 1;
        font-family: 'Geist Mono', monospace;
        font-size: 12px;
        color: var(--c2-fg-1);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .c2-ws-file-code {
        flex: 1;
        margin: 0;
        padding: 14px 16px;
        font-family: 'Geist Mono', monospace;
        font-size: 12px;
        line-height: 1.65;
        color: var(--c2-fg-1);
        overflow: auto;
        white-space: pre;
        background: var(--c2-bg-0);
        scrollbar-width: thin;
        scrollbar-color: var(--c2-border-2) transparent;
    }

    .c2-ws-no-file {
        flex: 1;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 12.5px;
        color: var(--c2-fg-3);
    }

    /* ── Computer-mode file cards ─────────────────────────────── */
    .c2-ws-file-list {
        display: flex;
        flex-direction: column;
        gap: 4px;
        margin-top: 8px;
        margin-bottom: 4px;
    }
    .c2-ws-file-card {
        display: flex;
        align-items: center;
        gap: 10px;
        height: 34px;
        padding: 0 12px;
        border-radius: 8px;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-1);
        color: var(--c2-fg-1);
        font-family: inherit;
        font-size: 12.5px;
        cursor: pointer;
        transition: background 120ms, border-color 120ms;
        text-align: left;
        width: 100%;
    }
    .c2-ws-file-card:hover {
        background: var(--c2-bg-2);
        border-color: var(--c2-border-2);
        color: var(--c2-fg-0);
    }
    .c2-wsf-ext {
        font-family: 'Geist Mono', monospace;
        font-size: 10px;
        font-weight: 600;
        color: var(--c2-fg-3);
        letter-spacing: 0.4px;
        background: var(--c2-bg-3);
        border: 1px solid var(--c2-border-1);
        padding: 2px 6px;
        border-radius: 4px;
        flex-shrink: 0;
    }
    .c2-wsf-path {
        flex: 1;
        font-family: 'Geist Mono', monospace;
        font-size: 12px;
        color: var(--c2-fg-0);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        min-width: 0;
    }
    .c2-wsf-open {
        color: var(--c2-fg-3);
        flex-shrink: 0;
        opacity: 0;
        transition: opacity 120ms;
    }
    .c2-ws-file-card:hover .c2-wsf-open { opacity: 1; }

    /* Terminal tab */
    .c2-ws-terminal {
        flex: 1;
        overflow: hidden;
        display: flex;
        flex-direction: column;
        min-height: 0;
    }
</style>
