<script lang="ts">
    import { chat, sendThink, type Attachment } from '$lib/stores/chat';

    let input = $state('');
    let textarea: HTMLTextAreaElement;
    let fileInput: HTMLInputElement;
    let attachments = $state<Attachment[]>([]);
    let dragOver = $state(false);

    const disabled = $derived($chat.phase !== 'idle' && $chat.phase !== 'done');

    function submit() {
        const text = input.trim();
        if ((!text && attachments.length === 0) || disabled) return;
        sendThink(text || (attachments.some(a => a.type === 'image') ? '(image attached)' : '(file attached)'), [...attachments]);
        input = '';
        attachments = [];
        if (textarea) textarea.style.height = 'auto';
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

    function getExtension(name: string): string {
        const i = name.lastIndexOf('.');
        return i >= 0 ? name.slice(i + 1).toLowerCase() : '';
    }

    function readFiles(files: FileList | File[]) {
        for (const file of files) {
            if (attachments.length >= 4) break;
            const ext = getExtension(file.name);

            if (file.type.startsWith('image/')) {
                const reader = new FileReader();
                reader.onload = () => {
                    attachments = [...attachments, {
                        type: 'image',
                        name: file.name,
                        dataUrl: reader.result as string,
                    }];
                };
                reader.readAsDataURL(file);
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
        if (images.length > 0) {
            e.preventDefault();
            readFiles(images);
        }
    }
</script>

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

    <div class="island" class:drag-over={dragOver}>
        <input
            bind:this={fileInput}
            type="file"
            accept="image/*,.txt,.html,.htm,.css,.js,.ts,.py,.json,.md,.csv,.xml,.yaml,.yml,.svg,.sh,.sql,.go,.rs,.java,.c,.cpp,.h,.toml,.ini"
            multiple
            onchange={onFileSelect}
            class="file-hidden"
        />
        <button
            class="attach-btn"
            onclick={() => fileInput?.click()}
            {disabled}
            aria-label="Attach file"
            title="Attach file"
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
            <button class="send" onclick={submit} {disabled} aria-label="Send message">
                <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                    <path d="M3.5 9h11M10 4.5L14.5 9 10 13.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            </button>
        </div>
    </div>
</div>

<style>
    .input-dock {
        padding: 8px 32px 28px;
        flex-shrink: 0;
        position: relative;
        z-index: 2;
    }

    /* ---- Attachment islands ---- */
    .attachments-bar {
        display: flex;
        gap: 8px;
        max-width: 720px;
        margin: 0 auto 8px;
        padding: 0 4px;
        flex-wrap: wrap;
    }

    .attachment-island {
        display: flex;
        align-items: center;
        gap: 8px;
        background: rgba(255, 255, 255, 0.88);
        backdrop-filter: blur(24px);
        -webkit-backdrop-filter: blur(24px);
        border: 1px solid rgba(0, 0, 0, 0.06);
        border-radius: 12px;
        padding: 6px 10px 6px 6px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
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
        background: rgba(0, 0, 0, 0.04);
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
        background: rgba(0, 0, 0, 0.06);
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
        background: rgba(0, 0, 0, 0.12);
        color: var(--text);
    }

    /* ---- Input island ---- */
    .island {
        display: flex;
        align-items: center;
        gap: 8px;
        max-width: 720px;
        margin: 0 auto;
        background: rgba(255, 255, 255, 0.92);
        backdrop-filter: blur(48px) saturate(1.5);
        -webkit-backdrop-filter: blur(48px) saturate(1.5);
        border: 1px solid rgba(255, 255, 255, 0.9);
        border-radius: var(--radius-lg);
        padding: 10px 12px 10px 12px;
        box-shadow:
            0 0 0 1px rgba(0, 0, 0, 0.03),
            0 2px 4px rgba(0, 0, 0, 0.03),
            0 8px 40px rgba(0, 0, 0, 0.06),
            inset 0 1px 0 rgba(255, 255, 255, 0.9);
        transition: box-shadow var(--transition-slow), border-color var(--transition);
    }
    .island:focus-within {
        border-color: rgba(255, 255, 255, 1);
        box-shadow:
            0 0 0 1px rgba(0, 0, 0, 0.04),
            0 4px 8px rgba(0, 0, 0, 0.04),
            0 16px 56px rgba(0, 0, 0, 0.08),
            inset 0 1px 0 rgba(255, 255, 255, 1);
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
        background: rgba(0, 0, 0, 0.05);
    }
    .attach-btn:disabled {
        opacity: 0.3;
        cursor: not-allowed;
    }

    textarea {
        flex: 1;
        background: none;
        color: var(--text);
        border: none;
        font-family: var(--font-body);
        font-size: 15px;
        line-height: 1.5;
        resize: none;
        outline: none;
        padding: 4px 0;
    }
    textarea::placeholder {
        color: var(--text-muted);
        font-weight: 400;
    }
    textarea:disabled {
        opacity: 0.4;
        cursor: not-allowed;
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
        color: white;
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
</style>
