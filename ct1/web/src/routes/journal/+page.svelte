<script lang="ts">
    import { onMount } from 'svelte';
    import StatsBar from '$lib/components/StatsBar.svelte';
    import JournalEntry from '$lib/components/JournalEntry.svelte';

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
</script>

<div class="journal-page">
    {#if loading}
        <p class="loading">Loading journal...</p>
    {:else}
        <StatsBar {stats} />
        <div class="entries">
            {#each entries.toReversed() as entry}
                <JournalEntry {entry} />
            {/each}
            {#if entries.length === 0}
                <p class="empty">No journal entries yet.</p>
            {/if}
        </div>
    {/if}
</div>

<style>
    .journal-page { max-width: 800px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }
    .entries { display: flex; flex-direction: column; gap: 4px; }
    .loading, .empty { color: var(--text-secondary); text-align: center; padding: 40px; }
</style>
