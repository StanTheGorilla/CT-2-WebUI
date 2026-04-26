<script lang="ts">
    let { code, open = false, width = 44, isStreaming = false, onClose, onWidthChange }:
        { code: string; open: boolean; width: number; isStreaming: boolean; onClose: () => void; onWidthChange: (w: number) => void } = $props();

    let activeTab = $state<'preview' | 'source'>('preview');
    let iframe = $state<HTMLIFrameElement | null>(null);
    let lastRendered = $state('');
    let copied = $state(false);
    let debounceTimer: ReturnType<typeof setTimeout>;

    // Show code while streaming; auto-switch to preview when done
    let prevStreaming = $state(false);
    $effect(() => {
        const s = isStreaming;
        if (s && !prevStreaming) activeTab = 'source';
        else if (!s && prevStreaming && code) activeTab = 'preview';
        prevStreaming = s;
    });

    function wrapPartialHtml(html: string): string {
        const t = html.trimStart().toLowerCase();
        if (t.startsWith('<!doctype') || t.startsWith('<html')) return html;
        return `<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><style>body{font-family:system-ui,sans-serif;padding:16px;color:#1a1a1a}</style></head><body>${html}</body></html>`;
    }

    $effect(() => {
        const frame = iframe;
        clearTimeout(debounceTimer);
        if (!frame || !code || activeTab !== 'preview') return;
        debounceTimer = setTimeout(() => {
            if (code !== lastRendered) {
                const navGuard = `<script>document.addEventListener('click',function(e){var a=e.target.closest('a');if(a){e.preventDefault();}});<\/script>`;
                frame.srcdoc = navGuard + wrapPartialHtml(code);
                lastRendered = code;
            }
        }, 500);
        return () => clearTimeout(debounceTimer);
    });

    async function copyCode() {
        try { await navigator.clipboard.writeText(code); copied = true; setTimeout(() => copied = false, 2000); } catch {}
    }

    function downloadCode() {
        const b = new Blob([code], { type: 'text/html' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(b); a.download = 'design.html'; a.click();
        URL.revokeObjectURL(a.href);
    }

    function openExternal() {
        const b = new Blob([wrapPartialHtml(code)], { type: 'text/html' });
        const url = URL.createObjectURL(b);
        window.open(url, '_blank');
        setTimeout(() => URL.revokeObjectURL(url), 5000);
    }

    function startResize(e: PointerEvent) {
        e.preventDefault();
        const startX = e.clientX;
        const startW = width;
        function onMove(mv: PointerEvent) {
            const newPct = Math.max(22, Math.min(68, startW + (startX - mv.clientX) / window.innerWidth * 100));
            onWidthChange(Math.round(newPct));
        }
        function onUp() {
            window.removeEventListener('pointermove', onMove);
            window.removeEventListener('pointerup', onUp);
        }
        window.addEventListener('pointermove', onMove);
        window.addEventListener('pointerup', onUp);
    }

    let lines = $derived(code ? code.split('\n') : []);
</script>

<aside class="c2-pv" class:c2-pv-open={open} style="width: {width}%">
    <!-- Invisible drag handle -->
    <button
        type="button"
        class="c2-pv-handle"
        onpointerdown={startResize}
        aria-label="Resize preview panel"
    ></button>

    <!-- Toolbar — matches handoff reference exactly -->
    <div class="c2-pv-toolbar">
        <span class="c2-pv-badge mono">HTML</span>
        <span class="c2-pv-filename mono">design.html</span>
        <div class="c2-pv-spacer"></div>

        <!-- Segment control matching primitives.jsx Segment -->
        <div class="c2-pv-segment">
            <button
                class="c2-pv-seg"
                class:c2-pv-seg-active={activeTab === 'preview'}
                onclick={() => activeTab = 'preview'}
            >Preview</button>
            <button
                class="c2-pv-seg"
                class:c2-pv-seg-active={activeTab === 'source'}
                onclick={() => activeTab = 'source'}
            >Code</button>
        </div>

        <!-- Icon buttons matching primitives.jsx IconButton size=28 -->
        <button class="c2-pv-icon" onclick={openExternal} title="Open in new tab">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6M15 3h6v6M10 14L21 3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
        </button>
        <button class="c2-pv-icon" onclick={onClose} title="Close">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
            </svg>
        </button>
    </div>

    <!-- Content area -->
    <div class="c2-pv-body">
        <!-- iframe always mounted so srcdoc is preserved when switching tabs -->
        <iframe
            bind:this={iframe}
            title="Design preview"
            sandbox="allow-scripts"
            class="c2-pv-frame"
            style:display={activeTab === 'preview' ? 'block' : 'none'}
        ></iframe>

        {#if activeTab === 'source'}
            <div class="c2-pv-code scroll">
                <div class="c2-pv-code-actions">
                    <button class="c2-pv-code-btn" onclick={copyCode}>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                            <rect x="9" y="9" width="13" height="13" rx="2" stroke="currentColor" stroke-width="1.8"/>
                            <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                        </svg>
                        {copied ? 'Copied!' : 'Copy'}
                    </button>
                    <button class="c2-pv-code-btn" onclick={downloadCode}>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                        Download
                    </button>
                </div>
                <table class="c2-pv-table">
                    <tbody>
                        {#each lines as line, i}
                            <tr>
                                <td class="c2-pv-ln">{i + 1}</td>
                                <td class="c2-pv-lc"><pre>{line}</pre></td>
                            </tr>
                        {/each}
                    </tbody>
                </table>
            </div>
        {/if}
    </div>
</aside>

<style>
    /* ── Panel shell ─────────────────────────────────────────────── */
    .c2-pv {
        position: absolute;
        top: 0; right: 0; bottom: 0;
        background: var(--c2-bg-1);
        border-left: 1px solid var(--c2-border-2);
        box-shadow: var(--c2-shadow-panel, -8px 0 40px oklch(0 0 0 / 0.40));
        display: flex;
        flex-direction: column;
        transform: translateX(106%);
        transition: transform 340ms var(--c2-spring, cubic-bezier(.22,1.2,.36,1));
        z-index: 20;
        will-change: transform;
    }
    :global([data-theme="light"]) .c2-pv {
        box-shadow: -4px 0 24px oklch(0 0 0 / 0.10);
    }
    .c2-pv.c2-pv-open {
        transform: translateX(0);
    }

    /* ── Drag handle (invisible hit area) ────────────────────────── */
    .c2-pv-handle {
        position: absolute;
        left: -4px; top: 0; bottom: 0;
        width: 8px;
        padding: 0;
        border: none;
        background: transparent;
        cursor: col-resize;
        z-index: 2;
    }

    /* ── Toolbar — matches handoff reference ─────────────────────── */
    .c2-pv-toolbar {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 10px 14px;
        border-bottom: 1px solid var(--c2-border-1);
        flex-shrink: 0;
    }

    /* Badge — matches primitives.jsx Badge tone="orange" */
    .c2-pv-badge {
        display: inline-flex;
        align-items: center;
        height: 20px;
        padding: 0 7px;
        font-size: 10.5px;
        font-weight: 500;
        letter-spacing: 0.3px;
        text-transform: uppercase;
        background: oklch(0.35 0.08 55 / 0.28);
        color: var(--c2-accent);
        border: 1px solid oklch(0.5 0.1 55 / 0.4);
        border-radius: 4px;
        flex-shrink: 0;
    }

    .c2-pv-filename {
        font-size: 12.5px;
        color: var(--c2-fg-0);
    }

    .c2-pv-spacer { flex: 1; }

    /* Segment — matches primitives.jsx Segment */
    .c2-pv-segment {
        display: inline-flex;
        padding: 3px;
        border-radius: 10px;
        background: var(--c2-bg-2);
        border: 1px solid var(--c2-border-1);
        gap: 2px;
        flex-shrink: 0;
    }
    .c2-pv-seg {
        height: 28px;
        padding: 0 12px;
        border-radius: 7px;
        font-size: 12px;
        font-weight: 500;
        font-family: 'Geist', ui-sans-serif, system-ui, sans-serif;
        color: var(--c2-fg-2);
        background: transparent;
        border: 1px solid transparent;
        cursor: pointer;
        transition: all 120ms;
    }
    .c2-pv-seg:hover:not(.c2-pv-seg-active) { color: var(--c2-fg-1); }
    .c2-pv-seg-active {
        color: var(--c2-fg-0);
        background: var(--c2-bg-0);
        border-color: var(--c2-border-2);
        box-shadow: 0 1px 0 var(--c2-border-2) inset;
    }

    /* Icon buttons — matches primitives.jsx IconButton size=28 */
    .c2-pv-icon {
        width: 28px;
        height: 28px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 8px;
        background: transparent;
        color: var(--c2-fg-1);
        border: 1px solid transparent;
        cursor: pointer;
        transition: background 120ms, color 120ms, border-color 120ms;
        flex-shrink: 0;
    }
    .c2-pv-icon:hover {
        background: var(--c2-bg-2);
        color: var(--c2-fg-0);
    }

    /* ── Content area ────────────────────────────────────────────── */
    .c2-pv-body {
        flex: 1;
        background: var(--c2-bg-0);
        position: relative;
        overflow: hidden;
    }

    .c2-pv-frame {
        width: 100%;
        height: 100%;
        border: none;
        background: white;
        display: block;
    }

    /* ── Code view ───────────────────────────────────────────────── */
    .c2-pv-code {
        height: 100%;
        overflow: auto;
        scrollbar-width: thin;
        scrollbar-color: var(--c2-border-2) transparent;
        padding: 10px 0;
        position: relative;
    }
    .c2-pv-code-actions {
        position: absolute;
        top: 10px;
        right: 14px;
        display: flex;
        gap: 6px;
        z-index: 5;
    }
    .c2-pv-code-btn {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        height: 26px;
        padding: 0 10px;
        border-radius: 7px;
        font-size: 11.5px;
        font-weight: 500;
        font-family: 'Geist', ui-sans-serif, system-ui, sans-serif;
        color: var(--c2-fg-2);
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-2);
        cursor: pointer;
        transition: background 120ms, color 120ms;
    }
    .c2-pv-code-btn:hover { background: var(--c2-bg-2); color: var(--c2-fg-0); }

    .c2-pv-table {
        border-collapse: collapse;
        width: 100%;
        font-family: 'Geist Mono', monospace;
        font-size: 12px;
        line-height: 1.65;
    }
    .c2-pv-ln {
        width: 48px;
        padding: 0 12px 0 16px;
        text-align: right;
        color: var(--c2-fg-3);
        user-select: none;
        vertical-align: top;
        font-size: 11px;
    }
    .c2-pv-lc {
        padding: 0 80px 0 8px;
        white-space: pre-wrap;
        word-break: break-all;
        color: var(--c2-fg-1);
    }
    .c2-pv-lc pre {
        margin: 0; padding: 0;
        background: none; border: none;
        font: inherit; color: inherit;
    }
</style>
