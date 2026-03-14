<script lang="ts">
    let { stats }: { stats: Record<string, any> } = $props();
</script>

<div class="stats">
    <div class="stat">
        <span class="value">{stats.total ?? 0}</span>
        <span class="label">entries</span>
    </div>
    <div class="stat">
        <span class="value">{((stats.avg_self_score ?? 0) * 100).toFixed(0)}%</span>
        <span class="label">avg score</span>
    </div>
    <div class="stat">
        <span class="value">{(stats.avg_rounds ?? 0).toFixed(1)}</span>
        <span class="label">avg rounds</span>
    </div>
</div>

<style>
    .stats { display: flex; gap: 32px; padding: 16px 20px; background: var(--surface); border-radius: var(--radius); }
    .stat { display: flex; flex-direction: column; }
    .value { font-size: 24px; font-weight: 600; letter-spacing: -0.02em; }
    .label { font-size: 12px; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em; }
</style>
