<script lang="ts">
    import type { SpecialistData } from '$lib/stores/chat';
    let { data }: { data: SpecialistData } = $props();

    let collapsed = $state(false);
</script>

<div class="card">
    <button class="card-header" onclick={() => collapsed = !collapsed}>
        <div class="accent-line"></div>
        <span class="card-title">Specialist Brief</span>
        <span class="toggle">{collapsed ? '+' : '\u2212'}</span>
    </button>
    {#if !collapsed}
        <div class="card-body">
            {#if data.palette}
                <div class="section">
                    <span class="section-label">Palette</span>
                    <div class="swatches">
                        {#each Object.entries(data.palette) as [name, hex]}
                            <div class="swatch">
                                <div class="color-chip" style="background: {hex}"></div>
                                <span class="color-name">{name}</span>
                                <span class="color-hex">{hex}</span>
                            </div>
                        {/each}
                    </div>
                </div>
            {/if}

            {#if data.typography}
                <div class="section">
                    <span class="section-label">Typography</span>
                    <div class="typo-grid">
                        {#each Object.entries(data.typography) as [key, val]}
                            <div class="typo-row">
                                <span class="typo-key">{key.replace(/_/g, ' ')}</span>
                                <span class="typo-val">{val}</span>
                            </div>
                        {/each}
                    </div>
                </div>
            {/if}

            {#if data.sections && data.sections.length > 0}
                <div class="section">
                    <span class="section-label">Sections</span>
                    <div class="pill-row">
                        {#each data.sections as sec, i}
                            <span class="pill">{i + 1}. {sec}</span>
                        {/each}
                    </div>
                </div>
            {/if}

            {#if data.rationale}
                <div class="section">
                    <span class="section-label">Rationale</span>
                    <p class="rationale">{data.rationale}</p>
                </div>
            {/if}
        </div>
    {/if}
</div>

<style>
    .card {
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border-radius: var(--radius);
        border: var(--bubble-border);
        box-shadow: var(--bubble-glow);
        overflow: hidden;
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
    }
    .card-header {
        display: flex;
        align-items: center;
        gap: 12px;
        width: 100%;
        background: none;
        border: none;
        cursor: pointer;
        padding: 12px 18px;
        transition: background var(--transition);
        font-family: var(--font-body);
    }
    .card-header:hover { background: rgba(0, 0, 0, 0.02); }
    .accent-line {
        width: 3px;
        height: 18px;
        border-radius: 2px;
        background: var(--specialist);
    }
    .card-title {
        font-size: 12px;
        font-weight: 600;
        color: var(--specialist);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        flex: 1;
        text-align: left;
    }
    .toggle { color: var(--text-muted); font-size: 18px; font-weight: 300; }
    .card-body {
        padding: 14px 18px;
        display: flex;
        flex-direction: column;
        gap: 16px;
        border-top: 1px solid rgba(255, 255, 255, 0.4);
    }
    .section { display: flex; flex-direction: column; gap: 8px; }
    .section-label {
        font-size: 11px;
        font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .swatches { display: flex; flex-wrap: wrap; gap: 10px; }
    .swatch { display: flex; align-items: center; gap: 8px; }
    .color-chip {
        width: 20px;
        height: 20px;
        border-radius: 6px;
        border: 1px solid rgba(255, 255, 255, 0.5);
        box-shadow: var(--shadow-xs);
    }
    .color-name { font-size: 13px; color: var(--text-secondary); font-weight: 500; }
    .color-hex { font-size: 12px; color: var(--text-muted); font-family: var(--font-mono); }
    .typo-grid { display: flex; flex-direction: column; gap: 4px; }
    .typo-row { display: flex; gap: 10px; font-size: 14px; }
    .typo-key { color: var(--text-secondary); text-transform: capitalize; min-width: 120px; }
    .typo-val { color: var(--text); font-weight: 500; }
    .pill-row { display: flex; flex-wrap: wrap; gap: 8px; }
    .pill {
        background: rgba(0, 0, 0, 0.04);
        color: var(--text-secondary);
        font-size: 13px;
        font-weight: 500;
        padding: 4px 14px;
        border-radius: var(--radius-pill);
        border: 1px solid rgba(255, 255, 255, 0.5);
    }
    .rationale { font-size: 14px; color: var(--text-secondary); font-style: italic; margin: 0; line-height: 1.6; }
</style>
