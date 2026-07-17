<script lang="ts">
    let { config, saveParam }: {
        config: Record<string, any>;
        saveParam: (key: string, value: number | boolean) => Promise<void>;
    } = $props();

    let temperature = $state(0.7);
    let topP = $state(0.9);
    let topK = $state(40);
    let presencePenalty = $state(0.2);
    let repeatPenalty = $state(1.10);

    $effect(() => {
        if (config.temperature !== undefined) {
            temperature = config.temperature ?? 0.7;
            topP = config.top_p ?? 0.9;
            topK = config.top_k ?? 40;
            presencePenalty = config.presence_penalty ?? 0.2;
            repeatPenalty = config.repeat_penalty ?? 1.10;
        }
    });

</script>

                <div class="c2-sh">
                    <h1 class="c2-sh-title">Generation parameters</h1>
                    <p class="c2-sh-sub">Control how the model samples tokens. Friendly labels shown alongside their technical names.</p>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Creativity <span class="c2-param">/ temperature</span></div>
                        <div class="c2-row-desc">Higher values produce more varied output. 0.7 is a balanced default.</div>
                    </div>
                    <div class="c2-row-control">
                        <div class="c2-slider-wrap">
                            <input type="range" min="0" max="2" step="0.01" bind:value={temperature} onchange={() => saveParam('temperature', temperature)} class="c2-slider" />
                            <div class="c2-slider-val">{temperature.toFixed(2)}</div>
                        </div>
                    </div>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Nucleus sampling <span class="c2-param">/ top_p</span></div>
                        <div class="c2-row-desc">Keep the smallest set of tokens whose cumulative probability meets this threshold.</div>
                    </div>
                    <div class="c2-row-control">
                        <div class="c2-slider-wrap">
                            <input type="range" min="0" max="1" step="0.01" bind:value={topP} onchange={() => saveParam('top_p', topP)} class="c2-slider" />
                            <div class="c2-slider-val">{topP.toFixed(2)}</div>
                        </div>
                    </div>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Top-K <span class="c2-param">/ top_k</span></div>
                        <div class="c2-row-desc">Restrict sampling to the K most likely tokens at each step.</div>
                    </div>
                    <div class="c2-row-control">
                        <div class="c2-slider-wrap">
                            <input type="range" min="0" max="200" step="1" bind:value={topK} onchange={() => saveParam('top_k', topK)} class="c2-slider" />
                            <div class="c2-slider-val">{topK}</div>
                        </div>
                    </div>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Presence penalty <span class="c2-param">/ presence_penalty</span></div>
                        <div class="c2-row-desc">Discourages the model from repeating tokens that already appear in the context.</div>
                    </div>
                    <div class="c2-row-control">
                        <div class="c2-slider-wrap">
                            <input type="range" min="0" max="2" step="0.01" bind:value={presencePenalty} onchange={() => saveParam('presence_penalty', presencePenalty)} class="c2-slider" />
                            <div class="c2-slider-val">{presencePenalty.toFixed(2)}</div>
                        </div>
                    </div>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Repeat penalty <span class="c2-param">/ repeat_penalty</span></div>
                        <div class="c2-row-desc">Penalizes tokens that appear repeatedly in the output. Higher values reduce looping and repetition.</div>
                    </div>
                    <div class="c2-row-control">
                        <div class="c2-slider-wrap">
                            <input type="range" min="1.0" max="1.5" step="0.01" bind:value={repeatPenalty} onchange={() => saveParam('repeat_penalty', repeatPenalty)} class="c2-slider" />
                            <div class="c2-slider-val">{repeatPenalty.toFixed(2)}</div>
                        </div>
                    </div>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Context size</div>
                        <div class="c2-row-desc">Set by the loaded model. Read-only.</div>
                    </div>
                    <div class="c2-row-control">
                        <span class="c2-readonly-val">{config.context_size >= 1024 ? `${Math.round(config.context_size / 1024)}K` : (config.context_size ?? '—')} tokens</span>
                    </div>
                </div>
