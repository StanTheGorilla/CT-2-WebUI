<script lang="ts">
    import type { Plan } from '$lib/stores/chat';
    let { plan }: { plan: Plan } = $props();

    let expanded = $state(false);

    const typeLabels: Record<string, string> = {
        html_page: 'HTML Page',
        python_script: 'Python',
        javascript: 'JavaScript',
        api: 'API',
        other: 'Code',
    };
    const complexityColors: Record<string, string> = {
        simple: 'var(--success)',
        moderate: 'var(--warning)',
        complex: 'var(--brain)',
    };
</script>

<div class="plan-card">
    <button class="plan-header" onclick={() => expanded = !expanded}>
        <div class="plan-meta">
            <span class="type-badge">{typeLabels[plan.output_type] ?? plan.output_type}</span>
            <span class="complexity-dot" style="background: {complexityColors[plan.complexity] ?? 'var(--text-muted)'}"></span>
            <span class="complexity-label">{plan.complexity}</span>
        </div>
        <div class="plan-right">
            <span class="plan-title">Build Plan</span>
            <span class="toggle-icon">{expanded ? '\u25B4' : '\u25BE'}</span>
        </div>
    </button>
    <div class="accent-bar"></div>

    {#if plan.components.length > 0}
        <div class="components">
            {#each plan.components as c}
                <div class="component">
                    <span class="c-num">{c.id}</span>
                    <span class="c-name">{c.name}</span>
                    {#if c.description}
                        <span class="c-desc">{c.description}</span>
                    {/if}
                </div>
            {/each}
        </div>
    {/if}

    {#if expanded}
        <div class="raw-section">
            <span class="raw-label">Raw plan (sent to Director)</span>
            <pre class="raw-json">{JSON.stringify(plan, null, 2)}</pre>
        </div>
    {/if}
</div>

<style>
    .plan-card {
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: 14px;
        overflow: hidden;
        box-shadow: var(--bubble-glow);
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
        max-width: min(760px, 92%);
    }
    .plan-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 10px 16px;
        width: 100%;
        background: none;
        border: none;
        cursor: pointer;
        font-family: var(--font-body);
        transition: background var(--transition);
    }
    .plan-header:hover { background: var(--accent-subtle); }
    .accent-bar {
        height: 1px;
        background: linear-gradient(90deg, var(--border-subtle) 0%, var(--accent-subtle) 100%);
        margin: 0;
    }
    .plan-meta {
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .type-badge {
        font-size: 11px;
        font-weight: 600;
        color: var(--text-secondary);
        background: var(--accent-subtle);
        border: 1px solid var(--border);
        border-radius: var(--radius-pill);
        padding: 2px 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .complexity-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
    }
    .complexity-label {
        font-size: 11px;
        color: var(--text-muted);
        text-transform: capitalize;
    }
    .plan-right {
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .plan-title {
        font-size: 11px;
        font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .toggle-icon {
        font-size: 10px;
        color: var(--text-muted);
    }
    .components {
        padding: 10px 16px 12px;
        display: flex;
        flex-direction: column;
        gap: 5px;
    }
    .component {
        display: flex;
        align-items: baseline;
        gap: 8px;
        font-size: 13px;
    }
    .c-num {
        font-size: 11px;
        font-weight: 600;
        color: var(--text-muted);
        font-family: var(--font-mono);
        min-width: 14px;
        text-align: right;
    }
    .c-name {
        font-weight: 600;
        color: var(--text-secondary);
        flex-shrink: 0;
    }
    .c-desc {
        color: var(--text-muted);
        font-size: 12px;
    }
    .raw-section {
        border-top: 1px solid var(--border);
        padding: 10px 16px 14px;
    }
    .raw-label {
        display: block;
        font-size: 10px;
        font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin-bottom: 6px;
    }
    .raw-json {
        font-family: var(--font-mono);
        font-size: 11px;
        line-height: 1.5;
        color: var(--text-secondary);
        background: var(--accent-subtle);
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius-sm);
        padding: 10px 12px;
        white-space: pre-wrap;
        word-break: break-word;
        margin: 0;
        max-height: 300px;
        overflow-y: auto;
    }
</style>
