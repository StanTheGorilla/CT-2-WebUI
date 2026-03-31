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
    <div class="search-field">
        <svg class="search-icon" width="13" height="13" viewBox="0 0 16 16" fill="none">
            <circle cx="7" cy="7" r="5" stroke="currentColor" stroke-width="1.4"/>
            <path d="M11 11l3.5 3.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
        </svg>
        <input
            class="search-input"
            type="text"
            placeholder="Search..."
            bind:value={query}
            oninput={onInput}
        />
    </div>
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
        padding: 0 12px 6px;
    }
    .search-field {
        position: relative;
        display: flex;
        align-items: center;
    }
    .search-icon {
        position: absolute;
        left: 10px;
        color: var(--text-muted);
        pointer-events: none;
    }
    .search-input {
        width: 100%;
        padding: 7px 10px 7px 30px;
        font-size: 12px;
        font-family: inherit;
        font-weight: 400;
        letter-spacing: 0.01em;
        border: 1px solid var(--border);
        border-radius: 10px;
        background: var(--surface);
        color: var(--text);
        outline: none;
        transition: border-color 200ms ease, background 200ms ease;
    }
    .search-input:focus {
        border-color: var(--border-strong);
        background: var(--surface-hover);
    }
    .search-input::placeholder {
        color: var(--text-muted);
        font-weight: 400;
    }
    .search-results {
        position: absolute;
        top: calc(100% + 4px);
        left: 12px;
        right: 12px;
        background: var(--bubble-strong);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: 12px;
        box-shadow: var(--shadow-md);
        z-index: 10;
        max-height: 220px;
        overflow-y: auto;
        scrollbar-width: none;
        padding: 4px;
    }
    .search-results::-webkit-scrollbar {
        display: none;
    }
    .search-result {
        display: flex;
        flex-direction: column;
        gap: 2px;
        width: 100%;
        text-align: left;
        padding: 8px 10px;
        border: none;
        background: transparent;
        cursor: pointer;
        font-family: inherit;
        color: inherit;
        border-radius: 8px;
        transition: background 150ms ease;
    }
    .search-result:hover {
        background: var(--surface);
    }
    .result-title {
        font-size: 12px;
        font-weight: 600;
        color: var(--text);
        letter-spacing: -0.01em;
    }
    .result-snippet {
        font-size: 11px;
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
