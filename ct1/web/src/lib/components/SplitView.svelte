<script lang="ts">
    import type { MindTurn } from '$lib/stores/chat';
    import { render } from '$lib/markdown';

    let { dialogue }: { dialogue: MindTurn[] } = $props();

    const minds = ['alpha', 'beta', 'gamma'] as const;
    const colors: Record<string, string> = {
        alpha: 'var(--mind-alpha)',
        beta: 'var(--mind-beta)',
        gamma: 'var(--mind-gamma)',
    };

    const columns = $derived(
        Object.fromEntries(
            minds.map((m) => [m, dialogue.filter((t) => t.name === m)])
        )
    );
</script>

<div class="split">
    {#each minds as mind}
        <div class="column" style="--col-color: {colors[mind]}">
            <div class="col-header">{mind}</div>
            <div class="col-body">
                {#each columns[mind] as turn}
                    <div class="col-turn">{@html render(turn.text)}</div>
                {/each}
            </div>
        </div>
    {/each}
</div>

<style>
    .split {
        display: grid;
        grid-template-columns: 1fr 1fr 1fr;
        gap: 1px;
        background: var(--border);
        border-radius: 8px;
        overflow: hidden;
    }
    .column { background: var(--bg); border-top: 2px solid var(--col-color); }
    .col-header {
        color: var(--col-color);
        font-size: 12px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        padding: 10px 14px;
        border-bottom: 1px solid var(--border);
    }
    .col-body { padding: 12px 14px; display: flex; flex-direction: column; gap: 12px; }
    .col-turn { color: var(--text); font-size: 13px; line-height: 1.6; }
    .col-turn :global(p) { margin-bottom: 6px; }
    .col-turn :global(p:last-child) { margin-bottom: 0; }
</style>
