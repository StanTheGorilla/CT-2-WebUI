<script lang="ts">
    import type { Intent } from '$lib/stores/chat';
    let { intent }: { intent: Intent } = $props();

    const typeColors: Record<string, string> = {
        code: 'var(--mind-alpha)',
        artifact: 'var(--mind-gamma)',
        question: 'var(--accent)',
        analysis: 'var(--mind-beta)',
    };
</script>

<div class="intent-card">
    <div class="row">
        <span class="badge" style="background: {typeColors[intent.task_type] || 'var(--accent)'}">
            {intent.task_type}
        </span>
        <span class="complexity">{intent.complexity}</span>
    </div>
    <p class="what">{intent.what_to_produce}</p>
    {#if intent.requirements.length > 0}
        <div class="reqs">
            {#each intent.requirements as req}
                <span class="pill">{req}</span>
            {/each}
        </div>
    {/if}
</div>

<style>
    .intent-card {
        background: var(--surface);
        border-radius: var(--radius);
        padding: 16px 20px;
        display: flex;
        flex-direction: column;
        gap: 8px;
    }
    .row { display: flex; align-items: center; gap: 10px; }
    .badge {
        color: var(--bg);
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        padding: 3px 10px;
        border-radius: 10px;
    }
    .complexity { color: var(--text-secondary); font-size: 13px; }
    .what { color: var(--text); font-size: 15px; }
    .reqs { display: flex; flex-wrap: wrap; gap: 6px; }
    .pill {
        background: var(--bg);
        color: var(--text-secondary);
        font-size: 12px;
        padding: 4px 12px;
        border-radius: 16px;
        border: 1px solid var(--border);
    }
</style>
