<script lang="ts">
    import { render } from '$lib/markdown';
    let { name, text }: { name: string; text: string } = $props();

    const colors: Record<string, string> = {
        alpha: 'var(--mind-alpha)',
        beta: 'var(--mind-beta)',
        gamma: 'var(--mind-gamma)',
    };
    const labels: Record<string, string> = {
        alpha: '\u03B1',
        beta: '\u03B2',
        gamma: '\u03B3',
    };
</script>

<div class="turn" style="--mind-color: {colors[name] || 'var(--text-secondary)'}">
    <div class="header">
        <span class="dot"></span>
        <span class="name">{labels[name] || name} {name}</span>
    </div>
    <div class="body">{@html render(text)}</div>
</div>

<style>
    .turn {
        border-left: 2px solid var(--mind-color);
        padding: 0 0 0 16px;
        animation: fadeSlideIn 300ms ease;
    }
    .header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--mind-color); }
    .name { color: var(--mind-color); font-size: 13px; font-weight: 600; }
    .body { color: var(--text); font-size: 14px; line-height: 1.6; }
    .body :global(p) { margin-bottom: 8px; }
    .body :global(p:last-child) { margin-bottom: 0; }
    @keyframes fadeSlideIn {
        from { opacity: 0; transform: translateY(8px); }
        to { opacity: 1; transform: translateY(0); }
    }
</style>
