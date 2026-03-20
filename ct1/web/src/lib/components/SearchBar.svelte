<script lang="ts">
    let query = $state('');
    let results = $state<any[]>([]);
    let debounceTimer: ReturnType<typeof setTimeout>;

    import { loadFromHistory } from '$lib/stores/chat';
    import { activeConversationId, loadConversation } from '$lib/stores/conversations';

    function onInput() {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(async () => {
            if (!query.trim()) {
                results = [];
                return;
            }
            const res = await fetch(`/api/search?q=${encodeURIComponent(query)}&limit=10`);
            if (res.ok) results = await res.json();
        }, 300);
    }

    async function selectResult(convId: string) {
        const conv = await loadConversation(convId);
        if (conv) {
            activeConversationId.set(convId);
            loadFromHistory(conv);
        }
        query = '';
        results = [];
    }
</script>

<div class="search-wrap">
    <input
        class="search-input"
        type="text"
        placeholder="Search conversations..."
        bind:value={query}
        oninput={onInput}
    />
    {#if results.length > 0}
        <div class="search-results">
            {#each results as r}
                <button class="search-result" onclick={() => selectResult(r.conversation_id)}>
                    <span class="result-title">{r.conversation_title}</span>
                    <span class="result-snippet">{@html r.snippet}</span>
                </button>
            {/each}
        </div>
    {/if}
</div>

<style>
    .search-wrap {
        position: relative;
        padding: 0 16px 8px;
    }
    .search-input {
        width: 100%;
        padding: 8px 12px;
        font-size: 13px;
        font-family: inherit;
        border: 1px solid rgba(0, 0, 0, 0.06);
        border-radius: var(--radius-sm);
        background: var(--bubble);
        color: var(--text);
        outline: none;
        transition: border-color var(--transition);
    }
    .search-input:focus {
        border-color: rgba(0, 0, 0, 0.12);
    }
    .search-input::placeholder {
        color: var(--text-muted);
    }
    .search-results {
        position: absolute;
        top: 100%;
        left: 16px;
        right: 16px;
        background: var(--bubble-strong);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: var(--radius-sm);
        box-shadow: var(--shadow-md);
        z-index: 10;
        max-height: 240px;
        overflow-y: auto;
    }
    .search-result {
        display: flex;
        flex-direction: column;
        gap: 2px;
        width: 100%;
        text-align: left;
        padding: 8px 12px;
        border: none;
        background: transparent;
        cursor: pointer;
        font-family: inherit;
        color: inherit;
        transition: background var(--transition);
    }
    .search-result:hover {
        background: rgba(0, 0, 0, 0.04);
    }
    .result-title {
        font-size: 12px;
        font-weight: 600;
        color: var(--text);
    }
    .result-snippet {
        font-size: 12px;
        color: var(--text-muted);
        line-height: 1.4;
    }
    .result-snippet :global(mark) {
        background: rgba(232, 133, 12, 0.2);
        color: var(--text);
        border-radius: 2px;
        padding: 0 2px;
    }
</style>
