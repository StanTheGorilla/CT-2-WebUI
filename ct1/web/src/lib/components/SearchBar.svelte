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
        padding: 0;
    }
    .search-field {
        position: relative;
        display: flex;
        align-items: center;
    }
    .search-field::before {
        content: none;
    }
    .search-icon {
        position: absolute;
        left: 14px;
        color: var(--text-muted);
        pointer-events: none;
        transition: color 180ms ease;
    }
    .search-input {
        width: 100%;
        min-height: 42px;
        padding: 10px 14px 10px 38px;
        font-size: 13px;
        font-family: inherit;
        font-weight: 500;
        letter-spacing: 0.01em;
        border: 1px solid var(--border);
        border-radius: 14px;
        background: color-mix(in srgb, var(--surface-solid) 50%, var(--surface));
        color: var(--text);
        outline: none;
        transition: border-color 200ms ease, background 200ms ease, box-shadow 200ms ease;
        box-shadow: none;
    }
    .search-input:focus {
        border-color: var(--border-strong);
        background: var(--surface-hover);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
    }
    .search-field:focus-within .search-icon {
        color: var(--text-secondary);
    }
    .search-input::placeholder {
        color: var(--text-muted);
        font-weight: 400;
    }
    .search-results {
        position: absolute;
        top: calc(100% + 4px);
        left: 0;
        right: 0;
        background: color-mix(in srgb, var(--surface-solid) 78%, var(--bubble-strong));
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: 14px;
        box-shadow: 0 14px 30px rgba(0, 0, 0, 0.08);
        z-index: 10;
        max-height: 260px;
        overflow-y: auto;
        scrollbar-width: none;
        padding: 6px;
    }
    .search-results::-webkit-scrollbar {
        display: none;
    }
    .search-result {
        display: flex;
        flex-direction: column;
        gap: 4px;
        width: 100%;
        text-align: left;
        padding: 10px 12px;
        border: none;
        background: transparent;
        cursor: pointer;
        font-family: inherit;
        color: inherit;
        border-radius: 10px;
        transition: background 150ms ease, box-shadow 150ms ease;
    }
    .search-result:hover {
        background: color-mix(in srgb, var(--surface-solid) 40%, var(--surface));
        box-shadow: none;
    }
    .result-title {
        font-size: 12.5px;
        font-weight: 600;
        color: var(--text);
        letter-spacing: -0.01em;
    }
    .result-snippet {
        font-size: 11.5px;
        color: var(--text-muted);
        line-height: 1.4;
    }
    .result-snippet :global(mark) {
        background: rgba(232, 133, 12, 0.18);
        color: var(--text);
        border-radius: 4px;
        padding: 0 3px;
    }
</style>
