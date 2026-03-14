<script lang="ts">
    import type { MindTurn as MindTurnType } from '$lib/stores/chat';
    import MindTurn from './MindTurn.svelte';
    import SplitView from './SplitView.svelte';

    let { dialogue, phase, currentRound }:
        { dialogue: MindTurnType[]; phase: string; currentRound: number } = $props();

    let viewMode = $state<'timeline' | 'split'>('timeline');
    let container: HTMLElement;

    $effect(() => {
        if (dialogue.length && container) {
            container.scrollTop = container.scrollHeight;
        }
    });
</script>

<div class="panel">
    <div class="panel-header">
        <span class="title">Deliberation</span>
        <div class="view-toggle">
            <button class:active={viewMode === 'timeline'} onclick={() => viewMode = 'timeline'}>Timeline</button>
            <button class:active={viewMode === 'split'} onclick={() => viewMode = 'split'}>Split</button>
        </div>
    </div>
    <div class="panel-body" bind:this={container}>
        {#if viewMode === 'timeline'}
            {#each dialogue as turn, i}
                {#if i === 0 || turn.round !== dialogue[i - 1].round}
                    <div class="round-label">round {turn.round}</div>
                {/if}
                <MindTurn name={turn.name} text={turn.text} />
            {/each}
        {:else}
            <SplitView {dialogue} />
        {/if}

        {#if phase === 'deliberating'}
            <div class="thinking"><span class="pulse"></span> thinking...</div>
        {/if}
    </div>
</div>

<style>
    .panel { background: var(--surface); border-radius: var(--radius); overflow: hidden; display: flex; flex-direction: column; }
    .panel-header {
        display: flex; align-items: center; justify-content: space-between;
        padding: 12px 20px; border-bottom: 1px solid var(--border);
    }
    .title { font-size: 13px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em; }
    .view-toggle { display: flex; gap: 2px; background: var(--bg); border-radius: 8px; padding: 2px; }
    .view-toggle button {
        background: none; border: none; color: var(--text-secondary);
        font-family: var(--font-body); font-size: 12px; font-weight: 500;
        padding: 4px 12px; border-radius: 6px; cursor: pointer; transition: all var(--transition);
    }
    .view-toggle button.active { background: var(--surface-hover); color: var(--text); }
    .panel-body { padding: 20px; display: flex; flex-direction: column; gap: 16px; max-height: 500px; overflow-y: auto; }
    .round-label { color: var(--text-muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; }
    .thinking { display: flex; align-items: center; gap: 8px; color: var(--text-secondary); font-size: 13px; }
    .pulse { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); animation: pulse 1.5s ease-in-out infinite; }
    @keyframes pulse { 0%, 100% { opacity: 0.3; } 50% { opacity: 1; } }
</style>
