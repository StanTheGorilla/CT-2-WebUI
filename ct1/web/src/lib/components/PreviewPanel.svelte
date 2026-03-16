<script lang="ts">
    import hljs from 'highlight.js/lib/core';
    import xml from 'highlight.js/lib/languages/xml';
    import css from 'highlight.js/lib/languages/css';
    import javascript from 'highlight.js/lib/languages/javascript';

    hljs.registerLanguage('xml', xml);
    hljs.registerLanguage('css', css);
    hljs.registerLanguage('javascript', javascript);

    let { code, onClose }:
        { code: string; onClose: () => void } = $props();

    let activeTab = $state<'preview' | 'code'>('preview');
    let copied = $state(false);
    let iframe = $state<HTMLIFrameElement>();

    let highlighted = $derived(() => {
        if (!code) return '';
        try {
            return hljs.highlight(code, { language: 'xml' }).value;
        } catch {
            return code.replace(/</g, '&lt;').replace(/>/g, '&gt;');
        }
    });

    let lines = $derived(() => {
        return code ? code.split('\n') : [];
    });

    async function copyCode() {
        await navigator.clipboard.writeText(code);
        copied = true;
        setTimeout(() => { copied = false; }, 2000);
    }

    $effect(() => {
        if (iframe && code && activeTab === 'preview') {
            // Inject script to prevent link navigation inside the preview
            const navGuard = `<script>document.addEventListener('click',function(e){var a=e.target.closest('a');if(a){e.preventDefault();}});<\/script>`;
            iframe.srcdoc = navGuard + code;
        }
    });
</script>

<div class="preview">
    <div class="toolbar">
        <div class="tab-group">
            <button
                class="tab"
                class:active={activeTab === 'preview'}
                onclick={() => activeTab = 'preview'}
            >Preview</button>
            <button
                class="tab"
                class:active={activeTab === 'code'}
                onclick={() => activeTab = 'code'}
            >Code</button>
        </div>
        <button class="close" onclick={onClose} aria-label="Close preview">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
        </button>
    </div>

    <div class="content">
        {#if activeTab === 'preview'}
            <iframe
                bind:this={iframe}
                title="Preview"
                sandbox="allow-scripts"
                class="preview-frame"
            ></iframe>
        {:else}
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
        border-bottom: 1px solid rgba(255, 255, 255, 0.5);
        flex-shrink: 0;
    }
    .tab-group {
        display: flex;
        background: rgba(0, 0, 0, 0.04);
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
        background: rgba(255, 255, 255, 0.8);
        color: var(--text);
        box-shadow: var(--shadow-xs);
    }
    .close {
        width: 30px;
        height: 30px;
        border: none;
        border-radius: var(--radius-sm);
        background: transparent;
        color: var(--text-muted);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all var(--transition);
    }
    .close:hover {
        background: rgba(0, 0, 0, 0.04);
        color: var(--text);
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
        border: 1px solid rgba(255, 255, 255, 0.6);
        border-radius: var(--radius-pill);
        background: rgba(255, 255, 255, 0.7);
        color: var(--text-secondary);
        cursor: pointer;
        transition: all var(--transition);
    }
    .copy:hover {
        background: rgba(255, 255, 255, 0.9);
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
