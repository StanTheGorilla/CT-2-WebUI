<script lang="ts">
    import { onMount } from 'svelte';

    interface PlanEntry {
        sig: string;
        task_type: string;
        complexity: string;
        score: number;
        count: number;
        created_at: string | null;
    }

    let entries = $state<PlanEntry[]>([]);
    let totalEntries = $state(0);
    let avgScore = $state(0);
    let loading = $state(true);

    onMount(async () => {
        try {
            const res = await fetch('/api/journal?limit=100');
            const data = await res.json();
            entries = data.entries ?? [];
            totalEntries = data.stats?.total ?? 0;
            avgScore = data.stats?.avg_score ?? 0;
        } finally {
            loading = false;
        }
    });

    function scoreTone(s: number) {
        return s >= 0.8 ? 'var(--c2-ok)' : s >= 0.5 ? 'var(--c2-warn)' : 'var(--c2-err)';
    }

    function taskLabel(t: string) {
        return t.charAt(0).toUpperCase() + t.slice(1);
    }

    function sigDisplay(sig: string) {
        return sig.includes('#') ? sig.split('#')[0] : sig;
    }

    function complexityColor(c: string) {
        if (c === 'deep') return 'oklch(0.55 0.08 300 / 0.28)';
        if (c === 'moderate') return 'oklch(0.50 0.08 240 / 0.28)';
        return 'oklch(0.55 0.06 150 / 0.28)';
    }
</script>

<div class="c2-journal">
    <div class="c2-journal-inner">
        <div class="c2-journal-hero">
            <div class="c2-journal-eyebrow">Plan Cache</div>
            <h1 class="c2-journal-heading">
                Patterns <em class="c2-journal-em">learned.</em>
            </h1>
            <p class="c2-journal-sub">
                CT-2 builds an execution plan for each new type of task.
                When it sees a matching pattern, it skips deliberation and goes
                straight to generation — making repeated task types 3–5× faster.
            </p>
            {#if totalEntries > 0}
                <div class="c2-stats-row">
                    <div class="c2-stat">
                        <span class="c2-stat-num">{totalEntries}</span>
                        <span class="c2-stat-label">patterns cached</span>
                    </div>
                    <div class="c2-stat">
                        <span class="c2-stat-num">{(avgScore * 100).toFixed(0)}%</span>
                        <span class="c2-stat-label">avg confidence</span>
                    </div>
                </div>
            {/if}
        </div>

        {#if loading}
            <div class="c2-journal-loading">Loading…</div>
        {:else if entries.length === 0}
            <div class="c2-journal-loading">No cached plans yet. Use CT-2 a few times and patterns will appear here.</div>
        {:else}
            <div class="c2-journal-list">
                {#each entries as entry, i}
                    <article class="c2-journal-entry" class:c2-entry-first={i === 0}>
                        <div class="c2-entry-meta">
                            <span class="c2-score-pill" style="--dot: {scoreTone(entry.score ?? 0.5)}">
                                <span class="c2-score-dot"></span>
                                {((entry.score ?? 0.5) * 100).toFixed(0)}%
                            </span>
                            <span
                                class="c2-mode-badge"
                                style="background:{complexityColor(entry.complexity)}; border:1px solid oklch(0.5 0.1 240 / 0.3);"
                            >{entry.complexity}</span>
                            <span class="c2-mode-badge" style="background:var(--c2-bg-2); border:1px solid var(--c2-border-2);">{taskLabel(entry.task_type)}</span>
                            {#if entry.count > 1}
                                <span class="c2-entry-time">×{entry.count}</span>
                            {/if}
                        </div>
                        <p class="c2-entry-text">{sigDisplay(entry.sig)}</p>
                    </article>
                {/each}
            </div>
        {/if}
    </div>
</div>

<style>
    .c2-journal {
        position: absolute;
        inset: 0;
        overflow-y: auto;
        scrollbar-width: thin;
        scrollbar-color: var(--c2-border-2) transparent;
        font-family: 'Geist', ui-sans-serif, system-ui, sans-serif;
        color: var(--c2-fg-0);
    }
    .c2-journal-inner {
        max-width: 680px;
        margin: 0 auto;
        padding: 48px 32px 80px;
    }

    .c2-journal-hero {
        margin-bottom: 40px;
    }
    .c2-journal-eyebrow {
        font-family: 'Geist Mono', monospace;
        font-size: 11px;
        color: var(--c2-fg-3);
        letter-spacing: 0.6px;
        text-transform: uppercase;
        margin-bottom: 8px;
    }
    .c2-journal-heading {
        font-family: 'Instrument Serif', 'Cormorant Garamond', Georgia, serif;
        font-size: 56px;
        font-weight: 400;
        letter-spacing: -1.2px;
        margin: 0;
        line-height: 1;
        color: var(--c2-fg-0);
    }
    .c2-journal-em {
        color: var(--c2-fg-2);
        font-style: italic;
    }
    .c2-journal-sub {
        font-size: 15px;
        color: var(--c2-fg-2);
        margin: 14px 0 0;
        line-height: 1.6;
        max-width: 520px;
    }

    .c2-stats-row {
        display: flex;
        gap: 24px;
        margin-top: 24px;
    }
    .c2-stat {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }
    .c2-stat-num {
        font-family: 'Geist Mono', monospace;
        font-size: 28px;
        font-weight: 500;
        color: var(--c2-fg-0);
        letter-spacing: -0.5px;
    }
    .c2-stat-label {
        font-family: 'Geist Mono', monospace;
        font-size: 10.5px;
        color: var(--c2-fg-3);
        letter-spacing: 0.3px;
        text-transform: uppercase;
    }

    .c2-journal-loading {
        color: var(--c2-fg-3);
        text-align: center;
        padding: 48px;
        font-size: 14px;
    }

    .c2-journal-list {
        display: flex;
        flex-direction: column;
        gap: 0;
    }
    .c2-journal-entry {
        padding: 24px 0;
        border-bottom: 1px solid var(--c2-border-1);
    }
    .c2-entry-first {
        border-top: 1px solid var(--c2-border-1);
    }

    .c2-entry-meta {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 10px;
    }
    .c2-score-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        height: 22px;
        padding: 0 8px;
        border-radius: 999px;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-1);
        font-family: 'Geist Mono', monospace;
        font-size: 11px;
        color: var(--c2-fg-1);
    }
    .c2-score-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: var(--dot);
        flex-shrink: 0;
    }
    .c2-mode-badge {
        font-family: 'Geist Mono', monospace;
        display: inline-flex;
        align-items: center;
        height: 20px;
        padding: 0 7px;
        border-radius: 4px;
        font-size: 10.5px;
        font-weight: 500;
        letter-spacing: 0.3px;
        text-transform: uppercase;
        color: var(--c2-fg-1);
    }
    .c2-entry-time {
        font-family: 'Geist Mono', monospace;
        font-size: 11.5px;
        color: var(--c2-fg-3);
    }
    .c2-entry-text {
        font-family: 'Geist Mono', monospace;
        font-size: 13.5px;
        line-height: 1.7;
        color: var(--c2-fg-0);
        margin: 0;
        text-wrap: pretty;
        word-break: break-all;
    }
</style>
