<script lang="ts">
    import { preferences, toggleTheme, setCt2Bg } from '$lib/stores/preferences';

    let confirmReset = $state(false);
</script>

                <div class="c2-sh">
                    <h1 class="c2-sh-title">Interface</h1>
                    <p class="c2-sh-sub">Appearance and app-level preferences.</p>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Theme</div>
                    </div>
                    <div class="c2-row-control">
                        <div class="c2-seg">
                            {#each (['dark', 'light'] as const) as v}
                                <button
                                    class="c2-seg-btn"
                                    class:c2-seg-active={$preferences.theme === v}
                                    onclick={toggleTheme}
                                >{v.charAt(0).toUpperCase() + v.slice(1)}</button>
                            {/each}
                        </div>
                    </div>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Background <span class="c2-param">/ ct2Bg</span></div>
                        <div class="c2-row-desc">The ambient art image behind the interface. Flat gives a cleaner, fully dark surface.</div>
                    </div>
                    <div class="c2-row-control">
                        <div class="c2-seg">
                            <button
                                class="c2-seg-btn"
                                class:c2-seg-active={($preferences.ct2Bg ?? 'image') !== 'none'}
                                onclick={() => setCt2Bg('image')}
                            >Nature</button>
                            <button
                                class="c2-seg-btn"
                                class:c2-seg-active={($preferences.ct2Bg ?? 'image') === 'none'}
                                onclick={() => setCt2Bg('none')}
                            >Flat</button>
                        </div>
                    </div>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Web search</div>
                        <div class="c2-row-desc">Allow the model to query the web when the search pill is active.</div>
                    </div>
                    <div class="c2-row-control">
                        <button
                            class="c2-switch"
                            class:c2-switch-on={$preferences.webSearchEnabled}
                            onclick={() => preferences.update(p => ({ ...p, webSearchEnabled: !p.webSearchEnabled }))}
                            role="switch"
                            aria-checked={$preferences.webSearchEnabled}
                            aria-label="Toggle web search"
                        >
                            <span class="c2-switch-knob"></span>
                        </button>
                    </div>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Reset all settings</div>
                        <div class="c2-row-desc">Restores all generation, Atlas, and interface preferences to their defaults.</div>
                    </div>
                    <div class="c2-row-control">
                        {#if confirmReset}
                            <div style="display:inline-flex;gap:8px;">
                                <button class="c2-btn-ghost" onclick={() => confirmReset = false}>Cancel</button>
                                <button class="c2-btn-danger" onclick={() => { preferences.set({ theme: 'light', ct2Bg: 'image', showThinking: false, designRefinement: true, webSearchEnabled: false, requireCommandApproval: false, notifyOnDone: true, atlasMode: false, atlasEffortMode: 'auto', atlasEffortLevel: 3, atlasSelfVerification: true, atlasMultiPerspective: true, atlasIterativeRefinement: true }); confirmReset = false; }}>Yes, reset</button>
                            </div>
                        {:else}
                            <button class="c2-btn-outline c2-btn-err" onclick={() => confirmReset = true}>Reset…</button>
                        {/if}
                    </div>
                </div>
