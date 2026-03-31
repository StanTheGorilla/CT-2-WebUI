<script lang="ts">
    import { chat } from '$lib/stores/chat';
    import type { AtlasCandidate, AtlasEffort } from '$lib/stores/chat';

    let expanded = $state(true);

    let active = $derived($chat.atlasActive);
    let phase = $derived($chat.atlasPhase);
    let candidates = $derived($chat.atlasCandidates);
    let effort = $derived($chat.atlasEffort);
    let pipelinePhase = $derived($chat.phase);
    let tps = $derived($chat.tokensPerSec);
    let chars = $derived($chat.streamingText?.length ?? 0);

    function phaseLabel(p: string | null): string {
        switch (p) {
            case 'estimating': return 'Estimating difficulty';
            case 'generating': return 'Generating candidates';
            case 'testing': return 'Running self-tests';
            case 'selecting': return 'Selecting best';
            case 'repairing': return 'Repairing failures';
            default: return 'Atlas';
        }
    }

    function pipelineDetail(p: string): string {
        switch (p) {
            case 'routing': return 'classifying';
            case 'planning': return 'planning';
            case 'spec_generating': return 'planning spec';
            case 'spec_validated': return 'spec ready';
            case 'component_generating': return 'components';
            case 'generating': return 'generating';
            case 'assembling': return 'assembling';
            case 'validating': return 'validating';
            case 'fixing': return 'fixing';
            case 'polishing': return 'polishing';
            case 'refining': return 'refining';
            default: return '';
        }
    }

    function formatChars(n: number): string {
        if (n >= 10000) return (n / 1000).toFixed(1) + 'k';
        if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
        return n.toString();
    }

    function statusIcon(status: string): string {
        switch (status) {
            case 'selected': return '\u2713';
            case 'scored': return '\u2022';
            case 'generating': return '\u25CB';
            case 'failed': return '\u2717';
            default: return '\u25CB';
        }
    }

    let activeCandidate = $derived(candidates.findIndex(c => c.status === 'generating'));
</script>

{#if active}
    <div class="atlas-progress">
        <button class="atlas-header" onclick={() => expanded = !expanded}>
            <span class="atlas-spinner"></span>
            <span class="atlas-phase">{phaseLabel(phase)}</span>
            {#if phase === 'generating' && pipelineDetail(pipelinePhase)}
                <span class="atlas-pipeline">{pipelineDetail(pipelinePhase)}</span>
            {/if}
            {#if effort}
                <span class="atlas-meta">
                    k={effort.k} &middot; {effort.tier}
                    {#if tps > 0}
                        &middot; {tps} t/s
                    {/if}
                    {#if chars > 0}
                        &middot; {formatChars(chars)}
                    {/if}
                </span>
            {/if}
            <span class="atlas-chevron" class:open={expanded}></span>
        </button>

        {#if expanded && candidates.length > 0}
            <div class="atlas-candidates">
                {#each candidates as c, i}
                    <div class="atlas-candidate" class:active={c.status === 'generating'} class:selected={c.status === 'selected'}>
                        <span class="candidate-icon" class:done={c.status === 'scored' || c.status === 'selected'} class:fail={c.status === 'failed'}>
                            {statusIcon(c.status)}
                        </span>
                        <span class="candidate-label">
                            {i === 0 ? 'Baseline' : `Perspective ${i}`}
                        </span>
                        {#if c.status === 'generating' && i === activeCandidate}
                            <span class="candidate-active">generating</span>
                        {/if}
                        {#if c.score !== null}
                            <span class="candidate-score">{(c.score * 100).toFixed(0)}%</span>
                        {/if}
                        {#if c.testsPassed !== null && c.testsTotal !== null && c.testsTotal > 0}
                            <span class="candidate-tests">{c.testsPassed}/{c.testsTotal} tests</span>
                        {/if}
                    </div>
                {/each}
            </div>
        {/if}
    </div>
{/if}

<style>
    .atlas-progress {
        border: 1px solid var(--border-subtle, var(--border));
        border-radius: var(--radius-sm, 6px);
        background: var(--bubble, #f8f8f8);
        margin-bottom: 8px;
        overflow: hidden;
    }
    .atlas-header {
        display: flex;
        align-items: center;
        gap: 8px;
        width: 100%;
        padding: 8px 12px;
        background: none;
        border: none;
        cursor: pointer;
        font-family: inherit;
        font-size: 12.5px;
        color: var(--text-secondary, #666);
        text-align: left;
    }
    .atlas-header:hover {
        background: var(--accent-subtle, rgba(0,0,0,0.03));
    }
    .atlas-spinner {
        width: 12px;
        height: 12px;
        border: 2px solid var(--border, #ddd);
        border-top-color: var(--text-secondary, #666);
        border-radius: 50%;
        animation: atlas-spin 0.7s linear infinite;
        flex-shrink: 0;
    }
    @keyframes atlas-spin { to { transform: rotate(360deg); } }

    .atlas-phase {
        font-weight: 600;
        color: var(--text, #222);
    }
    .atlas-pipeline {
        font-size: 11px;
        color: var(--text-muted, #999);
        font-style: italic;
    }
    .atlas-meta {
        font-family: var(--font-mono, monospace);
        font-size: 11px;
        color: var(--text-muted, #999);
        margin-left: auto;
    }
    .atlas-chevron {
        width: 0;
        height: 0;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid var(--text-muted, #999);
        transition: transform 0.15s;
        flex-shrink: 0;
    }
    .atlas-chevron.open {
        transform: rotate(180deg);
    }

    .atlas-candidates {
        padding: 4px 12px 8px;
        display: flex;
        flex-direction: column;
        gap: 4px;
    }
    .atlas-candidate {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 4px 8px;
        border-radius: var(--radius-sm, 6px);
        font-size: 12px;
        color: var(--text-secondary, #666);
    }
    .atlas-candidate.active {
        background: var(--accent-subtle, rgba(0,0,0,0.03));
    }
    .atlas-candidate.selected {
        background: rgba(46, 160, 67, 0.08);
    }
    .candidate-icon {
        font-size: 11px;
        color: var(--text-muted, #999);
        width: 14px;
        text-align: center;
    }
    .candidate-icon.done { color: var(--text-secondary, #666); }
    .candidate-icon.fail { color: var(--error, #d32f2f); }
    .candidate-label {
        font-weight: 500;
    }
    .candidate-active {
        font-size: 10px;
        color: var(--text-muted, #999);
        font-style: italic;
    }
    .candidate-score {
        font-family: var(--font-mono, monospace);
        font-size: 11px;
        font-weight: 600;
        color: var(--text, #222);
        margin-left: auto;
    }
    .candidate-tests {
        font-family: var(--font-mono, monospace);
        font-size: 11px;
        color: var(--text-muted, #999);
    }
</style>
