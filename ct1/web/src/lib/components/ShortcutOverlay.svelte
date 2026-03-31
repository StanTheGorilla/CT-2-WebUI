<script lang="ts">
    let { open = $bindable(false) } = $props();

    const shortcuts = [
        { keys: 'Ctrl + N', action: 'New conversation' },
        { keys: 'Ctrl + K', action: 'Search conversations' },
        { keys: 'Ctrl + Shift + S', action: 'Toggle sidebar' },
        { keys: 'Ctrl + /', action: 'Show shortcuts' },
        { keys: 'Ctrl + Enter', action: 'Send message' },
        { keys: 'Escape', action: 'Close overlay' },
    ];
</script>

{#if open}
    <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
    <div class="overlay-backdrop" onclick={() => open = false} onkeydown={(e) => { if (e.key === 'Escape') open = false; }} role="dialog" tabindex="-1">
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div class="overlay-card" onclick={(e) => e.stopPropagation()} onkeydown={() => {}}>
            <h3 class="overlay-title">Keyboard Shortcuts</h3>
            <div class="shortcut-list">
                {#each shortcuts as s}
                    <div class="shortcut-row">
                        <kbd class="shortcut-keys">{s.keys}</kbd>
                        <span class="shortcut-action">{s.action}</span>
                    </div>
                {/each}
            </div>
        </div>
    </div>
{/if}

<style>
    .overlay-backdrop {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.3);
        backdrop-filter: blur(4px);
        -webkit-backdrop-filter: blur(4px);
        z-index: 200;
        display: flex;
        align-items: center;
        justify-content: center;
        animation: fadeIn 200ms ease;
    }

    .overlay-card {
        background: var(--bubble-strong);
        backdrop-filter: var(--bubble-blur-heavy);
        -webkit-backdrop-filter: var(--bubble-blur-heavy);
        border: var(--bubble-border);
        border-radius: var(--radius-lg);
        box-shadow: var(--shadow-lg);
        padding: 28px 32px;
        min-width: 340px;
        max-width: 420px;
        animation: springPop 400ms var(--spring) both;
    }

    .overlay-title {
        font-size: 16px;
        font-weight: 600;
        color: var(--text);
        margin-bottom: 20px;
        letter-spacing: -0.01em;
    }

    .shortcut-list {
        display: flex;
        flex-direction: column;
        gap: 10px;
    }

    .shortcut-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
    }

    .shortcut-keys {
        font-family: var(--font-mono);
        font-size: 12px;
        font-weight: 500;
        color: var(--text);
        background: var(--accent-subtle);
        border: 1px solid var(--border-subtle);
        border-radius: 6px;
        padding: 4px 10px;
        white-space: nowrap;
    }

    .shortcut-action {
        font-size: 13px;
        color: var(--text-secondary);
    }
</style>
