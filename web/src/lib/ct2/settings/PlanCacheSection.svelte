<script lang="ts">
    import { onMount } from 'svelte';

    let { config, saveParam }: {
        config: Record<string, any>;
        saveParam: (key: string, value: number | boolean) => Promise<void>;
    } = $props();

    let planCacheStats = $state<{entries:number;avg_score:number;recent:Array<{sig:string;task_type:string;complexity:string;count:number;score:number}>}>({entries:0,avg_score:0,recent:[]});
    let planCacheClearing = $state(false);
    let planCacheMsg = $state('');
    let planCacheFast = $state(false);

    async function fetchPlanCache() {
        try {
            planCacheStats = await (await fetch('/api/plan-cache/stats')).json();
        } catch {}
    }

    async function clearPlanCache() {
        planCacheClearing = true; planCacheMsg = '';
        try {
            const d = await (await fetch('/api/plan-cache', { method: 'DELETE' })).json();
            planCacheMsg = d.ok ? `Cleared ${d.removed} cached plan(s).` : (d.error || 'Failed');
            await fetchPlanCache();
        } catch (e: any) {
            planCacheMsg = e.message || 'Failed';
        } finally { planCacheClearing = false; }
    }

    // Reflect the persisted setting once config loads (fixes toggle
    // always showing "off" after a page reload).
    $effect(() => { planCacheFast = !!config.plan_cache_fast; });

    onMount(() => { fetchPlanCache(); });
</script>

                <div class="c2-sh">
                    <h1 class="c2-sh-title">Plan cache</h1>
                    <p class="c2-sh-sub">Learned task signatures let the AI skip deliberation and respond faster over time.</p>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Cached entries</div>
                        <div class="c2-row-desc">Each entry maps a task pattern to a fast execution path. Grows automatically as you use the AI.</div>
                    </div>
                    <div class="c2-row-control">
                        <span class="c2-badge-big">{planCacheStats.entries ?? '—'}</span>
                    </div>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Fast-path acceleration</div>
                        <div class="c2-row-desc">When enabled, reusing a cached pattern skips the AI routing and planning steps. Off by default — enable after the cache has entries for your common tasks.</div>
                    </div>
                    <div class="c2-row-control">
                        <button class="c2-toggle" class:c2-toggle-on={planCacheFast} onclick={() => { planCacheFast = !planCacheFast; saveParam('plan_cache_fast', planCacheFast); }} type="button">
                            <span class="c2-toggle-knob"></span>
                        </button>
                    </div>
                </div>

                {#if planCacheStats.recent?.length}
                    <div class="c2-subsection-label" style="margin-top:8px;">Recent entries</div>
                    <div class="c2-pc-list">
                        {#each planCacheStats.recent as p}
                            <div class="c2-pc-item">
                                <div class="c2-pc-item-left">
                                    <span class="c2-pc-sig" title={p.sig}>{p.sig.length > 40 ? p.sig.slice(0, 38) + '…' : p.sig}</span>
                                    <span class="c2-pc-meta">{p.task_type} · {p.complexity} · ×{p.count}</span>
                                </div>
                                <div class="c2-pc-score" style="--score:{p.score}">{p.score.toFixed(1)}</div>
                            </div>
                        {/each}
                    </div>
                {:else if planCacheStats.entries === 0}
                    <p class="c2-row-desc" style="padding-top:8px;">No cached plans yet. Each new task type the AI learns will appear here.</p>
                {/if}

                <div style="margin-top:20px;display:flex;align-items:center;gap:12px;">
                    <button class="c2-btn-outline c2-btn-err" onclick={clearPlanCache} disabled={planCacheClearing}>
                        {planCacheClearing ? 'Clearing…' : 'Clear cache'}
                    </button>
                    {#if planCacheMsg}<span class="c2-row-desc">{planCacheMsg}</span>{/if}
                </div>
