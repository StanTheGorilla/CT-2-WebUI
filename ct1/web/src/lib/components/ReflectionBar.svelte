<script lang="ts">
    import type { Reflection } from '$lib/stores/chat';
    let { reflection }: { reflection: Reflection } = $props();

    let expanded = $state(false);
    let score = $derived(reflection.self_score ?? 0.5);
    let scoreColor = $derived(score >= 0.7 ? 'var(--success)' : score >= 0.4 ? 'var(--warning)' : 'var(--error)');
</script>

<div class="island">
    <button class="bar" onclick={() => expanded = !expanded}>
        <div class="score-group">
            <span class="score-dot" style="background: {scoreColor}; box-shadow: 0 0 6px {scoreColor}40"></span>
            <span class="score-text">{(score * 100).toFixed(0)}%</span>
            <span class="bar-label">Reflection</span>
        </div>
        <span class="chevron" class:open={expanded}>›</span>
    </button>

    {#if expanded && reflection.lesson}
        <div class="detail">
            <span class="detail-label">Lesson</span>
            <p>{reflection.lesson}</p>
        </div>
    {/if}
</div>

<style>
    .island {
        flex: 1;
        min-width: 0;
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: var(--radius);
        overflow: hidden;
        box-shadow: var(--bubble-glow);
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
    }
    .bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        width: 100%;
        background: transparent;
        padding: 10px 18px;
        cursor: pointer;
        transition: background var(--transition);
        font-family: var(--font-body);
        border: none;
    }
    .bar:hover { background: var(--accent-subtle); }
    .score-group { display: flex; align-items: center; gap: 10px; }
    .score-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
    .score-text {
        color: var(--text-secondary);
        font-size: 14px;
        font-weight: 600;
        font-variant-numeric: tabular-nums;
    }
    .bar-label {
        font-size: 11px;
        font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .chevron {
        color: var(--text-muted);
        font-size: 16px;
        font-weight: 300;
        transition: transform var(--transition);
        display: inline-block;
    }
    .chevron.open { transform: rotate(90deg); }
    .detail {
        border-top: 1px solid var(--border);
        padding: 12px 18px 14px;
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
