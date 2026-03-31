<script lang="ts">
    import type { SpecialistData } from '$lib/stores/chat';
    let { data }: { data: SpecialistData } = $props();

    let collapsed = $state(false);

    let route = $derived(data._route || '');

    let icon = $derived(
        route === 'ROUTE_DESIGN' ? '\u2B22' :
        route === 'ROUTE_CODE' ? '\u276F' :
        route === 'ROUTE_COMPUTER' ? '\u25A3' :
        '\u2139'
    );

    let title = $derived(
        route === 'ROUTE_DESIGN' ? 'Design Brief' :
        route === 'ROUTE_CODE' ? 'Code Brief' :
        route === 'ROUTE_COMPUTER' ? 'Project Brief' :
        route === 'ROUTE_DIRECT' ? 'Context' :
        'Brief'
    );

    /** Key-value pairs */
    let entries = $derived.by(() => {
        const items: { label: string; value: string }[] = [];
        if (route === 'ROUTE_DESIGN') {
            if (data.project_type) items.push({ label: 'Project', value: data.project_type });
            if (data.audience) items.push({ label: 'Audience', value: data.audience });
            if (data.mood?.length) items.push({ label: 'Mood', value: data.mood.join(', ') });
            if (data.theme) items.push({ label: 'Theme', value: data.theme });
            if (data.color_hints?.length) {
                const hints = data.color_hints.filter(Boolean);
                if (hints.length) items.push({ label: 'Colors', value: hints.join(', ') });
            }
            if (data.special?.length) {
                const sp = data.special.filter(Boolean);
                if (sp.length) items.push({ label: 'Special', value: sp.join(', ') });
            }
        } else if (route === 'ROUTE_CODE') {
            if (data.language) items.push({ label: 'Language', value: data.language });
            if (data.type) items.push({ label: 'Type', value: data.type });
            if (data.output_format) items.push({ label: 'Output', value: data.output_format });
        } else if (route === 'ROUTE_COMPUTER') {
            if (data.language) items.push({ label: 'Language', value: data.language });
            if (data.framework && data.framework !== 'none') items.push({ label: 'Framework', value: data.framework });
            if (data.run_command) items.push({ label: 'Run', value: data.run_command });
        } else if (route === 'ROUTE_DIRECT') {
            if (data.topic) items.push({ label: 'Topic', value: data.topic });
            if (data.answer_type) items.push({ label: 'Type', value: data.answer_type });
            if (data.depth) items.push({ label: 'Depth', value: data.depth });
        }
        return items;
    });

    /** List items */
    let lists = $derived.by(() => {
        const result: { label: string; items: string[] }[] = [];
        if (data.sections?.length) result.push({ label: 'Sections', items: data.sections });
        if (data.requirements?.length) result.push({ label: 'Requirements', items: data.requirements });
        if (data.files?.length) result.push({ label: 'Files', items: data.files });
        if (data.key_points?.length) result.push({ label: 'Key points', items: data.key_points });
        if (data.edge_cases?.length) result.push({ label: 'Edge cases', items: data.edge_cases });
        return result;
    });

    let hasContent = $derived(entries.length > 0 || lists.length > 0);
</script>

{#if hasContent}
<div class="card" class:design={route === 'ROUTE_DESIGN'} class:code={route === 'ROUTE_CODE'} class:computer={route === 'ROUTE_COMPUTER'}>
    <button class="card-header" onclick={() => collapsed = !collapsed}>
        <span class="card-icon">{icon}</span>
        <span class="card-title">{title}</span>
        <span class="toggle">{collapsed ? '\u25BE' : '\u25B4'}</span>
    </button>
    {#if !collapsed}
        <div class="card-body">
            {#if entries.length > 0}
                <div class="entries">
                    {#each entries as { label, value }}
                        <div class="entry">
                            <span class="entry-label">{label}</span>
                            <span class="entry-value">{value}</span>
                        </div>
                    {/each}
                </div>
            {/if}

            {#each lists as list}
                <div class="list-section">
                    <span class="list-label">{list.label}</span>
                    <div class="list-items">
                        {#each list.items as item, i}
                            <span class="list-pill">
                                <span class="pill-num">{i + 1}</span>
                                {item}
                            </span>
                        {/each}
                    </div>
                </div>
            {/each}
        </div>
    {/if}
</div>
{/if}

<style>
    .card {
        --card-accent: var(--specialist);
        background: var(--surface-solid);
        border: 1px solid var(--border);
        border-left: 2px solid var(--card-accent);
        border-radius: 14px;
        overflow: hidden;
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
        max-width: 480px;
    }
    .card.design { --card-accent: var(--specialist); }
    .card.code { --card-accent: var(--brain); }
    .card.computer { --card-accent: var(--success); }

    .card-header {
        display: flex;
        align-items: center;
        gap: 8px;
        width: 100%;
        background: none;
        border: none;
        cursor: pointer;
        padding: 9px 14px;
        transition: background var(--transition);
        font-family: var(--font-body);
    }
    .card-header:hover { background: var(--accent-subtle); }

    .card-icon {
        font-size: 10px;
        color: var(--card-accent);
        opacity: 0.8;
    }
    .card-title {
        font-size: 11px;
        font-weight: 600;
        color: var(--card-accent);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        flex: 1;
        text-align: left;
    }
    .toggle {
        color: var(--text-muted);
        font-size: 10px;
    }

    .card-body {
        padding: 6px 14px 12px;
        display: flex;
        flex-direction: column;
        gap: 10px;
        border-top: 1px solid var(--border-subtle);
    }

    /* Key-value entries */
    .entries {
        display: flex;
        flex-wrap: wrap;
        gap: 4px 6px;
    }
    .entry {
        display: inline-flex;
        align-items: baseline;
        gap: 5px;
        font-size: 12px;
        padding: 2px 0;
    }
    .entry-label {
        color: var(--text-muted);
        font-size: 11px;
        font-weight: 500;
    }
    .entry-label::after {
        content: ':';
    }
    .entry-value {
        color: var(--text-secondary);
        font-weight: 500;
    }
    /* Separator between entries */
    .entry + .entry::before {
        content: '\00B7';
        color: var(--text-muted);
        opacity: 0.4;
        margin-right: 6px;
        font-weight: 700;
    }

    /* List sections */
    .list-section {
        display: flex;
        flex-direction: column;
        gap: 5px;
    }
    .list-label {
        font-size: 10px;
        font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .list-items {
        display: flex;
        flex-wrap: wrap;
        gap: 4px;
    }
    .list-pill {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        background: var(--accent-subtle);
        color: var(--text-secondary);
        font-size: 11px;
        font-weight: 500;
        padding: 3px 10px 3px 6px;
        border-radius: var(--radius-pill);
        border: 1px solid var(--border-subtle);
    }
    .pill-num {
        font-size: 9px;
        font-weight: 600;
        color: var(--card-accent);
        opacity: 0.6;
        min-width: 12px;
        text-align: center;
    }
</style>
