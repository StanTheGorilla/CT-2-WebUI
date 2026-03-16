<script lang="ts">
    import { render } from '$lib/markdown';
    let { entry }: { entry: Record<string, any> } = $props();
    let expanded = $state(false);

    let score = $derived(entry.self_score ?? 0.5);
    let scoreColor = $derived(score >= 0.7 ? 'var(--success)' : score >= 0.4 ? 'var(--warning)' : 'var(--error)');
</script>

<button class="entry" onclick={() => expanded = !expanded}>
    <div class="entry-row">
        <span class="goal">{entry.goal ?? 'Unknown'}</span>
        <div class="meta">
            <span class="score" style="color: {scoreColor}">{(score * 100).toFixed(0)}%</span>
            <span class="rounds">{entry.rounds ?? '?'}r</span>
            <span class="complexity">{entry.complexity ?? ''}</span>
        </div>
    </div>
</button>

{#if expanded}
    <div class="detail">
        {#if entry.lesson && entry.lesson !== 'reflection parse failed'}
            <div class="section">
                <span class="section-label">Lesson</span>
                <p>{entry.lesson}</p>
            </div>
        {/if}
        {#if entry.outcome}
            <div class="section">
                <span class="section-label">Outcome</span>
                <div class="outcome">{@html render(entry.outcome)}</div>
            </div>
        {/if}
    </div>
{/if}

<style>
    .entry {
        display: block;
        width: 100%;
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: var(--radius);
        padding: 14px 20px;
        cursor: pointer;
        text-align: left;
        transition: background var(--transition);
        box-shadow: var(--bubble-glow);
        font-family: var(--font-body);
    }
    .entry:hover { background: var(--surface-hover); }
    .entry-row { display: flex; justify-content: space-between; align-items: center; }
    .goal {
        color: var(--text);
        font-size: 14px;
        flex: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        margin-right: 16px;
    }
    .meta { display: flex; gap: 12px; font-size: 13px; flex-shrink: 0; }
    .score { font-weight: 600; font-variant-numeric: tabular-nums; }
    .rounds { color: var(--text-secondary); }
    .complexity { color: var(--text-muted); }
    .detail {
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-top: none;
        border-radius: 0 0 var(--radius) var(--radius);
        padding: 0 20px 16px;
        margin-top: -8px;
    }
    .section { margin-top: 12px; }
    .section-label {
        color: var(--text-muted);
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .section p, .outcome { color: var(--text-secondary); font-size: 14px; margin-top: 4px; line-height: 1.6; }
</style>
