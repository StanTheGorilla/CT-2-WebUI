<script lang="ts">
    import type { MindTurn as MindTurnType } from '$lib/stores/chat';
    import MindTurn from './MindTurn.svelte';
    import SplitView from './SplitView.svelte';

    let { dialogue, phase, currentRound }:
        { dialogue: MindTurnType[]; phase: string; currentRound: number } = $props();

    let viewMode = $state<'timeline' | 'split'>('timeline');
    let collapsed = $state(false);
    let container: HTMLElement;

    $effect(() => {
        if (dialogue.length && container) {
            container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
        }
    });
</script>

<div class="panel">
    <div class="panel-header">
        <button class="title-btn" onclick={() => collapsed = !collapsed}>
            <span class="title">Deliberation</span>
            <span class="turn-count">{dialogue.length} turns</span>
            <span class="chevron">{collapsed ? '+' : '\u2212'}</span>
        </button>
        {#if !collapsed}
            <div class="view-toggle">
                <button class:active={viewMode === 'timeline'} onclick={() => viewMode = 'timeline'}>Timeline</button>
                <button class:active={viewMode === 'split'} onclick={() => viewMode = 'split'}>Split</button>
            </div>
        {/if}
    </div>
    {#if !collapsed}
        <div class="panel-body" bind:this={container}>
            {#if viewMode === 'timeline'}
                {#each dialogue as turn, i}
                    {#if turn.name === 'brain'}
                        <div class="brain-card">
                            <div class="brain-header">
                                <span class="brain-dot"></span>
                                <span class="brain-label">Brain Assessment</span>
                            </div>
                            <div class="brain-body">{turn.text}</div>
                        </div>
                    {:else}
                        {#if i === 0 || turn.round !== dialogue[i - 1].round}
                            <div class="round-label">round {turn.round}</div>
                        {/if}
                        <MindTurn name={turn.name} text={turn.text} />
                    {/if}
                {/each}
            {:else}
                <SplitView {dialogue} />
            {/if}

            {#if phase === 'deliberating'}
                <div class="thinking"><span class="pulse"></span> thinking...</div>
            {/if}
        </div>
    {/if}
</div>

<style>
    .panel { background: var(--surface); border-radius: var(--radius); display: flex; flex-direction: column; }
    .panel-header {
        display: flex; align-items: center; justify-content: space-between;
        padding: 12px 20px; border-bottom: 1px solid var(--border);
    }
    .title-btn {
        display: flex; align-items: center; gap: 8px;
        background: none; border: none; cursor: pointer; padding: 0;
    }
    .title { font-size: 13px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em; }
    .turn-count { font-size: 12px; color: var(--text-muted); }
    .chevron { color: var(--text-muted); font-size: 16px; }
    .view-toggle { display: flex; gap: 2px; background: var(--bg); border-radius: 8px; padding: 2px; }
    .view-toggle button {
        background: none; border: none; color: var(--text-secondary);
        font-family: var(--font-body); font-size: 12px; font-weight: 500;
        padding: 4px 12px; border-radius: 6px; cursor: pointer; transition: all var(--transition);
    }
    .view-toggle button.active { background: var(--surface-hover); color: var(--text); }
    .panel-body { padding: 20px; display: flex; flex-direction: column; gap: 16px; max-height: 60vh; overflow-y: auto; scroll-behavior: smooth; }
    .round-label { color: var(--text-muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; }

    .brain-card {
        background: var(--bg);
        border: 1px solid var(--brain);
        border-radius: var(--radius);
        padding: 14px 18px;
        animation: fadeSlideIn 300ms ease;
    }
    .brain-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
    .brain-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--brain); }
    .brain-label { color: var(--brain); font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; }
    .brain-body { color: var(--text); font-size: 14px; line-height: 1.6; }

    .thinking { display: flex; align-items: center; gap: 8px; color: var(--text-secondary); font-size: 13px; }
    .pulse { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); animation: pulse 1.5s ease-in-out infinite; }
    @keyframes pulse { 0%, 100% { opacity: 0.3; } 50% { opacity: 1; } }
    @keyframes fadeSlideIn {
        from { opacity: 0; transform: translateY(8px); }
        to { opacity: 1; transform: translateY(0); }
    }
</style>
