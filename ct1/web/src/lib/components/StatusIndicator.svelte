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
    .indicator { display: flex; align-items: center; gap: 10px; padding: 12px 20px; background: var(--surface); border-radius: var(--radius); }
    .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--error); }
    .dot.alive { background: var(--success); }
    .label { font-weight: 600; font-size: 14px; }
    .url { color: var(--text-secondary); font-size: 13px; font-family: var(--font-mono); }
</style>
