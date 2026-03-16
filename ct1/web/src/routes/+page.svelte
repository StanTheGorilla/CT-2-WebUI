<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { chat, connect, disconnect } from '$lib/stores/chat';
    import { render } from '$lib/markdown';
    import ChatInput from '$lib/components/ChatInput.svelte';
    import SpecialistCard from '$lib/components/SpecialistCard.svelte';
    import ReflectionBar from '$lib/components/ReflectionBar.svelte';
    import PlanCard from '$lib/components/PlanCard.svelte';
    import PreviewPanel from '$lib/components/PreviewPanel.svelte';

    onMount(() => connect(() => { showPreview = false; didGenerate = false; }));
    onDestroy(() => disconnect());

    let isCode = $derived(
        $chat.route === 'ROUTE_DESIGN' || $chat.route === 'ROUTE_CODE'
    );

    let showPreview = $state(false);
    let previewCode = $derived($chat.response || $chat.streamingText || '');
    let codeExpanded = $state(false);

    // Preview panel resize
    let previewWidth = $state(Math.min(Math.round(window.innerWidth * 0.44), 700));
    let resizing = $state(false);

    function onResizeStart(e: PointerEvent) {
        resizing = true;
        (e.target as HTMLElement).setPointerCapture(e.pointerId);
    }
    function onResizeMove(e: PointerEvent) {
        if (!resizing) return;
        const newW = window.innerWidth - e.clientX;
        previewWidth = Math.max(280, Math.min(newW, window.innerWidth - 320));
    }
    function onResizeEnd() { resizing = false; }

    // Track whether a generation happened in THIS session (not a stale store from SPA nav)
    let didGenerate = $state(false);

    $effect(() => {
        if ($chat.phase === 'generating' || $chat.phase === 'fixing') {
            didGenerate = true;
        }
        if ($chat.phase === 'done' && isCode && $chat.response && didGenerate) {
            showPreview = true;
            didGenerate = false;
        }
        if ($chat.phase === 'routing') {
            showPreview = false;
            codeExpanded = false;
            didGenerate = false;
        }
    });

    let messagesEl: HTMLElement;

    $effect(() => {
        $chat.streamingText;
        $chat.specialistStream;
        $chat.response;
        $chat.phase;
        if (messagesEl) {
            requestAnimationFrame(() => {
                messagesEl.scrollTop = messagesEl.scrollHeight;
            });
        }
    });

    let history = $derived(() => {
        const conv = $chat.conversation;
        if ($chat.phase !== 'idle' && $chat.phase !== 'done') {
            return conv.slice(0, -1);
        }
        let lastUserIdx = -1;
        for (let i = conv.length - 1; i >= 0; i--) {
            if (conv[i].role === 'user') { lastUserIdx = i; break; }
        }
        return lastUserIdx > 0 ? conv.slice(0, lastUserIdx) : [];
    });

    const routeLabels: Record<string, string> = {
        'ROUTE_DESIGN': 'Design',
        'ROUTE_CODE': 'Code',
        'ROUTE_DIRECT': 'Direct',
    };
    const routeColors: Record<string, string> = {
        'ROUTE_DESIGN': 'var(--specialist)',
        'ROUTE_CODE': 'var(--text)',
        'ROUTE_DIRECT': 'var(--success)',
    };
</script>

<div class="page">
    <div class="chat-panel">
        <div class="messages" bind:this={messagesEl}>
            <div class="messages-inner">
                {#each history() as turn, idx}
                    {#if turn.role === 'user'}
                        <div class="user-bubble" style="animation-delay: {idx * 30}ms">
                            <p>{turn.content}</p>
                        </div>
                    {:else}
                        <div class="ai-bubble" style="animation-delay: {idx * 30}ms">
                            {@html render(turn.content)}
                        </div>
                    {/if}
                {/each}

                {#if $chat.phase !== 'idle'}
                    {#each $chat.conversation as turn, i}
                        {#if turn.role === 'user' && i >= history().length}
                            <div class="user-bubble">
                                <p>{turn.content}</p>
                            </div>
                        {/if}
                    {/each}
                {/if}

                {#if $chat.route}
                    <div class="badge-row">
                        <span class="route-badge" style="background: {routeColors[$chat.route] || 'var(--accent)'}">
                            {routeLabels[$chat.route] || $chat.route}
                        </span>
                    </div>
                {/if}

                {#if $chat.plan && $chat.plan.components.length > 0}
                    <PlanCard plan={$chat.plan} />
                {/if}

                <!-- Phase progress cards — always visible during active phases -->
                {#if $chat.phase === 'routing'}
                    <div class="working-card">
                        <span class="dot-pulse"></span>
                        <span class="working-label">Classifying request...</span>
                    </div>
                {/if}

                {#if $chat.phase === 'planning'}
                    <div class="working-card">
                        <span class="dot-pulse"></span>
                        <span class="working-label">Building task plan...</span>
                    </div>
                {/if}

                {#if $chat.phase === 'consulting'}
                    <div class="working-card specialist-wc">
                        <span class="dot-pulse specialist-dot"></span>
                        <span class="working-label">Consulting design specialist...</span>
                    </div>
                {/if}

                {#if $chat.specialistData}
                    <SpecialistCard data={$chat.specialistData} />
                {/if}

                <!-- Generating: show card immediately, fill in as tokens arrive -->
                {#if $chat.phase === 'generating' || $chat.phase === 'fixing'}
                    {#if $chat.streamingThinking}
                        <div class="stream-card muted">
                            <div class="stream-bar">
                                <span class="stream-title">Thinking</span>
                            </div>
                            <pre class="stream-body">{$chat.streamingThinking}</pre>
                        </div>
                    {/if}

                    <div class="stream-card brain">
                        <div class="stream-bar">
                            <span class="stream-indicator brain"></span>
                            <span class="stream-title">
                                {$chat.phase === 'fixing' ? 'Fixing issues' : isCode ? 'Generating code' : 'Responding'}
                            </span>
                            <span class="stream-meta">
                                {$chat.streamingText ? `${$chat.streamingText.length} chars` : '...'}
                            </span>
                            {#if isCode && $chat.streamingText.length > 200}
                                <button class="stream-preview-btn" onclick={() => showPreview = !showPreview}>
                                    {showPreview ? 'Hide' : '⬡ Preview'}
                                </button>
                            {/if}
                        </div>
                        {#if !isCode && $chat.streamingText}
                            <pre class="stream-body">{$chat.streamingText}</pre>
                        {/if}
                    </div>
                {/if}

                {#if $chat.phase === 'validating'}
                    <div class="working-card">
                        <span class="dot-pulse"></span>
                        <span class="working-label">Validating output...</span>
                    </div>
                {/if}

                {#if $chat.validationIssues.length > 0}
                    <div class="validation-card">
                        <div class="validation-bar">
                            <span class="validation-dot"></span>
                            <span>Validation</span>
                            {#if $chat.review}
                                <span class="verdict" class:pass={$chat.review.pass} class:fail={!$chat.review.pass}>
                                    {$chat.review.pass ? 'PASS' : 'FAIL'}
                                </span>
                            {/if}
                        </div>
                        <ul>
                            {#each $chat.validationIssues as issue}
                                <li>{issue}</li>
                            {/each}
                        </ul>
                    </div>
                {/if}

                <!-- ALWAYS show the response in the chat — for ALL routes -->
                {#if $chat.response}
                    <div class="ai-bubble response-bubble">
                        {#if isCode}
                            <!-- Code chip row: expand code + toggle preview -->
                            <div class="code-attachment">
                                <button class="attachment-header" onclick={() => codeExpanded = !codeExpanded}>
                                    <svg width="13" height="13" viewBox="0 0 13 13" fill="none" style="flex-shrink:0">
                                        <path d="M4 2L9 6.5L4 11" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"
                                            style="transform-origin:center;transform:rotate({codeExpanded?90:0}deg);transition:transform 200ms ease"/>
                                    </svg>
                                    <span class="attachment-label">
                                        {$chat.plan?.output_type === 'python_script' ? 'Python' :
                                         $chat.plan?.output_type === 'javascript' ? 'JavaScript' : 'HTML'}
                                    </span>
                                    <span class="attachment-size">{$chat.response.length} chars</span>
                                </button>
                                {#if codeExpanded}
                                    <pre class="attachment-code">{$chat.response}</pre>
                                {/if}
                                {#if $chat.plan?.output_type !== 'python_script'}
                                    <button class="preview-btn" onclick={() => showPreview = !showPreview}>
                                        <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
                                            <rect x="1.5" y="2.5" width="10" height="8" rx="1.5" stroke="currentColor" stroke-width="1.3"/>
                                            <path d="M5 5.5l2.5 1.5L5 8.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
                                        </svg>
                                        {showPreview ? 'Hide preview' : 'Open preview'}
                                    </button>
                                {/if}
                            </div>
                        {:else}
                            {@html render($chat.response)}
                        {/if}
                    </div>
                {/if}

                {#if $chat.reflection}
                    <ReflectionBar reflection={$chat.reflection} />
                {/if}
            </div>
        </div>

        <ChatInput />
    </div>

    {#if showPreview && previewCode}
        <div class="preview-panel" style="width: {previewWidth}px" class:resizing>
            <div
                class="resize-handle"
                role="separator"
                aria-label="Resize preview"
                onpointerdown={onResizeStart}
                onpointermove={onResizeMove}
                onpointerup={onResizeEnd}
            ></div>
            <PreviewPanel
                code={previewCode}
                onClose={() => { showPreview = false; }}
            />
        </div>
    {/if}
</div>

<style>
    /* ---- Page layout ---- */
    .page {
        height: 100%;
        position: relative;
    }

    .chat-panel {
        display: flex;
        flex-direction: column;
        height: 100%;
        /* always full-width — preview floats on top, never shrinks chat */
    }

    /* Preview panel: pure floating overlay, zero shadow bleed */
    .preview-panel {
        position: fixed;
        top: 56px;
        right: 0;
        bottom: 0;
        z-index: 50;
        animation: slideInRight 350ms cubic-bezier(0.4, 0, 0.2, 1) both;
    }
    .preview-panel.resizing {
        animation: none;
        user-select: none;
    }
    .preview-panel.resizing :global(*) {
        pointer-events: none;
    }

    /* Drag handle on left edge */
    .resize-handle {
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        width: 6px;
        cursor: col-resize;
        z-index: 10;
        background: transparent;
        transition: background var(--transition);
    }
    .resize-handle::after {
        content: '';
        position: absolute;
        left: 2px;
        top: 50%;
        transform: translateY(-50%);
        width: 2px;
        height: 32px;
        border-radius: 1px;
        background: rgba(0, 0, 0, 0.12);
        transition: background var(--transition), height var(--transition);
    }
    .resize-handle:hover::after,
    .resizing .resize-handle::after {
        background: rgba(0, 0, 0, 0.28);
        height: 48px;
    }

    .messages {
        flex: 1;
        overflow-y: auto;
        scroll-behavior: smooth;
        position: relative;
        z-index: 1;
    }

    .messages-inner {
        display: flex;
        flex-direction: column;
        gap: 14px;
        max-width: 800px;
        margin: 0 auto;
        padding: 32px 32px 20px;
    }

    /* ---- User bubble — solid dark ---- */
    .user-bubble {
        align-self: flex-end;
        background: var(--text);
        color: #FAFAF9;
        padding: 12px 20px;
        border-radius: 22px 22px 6px 22px;
        max-width: 60%;
        font-size: 15px;
        font-weight: 400;
        line-height: 1.55;
        box-shadow:
            0 2px 8px rgba(0, 0, 0, 0.12),
            0 1px 2px rgba(0, 0, 0, 0.08);
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
    }
    .user-bubble p { margin: 0; }

    /* ---- AI bubble — frosted glass ---- */
    .ai-bubble {
        align-self: flex-start;
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: 6px 22px 22px 22px;
        padding: 16px 20px;
        color: var(--text);
        font-size: 15px;
        line-height: 1.7;
        max-width: 85%;
        box-shadow: var(--bubble-glow);
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
    }
    .ai-bubble :global(pre) { margin: 12px 0; overflow-x: auto; }
    .ai-bubble :global(code) { font-size: 13px; }
    .ai-bubble :global(p) { margin-bottom: 10px; }
    .ai-bubble :global(p:last-child) { margin-bottom: 0; }

    .response-bubble {
        max-width: 90%;
    }
    .response-note {
        font-size: 14px;
        color: var(--text-secondary);
        margin-bottom: 8px;
    }

    /* ---- Code attachment inside AI bubble ---- */
    .code-attachment {
        margin-top: 8px;
        border-top: 1px solid rgba(255, 255, 255, 0.4);
        padding-top: 8px;
    }
    .attachment-header {
        display: flex;
        align-items: center;
        gap: 8px;
        background: none;
        border: none;
        cursor: pointer;
        font-family: var(--font-body);
        color: var(--text-secondary);
        font-size: 13px;
        font-weight: 500;
        padding: 6px 0;
        width: 100%;
        text-align: left;
        transition: color var(--transition);
    }
    .attachment-header:hover { color: var(--text); }
    .attachment-label { font-weight: 600; }
    .attachment-size {
        margin-left: auto;
        font-size: 11px;
        font-family: var(--font-mono);
        color: var(--text-muted);
    }
    .attachment-code {
        font-family: var(--font-mono);
        font-size: 12px;
        line-height: 1.55;
        color: var(--text-secondary);
        background: rgba(0, 0, 0, 0.03);
        border: 1px solid rgba(0, 0, 0, 0.04);
        border-radius: var(--radius-sm);
        padding: 12px 14px;
        white-space: pre-wrap;
        word-break: break-all;
        max-height: 300px;
        overflow-y: auto;
        margin: 4px 0 8px;
    }
    .preview-btn {
        display: flex;
        align-items: center;
        gap: 6px;
        background: rgba(0, 0, 0, 0.04);
        border: 1px solid rgba(255, 255, 255, 0.5);
        border-radius: var(--radius-sm);
        padding: 7px 14px;
        font-family: var(--font-body);
        font-size: 13px;
        font-weight: 500;
        color: var(--text-secondary);
        cursor: pointer;
        transition: all var(--transition);
    }
    .preview-btn:hover {
        background: rgba(0, 0, 0, 0.06);
        color: var(--text);
    }

    /* ---- Route badge ---- */
    .badge-row { display: flex; }
    .route-badge {
        color: white;
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        padding: 4px 16px;
        border-radius: var(--radius-pill);
        animation: springPop var(--spring-duration) var(--spring) both;
    }

    /* ---- Working/phase indicator cards ---- */
    .working-card {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 12px 18px;
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: var(--radius);
        box-shadow: var(--bubble-glow);
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
        align-self: flex-start;
    }
    .working-card.specialist-wc {
        border-left: 3px solid var(--specialist);
    }
    .working-label {
        font-size: 13px;
        font-weight: 500;
        color: var(--text-secondary);
    }
    .dot-pulse {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: var(--brain);
        box-shadow: 0 0 6px rgba(232, 133, 12, 0.4);
        animation: pulse 1.4s ease-in-out infinite;
        flex-shrink: 0;
    }
    .dot-pulse.specialist-dot {
        background: var(--specialist);
        box-shadow: 0 0 6px rgba(155, 109, 255, 0.4);
    }

    /* ---- Stream cards ---- */
    .stream-card {
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: var(--radius);
        overflow: hidden;
        box-shadow: var(--bubble-glow);
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
    }
    .stream-card.specialist { border-left: 3px solid var(--specialist); }
    .stream-card.brain { border-left: 3px solid var(--brain); }
    .stream-card.muted { border-left: 3px solid var(--text-muted); }

    .stream-bar {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 10px 16px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.4);
    }
    .stream-indicator {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        animation: pulse 2s ease-in-out infinite;
    }
    .stream-indicator.specialist {
        background: var(--specialist);
        box-shadow: 0 0 6px rgba(155, 109, 255, 0.4);
    }
    .stream-indicator.brain {
        background: var(--brain);
        box-shadow: 0 0 6px rgba(232, 133, 12, 0.4);
    }
    .stream-title {
        font-size: 12px;
        font-weight: 600;
        color: var(--text-secondary);
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .stream-meta {
        font-size: 11px;
        font-family: var(--font-mono);
        color: var(--text-muted);
        margin-left: auto;
    }
    .stream-preview-btn {
        margin-left: 8px;
        padding: 3px 10px;
        background: rgba(232, 133, 12, 0.1);
        border: 1px solid rgba(232, 133, 12, 0.25);
        border-radius: var(--radius-pill);
        font-family: var(--font-body);
        font-size: 11px;
        font-weight: 600;
        color: var(--brain);
        cursor: pointer;
        transition: all var(--transition);
        flex-shrink: 0;
    }
    .stream-preview-btn:hover {
        background: rgba(232, 133, 12, 0.18);
        border-color: rgba(232, 133, 12, 0.4);
    }
    .stream-body {
        font-family: var(--font-mono);
        font-size: 12px;
        color: var(--text-secondary);
        white-space: pre-wrap;
        word-break: break-all;
        margin: 0;
        padding: 14px 16px;
        line-height: 1.6;
        background: none;
        border: none;
        border-radius: 0;
        max-height: 300px;
        overflow-y: auto;
    }

    /* ---- Validation ---- */
    .validation-card {
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-left: 3px solid var(--warning);
        border-radius: var(--radius);
        padding: 16px 18px;
        box-shadow: var(--bubble-glow);
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
    }
    .validation-bar {
        display: flex;
        align-items: center;
        gap: 10px;
        font-size: 12px;
        font-weight: 600;
        color: var(--warning);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 12px;
    }
    .validation-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: var(--warning);
    }
    .verdict {
        margin-left: auto;
        font-size: 11px;
        padding: 3px 10px;
        border-radius: var(--radius-sm);
        font-weight: 700;
        letter-spacing: 0.04em;
    }
    .verdict.pass { background: var(--success); color: white; }
    .verdict.fail { background: var(--error); color: white; }
    .validation-card ul {
        list-style: none;
        display: flex;
        flex-direction: column;
        gap: 6px;
    }
    .validation-card li {
        font-size: 14px;
        color: var(--text-secondary);
        padding-left: 16px;
        position: relative;
        line-height: 1.5;
    }
    .validation-card li::before {
        content: '\00d7';
        position: absolute;
        left: 0;
        color: var(--warning);
        font-weight: bold;
    }
</style>
