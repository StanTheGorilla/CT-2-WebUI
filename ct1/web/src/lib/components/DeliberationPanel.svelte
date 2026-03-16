<script lang="ts">
    import type { MindTurn as MindTurnType } from '$lib/stores/chat';
    import MindTurn from './MindTurn.svelte';

    let { dialogue, phase, label = 'Deliberation' }:
        { dialogue: MindTurnType[]; phase: string; label?: string } = $props();

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
            <span class="title">{label}</span>
            <span class="turn-count">{dialogue.length} turns</span>
            <span class="chevron">{collapsed ? '+' : '\u2212'}</span>
        </button>
    </div>
    {#if !collapsed}
        <div class="panel-body" bind:this={container}>
            {#each dialogue as turn}
                <MindTurn name={turn.name} text={turn.text} />
            {/each}

            {#if phase === 'preparing'}
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
    .panel-body { padding: 20px; display: flex; flex-direction: column; gap: 16px; max-height: 60vh; overflow-y: auto; scroll-behavior: smooth; }

    .thinking { display: flex; align-items: center; gap: 8px; color: var(--text-secondary); font-size: 13px; }
    .pulse { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); animation: pulse 1.5s ease-in-out infinite; }
    @keyframes pulse { 0%, 100% { opacity: 0.3; } 50% { opacity: 1; } }
</style>
