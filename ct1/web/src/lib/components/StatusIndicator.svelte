<script lang="ts">
    let { label, status }: { label: string; status: Record<string, any> } = $props();
    let alive = $derived(status?.alive ?? false);
</script>

<div class="indicator">
    <span class="dot" class:alive></span>
    <span class="label">{label}</span>
    <span class="url">{status?.url ?? 'unknown'}</span>
</div>

<style>
    .indicator {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 14px 20px;
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: var(--radius);
        box-shadow: var(--bubble-glow);
    }
    .dot {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: var(--error);
        flex-shrink: 0;
    }
    .dot.alive {
        background: var(--success);
        box-shadow: 0 0 6px rgba(45, 164, 78, 0.3);
    }
    .label { font-weight: 600; font-size: 14px; color: var(--text); }
    .url { color: var(--text-muted); font-size: 13px; font-family: var(--font-mono); }
</style>
