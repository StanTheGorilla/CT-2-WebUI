<script lang="ts">
    import { onMount } from 'svelte';
    import { chat, sendThink, setMode, stopGeneration, toggleContextFile, clearContextFiles, type Attachment, type ModeOverride } from '$lib/stores/chat';

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
    const TEXT_FILE_ACCEPT = '.txt,.html,.htm,.css,.js,.ts,.py,.json,.md,.csv,.xml,.yaml,.yml,.svg,.sh,.bat,.sql,.rb,.go,.rs,.java,.c,.cpp,.h,.hpp,.toml,.ini,.cfg';

    const disabled = $derived($chat.phase !== 'idle' && $chat.phase !== 'done');
    const currentMode = $derived($chat.modeOverride);
    const isWorkspaceSession = $derived(!!$chat.workspaceId);
    const hasWorkspaceContext = $derived(!!$chat.workspaceId);
    const contextCount = $derived($chat.contextFiles.length);
    const attachAccept = $derived(`${visionSupported ? 'image/*,' : ''}${TEXT_FILE_ACCEPT}`);
    const attachLabel = $derived(visionSupported ? 'Attach file or image' : 'Attach file (current model has no vision)');

    const modes: { key: ModeOverride; label: string }[] = [
        { key: 'chat', label: 'Chat' },
        { key: 'design', label: 'Design' },
        { key: 'code', label: 'Code' },
        { key: 'auto', label: 'Auto' },
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
            const res = await fetch('/api/model');
            const data = await res.json();
            visionSupported = data.vision_supported ?? false;
        } catch {
            visionSupported = false;
        }
    }

    function getExtension(name: string): string {
        const i = name.lastIndexOf('.');
        return i >= 0 ? name.slice(i + 1).toLowerCase() : '';
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
                reader.onload = () => {
                    attachments = [...attachments, {
                        type: 'image',
                        name: file.name,
                        dataUrl: reader.result as string,
                    }];
                };
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
        if (wasDisabled && !disabled && textarea) {
            requestAnimationFrame(() => textarea?.focus());
        }
        wasDisabled = disabled;
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
                            <svg width="18" height="18" viewBox="0 0 16 16" fill="none">
                                <path d="M4 1h5.5L13 4.5V14a1 1 0 01-1 1H4a1 1 0 01-1-1V2a1 1 0 011-1z" stroke="currentColor" stroke-width="1.2"/>
                                <path d="M9 1v4h4" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
                            </svg>
                        </div>
                    {/if}
                    <span class="att-name">{att.name.length > 18 ? att.name.slice(0, 15) + '...' : att.name}</span>
                    {#if att.type === 'file' && att.textContent}
                        <span class="att-size">{(att.textContent.length / 1000).toFixed(1)}k</span>
                    {/if}
                    <button class="att-remove" onclick={() => removeAttachment(i)} aria-label="Remove {att.name}">
                        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                            <path d="M3 3l6 6M9 3l-6 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                        </svg>
                    </button>
                </div>
            {/each}
        </div>
    {/if}

    {#if !isWorkspaceSession}
        <div class="mode-bar">
            {#each modes as m}
                <button
                    class="mode-pill"
                    class:active={currentMode === m.key}
                    onclick={() => setMode(m.key)}
                    {disabled}
                >
                    <svg class="mode-icon" width="14" height="14" viewBox="0 0 16 16" fill="none">
                        {#if m.key === 'auto'}
                            <path d="M8 2l1.5 3.5L13 7l-3.5 1.5L8 12l-1.5-3.5L3 7l3.5-1.5z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
                        {:else if m.key === 'design'}
                            <circle cx="8" cy="8" r="5.5" stroke="currentColor" stroke-width="1.2"/>
                            <circle cx="8" cy="8" r="2" fill="currentColor" opacity="0.4"/>
                        {:else if m.key === 'code'}
                            <path d="M5.5 4L2 8l3.5 4M10.5 4L14 8l-3.5 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
                        {:else if m.key === 'chat'}
                            <path d="M3 4.5A1.5 1.5 0 014.5 3h7A1.5 1.5 0 0113 4.5v5a1.5 1.5 0 01-1.5 1.5H7l-3 2.5V11H4.5A1.5 1.5 0 013 9.5z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
                        {:else if m.key === 'computer'}
                            <rect x="2" y="3" width="12" height="8" rx="1.5" stroke="currentColor" stroke-width="1.2"/>
                            <path d="M5.5 14h5M8 11v3" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
                        {/if}
                    </svg>
                    {m.label}
                </button>
            {/each}
        </div>
    {/if}

    {#if hasWorkspaceContext}
        <div class="ctx-anchor">
            <button
                class="workspace-ctx-badge"
                class:active={contextCount > 0}
                onclick={openPopover}
                type="button"
            >
                <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                    <path d="M2 5V3a1 1 0 011-1h4l2 2h4a1 1 0 011 1v7a1 1 0 01-1 1H3a1 1 0 01-1-1V5z" stroke="currentColor" stroke-width="1.2"/>
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

    <div class="island" class:drag-over={dragOver} class:is-busy={disabled}>
        <input
            bind:this={fileInput}
            type="file"
            accept={attachAccept}
            multiple
            onchange={onFileSelect}
            class="file-hidden"
        />
        <button
            class="attach-btn"
            onclick={() => fileInput?.click()}
            {disabled}
            aria-label={attachLabel}
            title={attachLabel}
        >
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                <path d="M15.5 8.5l-6.4 6.4a3.5 3.5 0 01-5-5l6.4-6.4a2.1 2.1 0 013 3L7.2 12.8a.7.7 0 01-1-1l5.3-5.3" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
        </button>
        <textarea
            bind:this={textarea}
            bind:value={input}
            onkeydown={onKeydown}
            oninput={autoGrow}
            onpaste={onPaste}
            placeholder="Ask CT-2 anything..."
            rows="1"
            {disabled}
        ></textarea>
        <div class="island-actions">
            <span class="hint">Ctrl+Enter</span>
            {#if disabled}
                <button class="send send-stop" onclick={stopGeneration} aria-label="Stop generation" title="Stop">
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                        <rect x="1" y="1" width="10" height="10" rx="2" fill="currentColor"/>
                    </svg>
                </button>
            {:else}
                <button class="send" onclick={submit} aria-label="Send message">
                    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                        <path d="M3.5 9h11M10 4.5L14.5 9 10 13.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                </button>
            {/if}
        </div>
    </div>
</div>

<style>
    .input-dock {
        --composer-max: 860px;
        padding: 10px clamp(20px, 3vw, 36px) 28px;
        flex-shrink: 0;
        position: relative;
        z-index: 2;
    }

    /* ---- Attachment islands ---- */
    .attachments-bar {
        display: flex;
        gap: 8px;
        width: min(100%, var(--composer-max));
        max-width: none;
        margin: 0 auto 8px;
        padding: 0 4px;
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
        to { opacity: 1; transform: scale(1) translateY(0); }
    }

    .att-thumb {
        width: 36px;
        height: 36px;
        border-radius: 8px;
        object-fit: cover;
        flex-shrink: 0;
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

    /* ---- Mode selector pills ---- */
    .mode-bar {
        display: flex;
        gap: 2px;
        max-width: min(100%, var(--composer-max));
        margin: 0 auto 8px;
        justify-content: center;
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border-light);
        border-radius: var(--radius-pill);
        padding: 3px;
        width: fit-content;
        box-shadow: var(--shadow-xs);
    }
    .mode-pill {
        display: flex;
        align-items: center;
        gap: 5px;
        padding: 5px 14px;
        border: none;
        border-radius: var(--radius-pill);
        background: transparent;
        color: var(--text-muted);
        font-family: var(--font-body);
        font-size: 12px;
        font-weight: 500;
        cursor: pointer;
        transition: all var(--transition);
        user-select: none;
        letter-spacing: 0.01em;
    }
    .mode-pill:hover:not(:disabled):not(.active) {
        color: var(--text-secondary);
        background: var(--accent-subtle);
    }
    .mode-pill.active {
        background: var(--surface-solid);
        color: var(--text);
        box-shadow: var(--shadow-sm);
    }
    .mode-pill:disabled {
        opacity: 0.3;
        cursor: not-allowed;
    }
    .mode-icon {
        flex-shrink: 0;
        opacity: 0.6;
    }
    .mode-pill.active .mode-icon {
        opacity: 1;
    }

    /* ---- Workspace context badge + popover ---- */
    .ctx-anchor {
        position: relative;
        width: min(100%, var(--composer-max));
        max-width: none;
        margin: 0 auto 6px;
    }

    .workspace-ctx-badge {
        display: flex;
        align-items: center;
        gap: 5px;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 11px;
        color: var(--text-secondary);
        background: transparent;
        border: 1px solid var(--border-subtle);
        cursor: pointer;
        transition: background 0.15s, color 0.15s;
        font-family: var(--font-body);
        font-weight: 500;
    }
    .workspace-ctx-badge:hover,
    .workspace-ctx-badge.active {
        background: var(--accent-subtle);
        color: var(--text);
        border-color: var(--border);
    }

    .ctx-popover {
        position: absolute;
        bottom: calc(100% + 6px);
        left: 0;
        min-width: 240px;
        max-width: 340px;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 10px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.18);
        z-index: 100;
        overflow: hidden;
    }

    .ctx-popover-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 8px 12px;
        font-size: 11px;
        font-weight: 600;
        color: var(--text-secondary);
        border-bottom: 1px solid var(--border-subtle);
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .ctx-clear {
        font-size: 11px;
        color: var(--accent);
        background: none;
        border: none;
        cursor: pointer;
        padding: 0;
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
        padding: 5px 12px;
        cursor: pointer;
        font-size: 12px;
        color: var(--text);
    }
    .ctx-file-row:hover { background: var(--hover); }

    .ctx-file-path {
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        font-family: var(--font-mono, monospace);
        font-size: 11px;
    }

    .ctx-empty {
        padding: 12px;
        font-size: 12px;
        color: var(--text-secondary);
        text-align: center;
    }

    /* ---- Input island ---- */
    .island {
        display: flex;
        align-items: center;
        gap: 8px;
        width: min(100%, var(--composer-max));
        max-width: none;
        margin: 0 auto;
        background: var(--bubble-strong);
        backdrop-filter: var(--bubble-blur-heavy);
        -webkit-backdrop-filter: var(--bubble-blur-heavy);
        border: var(--bubble-border);
        border-radius: var(--radius-lg);
        min-height: 58px;
        padding: 12px 15px;
        box-shadow: var(--bubble-glow);
        transition: box-shadow var(--transition-slow), border-color var(--transition);
    }
    .island:focus-within {
        box-shadow: var(--bubble-glow-strong);
    }
    .island.is-busy {
        border-color: var(--border);
        box-shadow: var(--bubble-glow);
    }
    .island.drag-over {
        border-color: var(--accent);
        box-shadow:
            0 0 0 2px color-mix(in srgb, var(--accent) 20%, transparent),
            0 8px 40px rgba(0, 0, 0, 0.08);
    }

    .file-hidden {
        display: none;
    }

    .attach-btn {
        width: 34px;
        height: 34px;
        border: none;
        background: transparent;
        border-radius: 50%;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        color: var(--text-muted);
        transition: color 0.15s, background 0.15s;
    }
    .attach-btn:hover:not(:disabled) {
        color: var(--text);
        background: var(--accent-subtle);
    }
    .attach-btn:disabled {
        opacity: 0.5;
        cursor: default;
    }

    textarea {
        flex: 1;
        background: none;
        color: var(--text);
        border: none;
        font-family: var(--font-body);
        font-size: 15px;
        line-height: 1.5;
        min-height: 24px;
        resize: none;
        outline: none;
        padding: 4px 0;
    }
    textarea::placeholder {
        color: var(--text-muted);
        font-weight: 400;
    }
    textarea:disabled {
        opacity: 0.82;
        cursor: default;
    }

    .island-actions {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-shrink: 0;
    }

    .hint {
        font-size: 11px;
        font-weight: 500;
        color: var(--text-muted);
        letter-spacing: 0.02em;
        opacity: 0;
        transition: opacity var(--transition);
    }
    .island:focus-within .hint {
        opacity: 1;
    }

    .send {
        width: 38px;
        height: 38px;
        border: none;
        border-radius: 50%;
        background: var(--text);
        color: var(--bg);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        transition: transform var(--spring-duration) var(--spring), opacity var(--transition);
    }
    .send:hover:not(:disabled) {
        transform: scale(1.05);
    }
    .send:active:not(:disabled) {
        transform: scale(0.93);
    }
    .send:disabled {
        opacity: 0.15;
        cursor: not-allowed;
    }
    .send-stop {
        background: rgba(239, 68, 68, 0.12);
        color: var(--error, #ef4444);
        border: 1px solid rgba(239, 68, 68, 0.25);
    }
    .send-stop:hover {
        background: rgba(239, 68, 68, 0.22);
        transform: scale(1.05);
    }
</style>
