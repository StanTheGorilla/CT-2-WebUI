<script lang="ts">
    import { render } from '$lib/markdown';
    let { response }: { response: string } = $props();
</script>

<div class="response">
    <div class="response-header">
        <span class="dot"></span>
        <span class="label">CT-1</span>
    </div>
    <div class="response-body">{@html render(response)}</div>
</div>

<style>
    .response { background: var(--surface); border-radius: var(--radius); overflow: hidden; }
    .response-header {
        display: flex; align-items: center; gap: 8px;
        padding: 12px 20px; border-bottom: 1px solid var(--border);
    }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--brain); }
    .label { color: var(--brain); font-size: 13px; font-weight: 600; }
    .response-body { padding: 20px; color: var(--text); font-size: 15px; line-height: 1.7; }
    .response-body :global(pre) { position: relative; margin: 16px 0; }
    .response-body :global(code) { font-size: 13px; }
    .response-body :global(p) { margin-bottom: 12px; }
    .response-body :global(h1), .response-body :global(h2), .response-body :global(h3) { margin: 20px 0 8px; }
    .response-body :global(ul), .response-body :global(ol) { padding-left: 20px; margin-bottom: 12px; }
</style>
