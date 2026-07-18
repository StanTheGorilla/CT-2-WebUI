<script lang="ts">
    import { tick, onMount } from 'svelte';
    import {
        chat, sendThink, stopGeneration, setMode, setContextSize,
        toggleRag, cancelCompaction, toggleContextFile, clearContextFiles,
        pendingInputPrompt, type Attachment,
    } from '$lib/stores/chat';
    import { preferences } from '$lib/stores/preferences';
    import { showToast } from '$lib/stores/toasts';
    import { CHAT_MODE_ITEMS, CHAT_MODE_LABELS } from '$lib/chatUi';

    let isActive    = $derived($chat.phase !== 'idle' && $chat.phase !== 'done');
    let isWorkspace = $derived(!!$chat.workspaceId);

    // ── Composer state ───────────────────────────────────────────
    let text = $state('');
    let contextSize = $state(0);
    let ragCost = $state(0);
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
    let taEl   = $state<HTMLTextAreaElement | null>(null);

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
        if (images.length > 0) {
            e.preventDefault();
            // readFiles shows the "switch to a vision model" toast when the
            // active model can't see images — never swallow a paste silently.
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

    // ── Auto resize textarea ─────────────────────────────────────
    $effect(() => {
        void text;
        if (taEl) {
            taEl.style.height = 'auto';
            taEl.style.height = Math.min(220, taEl.scrollHeight) + 'px';
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

</script>

<svelte:window onclick={handleOutsideClick} onkeydown={handleGlobalKey} />

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
