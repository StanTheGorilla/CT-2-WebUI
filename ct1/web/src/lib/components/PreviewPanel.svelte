<script lang="ts">
    let { code, outputType = 'html_page', onClose }:
        { code: string; outputType?: string; onClose: () => void } = $props();

    let activeTab = $state<'preview' | 'code'>('code');
    let copied = $state(false);
    let iframe = $state<HTMLIFrameElement>();
    let lastOutputType = $state('');

    const _EXT: Record<string, string> = {
        html_page: 'design.html', python: 'script.py', javascript: 'script.js',
        typescript: 'script.ts', css: 'styles.css', rust: 'main.rs',
        go: 'main.go', java: 'Main.java', cpp: 'main.cpp', c: 'main.c',
    };

    function downloadCode() {
        const filename = _EXT[outputType] ?? 'output.txt';
        const blob = new Blob([code], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
    }

    let lines = $derived(() => {
        return code ? code.split('\n') : [];
    });

    async function copyCode() {
        await navigator.clipboard.writeText(code);
        copied = true;
        setTimeout(() => { copied = false; }, 2000);
    }

    // Debounce iframe updates during streaming (~2 updates/sec instead of per-token)
    let debounceTimer: ReturnType<typeof setTimeout>;
    let lastRendered = '';

    function wrapPartialHtml(html: string): string {
        const trimmed = html.trimStart().toLowerCase();
        if (trimmed.startsWith('<!doctype') || trimmed.startsWith('<html')) return html;
        return `<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><style>body{font-family:system-ui,sans-serif;padding:16px;color:#1a1a1a}</style></head><body>${html}</body></html>`;
    }

    $effect(() => {
        if (outputType !== lastOutputType) {
            lastOutputType = outputType;
            activeTab = outputType === 'html_page' ? 'preview' : 'code';
            lastRendered = '';
        }
    });

    $effect(() => {
        const frame = iframe;
        clearTimeout(debounceTimer);
        if (!frame || !code || activeTab !== 'preview') return;

        debounceTimer = setTimeout(() => {
            if (code !== lastRendered) {
                const navGuard = `<script>document.addEventListener('click',function(e){var a=e.target.closest('a');if(a){e.preventDefault();}});<\/script>`;
                const safeHtml = wrapPartialHtml(code);
                frame.srcdoc = navGuard + safeHtml;
                lastRendered = code;
            }
        }, 500);

        return () => {
            clearTimeout(debounceTimer);
        };
    });
</script>

<div class="preview">
    <div class="toolbar">
        <div class="tab-group">
            {#if outputType === 'html_page'}
            <button
                class="tab"
                class:active={activeTab === 'preview'}
                onclick={() => activeTab = 'preview'}
            >Preview</button>
            {/if}
            <button
                class="tab"
                class:active={activeTab === 'code'}
                onclick={() => activeTab = 'code'}
            >Code</button>
        </div>
        <div class="toolbar-actions">
            <button class="action-btn" onclick={downloadCode} aria-label="Download file" title="Download">
                <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
                    <path d="M7 2v7M4 7l3 3 3-3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
                    <path d="M2 11h10" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
                </svg>
                <span>Download</span>
            </button>
            <button class="close" onclick={onClose} aria-label="Close preview" title="Close preview">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                    <path d="M2.5 2.5l7 7M9.5 2.5l-7 7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
                </svg>
                <span>Close</span>
            </button>
        </div>
    </div>

    <div class="content">
        <!-- Keep iframe always mounted so srcdoc is preserved when switching tabs -->
        <iframe
            bind:this={iframe}
            title="Preview"
            sandbox="allow-scripts"
            class="preview-frame"
            style:display={activeTab === 'preview' ? 'block' : 'none'}
        ></iframe>
        {#if activeTab === 'code'}
            <div class="code-view">
                <button class="copy" class:copied onclick={copyCode}>
                    {copied ? 'Copied' : 'Copy'}
                </button>
                <div class="code-scroll">
                    <table class="code-table">
                        <tbody>
                            {#each lines() as line, i}
                                <tr>
                                    <td class="ln">{i + 1}</td>
                                    <td class="lc"><pre>{line}</pre></td>
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                </div>
            </div>
        {/if}
    </div>
</div>

<style>
    .preview {
        display: flex;
        flex-direction: column;
        height: 100%;
        background: var(--bubble-strong);
        backdrop-filter: var(--bubble-blur-heavy);
        -webkit-backdrop-filter: var(--bubble-blur-heavy);
    }
    .toolbar {
        height: 48px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 16px;
        border-bottom: 1px solid var(--border);
        flex-shrink: 0;
    }
    .tab-group {
        display: flex;
        background: var(--accent-subtle);
        border-radius: var(--radius-sm);
        padding: 2px;
    }
    .tab {
        font-family: var(--font-body);
        font-size: 12px;
        font-weight: 500;
        padding: 5px 16px;
        border: none;
        border-radius: 8px;
        cursor: pointer;
        background: transparent;
        color: var(--text-muted);
        transition: all var(--transition);
    }
    .tab.active {
        background: var(--surface-hover);
        color: var(--text);
        box-shadow: var(--shadow-xs);
    }
    .toolbar-actions {
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .action-btn, .close {
        display: flex;
        align-items: center;
        gap: 6px;
        height: 30px;
        padding: 0 12px 0 10px;
        border: 1px solid var(--border);
        border-radius: var(--radius-pill);
        background: var(--accent-subtle);
        color: var(--text-secondary);
        font-family: var(--font-body);
        font-size: 12px;
        font-weight: 500;
        cursor: pointer;
        transition: all var(--transition);
    }
    .action-btn:hover, .close:hover {
        background: var(--surface);
        color: var(--text);
        border-color: var(--border-strong);
    }
    .content { flex: 1; overflow: hidden; }
    .preview-frame {
        width: 100%;
        height: 100%;
        border: none;
        background: white;
    }
    .code-view {
        height: 100%;
        position: relative;
        overflow: hidden;
    }
    .copy {
        position: absolute;
        top: 12px;
        right: 14px;
        z-index: 5;
        font-family: var(--font-body);
        font-size: 12px;
        font-weight: 500;
        padding: 5px 16px;
        border: 1px solid var(--border);
        border-radius: var(--radius-pill);
        background: var(--surface);
        color: var(--text-secondary);
        cursor: pointer;
        transition: all var(--transition);
    }
    .copy:hover {
        background: var(--surface-hover);
        color: var(--text);
    }
    .copy.copied {
        border-color: var(--success);
        color: var(--success);
    }
    .code-scroll {
        height: 100%;
        overflow: auto;
        padding: 14px 0;
    }
    .code-table {
        border-collapse: collapse;
        width: 100%;
        font-family: var(--font-mono);
        font-size: 13px;
        line-height: 1.65;
    }
    .ln {
        width: 52px;
        padding: 0 14px 0 18px;
        text-align: right;
        color: var(--text-muted);
        user-select: none;
        vertical-align: top;
        font-size: 12px;
    }
    .lc {
        padding: 0 18px 0 8px;
        white-space: pre-wrap;
        word-break: break-all;
        color: var(--text);
    }
    .lc pre {
        margin: 0;
        padding: 0;
        background: none;
        border: none;
        font: inherit;
        color: inherit;
    }
</style>
