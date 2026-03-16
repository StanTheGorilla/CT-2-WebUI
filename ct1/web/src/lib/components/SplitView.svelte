<script lang="ts">
    import type { MindTurn } from '$lib/stores/chat';
    import { render } from '$lib/markdown';

    let { dialogue }: { dialogue: MindTurn[] } = $props();

    const minds = ['alpha', 'beta', 'gamma'] as const;
    const colors: Record<string, string> = {
        alpha: 'var(--mind-alpha)',
        beta: 'var(--mind-beta)',
        gamma: 'var(--mind-gamma)',
        brain: 'var(--brain)',
    };

    const columns = $derived(
        Object.fromEntries(
            minds.map((m) => [m, dialogue.filter((t) => t.name === m)])
        )
    );

    const brainTurns = $derived(dialogue.filter((t) => t.name === 'brain'));
</script>

<div class="split-container">
    <div class="split">
        {#each minds as mind}
            <div class="column" style="--col-color: {colors[mind]}">
                <div class="col-header">{mind}</div>
                <div class="col-body">
                    {#each columns[mind] as turn}
                        {#if turn.thinking}
                            <details class="col-thinking">
                                <summary>thinking</summary>
                                <div>{@html render(turn.thinking)}</div>
                            </details>
                        {/if}
                        <div class="col-turn">{@html render(turn.text)}</div>
                    {/each}
                </div>
            </div>
        {/each}
    </div>

    {#each brainTurns as turn}
        <div class="brain-row">
            <span class="brain-dot"></span>
            <span class="brain-label">brain</span>
            <div class="brain-text">{@html render(turn.text)}</div>
        </div>
    {/each}
</div>

<style>
    .split-container { display: flex; flex-direction: column; gap: 12px; }
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
    .col-thinking { font-size: 12px; color: var(--text-muted); }
    .col-thinking summary { cursor: pointer; font-style: italic; }
    .col-thinking div { padding: 6px 0; font-style: italic; line-height: 1.5; }

    .brain-row {
        background: var(--surface);
        border-left: 2px solid var(--brain);
        border-radius: 8px;
        padding: 12px 16px;
        animation: fadeSlideIn 300ms ease;
    }
    .brain-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--brain); vertical-align: middle; }
    .brain-label { color: var(--brain); font-size: 13px; font-weight: 600; margin-left: 6px; }
    .brain-text { color: var(--text); font-size: 14px; line-height: 1.6; margin-top: 6px; }
    .brain-text :global(p) { margin-bottom: 6px; }
    .brain-text :global(p:last-child) { margin-bottom: 0; }
    @keyframes fadeSlideIn {
        from { opacity: 0; transform: translateY(8px); }
        to { opacity: 1; transform: translateY(0); }
    }
</style>
