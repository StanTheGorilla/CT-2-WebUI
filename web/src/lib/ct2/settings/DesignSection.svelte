<script lang="ts">
    import { preferences } from '$lib/stores/preferences';
</script>

                <div class="c2-sh">
                    <h1 class="c2-sh-title">Design mode</h1>
                    <p class="c2-sh-sub">A second pass that re-reads generated HTML and refines CSS, spacing, and visual hierarchy before finalizing.</p>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">CSS refinement pass</div>
                        <div class="c2-row-desc">Adds 4–12s to design-mode responses, and meaningfully improves visual quality.</div>
                    </div>
                    <div class="c2-row-control">
                        <button
                            class="c2-switch"
                            class:c2-switch-on={$preferences.designRefinement}
                            onclick={() => preferences.update(p => ({ ...p, designRefinement: !p.designRefinement }))}
                            role="switch"
                            aria-checked={$preferences.designRefinement}
                            aria-label="Toggle CSS refinement pass"
                        >
                            <span class="c2-switch-knob"></span>
                        </button>
                    </div>
                </div>
