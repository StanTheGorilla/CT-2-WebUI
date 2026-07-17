<script lang="ts">
    import { compactPreviewText, CONTEXT_SUMMARY_NOTE } from '$lib/chatUi';

    type Variant = 'classic' | 'ct2';

    let {
        summary,
        open,
        onToggle,
        variant = 'classic',
        note = CONTEXT_SUMMARY_NOTE,
    }: {
        summary: string;
        open: boolean;
        onToggle: () => void;
        variant?: Variant;
        note?: string;
    } = $props();

    let preview = $derived(compactPreviewText(summary));
    let visibilityLabel = $derived(open ? 'full summary visible below' : 'preview visible below');
</script>

<div class="context-summary" class:classic={variant === 'classic'} class:ct2={variant === 'ct2'}>
    <button class="context-summary__header" onclick={onToggle}>
        <div class="context-summary__title-row">
            <span class="context-summary__icon" aria-hidden="true">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                    <path d="M6 9l6-6 6 6M6 15l6 6 6-6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
            </span>
            <span class="context-summary__title">Context Summary</span>
        </div>
        <div class="context-summary__meta">
            <span>{visibilityLabel}</span>
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" class="context-summary__chevron" class:open={open}>
                <path d="M9 18l6-6-6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
        </div>
    </button>

    <div class="context-summary__note">{note}</div>

    {#if open}
        <pre class="context-summary__body">{summary}</pre>
    {:else}
        <pre class="context-summary__preview">{preview}</pre>
    {/if}
</div>

<style>
    .context-summary {
        overflow: hidden;
    }

    .context-summary.classic {
        background: var(--surface);
        border: 1px solid var(--border);
        border-left: 2px solid var(--brain);
        border-radius: 14px;
        box-shadow: var(--bubble-glow);
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
        max-width: min(760px, 92%);
    }

    .context-summary.ct2 {
        align-self: stretch;
        max-width: 820px;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-1);
        border-radius: 8px;
    }

    .context-summary__header {
        width: 100%;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 14px;
        padding: 12px 16px;
        background: transparent;
        border: none;
        color: inherit;
        cursor: pointer;
        font-family: inherit;
        text-align: left;
    }

    .context-summary.ct2 .context-summary__header {
        gap: 10px;
        padding: 8px 12px;
        color: var(--c2-fg-2);
        font-size: 12px;
        font-family: 'Geist', ui-sans-serif, system-ui, sans-serif;
        transition: background 120ms;
    }

    .context-summary.ct2 .context-summary__header:hover {
        background: var(--c2-bg-2);
    }

    .context-summary__title-row {
        display: inline-flex;
        align-items: center;
        gap: 10px;
        min-width: 0;
    }

    .context-summary__title {
        font-size: 12.5px;
        font-weight: 600;
        color: var(--text-secondary);
        letter-spacing: 0.03em;
        text-transform: uppercase;
    }

    .context-summary.ct2 .context-summary__title {
        font-size: 12px;
        font-weight: 500;
        letter-spacing: 0.02em;
        text-transform: none;
        color: var(--c2-fg-1);
    }

    .context-summary__icon {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 22px;
        height: 22px;
        border-radius: 999px;
        background: rgba(232, 133, 12, 0.10);
        color: var(--brain);
        flex-shrink: 0;
    }

    .context-summary.ct2 .context-summary__icon {
        width: 18px;
        height: 18px;
        background: color-mix(in srgb, var(--c2-accent) 10%, transparent);
        color: var(--c2-accent);
    }

    .context-summary__meta {
        display: inline-flex;
        align-items: center;
        gap: 10px;
        color: var(--text-muted);
        font-size: 11.5px;
        flex-shrink: 0;
    }

    .context-summary.ct2 .context-summary__meta {
        color: var(--c2-fg-3);
        font-size: 11px;
        margin-left: auto;
    }

    .context-summary__chevron {
        transition: transform 0.18s ease;
        flex-shrink: 0;
    }

    .context-summary__chevron.open {
        transform: rotate(90deg);
    }

    .context-summary__note {
        padding: 0 16px 8px;
        color: var(--text-secondary);
        font-size: 12px;
        line-height: 1.5;
    }

    .context-summary.ct2 .context-summary__note {
        padding: 0 14px 8px;
        color: var(--c2-fg-2);
    }

    .context-summary__preview,
    .context-summary__body {
        margin: 0;
        padding: 0 16px 16px;
        font-family: var(--font-mono);
        font-size: 11.5px;
        line-height: 1.65;
        color: var(--text-muted);
        white-space: pre-wrap;
        word-break: break-word;
        background: none;
        border: none;
        border-radius: 0;
        box-shadow: none;
    }

    .context-summary.ct2 .context-summary__preview,
    .context-summary.ct2 .context-summary__body {
        padding: 10px 14px 14px;
        font-family: 'Geist Mono', monospace;
        color: var(--c2-fg-1);
        border-top: 1px solid var(--c2-border-1);
    }

    .context-summary__preview {
        color: var(--text-secondary);
        max-height: 9.5em;
        overflow: hidden;
    }

    .context-summary.ct2 .context-summary__preview {
        color: var(--c2-fg-2);
    }

    .context-summary__body {
        max-height: 260px;
        overflow-y: auto;
    }

    .context-summary.ct2 .context-summary__body {
        scrollbar-width: thin;
        scrollbar-color: var(--c2-border-2) transparent;
    }
</style>
