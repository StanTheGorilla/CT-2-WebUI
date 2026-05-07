<script lang="ts">
    import { onMount } from 'svelte';
    import { chat, sendThink, setMode, stopGeneration, toggleContextFile, clearContextFiles, pendingInputPrompt, setContextSize, toggleRag, cancelCompaction, type Attachment, type ModeOverride } from '$lib/stores/chat';
    import { preferences, toggleWebSearch } from '$lib/stores/preferences';
    import { isUpdating } from '$lib/stores/serverUpdate';
    import { CHAT_MODE_LABELS } from '$lib/chatUi';

    let input = $state('');
    let textarea: HTMLTextAreaElement;
    let fileInput: HTMLInputElement;
    let attachments = $state<Attachment[]>([]);
    let dragOver = $state(false);
    let popoverOpen = $state(false);
    let fileList = $state<string[]>([]);
    let fileListLoading = $state(false);
    let lastWorkspaceId = $state<string | null>(null);
    let fileListRequest = 0;
    let didInitialFocus = $state(false);
    let wasDisabled = $state(true);
    let visionSupported = $state(false);
    let contextSize = $state(0);
    let ragCost = $state(0);
    const TEXT_FILE_ACCEPT = '.txt,.html,.htm,.css,.js,.ts,.py,.json,.md,.csv,.xml,.yaml,.yml,.svg,.sh,.bat,.sql,.rb,.go,.rs,.java,.c,.cpp,.h,.hpp,.toml,.ini,.cfg';

    const disabled = $derived(($chat.phase !== 'idle' && $chat.phase !== 'done') || $isUpdating);
    const currentMode = $derived($chat.modeOverride);
    const isWorkspaceSession = $derived(!!$chat.workspaceId);
    const hasWorkspaceContext = $derived(!!$chat.workspaceId);
    const contextCount = $derived($chat.contextFiles.length);
    const attachAccept = $derived(`${visionSupported ? 'image/*,' : ''}${TEXT_FILE_ACCEPT}`);
    const attachLabel = $derived(visionSupported ? 'Attach file or image' : 'Attach file (current model has no vision)');

    const modes: { key: ModeOverride; label: string }[] = [
        { key: 'chat', label: CHAT_MODE_LABELS.chat },
        { key: 'design', label: CHAT_MODE_LABELS.design },
        { key: 'code', label: CHAT_MODE_LABELS.code },
        { key: 'auto', label: CHAT_MODE_LABELS.auto },
    ];

    function submit() {
        const text = input.trim();
        if ((!text && attachments.length === 0) || disabled) return;
        sendThink(text || (attachments.some(a => a.type === 'image') ? '(image attached)' : '(file attached)'), [...attachments]);
        input = '';
        attachments = [];
        if (textarea) textarea.style.height = 'auto';
    }

    async function openPopover() {
        const workspaceId = $chat.workspaceId;
        if (!workspaceId) return;
        popoverOpen = !popoverOpen;
        if (!popoverOpen) return;

        const requestId = ++fileListRequest;
        fileList = [];
        fileListLoading = true;
        try {
            const res = await fetch(`/api/workspaces/${workspaceId}/files`);
            const data = await res.json();
            if (requestId !== fileListRequest || workspaceId !== $chat.workspaceId || !popoverOpen) {
                return;
            }
            fileList = (data as Array<{ path: string; is_dir: boolean }>)
                .filter(f => !f.is_dir)
                .map(f => f.path);
        } catch {
            if (requestId === fileListRequest) {
                fileList = [];
            }
        } finally {
            if (requestId === fileListRequest) {
                fileListLoading = false;
            }
        }
    }

    function handleOutsideClick(e: MouseEvent) {
        const target = e.target as HTMLElement;
        if (!target.closest('.ctx-popover') && !target.closest('.workspace-ctx-badge')) {
            popoverOpen = false;
        }
    }

    function handleKeydown(e: KeyboardEvent) {
        if (e.key === 'Escape' && popoverOpen) popoverOpen = false;
    }

    function onKeydown(e: KeyboardEvent) {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            submit();
        }
    }

    function autoGrow() {
        if (!textarea) return;
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
    }

    const TEXT_EXTENSIONS = new Set([
        'txt', 'html', 'htm', 'css', 'js', 'ts', 'py', 'json', 'md',
        'csv', 'xml', 'yaml', 'yml', 'svg', 'sh', 'bat', 'sql', 'rb',
        'go', 'rs', 'java', 'c', 'cpp', 'h', 'hpp', 'toml', 'ini', 'cfg',
    ]);

    async function loadModelCapabilities() {
        try {
            const [modelRes, cfgRes, ragRes] = await Promise.all([
                fetch('/api/model'),
                fetch('/api/config'),
                fetch('/api/rag/status'),
            ]);
            let modelData: any = null;
            let cfgData: any = null;
            if (modelRes.ok) {
                modelData = await modelRes.json();
                visionSupported = modelData.vision_supported ?? false;
            }
            if (cfgRes.ok) {
                cfgData = await cfgRes.json();
            }
            if (ragRes.ok) {
                const ragData = await ragRes.json();
                ragCost = ragData.enabled ? (ragData.context_cost ?? 0) : 0;
            }
            contextSize = modelData?.context_size ?? cfgData?.context_size ?? 0;
            setContextSize(contextSize);
        } catch {
            visionSupported = false;
            contextSize = 0;
            setContextSize(0);
        }
    }

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

    // Estimated token usage: conversation history + current streaming + RAG overhead
    const usedTokens = $derived(estimateConvTokens($chat.conversation) + $chat.tokenCount + ($chat.ragEnabled ? ragCost : 0));
    const ctxPct = $derived(contextSize > 0 ? Math.min(100, Math.round(usedTokens / contextSize * 100)) : 0);
    const ctxLabel = $derived(
        usedTokens >= 1000
            ? `${(usedTokens / 1000).toFixed(1)}K`
            : `${usedTokens}`
    );
    const ctxMax = $derived(
        contextSize >= 1000
            ? `${Math.round(contextSize / 1000)}K`
            : `${contextSize}`
    );
    const showCtxBar = $derived(contextSize > 0 && $chat.conversation.length > 0);
    const hasCompactedHistory = $derived($chat.conversation.some((turn) => !!turn.isCompacted));

    // 1-second tick used to compute elapsed compaction time. Runs only while
    // a compaction is in flight to avoid waking the page needlessly.
    let nowMs = $state(Date.now());
    $effect(() => {
        if (!$chat.isCompacting || !$chat.compactStartedAt) return;
        const id = setInterval(() => { nowMs = Date.now(); }, 1000);
        nowMs = Date.now();
        return () => clearInterval(id);
    });
    const compactElapsedSec = $derived(
        $chat.compactStartedAt > 0
            ? Math.max(0, Math.floor((nowMs - $chat.compactStartedAt) / 1000))
            : 0
    );

    function getExtension(name: string): string {
        const i = name.lastIndexOf('.');
        return i >= 0 ? name.slice(i + 1).toLowerCase() : '';
    }

    const IMAGE_MAX_PX = 1536;

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
        if (remainingSlots === 0) return;

        let acceptedCount = 0;
        for (const file of Array.from(files)) {
            if (acceptedCount >= remainingSlots) break;
            const ext = getExtension(file.name);

            if (file.type.startsWith('image/')) {
                if (!visionSupported) continue;
                const reader = new FileReader();
                const fileName = file.name || 'image.png';
                reader.onload = () => _resizeAndAttach(reader.result as string, fileName);
                reader.readAsDataURL(file);
                acceptedCount += 1;
            } else if (TEXT_EXTENSIONS.has(ext) || file.type.startsWith('text/')) {
                const reader = new FileReader();
                reader.onload = () => {
                    const text = reader.result as string;
                    const truncated = text.length > 8000
                        ? text.slice(0, 8000) + '\n\n[... truncated, file too large ...]'
                        : text;
                    attachments = [...attachments, {
                        type: 'file',
                        name: file.name,
                        dataUrl: '',
                        textContent: truncated,
                    }];
                };
                reader.readAsText(file);
                acceptedCount += 1;
            }
        }
    }

    function onFileSelect(e: Event) {
        const target = e.target as HTMLInputElement;
        if (target.files) readFiles(target.files);
        target.value = '';
    }

    function onDrop(e: DragEvent) {
        e.preventDefault();
        dragOver = false;
        if (e.dataTransfer?.files) readFiles(e.dataTransfer.files);
    }

    function onDragOver(e: DragEvent) {
        e.preventDefault();
        dragOver = true;
    }

    function onDragLeave() {
        dragOver = false;
    }

    function removeAttachment(idx: number) {
        attachments = attachments.filter((_, i) => i !== idx);
    }

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

    onMount(() => {
        void loadModelCapabilities();
    });

    $effect(() => {
        const workspaceId = $chat.workspaceId;
        if (workspaceId !== lastWorkspaceId) {
            lastWorkspaceId = workspaceId;
            fileListRequest += 1;
            fileList = [];
            fileListLoading = false;
            popoverOpen = false;
        }
    });

    $effect(() => {
        if (!didInitialFocus && textarea && !disabled) {
            didInitialFocus = true;
            requestAnimationFrame(() => textarea?.focus());
        }
    });

    $effect(() => {
        if (wasDisabled && !disabled) {
            void loadModelCapabilities();
            if (textarea) requestAnimationFrame(() => textarea?.focus());
        }
        wasDisabled = disabled;
    });

    $effect(() => {
        const prompt = $pendingInputPrompt;
        if (prompt) {
            input = prompt;
            pendingInputPrompt.set('');
            requestAnimationFrame(() => {
                autoGrow();
                textarea?.focus();
            });
        }
    });
</script>

<svelte:window onclick={handleOutsideClick} onkeydown={handleKeydown} />

<div
    class="input-dock"
    ondrop={onDrop}
    ondragover={onDragOver}
    ondragleave={onDragLeave}
    role="region"
>
    {#if attachments.length > 0}
        <div class="attachments-bar">
            {#each attachments as att, i}
                <div class="attachment-island">
                    {#if att.type === 'image'}
                        <img src={att.dataUrl} alt={att.name} class="att-thumb" />
                    {:else}
                        <div class="att-file-icon">
                            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                                <path d="M4 1h5.5L13 4.5V14a1 1 0 01-1 1H4a1 1 0 01-1-1V2a1 1 0 011-1z" stroke="currentColor" stroke-width="1.5"/>
                                <path d="M9 1v4h4" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
                            </svg>
                        </div>
                    {/if}
                    <span class="att-name">{att.name.length > 18 ? att.name.slice(0, 15) + '...' : att.name}</span>
                    {#if att.type === 'file' && att.textContent}
                        <span class="att-size">{(att.textContent.length / 1000).toFixed(1)}k</span>
                    {/if}
                    <button class="att-remove" onclick={() => removeAttachment(i)} aria-label="Remove {att.name}">
                        <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                            <path d="M2 2l6 6M8 2l-6 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                        </svg>
                    </button>
                </div>
            {/each}
        </div>
    {/if}

    {#if showCtxBar}
        <div class="ctx-bar-wrap">
            <div class="ctx-bar-track">
                <div
                    class="ctx-bar-fill"
                    class:ctx-warn={ctxPct >= 70 && ctxPct < 85}
                    class:ctx-danger={ctxPct >= 85}
                    style="width: max(2px, {ctxPct}%)"
                ></div>
            </div>
            <span class="ctx-bar-label" class:ctx-warn={ctxPct >= 70 && ctxPct < 85} class:ctx-danger={ctxPct >= 85}>
                {ctxLabel} / {ctxMax} tokens
            </span>
            {#if $chat.isCompacting}
                <span class="ctx-state-badge compacting" role="status" aria-live="polite">
                    <span class="ctx-state-dot" aria-hidden="true"></span>
                    <span class="ctx-state-label">Compacting history</span>
                    <span class="ctx-state-sep" aria-hidden="true">·</span>
                    <span class="ctx-state-meta">{compactElapsedSec}s</span>
                    <button
                        type="button"
                        class="ctx-state-cancel"
                        onclick={cancelCompaction}
                        title="Cancel and use a quick fallback summary"
                        aria-label="Cancel compaction"
                    >Cancel</button>
                </span>
            {:else if hasCompactedHistory}
                <span class="ctx-state-badge compacted">
                    <span class="ctx-state-check" aria-hidden="true">
                        <svg width="9" height="9" viewBox="0 0 10 10" fill="none">
                            <path d="M2 5.2L4 7L8 3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    </span>
                    <span class="ctx-state-label">History summarized</span>
                </span>
            {/if}
        </div>
    {/if}

    <div class="composer" class:drag-over={dragOver}>
        <input
            bind:this={fileInput}
            type="file"
            accept={attachAccept}
            multiple
            onchange={onFileSelect}
            class="file-hidden"
        />

        <textarea
            bind:this={textarea}
            bind:value={input}
            onkeydown={onKeydown}
            oninput={autoGrow}
            onpaste={onPaste}
            placeholder={disabled ? 'CT-2 is responding… type to queue your next message' : 'Ask CT-2 anything...'}
            rows="1"
        ></textarea>

        <div class="composer-footer" class:is-busy={disabled}>
            <div class="footer-left">
                {#if !isWorkspaceSession}
                    {#each modes as m}
                        <button
                            class="mode-pill"
                            class:active={currentMode === m.key}
                            onclick={() => setMode(m.key)}
                            {disabled}
                        >
                            <svg class="pill-icon" width="14" height="14" viewBox="0 0 16 16" fill="none">
                                {#if m.key === 'auto'}
                                    <path d="M9.5 2L5 9H8L6.5 14L12 7H9Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>
                                {:else if m.key === 'design'}
                                    <path d="M11.5 2L14 4.5L5 13.5L2 14L2.5 11Z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                                    <path d="M9.5 4L12 6.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                                {:else if m.key === 'code'}
                                    <path d="M5.5 4L2 8l3.5 4M10.5 4L14 8l-3.5 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                                {:else if m.key === 'chat'}
                                    <path d="M3 4.5A1.5 1.5 0 014.5 3h7A1.5 1.5 0 0113 4.5v5a1.5 1.5 0 01-1.5 1.5H7l-3 2.5V11H4.5A1.5 1.5 0 013 9.5z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
                                {/if}
                            </svg>
                            {m.label}
                        </button>
                    {/each}
                {:else}
                    <div class="ctx-anchor">
                        <button
                            class="workspace-ctx-badge"
                            class:active={contextCount > 0}
                            onclick={openPopover}
                            type="button"
                        >
                            <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                                <path d="M2 5V3a1 1 0 011-1h4l2 2h4a1 1 0 011 1v7a1 1 0 01-1 1H3a1 1 0 01-1-1V5z" stroke="currentColor" stroke-width="1.5"/>
                            </svg>
                            {contextCount > 0 ? `${contextCount} file${contextCount === 1 ? '' : 's'} in context` : 'Attach files to context'}
                        </button>
                        {#if popoverOpen}
                            <div class="ctx-popover" role="dialog" aria-modal="true" aria-label="Workspace files">
                                <div class="ctx-popover-header">
                                    <span>Workspace files</span>
                                    {#if contextCount > 0}
                                        <button class="ctx-clear" onclick={clearContextFiles} type="button">Clear all</button>
                                    {/if}
                                </div>
                                {#if fileListLoading}
                                    <div class="ctx-empty">Loading...</div>
                                {:else if fileList.length === 0}
                                    <div class="ctx-empty">No files in workspace</div>
                                {:else}
                                    <ul class="ctx-file-list">
                                        {#each fileList as path}
                                            <li>
                                                <label class="ctx-file-row">
                                                    <input
                                                        type="checkbox"
                                                        checked={$chat.contextFiles.includes(path)}
                                                        onchange={() => toggleContextFile(path)}
                                                    />
                                                    <span class="ctx-file-path">{path}</span>
                                                </label>
                                            </li>
                                        {/each}
                                    </ul>
                                {/if}
                            </div>
                        {/if}
                    </div>
                {/if}

                <button
                    class="search-pill"
                    class:active={$preferences.webSearchEnabled}
                    onclick={toggleWebSearch}
                    type="button"
                    {disabled}
                    aria-pressed={$preferences.webSearchEnabled}
                    aria-label={$preferences.webSearchEnabled ? 'Web search on. Click to turn off.' : 'Web search off. Click to turn on.'}
                    title={$preferences.webSearchEnabled ? 'Web search on' : 'Web search off'}
                >
                    <svg class="pill-icon" width="14" height="14" viewBox="0 0 16 16" fill="none">
                        <circle cx="8" cy="8" r="5.5" stroke="currentColor" stroke-width="1.5"/>
                        <path d="M2.5 8h11" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                        <path d="M8 2.5c1.7 1.5 2.7 3.4 2.7 5.5S9.7 12 8 13.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                        <path d="M8 2.5C6.3 4 5.3 5.9 5.3 8S6.3 12 8 13.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                    Search
                </button>

                <button
                    class="rag-pill"
                    class:active={$chat.ragEnabled}
                    onclick={toggleRag}
                    type="button"
                    {disabled}
                    aria-pressed={$chat.ragEnabled}
                    aria-label={$chat.ragEnabled ? 'RAG on. Click to turn off.' : 'RAG off. Click to turn on.'}
                    title={$chat.ragEnabled ? 'RAG: document context on' : 'RAG: document context off'}
                >
                    <svg class="pill-icon" width="14" height="14" viewBox="0 0 16 16" fill="none">
                        <path d="M2 3h4l1 2h6a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
                        <path d="M6 9v3M10 9v3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                    </svg>
                    RAG
                </button>
            </div>

            <div class="footer-right">
                <span class="send-hint">Ctrl+Enter</span>
                <button
                    class="attach-btn"
                    onclick={() => fileInput?.click()}
                    {disabled}
                    aria-label={attachLabel}
                    title={attachLabel}
                >
                    <svg width="17" height="17" viewBox="0 0 18 18" fill="none">
                        <path d="M15.5 8.5l-6.4 6.4a3.5 3.5 0 01-5-5l6.4-6.4a2.1 2.1 0 013 3L7.2 12.8a.7.7 0 01-1-1l5.3-5.3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                </button>
                {#if disabled}
                    <button class="send send-stop" onclick={stopGeneration} aria-label="Stop generation" title="Stop">
                        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                            <rect x="2" y="2" width="8" height="8" rx="1.5" fill="currentColor"/>
                        </svg>
                    </button>
                {:else}
                    <button class="send" onclick={submit} aria-label="Send message" title="Send (Ctrl+Enter)">
                        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                            <path d="M8 13V3M3.5 7.5L8 3l4.5 4.5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    </button>
                {/if}
            </div>
        </div>
    </div>
</div>

<style>
    .input-dock {
        --composer-max: 860px;
        padding: 8px clamp(20px, 3vw, 36px) 28px;
        flex-shrink: 0;
        position: relative;
        z-index: 2;
    }

    /* ---- Attachment preview strip ---- */
    .attachments-bar {
        display: flex;
        gap: 8px;
        width: min(100%, var(--composer-max));
        margin: 0 auto 8px;
        flex-wrap: wrap;
    }

    .attachment-island {
        display: flex;
        align-items: center;
        gap: 8px;
        background: var(--bubble-strong);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: 12px;
        padding: 6px 10px 6px 6px;
        box-shadow: var(--shadow-sm);
        animation: islandIn 0.25s cubic-bezier(0.34, 1.56, 0.64, 1) both;
    }

    @keyframes islandIn {
        from { opacity: 0; transform: scale(0.85) translateY(6px); }
        to   { opacity: 1; transform: scale(1)    translateY(0); }
    }

    .att-thumb {
        width: 36px;
        height: 36px;
        border-radius: 8px;
        object-fit: cover;
        flex-shrink: 0;
    }

    .att-file-icon {
        width: 36px;
        height: 36px;
        border-radius: 8px;
        background: var(--accent-subtle);
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        color: var(--text-muted);
    }

    .att-name {
        font-size: 12px;
        font-weight: 500;
        color: var(--text-secondary);
        max-width: 120px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .att-size {
        font-size: 11px;
        color: var(--text-muted);
        opacity: 0.7;
    }

    .att-remove {
        width: 20px;
        height: 20px;
        border: none;
        background: var(--surface);
        border-radius: 50%;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--text-muted);
        flex-shrink: 0;
        transition: background 0.15s, color 0.15s;
    }
    .att-remove:hover {
        background: var(--surface-hover);
        color: var(--text);
    }

    /* ---- Main composer ---- */
    .composer {
        position: relative;
        display: flex;
        flex-direction: column;
        width: min(100%, var(--composer-max));
        margin: 0 auto;
        background: var(--bubble-strong);
        backdrop-filter: var(--bubble-blur-heavy);
        -webkit-backdrop-filter: var(--bubble-blur-heavy);
        border: var(--bubble-border);
        border-radius: 22px;
        padding: 18px 18px 14px;
        box-shadow: var(--bubble-glow);
        transition: box-shadow var(--transition-slow), border-color var(--transition);
        overflow: visible;
    }
    .composer:focus-within {
        box-shadow: var(--bubble-glow-strong);
    }
    .composer-footer.is-busy {
        opacity: 0.5;
        pointer-events: none;
    }
    .composer.drag-over {
        border-color: var(--accent);
        box-shadow:
            0 0 0 2px color-mix(in srgb, var(--accent) 20%, transparent),
            0 8px 40px rgba(0, 0, 0, 0.08);
    }

    .file-hidden { display: none; }

    /* ---- Textarea ---- */
    textarea {
        width: 100%;
        background: none;
        color: var(--text);
        border: none;
        font-family: var(--font-body);
        font-size: 15px;
        line-height: 1.6;
        min-height: 52px;
        resize: none;
        outline: none;
        padding: 0 0 16px;
    }
    textarea::placeholder {
        color: var(--text-muted);
        font-weight: 400;
    }
    textarea:disabled {
        opacity: 0.82;
        cursor: default;
    }

    /* ---- Footer toolbar ---- */
    .composer-footer {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        padding-top: 10px;
        margin-top: 2px;
        border-top: 1px solid var(--border-subtle);
        /* Give pill borders clearance from the separator line */
        padding-bottom: 2px;
    }

    .footer-left {
        display: flex;
        align-items: center;
        gap: 3px;
        min-width: 0;
        overflow: visible;
        padding: 2px 0;
    }

    .footer-right {
        display: flex;
        align-items: center;
        gap: 6px;
        flex-shrink: 0;
        padding: 2px 0;
    }

    /* ---- Mode pills ---- */
    .pill-icon {
        flex-shrink: 0;
        opacity: 0.7;
    }

    .mode-pill {
        display: flex;
        align-items: center;
        gap: 5px;
        padding: 5px 11px;
        border: 1px solid transparent;
        border-radius: 8px;
        background: transparent;
        color: var(--text-muted);
        font-family: var(--font-body);
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        transition: background var(--transition), color var(--transition), border-color var(--transition);
        white-space: nowrap;
        user-select: none;
        isolation: isolate;
    }
    .mode-pill:hover:not(:disabled):not(.active) {
        color: var(--text-secondary);
        background: var(--accent-subtle);
        border-color: var(--border-subtle);
    }
    .mode-pill.active {
        background: var(--accent-subtle);
        color: var(--text);
        border-color: var(--border);
    }
    .mode-pill.active .pill-icon {
        opacity: 1;
    }
    .mode-pill:disabled {
        opacity: 0.3;
        cursor: not-allowed;
    }

    /* ---- Search pill — identical style to mode pills ---- */
    .search-pill {
        display: flex;
        align-items: center;
        gap: 5px;
        padding: 5px 11px;
        border: 1px solid transparent;
        border-radius: 8px;
        background: transparent;
        color: var(--text-muted);
        font-family: var(--font-body);
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        transition: background var(--transition), color var(--transition), border-color var(--transition);
        white-space: nowrap;
        user-select: none;
        margin-left: 5px;
        isolation: isolate;
    }
    .search-pill:hover:not(:disabled):not(.active) {
        color: var(--text-secondary);
        background: var(--accent-subtle);
        border-color: var(--border-subtle);
    }
    .search-pill.active {
        background: var(--accent-subtle);
        color: var(--text);
        border-color: var(--border);
    }
    .search-pill.active .pill-icon {
        opacity: 1;
    }
    .search-pill:disabled {
        opacity: 0.3;
        cursor: not-allowed;
    }

    .rag-pill {
        display: flex;
        align-items: center;
        gap: 5px;
        padding: 5px 11px;
        border: 1px solid transparent;
        border-radius: 8px;
        background: transparent;
        color: var(--text-muted);
        font-family: var(--font-body);
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        transition: background var(--transition), color var(--transition), border-color var(--transition);
        white-space: nowrap;
        user-select: none;
        margin-left: 5px;
        isolation: isolate;
    }
    .rag-pill:hover:not(:disabled):not(.active) {
        color: var(--text-secondary);
        background: var(--accent-subtle);
        border-color: var(--border-subtle);
    }
    .rag-pill.active {
        background: var(--accent-subtle);
        color: var(--text);
        border-color: var(--border);
    }
    .rag-pill.active .pill-icon {
        opacity: 1;
    }
    .rag-pill:disabled {
        opacity: 0.3;
        cursor: not-allowed;
    }

    /* ---- Workspace context badge + popover ---- */
    .ctx-anchor {
        position: relative;
    }

    .workspace-ctx-badge {
        display: flex;
        align-items: center;
        gap: 5px;
        padding: 5px 11px;
        border-radius: 8px;
        font-size: 13px;
        color: var(--text-muted);
        background: transparent;
        border: 1px solid var(--border-subtle);
        cursor: pointer;
        transition: background 0.15s, color 0.15s, border-color 0.15s;
        font-family: var(--font-body);
        font-weight: 500;
        white-space: nowrap;
    }
    .workspace-ctx-badge:hover,
    .workspace-ctx-badge.active {
        background: var(--accent-subtle);
        color: var(--text-secondary);
        border-color: var(--border);
    }

    .ctx-popover {
        position: absolute;
        bottom: calc(100% + 10px);
        left: 0;
        min-width: 240px;
        max-width: 340px;
        background: var(--surface-solid);
        border: 1px solid var(--border);
        border-radius: 14px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.14);
        z-index: 200;
        overflow: hidden;
    }

    .ctx-popover-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 14px;
        font-size: 11px;
        font-weight: 600;
        color: var(--text-secondary);
        border-bottom: 1px solid var(--border-subtle);
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    .ctx-clear {
        font-size: 11px;
        color: var(--accent);
        background: none;
        border: none;
        cursor: pointer;
        padding: 0;
        font-family: var(--font-body);
    }
    .ctx-clear:hover { text-decoration: underline; }

    .ctx-file-list {
        list-style: none;
        margin: 0;
        padding: 4px 0;
        max-height: 220px;
        overflow-y: auto;
    }

    .ctx-file-row {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 14px;
        cursor: pointer;
        font-size: 12px;
        color: var(--text);
    }
    .ctx-file-row:hover { background: var(--surface); }

    .ctx-file-path {
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        font-family: var(--font-mono, monospace);
        font-size: 11px;
    }

    .ctx-empty {
        padding: 14px;
        font-size: 12px;
        color: var(--text-secondary);
        text-align: center;
    }

    /* ---- Footer-right: hint, attach, send ---- */
    .send-hint {
        font-size: 11px;
        font-weight: 500;
        color: var(--text-muted);
        letter-spacing: 0.02em;
        opacity: 0;
        transition: opacity var(--transition);
        white-space: nowrap;
    }
    .composer:focus-within .send-hint {
        opacity: 1;
    }

    .attach-btn {
        width: 32px;
        height: 32px;
        border: none;
        background: transparent;
        border-radius: 8px;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        color: var(--text-muted);
        transition: color 0.15s, background 0.15s;
    }
    .attach-btn:hover:not(:disabled) {
        color: var(--text-secondary);
        background: var(--accent-subtle);
    }
    .attach-btn:disabled {
        opacity: 0.4;
        cursor: default;
    }

    .send {
        width: 34px;
        height: 34px;
        border: 1px solid transparent;
        border-radius: 50%;
        background: var(--text);
        color: var(--bg);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        transition:
            transform var(--spring-duration) var(--spring),
            opacity var(--transition),
            background var(--transition);
    }
    .send:hover:not(:disabled) {
        transform: scale(1.06);
    }
    .send:active:not(:disabled) {
        transform: scale(0.93);
    }
    .send:disabled {
        opacity: 0.15;
        cursor: not-allowed;
    }

    .send-stop {
        background: rgba(239, 68, 68, 0.1);
        color: var(--error, #ef4444);
        border-color: rgba(239, 68, 68, 0.25);
    }
    .send-stop:hover {
        background: rgba(239, 68, 68, 0.2);
        transform: scale(1.06);
    }

    /* ---- Context usage bar ---- */
    .ctx-bar-wrap {
        display: flex;
        align-items: center;
        gap: 10px;
        width: min(100%, var(--composer-max));
        margin: 0 auto 7px;
        padding: 0 4px;
    }
    .ctx-bar-track {
        flex: 1;
        height: 3px;
        background: var(--border-subtle);
        border-radius: 2px;
        overflow: hidden;
    }
    .ctx-bar-fill {
        height: 100%;
        background: var(--text-muted);
        border-radius: 2px;
        transition: width 0.4s ease, background 0.3s;
    }
    .ctx-bar-fill.ctx-warn { background: #e8a000; }
    .ctx-bar-fill.ctx-danger { background: var(--error, #ef4444); }
    .ctx-bar-label {
        font-size: 11px;
        font-weight: 500;
        color: var(--text-muted);
        white-space: nowrap;
        flex-shrink: 0;
        letter-spacing: 0.01em;
    }
    .ctx-bar-label.ctx-warn { color: #e8a000; }
    .ctx-bar-label.ctx-danger { color: var(--error, #ef4444); }
    .ctx-state-badge {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        height: 22px;
        padding: 0 10px;
        border-radius: 999px;
        font-size: 10.5px;
        font-weight: 600;
        letter-spacing: 0.02em;
        white-space: nowrap;
        border: 1px solid transparent;
        flex-shrink: 0;
    }
    .ctx-state-badge.compacting {
        color: var(--brain);
        background: rgba(232, 133, 12, 0.10);
        border-color: rgba(232, 133, 12, 0.22);
        padding-right: 4px; /* tighter on the cancel side — chip has its own padding */
    }
    .ctx-state-badge.compacted {
        color: var(--text-secondary);
        background: var(--surface);
        border-color: var(--border);
    }
    .ctx-state-label {
        line-height: 1;
    }
    .ctx-state-meta {
        color: var(--brain);
        opacity: 0.78;
        font-variant-numeric: tabular-nums;
        line-height: 1;
    }
    .ctx-state-sep {
        opacity: 0.5;
        line-height: 1;
        font-weight: 400;
    }
    .ctx-state-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: var(--brain);
        box-shadow: 0 0 0 0 rgba(232, 133, 12, 0.45);
        animation: ctxStatePulse 1.4s ease-in-out infinite;
        flex-shrink: 0;
    }
    @keyframes ctxStatePulse {
        0%   { box-shadow: 0 0 0 0 rgba(232, 133, 12, 0.45); transform: scale(1);    }
        70%  { box-shadow: 0 0 0 6px rgba(232, 133, 12, 0);  transform: scale(1.05); }
        100% { box-shadow: 0 0 0 0 rgba(232, 133, 12, 0);    transform: scale(1);    }
    }
    .ctx-state-check {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 12px;
        height: 12px;
        border-radius: 50%;
        background: rgba(120, 120, 120, 0.18);
        color: var(--text-secondary);
        flex-shrink: 0;
    }
    .ctx-state-cancel {
        appearance: none;
        margin-left: 2px;
        padding: 0 9px;
        height: 18px;
        line-height: 18px;
        border-radius: 999px;
        font-size: 9.5px;
        font-weight: 600;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: var(--brain);
        background: rgba(232, 133, 12, 0.06);
        border: 1px solid rgba(232, 133, 12, 0.35);
        cursor: pointer;
        transition: background 0.14s ease, border-color 0.14s ease, transform 0.08s ease;
    }
    .ctx-state-cancel:hover {
        background: rgba(232, 133, 12, 0.18);
        border-color: rgba(232, 133, 12, 0.6);
    }
    .ctx-state-cancel:active {
        transform: translateY(0.5px);
    }
    .ctx-state-cancel:focus-visible {
        outline: 2px solid rgba(232, 133, 12, 0.55);
        outline-offset: 1px;
    }
    @media (prefers-reduced-motion: reduce) {
        .ctx-state-dot { animation: none; }
    }
</style>
