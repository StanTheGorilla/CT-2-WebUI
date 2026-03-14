<script lang="ts">
    import type { Reflection } from '$lib/stores/chat';
    let { reflection }: { reflection: Reflection } = $props();

    let expanded = $state(false);
    let score = $derived(reflection.self_score ?? 0.5);
    let scoreColor = $derived(score >= 0.7 ? 'var(--success)' : score >= 0.4 ? 'var(--warning)' : 'var(--error)');
</script>

<button class="bar" onclick={() => expanded = !expanded}>
    <div class="metrics">
        <span class="metric"><span class="score-dot" style="background: {scoreColor}"></span> {(score * 100).toFixed(0)}%</span>
        <span class="sep"></span>
        <span class="metric">{reflection.rounds ?? '?'} rounds</span>
    </div>
    <span class="expand">{expanded ? '\u2212' : '+'}</span>
</button>

{#if expanded && reflection.lesson}
    <div class="detail">
        <span class="lesson-label">Lesson:</span> {reflection.lesson}
    </div>
{/if}

<style>
    .bar {
        display: flex; align-items: center; justify-content: space-between; width: 100%;
        background: var(--surface); border: none; border-radius: var(--radius);
        padding: 10px 20px; cursor: pointer; transition: background var(--transition);
    }
    .bar:hover { background: var(--surface-hover); }
    .metrics { display: flex; align-items: center; gap: 12px; }
    .metric { color: var(--text-secondary); font-family: var(--font-body); font-size: 13px; display: flex; align-items: center; gap: 6px; }
    .score-dot { width: 8px; height: 8px; border-radius: 50%; }
    .sep { width: 1px; height: 14px; background: var(--border); }
    .expand { color: var(--text-muted); font-size: 16px; }
    .detail {
        background: var(--surface); border-radius: 0 0 var(--radius) var(--radius);
        padding: 12px 20px; margin-top: -12px; font-size: 14px; color: var(--text-secondary);
    }
    .lesson-label { color: var(--text-muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; }
</style>
