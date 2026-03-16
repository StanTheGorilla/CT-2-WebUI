<script lang="ts">
    import type { Plan } from '$lib/stores/chat';
    let { plan }: { plan: Plan } = $props();

    const typeLabels: Record<string, string> = {
        html_page: 'HTML Page',
        python_script: 'Python Script',
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
    <div class="plan-header">
        <div class="plan-meta">
            <span class="type-badge">{typeLabels[plan.output_type] ?? plan.output_type}</span>
            <span class="complexity-dot" style="background: {complexityColors[plan.complexity] ?? 'var(--text-muted)'}"></span>
            <span class="complexity-label">{plan.complexity}</span>
        </div>
        <span class="plan-title">Build Plan</span>
    </div>

    {#if plan.components.length > 0}
        <ol class="components">
            {#each plan.components as c}
                <li class="component">
                    <span class="c-name">{c.name}</span>
                    {#if c.description}
                        <span class="c-desc">{c.description}</span>
                    {/if}
                </li>
            {/each}
        </ol>
    {/if}
</div>

<style>
    .plan-card {
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-left: 3px solid var(--text-muted);
        border-radius: var(--radius);
        overflow: hidden;
        box-shadow: var(--bubble-glow);
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
    }
    .plan-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 10px 16px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.4);
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
        background: rgba(0, 0, 0, 0.04);
        border: 1px solid rgba(255, 255, 255, 0.5);
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
    .plan-title {
        font-size: 11px;
        font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .components {
        list-style: none;
        padding: 10px 16px 12px;
        display: flex;
        flex-direction: column;
        gap: 6px;
        counter-reset: step;
    }
    .component {
        display: flex;
        align-items: baseline;
        gap: 8px;
        counter-increment: step;
        font-size: 13px;
    }
    .component::before {
        content: counter(step);
        font-size: 11px;
        font-weight: 600;
        color: var(--text-muted);
        font-family: var(--font-mono);
        min-width: 16px;
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
</style>
