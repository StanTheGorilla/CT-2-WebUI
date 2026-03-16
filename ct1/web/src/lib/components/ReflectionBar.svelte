<script lang="ts">
    import type { Reflection } from '$lib/stores/chat';
    let { reflection }: { reflection: Reflection } = $props();

    let expanded = $state(false);
    let score = $derived(reflection.self_score ?? 0.5);
    let scoreColor = $derived(score >= 0.7 ? 'var(--success)' : score >= 0.4 ? 'var(--warning)' : 'var(--error)');
</script>

<button class="bar" onclick={() => expanded = !expanded}>
    <div class="score-group">
        <span class="score-dot" style="background: {scoreColor}; box-shadow: 0 0 6px {scoreColor}"></span>
        <span class="score-text">{(score * 100).toFixed(0)}%</span>
    </div>
    <span class="expand-icon">{expanded ? '\u2212' : '+'}</span>
</button>

{#if expanded && reflection.lesson}
    <div class="detail">
        <span class="detail-label">Lesson</span>
        <p>{reflection.lesson}</p>
    </div>
{/if}

<style>
    .bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        width: 100%;
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: var(--radius);
        padding: 10px 18px;
        cursor: pointer;
        transition: background var(--transition);
        font-family: var(--font-body);
        box-shadow: var(--bubble-glow);
    }
    .bar:hover { background: var(--surface-hover); }
    .score-group { display: flex; align-items: center; gap: 10px; }
    .score-dot { width: 8px; height: 8px; border-radius: 50%; }
    .score-text {
        color: var(--text-secondary);
        font-size: 14px;
        font-weight: 600;
        font-variant-numeric: tabular-nums;
    }
    .expand-icon { color: var(--text-muted); font-size: 18px; font-weight: 300; }
    .detail {
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-top: none;
        border-radius: 0 0 var(--radius) var(--radius);
        padding: 14px 18px;
        margin-top: -14px;
        font-size: 14px;
        color: var(--text-secondary);
        line-height: 1.6;
    }
    .detail-label {
        display: block;
        color: var(--text-muted);
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin-bottom: 6px;
    }
    .detail p { margin: 0; }
</style>
