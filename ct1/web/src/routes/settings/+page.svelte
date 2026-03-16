<script lang="ts">
    import { onMount } from 'svelte';
    import StatusIndicator from '$lib/components/StatusIndicator.svelte';

    let brainStatus = $state<Record<string, any>>({});
    let mindsStatus = $state<Record<string, any>>({});
    let config = $state<Record<string, any>>({});
    let loading = $state(true);

    onMount(async () => {
        try {
            const [statusRes, configRes] = await Promise.all([
                fetch('/api/status'),
                fetch('/api/config'),
            ]);
            const statusData = await statusRes.json();
            brainStatus = statusData.brain ?? {};
            mindsStatus = statusData.minds ?? {};
            config = await configRes.json();
        } finally {
            loading = false;
        }
    });
</script>

<div class="settings-page">
    <h2>Server Status</h2>
    {#if loading}
        <p class="loading">Checking...</p>
    {:else}
        <div class="status-grid">
            <StatusIndicator label="Brain" status={brainStatus} />
            <StatusIndicator label="Minds" status={mindsStatus} />
        </div>
    {/if}

    {#if config.deliberation}
        <h2>Deliberation</h2>
        <div class="config-card">
            {#each Object.entries(config.deliberation) as [key, value]}
                <div class="config-row">
                    <span class="config-key">{key}</span>
                    <span class="config-value">{value}</span>
                </div>
            {/each}
        </div>
    {/if}

    {#if config.models}
        <h2>Models</h2>
        {#each Object.entries(config.models) as [name, params]}
            <div class="config-card">
                <div class="config-card-title">{name}</div>
                {#each Object.entries(params as Record<string, any>) as [key, value]}
                    <div class="config-row">
                        <span class="config-key">{key}</span>
                        <span class="config-value">{value}</span>
                    </div>
                {/each}
            </div>
        {/each}
    {/if}
</div>

<style>
    .settings-page {
        max-width: 600px;
        margin: 0 auto;
        display: flex;
        flex-direction: column;
        gap: 12px;
        padding: 32px 32px 40px;
        height: 100%;
        overflow-y: auto;
    }
    h2 {
        font-size: 17px;
        margin-top: 12px;
        color: var(--text);
    }
    .status-grid { display: flex; flex-direction: column; gap: 6px; }
    .config-card {
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: var(--radius);
        padding: 16px 20px;
        box-shadow: var(--bubble-glow);
    }
    .config-card-title {
        font-size: 13px;
        font-weight: 600;
        color: var(--text-secondary);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 8px;
    }
    .config-row {
        display: flex;
        justify-content: space-between;
        padding: 5px 0;
        font-size: 14px;
    }
    .config-key { color: var(--text-secondary); }
    .config-value { color: var(--text); font-family: var(--font-mono); font-size: 13px; }
    .loading { color: var(--text-muted); }
</style>
