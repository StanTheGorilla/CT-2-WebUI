<script lang="ts">
    import { onMount } from 'svelte';

    let entries = $state<Record<string, any>[]>([]);
    let stats = $state<Record<string, any>>({});
    let loading = $state(true);

    onMount(async () => {
        try {
            const res = await fetch('/api/journal?limit=100');
            const data = await res.json();
            entries = data.entries ?? [];
            stats = data.stats ?? {};
        } finally {
            loading = false;
        }
    });

    function scoreTone(s: number) {
        return s >= 70 ? 'var(--c2-ok)' : s >= 40 ? 'var(--c2-warn)' : 'var(--c2-err)';
    }

    const modeColors: Record<string, string> = {
        Design: 'oklch(0.55 0.08 300 / 0.28)',
        Code: 'oklch(0.50 0.08 240 / 0.28)',
        Chat: 'oklch(0.55 0.06 150 / 0.28)',
        Computer: 'oklch(0.55 0.08 55 / 0.28)',
    };
    const modeFgColors: Record<string, string> = {
        Design: 'var(--c2-fg-1)',
        Code: 'oklch(0.72 0.005 90)',
        Chat: 'var(--c2-ok)',
        Computer: 'var(--c2-accent)',
    };

    function fmtTime(isoStr: string) {
        if (!isoStr) return '';
        const d = new Date(isoStr);
        const now = new Date();
        const today = now.toDateString();
        const yesterday = new Date(now.getTime() - 86400000).toDateString();
        const ds = d.toDateString();
        const time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
        if (ds === today) return `Today · ${time}`;
        if (ds === yesterday) return 'Yesterday';
        return ds;
    }
</script>

<div class="c2-journal">
    <div class="c2-journal-inner">
        <div class="c2-journal-hero">
            <div class="c2-journal-eyebrow">Journal</div>
            <h1 class="c2-journal-heading">
                Lessons <em class="c2-journal-em">recorded.</em>
            </h1>
            <p class="c2-journal-sub">
                After each response, CT-2 reflects on what worked and what didn't.
                These are the lessons it keeps, written in its own voice,
                and re-read before the next generation.
            </p>
        </div>

        {#if loading}
            <div class="c2-journal-loading">Loading…</div>
        {:else if entries.length === 0}
            <div class="c2-journal-loading">No journal entries yet.</div>
        {:else}
            <div class="c2-journal-list">
                {#each entries.toReversed() as entry, i}
                    <article class="c2-journal-entry" class:c2-entry-first={i === 0}>
                        <div class="c2-entry-meta">
                            <span class="c2-score-pill" style="--dot: {scoreTone(entry.self_score ?? 0)}">
                                <span class="c2-score-dot"></span>
                                {entry.self_score ?? 0}%
                            </span>
                            {#if entry.route}
                                {@const mode = entry.route.replace('ROUTE_', '').charAt(0) + entry.route.replace('ROUTE_', '').slice(1).toLowerCase()}
                                <span
                                    class="c2-mode-badge"
                                    style="background:{modeColors[mode] ?? 'var(--c2-bg-2)'}; color:{modeFgColors[mode] ?? 'var(--c2-fg-1)'}; border:1px solid oklch(0.5 0.1 240 / 0.3);"
                                >{mode}</span>
                            {/if}
                            <span class="c2-entry-time">{fmtTime(entry.created_at ?? '')}</span>
                        </div>
                        <p class="c2-entry-text">{entry.lesson ?? ''}</p>
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
        margin-bottom: 32px;
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
    }
    .c2-entry-time {
        font-family: 'Geist Mono', monospace;
        font-size: 11.5px;
        color: var(--c2-fg-3);
    }
    .c2-entry-text {
        font-size: 15.5px;
        line-height: 1.7;
        color: var(--c2-fg-0);
        margin: 0;
        text-wrap: pretty;
    }
</style>
