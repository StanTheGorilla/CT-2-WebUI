<script lang="ts">
    import { tick, onMount } from 'svelte';
    import { chat, sendThink, stopGeneration, setMode, revertToTurn, setFeedback, regenerate, type Attachment } from '$lib/stores/chat';
    import { preferences } from '$lib/stores/preferences';
    import { render } from '$lib/markdown';
    import PreviewPanel from './PreviewPanel.svelte';

    // ── Composer state ───────────────────────────────────────────
    let text = $state('');
    let feedEl = $state<HTMLDivElement | null>(null);
    let taEl   = $state<HTMLTextAreaElement | null>(null);
    let hoveredTurn = $state<number | null>(null);
    let contextSize = $state(0);
    let expandedThinking = $state(new Set<number>());
    let expandedSearches = $state(new Set<number>());
    let liveThinkingOpen = $state(false);

    onMount(async () => {
        try {
            const cfg = await (await fetch('/api/config')).json();
            contextSize = cfg.context_size ?? 0;
        } catch {}
    });

    // ── Derived ──────────────────────────────────────────────────
    let isActive  = $derived($chat.phase !== 'idle' && $chat.phase !== 'done');

    // Context usage bar
    let usedTokens = $derived(
        Math.round($chat.conversation.reduce((acc, t) => acc + t.content.length, 0) / 3.5)
        + $chat.tokenCount
    );
    let ctxPct   = $derived(contextSize > 0 ? Math.min(100, Math.round(usedTokens / contextSize * 100)) : 0);
    let ctxLabel = $derived(usedTokens >= 1000 ? `${(usedTokens / 1000).toFixed(1)}K` : `${usedTokens}`);
    let ctxMax   = $derived(contextSize >= 1000 ? `${Math.round(contextSize / 1000)}K` : `${contextSize}`);
    let showCtxBar = $derived(contextSize > 0 && $chat.conversation.length > 0);
    let canSend   = $derived(!isActive && text.trim().length > 0);
    let isDesign  = $derived($chat.modeOverride === 'design');

    // ── Preview panel ────────────────────────────────────────────
    let showPreview = $state(false);
    let previewOverride = $state<string | null>(null);
    let previewWidth = $state(44);
    let isHtmlOutput = $derived($chat.route === 'ROUTE_DESIGN');
    function stripFences(s: string) {
        return s.replace(/^```\w*\s*\n/, '').replace(/\n?```\s*$/, '');
    }
    let previewCode = $derived(
        (isActive && isHtmlOutput && $chat.streamingText)
            ? stripFences($chat.streamingText)
            : previewOverride ?? $chat.response ?? ''
    );
    let previewVisible = $derived(showPreview && !!previewCode);
    function previewHistoryCode(code: string) { previewOverride = code; showPreview = true; }

    const suggestions = [
        { label: 'Design a landing page',  hint: 'a landing page for a focus app called FlowState' },
        { label: 'Write a Python script',  hint: 'a Python script that deduplicates CSV rows by email' },
        { label: 'Explain a concept',      hint: 'how self-attention works, for a non-technical reader' },
        { label: 'Debug code',             hint: 'why my React effect fires twice on mount' },
    ] as const;

    const MODE_ITEMS = ['auto', 'chat', 'design', 'code'] as const;
    const MODE_LABEL: Record<string, string> = { auto: 'Auto', chat: 'Chat', design: 'Design', code: 'Code' };

    const PHASE_LABEL: Record<string, string> = {
        routing: 'Classifying', planning: 'Planning', generating: 'Generating',
        polishing: 'Polishing', refining: 'Refining', validating: 'Validating',
        fixing: 'Fixing', spec_generating: 'Speccing',
        component_generating: 'Building', assembling: 'Assembling',
    };

    // ── Auto scroll ───────────────────────────────────────────────
    $effect(() => {
        void $chat.conversation.length;
        void $chat.streamingText;
        tick().then(() => { if (feedEl) feedEl.scrollTop = feedEl.scrollHeight; });
    });

    // ── Auto resize textarea ─────────────────────────────────────
    $effect(() => {
        void text;
        if (taEl) {
            taEl.style.height = 'auto';
            taEl.style.height = Math.min(220, taEl.scrollHeight) + 'px';
        }
    });

    // Auto-open live thinking panel when new thinking arrives; reset to open after generation
    $effect(() => { if (!isActive) liveThinkingOpen = true; });

    // Auto-open/close preview panel based on route and streaming progress
    $effect(() => {
        if (isActive && isHtmlOutput && $chat.streamingText.length > 300 && !showPreview) {
            showPreview = true; previewOverride = null;
        }
        if (isActive && !isHtmlOutput && showPreview) showPreview = false;
        if (!isActive && isHtmlOutput && $chat.response) previewOverride = null;
    });

    function send() {
        if (!canSend) return;
        const msg = text.trim();
        text = '';
        sendThink(msg);
    }

    function handleKey(e: KeyboardEvent) {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    }

    function pickSuggestion(hint: string) {
        text = hint;
        tick().then(() => taEl?.focus());
    }

    function copyText(t: string) {
        navigator.clipboard.writeText(t).catch(() => {});
    }

    function phaseLabel(p: string): string { return PHASE_LABEL[p] ?? p; }

    function routeLabel(r: string): string {
        if (!r) return '';
        const s = r.replace('ROUTE_', '');
        return s.charAt(0) + s.slice(1).toLowerCase();
    }

    function fileExt(turn: { detectedLang?: string; route?: string }): string {
        if (turn.detectedLang && turn.detectedLang !== 'text') return turn.detectedLang;
        if (turn.route === 'ROUTE_DESIGN') return 'html';
        if (turn.route === 'ROUTE_CODE') return 'py';
        return 'txt';
    }
</script>

<div class="c2-page-frame">
<div class="c2-chat" style:right={previewVisible ? previewWidth + '%' : '0'}>
    <!-- ── Feed ──────────────────────────────────────────────── -->
    <div class="c2-feed scroll" bind:this={feedEl}>
        {#if $chat.conversation.length === 0 && !isActive}
            <!-- Welcome ─────────────────────────────────────────── -->
            <div class="c2-welcome">
                <div class="c2-welcome-logo">
                    <span class="c2-wl-text">ct</span>
                    <span class="c2-wl-dot"></span>
                    <span class="c2-wl-2">2</span>
                </div>
                <div class="c2-welcome-tagline">
                    <span class="c2-tag-line"></span>
                    Local · Private · GPU
                    <span class="c2-tag-line"></span>
                </div>
                <h2 class="c2-welcome-h2">What would you like to build today?</h2>
                <div class="c2-sug-wrap">
                    {#each suggestions as s, i}
                        <button
                            class="c2-sug-pill"
                            style="animation-delay: {i * 60}ms"
                            onclick={() => pickSuggestion(s.hint)}
                        >{s.label}</button>
                    {/each}
                </div>
            </div>
        {:else}
            <!-- Conversation ────────────────────────────────────── -->
            <div class="c2-feed-inner">
                {#each $chat.conversation as turn, i}
                    {#if turn.role === 'user'}
                        <!-- User message -->
                        <div class="c2-turn-user"
                            onmouseenter={() => hoveredTurn = i}
                            onmouseleave={() => hoveredTurn = null}
                        >
                            <div class="c2-user-bubble">{turn.content}</div>
                            <div class="c2-user-foot" class:c2-visible={hoveredTurn === i}>
                                <button class="c2-revert-btn" onclick={() => revertToTurn(i)}>
                                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none">
                                        <path d="M3 7h14a4 4 0 0 1 0 8H7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                        <path d="M7 3L3 7l4 4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                    </svg>
                                    Revert here
                                </button>
                            </div>
                        </div>
                    {:else}
                        <!-- Assistant turn -->
                        <div class="c2-turn-assistant"
                            onmouseenter={() => hoveredTurn = i}
                            onmouseleave={() => hoveredTurn = null}
                        >
                            <span class="c2-rail"></span>
                            <span class="c2-rail-node">
                                <span class="c2-rail-inner"></span>
                            </span>

                            {#if turn.route}
                                <div class="c2-route-tag">
                                    <span class="c2-route-dot"></span>
                                    Routed → {routeLabel(turn.route)}
                                </div>
                            {/if}

                            <!-- Done status line -->
                            <div class="c2-status-line">
                                <svg class="c2-sl-check" width="12" height="12" viewBox="0 0 24 24" fill="none">
                                    <path d="M20 6L9 17l-5-5" stroke="var(--c2-ok)" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
                                </svg>
                                <span>Done</span>
                                {#if turn.reflection?.self_score}
                                    <span class="c2-sl-meta">{turn.reflection.self_score}%</span>
                                {/if}
                            </div>

                            <!-- ── Thinking block ────────────────────────── -->
                            {#if turn.thinking}
                                {@const thOpen = expandedThinking.has(i)}
                                <div class="c2-think-block">
                                    <button
                                        class="c2-think-header"
                                        onclick={() => {
                                            const s = new Set(expandedThinking);
                                            thOpen ? s.delete(i) : s.add(i);
                                            expandedThinking = s;
                                        }}
                                    >
                                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" class="c2-think-chevron" class:c2-think-open={thOpen}>
                                            <path d="M9 18l6-6-6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                        </svg>
                                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                                            <path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3M12 17h.01" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                                            <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="1.4"/>
                                        </svg>
                                        <span>Thinking</span>
                                        <span class="c2-sl-meta">{turn.thinking.length.toLocaleString()} chars</span>
                                    </button>
                                    {#if thOpen}
                                        <pre class="c2-think-body scroll">{turn.thinking}</pre>
                                    {/if}
                                </div>
                            {/if}

                            <!-- ── Search results (completed) ─────────────── -->
                            {#if turn.activeSearches?.length}
                                {#each turn.activeSearches as search, si}
                                    {@const sKey = i * 1000 + si}
                                    {@const sOpen = expandedSearches.has(sKey)}
                                    <div class="c2-search-block">
                                        <button
                                            class="c2-search-header"
                                            onclick={() => {
                                                const s = new Set(expandedSearches);
                                                sOpen ? s.delete(sKey) : s.add(sKey);
                                                expandedSearches = s;
                                            }}
                                        >
                                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                                                <circle cx="11" cy="11" r="8" stroke="currentColor" stroke-width="1.8"/>
                                                <path d="M21 21l-4.35-4.35" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                                            </svg>
                                            <span>Web search</span>
                                            <span class="c2-sl-meta">"{search.query}"</span>
                                            {#if search.results.length > 0}
                                                <span class="c2-sl-meta">· {search.results.length} results</span>
                                            {/if}
                                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" class="c2-think-chevron" class:c2-think-open={sOpen} style="margin-left:auto">
                                                <path d="M9 18l6-6-6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                            </svg>
                                        </button>
                                        {#if sOpen && search.results.length > 0}
                                            <div class="c2-search-results">
                                                {#each search.results as r}
                                                    <a class="c2-search-result" href={r.url} target="_blank" rel="noopener noreferrer">
                                                        <div class="c2-sr-title">{r.title}</div>
                                                        <div class="c2-sr-snippet">{r.snippet}</div>
                                                        <div class="c2-sr-url">{r.url}</div>
                                                    </a>
                                                {/each}
                                            </div>
                                        {/if}
                                    </div>
                                {/each}
                            {/if}

                            <!-- Content -->
                            {#if turn.isCode && turn.content}
                                <!-- Output card -->
                                <div class="c2-output-card">
                                    <div class="c2-output-header">
                                        <span class="c2-output-ext">{fileExt(turn)}</span>
                                        <span class="c2-output-name">{fileExt(turn) === 'html' ? 'output.html' : 'output.' + fileExt(turn)}</span>
                                        <span class="c2-output-chars">{turn.content.length.toLocaleString()} chars</span>
                                        <div style="flex:1"></div>
                                        <button class="c2-out-btn" onclick={() => copyText(turn.content)}>
                                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                                                <rect x="9" y="9" width="13" height="13" rx="2" stroke="currentColor" stroke-width="1.8"/>
                                                <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                                            </svg>
                                            Copy
                                        </button>
                                        <button class="c2-out-btn" onclick={() => {
                                            const b = new Blob([turn.content], { type: 'text/plain' });
                                            const a = document.createElement('a');
                                            a.href = URL.createObjectURL(b);
                                            a.download = 'output.' + fileExt(turn);
                                            a.click();
                                        }}>
                                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                                                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                                            </svg>
                                            Download
                                        </button>
                                        {#if turn.route === 'ROUTE_DESIGN'}
                                            <button class="c2-out-btn" onclick={() => previewHistoryCode(turn.content)}>
                                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                                                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" stroke="currentColor" stroke-width="1.8"/>
                                                    <circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="1.8"/>
                                                </svg>
                                                Preview
                                            </button>
                                        {/if}
                                    </div>
                                    <pre class="c2-output-pre scroll">{turn.content}</pre>
                                </div>
                            {:else if turn.content}
                                <!-- Chat bubble -->
                                <div class="c2-ai-bubble">
                                    <div class="c2-ai-text">{@html render(turn.content)}</div>
                                    <div class="c2-ai-actions" class:c2-visible={hoveredTurn === i}>
                                        <button class="c2-icon-btn" onclick={() => setFeedback(i, 1)}
                                            class:c2-icon-active={turn.feedback === 1} title="Good response">
                                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
                                                <path d="M7 22V11M2 13v7a2 2 0 002 2h13.4a2 2 0 001.98-1.72l1.2-9A2 2 0 0020.6 9H15V5a3 3 0 00-3-3 1 1 0 00-1 1v.5L9 9.07" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                                            </svg>
                                        </button>
                                        <button class="c2-icon-btn" onclick={() => setFeedback(i, -1)}
                                            class:c2-icon-active={turn.feedback === -1} title="Bad response">
                                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
                                                <path d="M17 2v11M22 11V4a2 2 0 00-2-2H6.6a2 2 0 00-1.98 1.72l-1.2 9A2 2 0 003.4 15H9v4a3 3 0 003 3 1 1 0 001-1v-.5L15 14.93" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                                            </svg>
                                        </button>
                                        <button class="c2-icon-btn" onclick={() => regenerate(i)} title="Regenerate">
                                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
                                                <path d="M1 4v6h6M23 20v-6h-6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                                                <path d="M20.49 9A9 9 0 005.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 013.51 15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                                            </svg>
                                        </button>
                                        <button class="c2-icon-btn" onclick={() => copyText(turn.content)} title="Copy">
                                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
                                                <rect x="9" y="9" width="13" height="13" rx="2" stroke="currentColor" stroke-width="1.8"/>
                                                <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                                            </svg>
                                        </button>
                                    </div>
                                </div>
                            {/if}
                        </div>
                    {/if}
                {/each}

                <!-- ── Live generation turn ──────────────────────── -->
                {#if isActive}
                    <div class="c2-turn-assistant">
                        <span class="c2-rail"></span>
                        <span class="c2-rail-node">
                            <span class="c2-rail-inner"></span>
                        </span>

                        {#if $chat.route}
                            <div class="c2-route-tag">
                                <span class="c2-route-dot"></span>
                                Routed → {routeLabel($chat.route)}
                            </div>
                        {/if}

                        <!-- Active status line -->
                        <div class="c2-status-line">
                            <span class="c2-pulse-dot"></span>
                            <span>{phaseLabel($chat.phase)}</span>
                            {#if $chat.tokensPerSec > 0}
                                <span class="c2-sl-meta">{$chat.tokensPerSec} tok/s</span>
                            {/if}
                        </div>

                        <!-- Search activity -->
                        {#each $chat.activeSearches as search}
                            <div class="c2-search-row">
                                {#if !search.done}
                                    <span class="c2-pulse-dot"></span>
                                {:else}
                                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                                        <circle cx="11" cy="11" r="8" stroke="var(--c2-fg-2)" stroke-width="1.8"/>
                                        <path d="M21 21l-4.35-4.35" stroke="var(--c2-fg-2)" stroke-width="1.8" stroke-linecap="round"/>
                                    </svg>
                                {/if}
                                <span>Web search</span>
                                <span class="c2-sl-meta">"{search.query}"</span>
                                {#if search.results.length > 0}
                                    <span class="c2-sl-meta">· {search.results.length} results</span>
                                {/if}
                            </div>
                        {/each}

                        <!-- Live thinking block -->
                        {#if $chat.streamingThinking}
                            <div class="c2-think-block">
                                <button class="c2-think-header" onclick={() => { liveThinkingOpen = !liveThinkingOpen; }}>
                                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" class="c2-think-chevron" class:c2-think-open={liveThinkingOpen}>
                                        <path d="M9 18l6-6-6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                    </svg>
                                    <span class="c2-pulse-dot"></span>
                                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                                        <path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3M12 17h.01" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                                        <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="1.4"/>
                                    </svg>
                                    <span>Thinking</span>
                                    <span class="c2-sl-meta">{$chat.streamingThinking.length.toLocaleString()} chars</span>
                                </button>
                                {#if liveThinkingOpen}
                                    <pre class="c2-think-body scroll">{$chat.streamingThinking}<span class="c2-cursor">|</span></pre>
                                {/if}
                            </div>
                        {/if}

                        <!-- Streaming output card -->
                        {#if $chat.streamingText}
                            <div class="c2-gen-card">
                                <div class="c2-gen-header">
                                    <span class="c2-pulse-dot"></span>
                                    <span class="c2-gen-title">{phaseLabel($chat.phase)}</span>
                                    <span class="c2-sl-meta">{$chat.streamingText.length.toLocaleString()} chars</span>
                                    {#if $chat.tokensPerSec > 0}
                                        <span class="c2-sl-meta">· {$chat.tokensPerSec} tok/s</span>
                                    {/if}
                                    <div style="flex:1"></div>
                                    <button class="c2-stop-btn" onclick={stopGeneration} title="Stop">
                                        <svg width="9" height="9" viewBox="0 0 10 10" fill="currentColor">
                                            <rect width="10" height="10" rx="1.5"/>
                                        </svg>
                                    </button>
                                </div>
                                <div class="c2-gen-body">
                                    {$chat.streamingText}<span class="c2-cursor">|</span>
                                </div>
                            </div>
                        {:else}
                            <!-- Phase-only (routing/planning) — show stop button -->
                            <div class="c2-phase-stop">
                                <button class="c2-revert-btn" onclick={stopGeneration}>Stop</button>
                            </div>
                        {/if}
                    </div>
                {/if}
            </div>
        {/if}
    </div>

    <!-- ── Composer ───────────────────────────────────────────── -->
    <div class="c2-composer-wrap">
        <div class="c2-composer-grad"></div>
        <div class="c2-composer-inner">
            <div class="c2-composer-box">
                <div class="c2-composer-ta-wrap">
                    <textarea
                        bind:this={taEl}
                        bind:value={text}
                        class="c2-ta"
                        placeholder="Ask CT-2 anything…"
                        rows={1}
                        onkeydown={handleKey}
                        disabled={isActive}
                    ></textarea>
                </div>

                <div class="c2-composer-toolbar">
                    <div class="c2-mode-pills">
                        {#each MODE_ITEMS as m}
                            <button
                                class="c2-mode-pill"
                                class:c2-mode-active={$chat.modeOverride === m}
                                onclick={() => setMode(m)}
                                disabled={isActive}
                            >{MODE_LABEL[m]}</button>
                        {/each}

                        <div class="c2-pill-sep"></div>

                        <button
                            class="c2-mode-pill"
                            class:c2-mode-active={$preferences.webSearchEnabled}
                            onclick={() => {
                                import('$lib/stores/preferences').then(m => m.toggleWebSearch());
                            }}
                            disabled={isActive}
                        >
                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
                                <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="1.8"/>
                                <path d="M12 2a14.5 14.5 0 010 20M2 12h20" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                            </svg>
                            Search
                        </button>
                    </div>

                    <div style="flex:1"></div>

                    {#if showCtxBar}
                        <div class="c2-ctx-bar" title="{usedTokens} / {contextSize} tokens used ({ctxPct}%)">
                            <div class="c2-ctx-track">
                                <div
                                    class="c2-ctx-fill"
                                    class:c2-ctx-warn={ctxPct >= 70}
                                    class:c2-ctx-crit={ctxPct >= 90}
                                    style="width: max(5px, {ctxPct}%)"
                                ></div>
                            </div>
                            <span class="c2-ctx-label">{ctxLabel} / {ctxMax}</span>
                        </div>
                    {/if}

                    <button
                        class="c2-send-btn"
                        class:c2-send-active={canSend}
                        onclick={send}
                        disabled={!canSend}
                        aria-label="Send"
                    >
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
                            <path d="M12 19V5M5 12l7-7 7 7" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    </button>
                </div>
            </div>

            <div class="c2-composer-footer">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                Runs locally on your GPU
            </div>
        </div>
    </div>
</div>
<PreviewPanel
    code={previewCode}
    open={previewVisible}
    width={previewWidth}
    onClose={() => showPreview = false}
    onWidthChange={(w) => previewWidth = w}
/>
</div>

<style>
    /* ── Page shell ────────────────────────────────────────────── */
    .c2-page-frame {
        position: absolute;
        inset: 0;
    }

    .c2-chat {
        position: absolute;
        top: 0; left: 0; bottom: 0; right: 0;
        transition: right 340ms cubic-bezier(.22,1.2,.36,1);
        display: flex;
        flex-direction: column;
        font-family: 'Geist', ui-sans-serif, system-ui, sans-serif;
        color: var(--c2-fg-0);
        overflow: hidden;
    }

    /* ── Feed ──────────────────────────────────────────────────── */
    .c2-feed {
        flex: 1;
        overflow-y: auto;
        scrollbar-width: thin;
        scrollbar-color: var(--c2-border-2) transparent;
    }

    .c2-feed-inner {
        max-width: var(--c2-feed-max, 860px);
        margin: 0 auto;
        padding: 32px 24px 16px;
        display: flex;
        flex-direction: column;
        gap: 28px;
    }

    /* ── Welcome ───────────────────────────────────────────────── */
    .c2-welcome {
        flex: 1;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 0 24px;
        min-height: calc(100vh - 200px);
        animation: c2-spring-up 320ms var(--c2-spring, cubic-bezier(.22,1.2,.36,1)) both;
    }

    .c2-welcome-logo {
        font-size: 84px;
        font-weight: 500;
        letter-spacing: -2.4px;
        color: var(--c2-fg-0);
        display: flex;
        align-items: center;
        gap: 6px;
        margin-bottom: 20px;
        line-height: 1;
    }

    .c2-wl-text { color: var(--c2-fg-0); }
    .c2-wl-2 { color: var(--c2-fg-1); }

    .c2-wl-dot {
        display: inline-block;
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: var(--c2-accent);
        opacity: 0.9;
        margin: 0 2px 10px;
        flex-shrink: 0;
    }

    .c2-welcome-tagline {
        font-family: 'Geist Mono', monospace;
        font-size: 10.5px;
        color: var(--c2-fg-3);
        letter-spacing: 1.2px;
        text-transform: uppercase;
        margin-bottom: 22px;
        display: inline-flex;
        align-items: center;
        gap: 10px;
    }

    .c2-tag-line {
        display: inline-block;
        width: 16px;
        height: 1px;
        background: var(--c2-border-2);
    }

    .c2-welcome-h2 {
        font-size: 22px;
        font-weight: 400;
        color: var(--c2-fg-1);
        margin: 0 0 28px;
        letter-spacing: -0.2px;
    }

    .c2-sug-wrap {
        display: flex;
        flex-wrap: wrap;
        justify-content: center;
        gap: 8px;
        max-width: 680px;
    }

    .c2-sug-pill {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 9px 14px;
        border-radius: 999px;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-2);
        color: var(--c2-fg-1);
        font-size: 13px;
        cursor: pointer;
        transition: background 160ms, color 160ms, border-color 160ms;
        animation: c2-spring-up 320ms var(--c2-spring, cubic-bezier(.22,1.2,.36,1)) both;
    }
    .c2-sug-pill:hover {
        background: var(--c2-bg-2);
        color: var(--c2-fg-0);
        border-color: var(--c2-border-3);
    }

    /* ── User message ──────────────────────────────────────────── */
    .c2-turn-user {
        display: flex;
        flex-direction: column;
        align-items: flex-end;
        gap: 4px;
        animation: c2-spring-up 320ms var(--c2-spring, cubic-bezier(.22,1.2,.36,1)) both;
    }

    .c2-user-bubble {
        max-width: 72%;
        background: var(--c2-bg-2);
        color: var(--c2-fg-0);
        padding: 10px 14px;
        border-radius: 14px 14px 4px 14px;
        font-size: 14px;
        line-height: 1.55;
        border: 1px solid var(--c2-border-1);
        white-space: pre-wrap;
        word-break: break-word;
    }

    .c2-user-foot {
        height: 22px;
        opacity: 0;
        transition: opacity 120ms;
        display: flex;
        align-items: center;
    }
    .c2-user-foot.c2-visible { opacity: 1; }

    /* ── Assistant turn ────────────────────────────────────────── */
    .c2-turn-assistant {
        position: relative;
        padding-left: 30px;
        display: flex;
        flex-direction: column;
        gap: 10px;
        animation: c2-spring-up 320ms var(--c2-spring, cubic-bezier(.22,1.2,.36,1)) both;
    }

    .c2-rail {
        position: absolute;
        left: 10px; top: 6px; bottom: 6px;
        width: 2px;
        border-radius: 999px;
        background: var(--c2-border-1);
    }

    .c2-rail-node {
        position: absolute;
        left: 4px; top: 2px;
        width: 14px; height: 14px;
        border-radius: 50%;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-2);
        display: inline-flex;
        align-items: center;
        justify-content: center;
    }

    .c2-rail-inner {
        width: 5px; height: 5px;
        border-radius: 50%;
        background: var(--c2-accent);
    }

    /* ── Route tag ─────────────────────────────────────────────── */
    .c2-route-tag {
        font-family: 'Geist Mono', monospace;
        align-self: flex-start;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        font-size: 11px;
        color: var(--c2-fg-2);
        letter-spacing: 0.6px;
        text-transform: uppercase;
        padding: 4px 10px;
        border-radius: 999px;
        background: var(--c2-bg-2);
        border: 1px solid var(--c2-border-1);
        animation: c2-slide-right 260ms var(--c2-spring, cubic-bezier(.22,1.2,.36,1)) both;
    }

    .c2-route-dot {
        width: 5px; height: 5px;
        border-radius: 50%;
        background: var(--c2-accent);
    }

    /* ── Status line ───────────────────────────────────────────── */
    .c2-status-line {
        display: inline-flex;
        align-items: center;
        gap: 10px;
        font-size: 12.5px;
        color: var(--c2-fg-2);
        padding: 2px 0;
    }

    .c2-sl-check { flex-shrink: 0; }

    .c2-sl-meta {
        font-family: 'Geist Mono', monospace;
        font-size: 11px;
        color: var(--c2-fg-3);
    }

    /* ── Pulsing dot (live) ────────────────────────────────────── */
    .c2-pulse-dot {
        display: inline-block;
        width: 6px; height: 6px;
        border-radius: 50%;
        background: var(--c2-accent);
        flex-shrink: 0;
        animation: c2-pulse-dot 1.8s ease-in-out infinite;
    }

    /* ── Search row ────────────────────────────────────────────── */
    .c2-search-row {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        font-size: 12px;
        color: var(--c2-fg-2);
        padding: 2px 0;
    }

    /* ── Generation card ───────────────────────────────────────── */
    .c2-gen-card {
        align-self: stretch;
        max-width: 820px;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-2);
        border-radius: 10px;
        overflow: hidden;
    }

    .c2-gen-header {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 12px;
        border-bottom: 1px solid var(--c2-border-1);
    }

    .c2-gen-title {
        font-size: 12.5px;
        font-weight: 500;
        color: var(--c2-fg-0);
    }

    .c2-gen-body {
        padding: 12px 14px;
        font-size: 13.5px;
        line-height: 1.6;
        color: var(--c2-fg-0);
        white-space: pre-wrap;
        word-break: break-word;
        max-height: 400px;
        overflow: hidden;
    }

    /* ── Blinking cursor ───────────────────────────────────────── */
    .c2-cursor {
        display: inline-block;
        width: 2px;
        color: var(--c2-accent);
        animation: c2-cursor-blink 1s step-end infinite;
        font-weight: 300;
        opacity: 0.8;
    }

    /* ── Stop button ───────────────────────────────────────────── */
    .c2-stop-btn {
        width: 24px; height: 24px;
        border-radius: 6px;
        background: var(--c2-bg-2);
        color: var(--c2-err);
        border: 1px solid var(--c2-border-1);
        display: inline-flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        transition: background 120ms;
        flex-shrink: 0;
    }
    .c2-stop-btn:hover { background: var(--c2-bg-3); }

    /* ── Phase-only stop ───────────────────────────────────────── */
    .c2-phase-stop {
        display: flex;
        align-items: center;
    }

    /* ── Output card ───────────────────────────────────────────── */
    .c2-output-card {
        align-self: stretch;
        max-width: 820px;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-1);
        border-radius: 10px;
        overflow: hidden;
    }

    .c2-output-header {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 10px;
        border-bottom: 1px solid var(--c2-border-1);
        background: var(--c2-bg-2);
    }

    .c2-output-ext {
        font-family: 'Geist Mono', monospace;
        font-size: 10px;
        color: var(--c2-fg-3);
        text-transform: uppercase;
        letter-spacing: 0.4px;
        padding: 1px 5px;
        border-radius: 3px;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-1);
    }

    .c2-output-name {
        font-family: 'Geist Mono', monospace;
        font-size: 12.5px;
        color: var(--c2-fg-0);
    }

    .c2-output-chars {
        font-family: 'Geist Mono', monospace;
        font-size: 11px;
        color: var(--c2-fg-3);
    }

    .c2-output-pre {
        margin: 0;
        padding: 12px 14px;
        font-family: 'Geist Mono', monospace;
        font-size: 12.5px;
        line-height: 1.6;
        color: var(--c2-fg-0);
        overflow-x: auto;
        scrollbar-width: thin;
        scrollbar-color: var(--c2-border-2) transparent;
        max-height: 420px;
        white-space: pre;
        background: none;
        border: none;
        border-radius: 0;
    }

    .c2-out-btn {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        font-family: 'Geist Mono', monospace;
        font-size: 11px;
        color: var(--c2-fg-2);
        padding: 3px 8px;
        border-radius: 5px;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-1);
        cursor: pointer;
        transition: background 120ms, color 120ms;
    }
    .c2-out-btn:hover { background: var(--c2-bg-2); color: var(--c2-fg-0); }

    /* ── AI bubble ─────────────────────────────────────────────── */
    .c2-ai-bubble {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 6px;
    }

    .c2-ai-text {
        max-width: 100%;
        color: var(--c2-fg-0);
        font-size: 14px;
        line-height: 1.65;
    }

    /* Markdown content inside ai bubble */
    .c2-ai-text :global(p) { margin: 0 0 8px; }
    .c2-ai-text :global(p:last-child) { margin-bottom: 0; }
    .c2-ai-text :global(h1) { font-size: 20px; font-weight: 600; letter-spacing: -0.3px; margin: 12px 0 6px; }
    .c2-ai-text :global(h2) { font-size: 16px; font-weight: 600; margin: 12px 0 6px; }
    .c2-ai-text :global(h3) { font-size: 13.5px; font-weight: 600; color: var(--c2-fg-1); margin: 10px 0 4px; }
    .c2-ai-text :global(ul) { margin: 6px 0; padding-left: 18px; }
    .c2-ai-text :global(li) { margin-bottom: 3px; }
    .c2-ai-text :global(code) {
        font-family: 'Geist Mono', monospace;
        font-size: 0.86em;
        padding: 1px 5px;
        border-radius: 4px;
        background: var(--c2-bg-2);
        border: 1px solid var(--c2-border-1);
    }
    .c2-ai-text :global(pre) {
        margin: 10px 0;
        border-radius: 8px;
        border: 1px solid var(--c2-border-1);
        background: var(--c2-bg-2);
        overflow: hidden;
    }
    .c2-ai-text :global(pre code) {
        display: block;
        padding: 12px 14px;
        font-size: 12.5px;
        line-height: 1.6;
        background: none;
        border: none;
        border-radius: 0;
        overflow-x: auto;
    }
    .c2-ai-text :global(blockquote) {
        border-left: 3px solid var(--c2-border-2);
        margin: 8px 0;
        padding: 4px 12px;
        color: var(--c2-fg-2);
    }
    .c2-ai-text :global(a) { color: var(--c2-accent); text-decoration: none; }
    .c2-ai-text :global(a:hover) { text-decoration: underline; }
    .c2-ai-text :global(strong) { font-weight: 600; color: var(--c2-fg-0); }
    .c2-ai-text :global(em) { font-style: italic; color: var(--c2-fg-1); }
    .c2-ai-text :global(table) { border-collapse: collapse; margin: 8px 0; font-size: 13px; }
    .c2-ai-text :global(th), .c2-ai-text :global(td) {
        border: 1px solid var(--c2-border-1);
        padding: 6px 10px;
    }
    .c2-ai-text :global(th) { background: var(--c2-bg-2); font-weight: 600; }
    .c2-ai-text :global(hr) { border: none; border-top: 1px solid var(--c2-border-1); margin: 12px 0; }

    /* ── AI bubble hover actions ───────────────────────────────── */
    .c2-ai-actions {
        display: flex;
        align-items: center;
        gap: 2px;
        height: 28px;
        opacity: 0;
        transition: opacity 120ms;
    }
    .c2-ai-actions.c2-visible { opacity: 1; }

    .c2-icon-btn {
        width: 26px; height: 26px;
        border-radius: 6px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        color: var(--c2-fg-2);
        background: none;
        border: none;
        cursor: pointer;
        transition: background 100ms, color 100ms;
    }
    .c2-icon-btn:hover { background: var(--c2-bg-2); color: var(--c2-fg-0); }
    .c2-icon-btn.c2-icon-active { color: var(--c2-accent); }

    /* ── Revert button ─────────────────────────────────────────── */
    .c2-revert-btn {
        font-family: 'Geist Mono', monospace;
        display: inline-flex;
        align-items: center;
        gap: 5px;
        font-size: 10.5px;
        color: var(--c2-fg-2);
        padding: 2px 7px;
        border-radius: 5px;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-1);
        cursor: pointer;
        transition: background 120ms, color 120ms;
    }
    .c2-revert-btn:hover { background: var(--c2-bg-2); color: var(--c2-fg-0); }

    /* ── Composer ──────────────────────────────────────────────── */
    .c2-composer-wrap {
        flex-shrink: 0;
        position: relative;
        z-index: 10;
    }

    .c2-composer-grad {
        position: absolute;
        top: -32px; left: 0; right: 0;
        height: 32px;
        background: linear-gradient(to top, var(--c2-bg-0), transparent);
        pointer-events: none;
    }

    .c2-composer-inner {
        max-width: var(--c2-feed-max, 860px);
        margin: 0 auto;
        padding: 0 24px 16px;
    }

    .c2-composer-box {
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-2);
        border-radius: 14px;
        box-shadow: var(--c2-shadow-card, 0 10px 28px -12px oklch(0 0 0 / 0.55));
        overflow: hidden;
    }

    .c2-composer-ta-wrap {
        padding: 14px 16px 8px;
    }

    .c2-ta {
        width: 100%;
        resize: none;
        font-size: 14px;
        line-height: 1.5;
        color: var(--c2-fg-0);
        min-height: 22px;
        max-height: 220px;
        overflow: auto;
        background: transparent;
        border: none;
        outline: none;
        font-family: 'Geist', ui-sans-serif, system-ui, sans-serif;
        scrollbar-width: thin;
        scrollbar-color: var(--c2-border-2) transparent;
    }
    .c2-ta::placeholder { color: var(--c2-fg-3); }
    .c2-ta:disabled { opacity: 0.6; cursor: not-allowed; }

    .c2-composer-toolbar {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 6px 8px 6px 10px;
        border-top: 1px solid var(--c2-border-1);
    }

    .c2-mode-pills {
        display: flex;
        gap: 3px;
        align-items: center;
    }

    .c2-mode-pill {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        height: 24px;
        padding: 0 9px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 500;
        color: var(--c2-fg-2);
        background: none;
        border: 1px solid transparent;
        cursor: pointer;
        transition: background 120ms, color 120ms, border-color 120ms;
    }
    .c2-mode-pill:hover:not(:disabled) {
        background: var(--c2-bg-2);
        color: var(--c2-fg-1);
    }
    .c2-mode-pill.c2-mode-active {
        background: var(--c2-bg-2);
        color: var(--c2-fg-0);
        border-color: var(--c2-border-2);
    }
    .c2-mode-pill:disabled { opacity: 0.5; cursor: not-allowed; }

    .c2-pill-sep {
        width: 1px;
        height: 16px;
        background: var(--c2-border-1);
        margin: 0 4px;
    }

    .c2-composer-hint {
        font-family: 'Geist Mono', monospace;
        font-size: 10.5px;
        color: var(--c2-fg-3);
        white-space: nowrap;
    }

    .c2-send-btn {
        width: 30px; height: 30px;
        border-radius: 8px;
        background: var(--c2-bg-2);
        color: var(--c2-fg-3);
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border: 1px solid var(--c2-border-1);
        cursor: not-allowed;
        transition: background 140ms, color 140ms, border-color 140ms;
        flex-shrink: 0;
    }
    .c2-send-btn.c2-send-active {
        background: var(--c2-accent);
        color: var(--c2-accent-fg, oklch(0.20 0.03 70));
        border-color: var(--c2-accent);
        cursor: pointer;
    }
    .c2-send-btn.c2-send-active:hover {
        opacity: 0.9;
    }

    .c2-composer-footer {
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: 5px;
        padding: 6px 10px 0;
        font-family: 'Geist Mono', monospace;
        font-size: 10.5px;
        color: var(--c2-fg-3);
    }

    /* ── Context bar ──────────────────────────────────────────── */
    .c2-ctx-bar {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        flex-shrink: 0;
    }
    .c2-ctx-track {
        width: 72px;
        height: 4px;
        border-radius: 999px;
        background: var(--c2-bg-3);
        overflow: hidden;
    }
    .c2-ctx-fill {
        height: 100%;
        border-radius: 999px;
        background: var(--c2-fg-3);
        transition: width 400ms ease, background 400ms ease;
        min-width: 5px;
    }
    .c2-ctx-fill.c2-ctx-warn { background: var(--c2-warn); }
    .c2-ctx-fill.c2-ctx-crit { background: var(--c2-err); }
    .c2-ctx-label {
        font-family: 'Geist Mono', monospace;
        font-size: 10.5px;
        color: var(--c2-fg-3);
        white-space: nowrap;
    }

    /* ── Thinking block ───────────────────────────────────────── */
    .c2-think-block {
        align-self: stretch;
        max-width: 820px;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-1);
        border-radius: 8px;
        overflow: hidden;
    }

    .c2-think-header {
        width: 100%;
        display: flex;
        align-items: center;
        gap: 7px;
        padding: 7px 10px;
        background: none;
        border: none;
        cursor: pointer;
        color: var(--c2-fg-2);
        font-size: 12px;
        font-family: 'Geist', ui-sans-serif, system-ui, sans-serif;
        text-align: left;
        transition: background 120ms;
    }
    .c2-think-header:hover { background: var(--c2-bg-2); }

    .c2-think-chevron {
        flex-shrink: 0;
        color: var(--c2-fg-3);
        transition: transform 160ms ease;
    }
    .c2-think-chevron.c2-think-open { transform: rotate(90deg); }

    .c2-think-body {
        margin: 0;
        padding: 8px 14px 12px;
        font-family: 'Geist Mono', monospace;
        font-size: 12px;
        line-height: 1.6;
        color: var(--c2-fg-2);
        white-space: pre-wrap;
        word-break: break-word;
        max-height: 220px;
        overflow-y: auto;
        border-top: 1px solid var(--c2-border-1);
        background: none;
        border-radius: 0;
        border-left: none;
        border-right: none;
        border-bottom: none;
        scrollbar-width: thin;
        scrollbar-color: var(--c2-border-2) transparent;
    }

    /* ── Search block (completed turns) ───────────────────────── */
    .c2-search-block {
        align-self: stretch;
        max-width: 820px;
        background: var(--c2-bg-1);
        border: 1px solid var(--c2-border-1);
        border-radius: 8px;
        overflow: hidden;
    }

    .c2-search-header {
        width: 100%;
        display: flex;
        align-items: center;
        gap: 7px;
        padding: 7px 10px;
        background: none;
        border: none;
        cursor: pointer;
        color: var(--c2-fg-2);
        font-size: 12px;
        font-family: 'Geist', ui-sans-serif, system-ui, sans-serif;
        text-align: left;
        transition: background 120ms;
    }
    .c2-search-header:hover { background: var(--c2-bg-2); }

    .c2-search-results {
        border-top: 1px solid var(--c2-border-1);
        display: flex;
        flex-direction: column;
    }

    .c2-search-result {
        display: flex;
        flex-direction: column;
        gap: 2px;
        padding: 8px 12px;
        border-bottom: 1px solid var(--c2-border-1);
        text-decoration: none;
        transition: background 120ms;
    }
    .c2-search-result:last-child { border-bottom: none; }
    .c2-search-result:hover { background: var(--c2-bg-2); }

    .c2-sr-title {
        font-size: 12.5px;
        font-weight: 500;
        color: var(--c2-fg-0);
        line-height: 1.4;
    }

    .c2-sr-snippet {
        font-size: 12px;
        color: var(--c2-fg-2);
        line-height: 1.5;
    }

    .c2-sr-url {
        font-family: 'Geist Mono', monospace;
        font-size: 10.5px;
        color: var(--c2-fg-3);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    /* ── Utility ───────────────────────────────────────────────── */
    .c2-visible { opacity: 1 !important; }
</style>
