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
    .stats {
        display: flex;
        gap: 32px;
        padding: 18px 24px;
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: var(--radius);
        box-shadow: var(--bubble-glow);
    }
    .stat { display: flex; flex-direction: column; }
    .value {
        font-size: 24px;
        font-weight: 600;
        letter-spacing: -0.02em;
        color: var(--text);
    }
    .label {
        font-size: 11px;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.06em;
        font-weight: 500;
    }
</style>
