<script lang="ts">
    import { preferences } from '$lib/stores/preferences';
</script>

                <div class="c2-sh">
                    <h1 class="c2-sh-title">Atlas mode</h1>
                    <p class="c2-sh-sub">An extended reasoning layer that runs additional exploration, verification, and perspective-taking passes.</p>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Enable Atlas</div>
                        <div class="c2-row-desc">Master toggle. When off, all sub-options are disabled.</div>
                    </div>
                    <div class="c2-row-control">
                        <button
                            class="c2-switch"
                            class:c2-switch-on={$preferences.atlasMode}
                            onclick={() => preferences.update(p => ({ ...p, atlasMode: !p.atlasMode }))}
                            role="switch"
                            aria-checked={$preferences.atlasMode}
                            aria-label="Toggle Atlas mode"
                        >
                            <span class="c2-switch-knob"></span>
                        </button>
                    </div>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Effort mode</div>
                    </div>
                    <div class="c2-row-control">
                        <div class="c2-seg">
                            {#each (['auto', 'manual'] as const) as v}
                                <button
                                    class="c2-seg-btn"
                                    class:c2-seg-active={$preferences.atlasEffortMode === v}
                                    onclick={() => preferences.update(p => ({ ...p, atlasEffortMode: v }))}
                                    disabled={!$preferences.atlasMode}
                                >{v.charAt(0).toUpperCase() + v.slice(1)}</button>
                            {/each}
                        </div>
                    </div>
                </div>

                {#if $preferences.atlasEffortMode === 'manual'}
                    <div class="c2-row">
                        <div class="c2-row-label">
                            <div class="c2-row-name">Effort level <span class="c2-param">/ atlas_effort</span></div>
                            <div class="c2-row-desc">How aggressively Atlas explores alternatives before committing.</div>
                        </div>
                        <div class="c2-row-control">
                            <div class="c2-slider-wrap">
                                <input type="range" min="1" max="5" step="1"
                                    value={$preferences.atlasEffortLevel}
                                    onchange={(e) => preferences.update(p => ({ ...p, atlasEffortLevel: Number((e.target as HTMLInputElement).value) }))}
                                    class="c2-slider"
                                    disabled={!$preferences.atlasMode}
                                />
                                <div class="c2-slider-val">{$preferences.atlasEffortLevel}</div>
                            </div>
                        </div>
                    </div>
                    <div class="c2-row">
                        <div class="c2-row-label">
                            <div class="c2-row-name">Self-verification</div>
                            <div class="c2-row-desc">Re-read the output and flag contradictions.</div>
                        </div>
                        <div class="c2-row-control">
                            <button class="c2-switch" class:c2-switch-on={$preferences.atlasSelfVerification}
                                onclick={() => preferences.update(p => ({ ...p, atlasSelfVerification: !p.atlasSelfVerification }))}
                                disabled={!$preferences.atlasMode} role="switch" aria-checked={$preferences.atlasSelfVerification}
                                aria-label="Toggle Atlas self-verification">
                                <span class="c2-switch-knob"></span>
                            </button>
                        </div>
                    </div>
                    <div class="c2-row">
                        <div class="c2-row-label">
                            <div class="c2-row-name">Multi-perspective</div>
                            <div class="c2-row-desc">Consider the problem from 3 distinct viewpoints before answering.</div>
                        </div>
                        <div class="c2-row-control">
                            <button class="c2-switch" class:c2-switch-on={$preferences.atlasMultiPerspective}
                                onclick={() => preferences.update(p => ({ ...p, atlasMultiPerspective: !p.atlasMultiPerspective }))}
                                disabled={!$preferences.atlasMode} role="switch" aria-checked={$preferences.atlasMultiPerspective}
                                aria-label="Toggle Atlas multi-perspective mode">
                                <span class="c2-switch-knob"></span>
                            </button>
                        </div>
                    </div>
                    <div class="c2-row">
                        <div class="c2-row-label">
                            <div class="c2-row-name">Iterative refinement</div>
                            <div class="c2-row-desc">Run additional polishing passes until no more changes are proposed.</div>
                        </div>
                        <div class="c2-row-control">
                            <button class="c2-switch" class:c2-switch-on={$preferences.atlasIterativeRefinement}
                                onclick={() => preferences.update(p => ({ ...p, atlasIterativeRefinement: !p.atlasIterativeRefinement }))}
                                disabled={!$preferences.atlasMode} role="switch" aria-checked={$preferences.atlasIterativeRefinement}
                                aria-label="Toggle Atlas iterative refinement">
                                <span class="c2-switch-knob"></span>
                            </button>
                        </div>
                    </div>
                {/if}
