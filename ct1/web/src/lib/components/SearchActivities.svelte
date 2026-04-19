<script lang="ts">
    import type { SearchActivity } from '$lib/stores/chat';

    let {
        searches = [],
        showStatus = false,
    }: {
        searches?: SearchActivity[];
        showStatus?: boolean;
    } = $props();
</script>

{#if showStatus}
    {#each searches as search}
        <div class="search-status">
            <span class="search-icon">
                <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                    <circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.4"/>
                    <path d="M8 2c-1.5 2-2 3.7-2 6s.5 4 2 6M8 2c1.5 2 2 3.7 2 6s-.5 4-2 6M2 8h12" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
                </svg>
            </span>
            <span class="search-label" class:pulse-text={!search.done}>
                {search.done ? 'Searched:' : 'Searching:'}
            </span>
            <span class="search-query">"{search.query}"</span>
            {#if search.done}
                {#if search.results.length > 0}
                    <span class="search-count">{search.results.length} results</span>
                {:else if search.error}
                    <span class="search-error">— {search.error}</span>
                {:else}
                    <span class="search-error">— no results</span>
                {/if}
            {/if}
        </div>
    {/each}
{/if}

{#each searches as search}
    {#if search.done}
        <details class="search-results-card">
            <summary class="search-results-header">
                <span class="search-results-icon">
                    <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                        <circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.4"/>
                        <path d="M8 2c-1.5 2-2 3.7-2 6s.5 4 2 6M8 2c1.5 2 2 3.7 2 6s-.5 4-2 6M2 8h12" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
                    </svg>
                </span>
                <span class="search-results-title">Web results{search.query ? ` for "${search.query}"` : ''}</span>
                <span class="search-results-count">{search.results.length}</span>
            </summary>
            <div class="search-results-body">
                {#if search.results.length > 0}
                    {#each search.results as result}
                        <div class="search-result-item">
                            <a href={result.url} target="_blank" rel="noopener noreferrer" class="sr-title">{result.title}</a>
                            <div class="sr-url">{result.url.length > 70 ? result.url.slice(0, 67) + '…' : result.url}</div>
                            {#if result.snippet}
                                <p class="sr-snippet">{result.snippet}</p>
                            {/if}
                        </div>
                    {/each}
                {:else}
                    <div class="search-empty">{search.error || 'No results returned.'}</div>
                {/if}
            </div>
        </details>
    {/if}
{/each}

<style>
    .search-status {
        display: flex;
        align-items: center;
        gap: 7px;
        font-size: 0.78rem;
        color: var(--text-2);
        margin: 6px 0 4px;
    }
    .search-icon {
        color: var(--accent, #3b82f6);
        flex-shrink: 0;
        display: flex;
    }
    .search-label { font-weight: 500; }
    .search-query { opacity: 0.75; font-style: italic; }
    .search-count {
        margin-left: auto;
        font-size: 0.72rem;
        opacity: 0.55;
    }
    .search-error {
        font-size: 0.72rem;
        color: var(--warning, #f59e0b);
        opacity: 0.85;
        font-style: italic;
    }
    .pulse-text { animation: pulseOpacity 1.2s ease-in-out infinite; }
    @keyframes pulseOpacity {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.45; }
    }

    .search-results-card {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 10px;
        margin: 4px 0;
        overflow: hidden;
    }
    .search-results-header {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 12px;
        cursor: pointer;
        font-size: 0.8rem;
        color: var(--text-2);
        list-style: none;
    }
    .search-results-header::-webkit-details-marker { display: none; }
    .search-results-icon {
        color: var(--accent, #3b82f6);
        display: flex;
        flex-shrink: 0;
    }
    .search-results-title {
        font-weight: 500;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .search-results-count {
        margin-left: auto;
        font-size: 0.7rem;
        background: var(--accent-subtle);
        color: var(--accent, #3b82f6);
        padding: 1px 7px;
        border-radius: 99px;
        font-weight: 600;
        flex-shrink: 0;
    }
    .search-results-body {
        border-top: 1px solid var(--border);
        padding: 4px 0;
        max-height: 340px;
        overflow-y: auto;
    }
    .search-result-item {
        padding: 8px 14px;
        border-bottom: 1px solid var(--border-subtle, color-mix(in srgb, var(--border) 50%, transparent));
    }
    .search-result-item:last-child { border-bottom: none; }
    .sr-title {
        font-size: 0.82rem;
        font-weight: 500;
        color: var(--accent, #3b82f6);
        text-decoration: none;
        display: block;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .sr-title:hover { text-decoration: underline; }
    .sr-url {
        font-size: 0.7rem;
        color: var(--text-muted);
        margin-top: 1px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .sr-snippet {
        font-size: 0.76rem;
        color: var(--text-2);
        margin: 3px 0 0;
        line-height: 1.4;
    }
    .search-empty {
        padding: 10px 14px;
        font-size: 0.76rem;
        color: var(--text-secondary);
    }
</style>
