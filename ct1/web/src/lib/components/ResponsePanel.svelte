<script lang="ts">
    import { render } from '$lib/markdown';
    let { response, thinking = '', label = 'CT-2' }: { response: string; thinking?: string; label?: string } = $props();

    let showThinking = $state(false);
</script>

<div class="response">
    <div class="response-bar">
        <div class="bar-indicator"></div>
        <span class="bar-label">{label}</span>
        {#if thinking}
            <button class="thinking-btn" onclick={() => showThinking = !showThinking}>
                {showThinking ? 'Hide' : 'Show'} thinking
            </button>
        {/if}
    </div>

    {#if showThinking && thinking}
        <div class="thinking">{@html render(thinking)}</div>
    {/if}

    <div class="body">{@html render(response)}</div>
</div>

<style>
    .response {
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border-radius: var(--radius);
        border: var(--bubble-border);
        box-shadow: var(--bubble-glow);
        overflow: hidden;
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
    }
    .response-bar {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 12px 18px;
        border-bottom: 1px solid var(--border);
    }
    .bar-indicator {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: var(--brain);
        box-shadow: 0 0 6px rgba(232, 133, 12, 0.3);
    }
    .bar-label {
        color: var(--brain);
        font-size: 13px;
        font-weight: 600;
        letter-spacing: -0.01em;
    }
    .thinking-btn {
        margin-left: auto;
        background: var(--accent-subtle);
        border: 1px solid var(--border);
        border-radius: var(--radius-sm);
        color: var(--text-secondary);
        font-family: var(--font-body);
        font-size: 12px;
        font-weight: 500;
        padding: 4px 12px;
        cursor: pointer;
        transition: all var(--transition);
    }
    .thinking-btn:hover {
        color: var(--text);
        background: var(--surface);
    }
    .thinking {
        padding: 14px 18px;
        background: var(--accent-subtle);
        border-bottom: 1px solid var(--border);
        color: var(--text-secondary);
        font-size: 14px;
        line-height: 1.65;
        font-style: italic;
    }
    .thinking :global(p) { margin-bottom: 8px; }
    .thinking :global(p:last-child) { margin-bottom: 0; }
    .body {
        padding: 18px;
        color: var(--text);
        font-size: 15px;
        line-height: 1.7;
    }
    .body :global(pre) { position: relative; margin: 14px 0; }
    .body :global(code) { font-size: 13px; }
    .body :global(p) { margin-bottom: 12px; }
    .body :global(p:last-child) { margin-bottom: 0; }
    .body :global(h1),
    .body :global(h2),
    .body :global(h3) { margin: 20px 0 8px; }
    .body :global(ul),
    .body :global(ol) { padding-left: 22px; margin-bottom: 12px; }
    .body :global(table) {
        width: 100%;
        border-collapse: collapse;
        margin: 12px 0;
        font-size: 14px;
        display: block;
        overflow-x: auto;
    }
    .body :global(thead) { display: table; width: 100%; table-layout: fixed; }
    .body :global(tbody) { display: table; width: 100%; table-layout: fixed; }
    .body :global(th),
    .body :global(td) {
        padding: 8px 12px;
        border: 1px solid var(--border);
        text-align: left;
        word-wrap: break-word;
        overflow-wrap: break-word;
    }
    .body :global(th) {
        background: var(--surface-hover);
        font-weight: 600;
    }
</style>
