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
    let previewOverride = $state<string | null>(null);
    // During active generation/editing, streamingText takes priority over stale override
    let previewCode = $derived(
        ($chat.phase === 'generating' || $chat.phase === 'fixing' || $chat.phase === 'polishing') && $chat.streamingText
            ? $chat.streamingText
            : previewOverride || $chat.response || $chat.streamingText || ''
    );
    let codeExpanded = $state(false);

    // Trace: expandable pills for each pipeline stage
    let traceOpen = $state<string | null>(null);
    function toggleTrace(key: string) { traceOpen = traceOpen === key ? null : key; }
    let hasThinking = $derived(!!$chat.thinking || !!$chat.draftThinking);
    let hasSpecialistTrace = $derived(!!$chat.specialistStream);
    let hasValidation = $derived(!!$chat.review || $chat.validationIssues.length > 0);

    // Preview panel resize
    let previewWidth = $state(Math.min(Math.round(window.innerWidth * 0.44), 700));
    let resizing = $state(false);
    let previewEntered = $state(false);

    $effect(() => {
        if (!showPreview) previewEntered = false;
    });

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

    let previewVisible = $derived(showPreview && !!previewCode);

    function downloadBlob(code: string, ext: string = 'html') {
        if (!code) return;
        const mime = ext === 'py' ? 'text/x-python' : ext === 'js' ? 'text/javascript' : 'text/html';
        const blob = new Blob([code], { type: mime });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `output.${ext}`;
        a.click();
        URL.revokeObjectURL(url);
    }

    function downloadCode() {
        const ext = $chat.plan?.output_type === 'python_script' ? 'py'
            : $chat.plan?.output_type === 'javascript' ? 'js' : 'html';
        downloadBlob($chat.response, ext);
    }

    function previewHistoryCode(code: string) {
        previewOverride = code;
        showPreview = true;
    }

    // Track whether a generation happened in THIS session (not a stale store from SPA nav)
    let didGenerate = $state(false);

    $effect(() => {
        if ($chat.phase === 'generating' || $chat.phase === 'fixing') {
            didGenerate = true;
        }
        // When new code arrives, clear stale override so preview shows latest
        if ($chat.phase === 'done' && isCode && $chat.response && didGenerate) {
            previewOverride = null;
            didGenerate = false;
        }
        if ($chat.phase === 'routing') {
            // Don't touch showPreview — user controls that
            // If preview is open, keep showing the last code until new code arrives
            if (showPreview && !previewOverride) {
                const lastCode = $chat.response || $chat.streamingText;
                if (lastCode) previewOverride = lastCode;
            }
            codeExpanded = false;
            didGenerate = false;
            traceOpen = null;
        }
    });

    function previewCurrentCode() {
        previewOverride = null;  // clear any history override
        showPreview = !showPreview;
    }

    let messagesEl: HTMLElement;
    let userNearBottom = $state(true);

    function onMessagesScroll() {
        if (!messagesEl) return;
        const gap = messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight;
        userNearBottom = gap < 150;
    }

    $effect(() => {
        $chat.streamingText;
        $chat.specialistStream;
        $chat.response;
        $chat.phase;
        if (messagesEl && userNearBottom) {
            requestAnimationFrame(() => {
                messagesEl.scrollTop = messagesEl.scrollHeight;
            });
        }
    });

    // Always scroll to bottom on new user message
    $effect(() => {
        if ($chat.phase === 'routing') {
            userNearBottom = true;
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
    <div class="chat-panel" class:resizing-layout={resizing} style={previewVisible ? `margin-right: ${previewWidth}px` : ''}>
        <div class="messages" bind:this={messagesEl} onscroll={onMessagesScroll}>
            <div class="messages-inner">
                {#each history() as turn, idx}
                    {#if turn.role === 'user'}
                        {#if turn.attachments && turn.attachments.length > 0}
                            <div class="user-attachments" style="animation-delay: {idx * 30}ms">
                                {#each turn.attachments as att}
                                    {#if att.type === 'image'}
                                        <img src={att.dataUrl} alt={att.name} class="bubble-img" />
                                    {:else}
                                        <span class="file-island">
                                            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                                                <path d="M4 1h5.5L13 4.5V14a1 1 0 01-1 1H4a1 1 0 01-1-1V2a1 1 0 011-1z" stroke="currentColor" stroke-width="1.2"/>
                                                <path d="M9 1v4h4" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
                                            </svg>
                                            {att.name}
                                        </span>
                                    {/if}
                                {/each}
                            </div>
                        {/if}
                        <div class="user-bubble" style="animation-delay: {idx * 30}ms">
                            <p>{turn.content}</p>
                        </div>
                    {:else if turn.isCode}
                        {#if turn.route}
                            <div class="badge-row">
                                <span class="route-badge" style="background: {routeColors[turn.route] || 'var(--accent)'}">
                                    {routeLabels[turn.route] || turn.route}
                                </span>
                            </div>
                        {/if}
                        {#if turn.plan && turn.plan.components.length > 0}
                            <PlanCard plan={turn.plan} />
                        {/if}
                        {#if turn.specialistData}
                            <SpecialistCard data={turn.specialistData} />
                        {/if}
                        <div class="file-card" style="animation-delay: {idx * 30}ms">
                            <div class="file-row">
                                <svg class="file-icon" width="16" height="16" viewBox="0 0 16 16" fill="none">
                                    <path d="M4 1h5.5L13 4.5V14a1 1 0 01-1 1H4a1 1 0 01-1-1V2a1 1 0 011-1z" stroke="currentColor" stroke-width="1.2"/>
                                    <path d="M9 1v4h4" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
                                </svg>
                                <span class="file-name">output.html</span>
                                <span class="file-size">{turn.content.length.toLocaleString()} chars</span>
                                <div class="file-actions">
                                    <button class="file-btn" onclick={() => previewHistoryCode(turn.content)} title="Preview">
                                        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                                            <rect x="1.5" y="2.5" width="11" height="9" rx="1.5" stroke="currentColor" stroke-width="1.2"/>
                                            <path d="M5.5 5.5l3 1.5-3 1.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
                                        </svg>
                                    </button>
                                    <button class="file-btn" onclick={() => downloadBlob(turn.content)} title="Download">
                                        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                                            <path d="M7 2v7.5M4 7.5L7 10.5l3-3" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
                                            <path d="M2 11.5h10" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
                                        </svg>
                                    </button>
                                </div>
                            </div>
                        </div>
                        {#if turn.reflection}
                            <div class="trace-row">
                                <ReflectionBar reflection={turn.reflection} />
                            </div>
                        {/if}
                    {:else}
                        <div class="ai-bubble" style="animation-delay: {idx * 30}ms">
                            {@html render(turn.content)}
                        </div>
                    {/if}
                {/each}

                {#if $chat.phase !== 'idle'}
                    {#each $chat.conversation as turn, i}
                        {#if turn.role === 'user' && i >= history().length}
                            {#if turn.attachments && turn.attachments.length > 0}
                                <div class="user-attachments">
                                    {#each turn.attachments as att}
                                        {#if att.type === 'image'}
                                            <img src={att.dataUrl} alt={att.name} class="bubble-img" />
                                        {:else}
                                            <span class="file-island">
                                                <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                                                    <path d="M4 1h5.5L13 4.5V14a1 1 0 01-1 1H4a1 1 0 01-1-1V2a1 1 0 011-1z" stroke="currentColor" stroke-width="1.2"/>
                                                    <path d="M9 1v4h4" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
                                                </svg>
                                                {att.name}
                                            </span>
                                        {/if}
                                    {/each}
                                </div>
                            {/if}
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

                {#if $chat.warning}
                    <div class="warning-banner">{$chat.warning}</div>
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
                    <div class="stream-card brain">
                        <div class="stream-bar">
                            <span class="stream-indicator brain"></span>
                            <span class="stream-title">
                                {$chat.phase === 'fixing' ? 'Fixing issues' : $chat.editing ? 'Editing code' : isCode ? 'Generating code' : 'Responding'}
                            </span>
                            <span class="stream-meta">
                                {#if $chat.editing}
                                    patching...
                                {:else}
                                    {$chat.streamingText ? `${$chat.streamingText.length} chars` : '...'}
                                {/if}
                            </span>
                            {#if isCode && !$chat.editing && $chat.streamingText.length > 200}
                                <button class="stream-preview-btn" onclick={previewCurrentCode}>
                                    {showPreview ? 'Hide' : 'Preview'}
                                </button>
                            {/if}
                        </div>
                        {#if !isCode && $chat.streamingText}
                            <pre class="stream-body">{$chat.streamingText}</pre>
                        {/if}
                    </div>

                    {#if $chat.streamingThinking}
                        <details class="thinking-details" open>
                            <summary class="thinking-summary">
                                <span class="thinking-dot"></span>
                                Thinking
                                <span class="thinking-len">{$chat.streamingThinking.length} chars</span>
                            </summary>
                            <pre class="thinking-body">{$chat.streamingThinking}</pre>
                        </details>
                    {/if}

                    {#if $chat.draft}
                        <div class="working-card">
                            <span class="dot-pulse"></span>
                            <span class="working-label">Reviewing output...</span>
                        </div>
                    {/if}
                {/if}

                {#if $chat.phase === 'polishing'}
                    <div class="stream-card polish-sc">
                        <div class="stream-bar">
                            <span class="stream-indicator polish-ind"></span>
                            <span class="stream-title">Polishing CSS</span>
                            <span class="stream-meta">
                                {$chat.streamingText ? `${$chat.streamingText.length} chars` : '...'}
                            </span>
                            {#if $chat.streamingText.length > 200}
                                <button class="stream-preview-btn" onclick={previewCurrentCode}>
                                    {showPreview ? 'Hide' : 'Preview'}
                                </button>
                            {/if}
                        </div>
                    </div>
                {/if}

                {#if $chat.phase === 'validating'}
                    <div class="working-card">
                        <span class="dot-pulse"></span>
                        <span class="working-label">Validating output...</span>
                    </div>
                {/if}

                {#if $chat.validationIssues.length > 0 && ($chat.phase === 'validating' || $chat.phase === 'fixing')}
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

                <!-- Text response (non-code routes) -->
                {#if $chat.response && !isCode}
                    <div class="ai-bubble response-bubble">
                        {@html render($chat.response)}
                    </div>
                {/if}

                <!-- Trace pills -->
                {#if hasSpecialistTrace || hasThinking || hasValidation || $chat.reflection}
                    <div class="trace-row">
                        {#if hasSpecialistTrace}
                            <button class="trace-pill" class:open={traceOpen === 'specialist'} onclick={() => toggleTrace('specialist')}>
                                <span class="trace-dot" style="background: var(--specialist)"></span>
                                Specialist
                            </button>
                        {/if}
                        {#if hasThinking}
                            <button class="trace-pill" class:open={traceOpen === 'thinking'} onclick={() => toggleTrace('thinking')}>
                                <span class="trace-dot" style="background: var(--brain)"></span>
                                Thinking
                            </button>
                        {/if}
                        {#if hasValidation}
                            <button class="trace-pill" class:open={traceOpen === 'validation'} onclick={() => toggleTrace('validation')}>
                                <span class="trace-dot" style="background: var(--warning)"></span>
                                Validation
                                {#if $chat.review}
                                    <span class="trace-verdict" class:pass={$chat.review.pass}>{$chat.review.pass ? 'PASS' : 'FAIL'}</span>
                                {/if}
                            </button>
                        {/if}
                        {#if $chat.reflection}
                            <ReflectionBar reflection={$chat.reflection} />
                        {/if}
                    </div>
                {/if}

                {#if traceOpen === 'specialist' && hasSpecialistTrace}
                    <div class="trace-card specialist-trace">
                        <pre class="trace-body">{$chat.specialistStream}</pre>
                    </div>
                {/if}

                {#if traceOpen === 'thinking' && hasThinking}
                    <div class="trace-card thinking-trace">
                        {#if $chat.draftThinking}
                            <div class="trace-section">
                                <span class="trace-label">Draft reasoning</span>
                                <pre class="trace-body">{$chat.draftThinking}</pre>
                            </div>
                        {/if}
                        {#if $chat.thinking}
                            <div class="trace-section">
                                <span class="trace-label">Final reasoning</span>
                                <pre class="trace-body">{$chat.thinking}</pre>
                            </div>
                        {/if}
                    </div>
                {/if}

                {#if traceOpen === 'validation' && hasValidation}
                    <div class="trace-card validation-trace">
                        {#if $chat.validationIssues.length > 0}
                            <ul class="trace-issues">
                                {#each $chat.validationIssues as issue}
                                    <li>{issue}</li>
                                {/each}
                            </ul>
                        {/if}
                        {#if $chat.review?.fix_instructions}
                            <div class="trace-section">
                                <span class="trace-label">Fix instructions</span>
                                <p class="trace-text">{$chat.review.fix_instructions}</p>
                            </div>
                        {/if}
                    </div>
                {/if}

                <!-- Code file attachment (bottom) -->
                {#if $chat.response && isCode}
                    <div class="file-card">
                        <div class="file-row">
                            <svg class="file-icon" width="16" height="16" viewBox="0 0 16 16" fill="none">
                                <path d="M4 1h5.5L13 4.5V14a1 1 0 01-1 1H4a1 1 0 01-1-1V2a1 1 0 011-1z" stroke="currentColor" stroke-width="1.2"/>
                                <path d="M9 1v4h4" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
                            </svg>
                            <span class="file-name">output.{$chat.plan?.output_type === 'python_script' ? 'py' : $chat.plan?.output_type === 'javascript' ? 'js' : 'html'}</span>
                            <span class="file-size">{$chat.response.length.toLocaleString()} chars</span>
                            <div class="file-actions">
                                <button class="file-btn" onclick={() => codeExpanded = !codeExpanded} title="View source">
                                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                                        <path d="M5 3L2 7l3 4M9 3l3 4-3 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
                                    </svg>
                                </button>
                                {#if $chat.plan?.output_type !== 'python_script'}
                                    <button class="file-btn" onclick={previewCurrentCode} title={showPreview ? 'Hide preview' : 'Preview'}>
                                        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                                            <rect x="1.5" y="2.5" width="11" height="9" rx="1.5" stroke="currentColor" stroke-width="1.2"/>
                                            <path d="M5.5 5.5l3 1.5-3 1.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
                                        </svg>
                                    </button>
                                {/if}
                                <button class="file-btn" onclick={downloadCode} title="Download file">
                                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                                        <path d="M7 2v7.5M4 7.5L7 10.5l3-3" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
                                        <path d="M2 11.5h10" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
                                    </svg>
                                </button>
                            </div>
                        </div>
                        {#if codeExpanded}
                            <pre class="attachment-code">{$chat.response}</pre>
                        {/if}
                    </div>
                {/if}
            </div>
        </div>

        <ChatInput />
    </div>

    {#if previewVisible}
        <div
            class="preview-panel"
            class:entering={!previewEntered}
            class:resizing
            style="width: {previewWidth}px"
            onanimationend={() => { previewEntered = true; }}
        >
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
        transition: margin-right 350ms cubic-bezier(0.4, 0, 0.2, 1);
    }
    .chat-panel.resizing-layout {
        transition: none;
    }

    /* Preview panel: fixed right, pushes chat via margin */
    .preview-panel {
        position: fixed;
        top: 56px;
        right: 0;
        bottom: 0;
        z-index: 50;
    }
    .preview-panel.entering {
        animation: slideInRight 350ms cubic-bezier(0.4, 0, 0.2, 1) both;
    }
    .preview-panel.resizing {
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
        scrollbar-width: none;
        -ms-overflow-style: none;
    }
    .messages::-webkit-scrollbar {
        display: none;
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

    .bubble-images {
        display: flex;
        gap: 6px;
        flex-wrap: wrap;
        margin-bottom: 8px;
    }
    .bubble-img {
        max-width: 180px;
        max-height: 120px;
        border-radius: 8px;
        object-fit: cover;
    }

    .user-attachments {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        justify-content: flex-end;
        margin-bottom: 4px;
    }

    .file-island {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-size: 12px;
        font-weight: 500;
        color: var(--text-secondary);
        background: rgba(255, 255, 255, 0.88);
        backdrop-filter: blur(24px);
        -webkit-backdrop-filter: blur(24px);
        border: 1px solid rgba(0, 0, 0, 0.06);
        padding: 6px 12px 6px 8px;
        border-radius: 10px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
    }
    .file-island svg {
        opacity: 0.5;
        flex-shrink: 0;
    }

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
    .ai-bubble :global(h1) { font-size: 20px; font-weight: 700; margin: 20px 0 8px; line-height: 1.3; }
    .ai-bubble :global(h2) { font-size: 17px; font-weight: 600; margin: 18px 0 6px; line-height: 1.35; }
    .ai-bubble :global(h3) { font-size: 15px; font-weight: 600; margin: 14px 0 4px; line-height: 1.4; }
    .ai-bubble :global(h1:first-child),
    .ai-bubble :global(h2:first-child),
    .ai-bubble :global(h3:first-child) { margin-top: 0; }
    .ai-bubble :global(p) { margin-bottom: 10px; }
    .ai-bubble :global(p:last-child) { margin-bottom: 0; }
    .ai-bubble :global(ul),
    .ai-bubble :global(ol) {
        margin: 8px 0 12px;
        padding-left: 22px;
    }
    .ai-bubble :global(li) {
        margin-bottom: 4px;
        line-height: 1.6;
    }
    .ai-bubble :global(li:last-child) { margin-bottom: 0; }
    .ai-bubble :global(li > ul),
    .ai-bubble :global(li > ol) { margin: 4px 0 4px; }
    .ai-bubble :global(strong) { font-weight: 600; }
    .ai-bubble :global(pre) {
        margin: 12px 0;
        overflow-x: auto;
        background: rgba(0, 0, 0, 0.03);
        border: 1px solid rgba(0, 0, 0, 0.04);
        border-radius: var(--radius-sm);
        padding: 12px 14px;
    }
    .ai-bubble :global(code) { font-size: 13px; }
    .ai-bubble :global(p code),
    .ai-bubble :global(li code) {
        background: rgba(0, 0, 0, 0.05);
        padding: 1px 5px;
        border-radius: 4px;
        font-size: 13px;
    }
    .ai-bubble :global(hr) {
        border: none;
        border-top: 1px solid rgba(0, 0, 0, 0.06);
        margin: 16px 0;
    }
    .ai-bubble :global(blockquote) {
        border-left: 3px solid rgba(0, 0, 0, 0.1);
        padding-left: 14px;
        margin: 10px 0;
        color: var(--text-secondary);
    }

    .response-bubble {
        max-width: 85%;
    }

    /* ---- File attachment card (bottom) ---- */
    .file-card {
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: var(--radius);
        overflow: hidden;
        box-shadow: var(--bubble-glow);
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
        max-width: 520px;
    }
    .file-row {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 12px 18px;
    }
    .file-icon {
        color: var(--text-muted);
        flex-shrink: 0;
    }
    .file-name {
        font-size: 14px;
        font-weight: 600;
        color: var(--text);
    }
    .file-size {
        font-size: 11px;
        font-family: var(--font-mono);
        color: var(--text-muted);
    }
    .file-actions {
        margin-left: auto;
        display: flex;
        gap: 4px;
    }
    .file-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 32px;
        height: 32px;
        background: rgba(0, 0, 0, 0.04);
        border: 1px solid rgba(255, 255, 255, 0.5);
        border-radius: var(--radius-sm);
        color: var(--text-muted);
        cursor: pointer;
        transition: all var(--transition);
    }
    .file-btn:hover {
        background: rgba(0, 0, 0, 0.07);
        color: var(--text);
    }
    .attachment-code {
        font-family: var(--font-mono);
        font-size: 12px;
        line-height: 1.55;
        color: var(--text-secondary);
        background: rgba(0, 0, 0, 0.03);
        border-top: 1px solid rgba(255, 255, 255, 0.35);
        padding: 14px 18px;
        white-space: pre-wrap;
        word-break: break-all;
        max-height: 300px;
        overflow-y: auto;
        margin: 0;
        border-radius: 0;
    }

    /* ---- Trace row: pipeline stage pills ---- */
    .trace-row {
        display: flex;
        align-items: stretch;
        gap: 8px;
        flex-wrap: wrap;
    }
    .trace-pill {
        display: flex;
        align-items: center;
        gap: 7px;
        padding: 9px 16px;
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: var(--radius);
        box-shadow: var(--bubble-glow);
        font-family: var(--font-body);
        font-size: 11px;
        font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        cursor: pointer;
        transition: color var(--transition), background var(--transition);
        white-space: nowrap;
        flex-shrink: 0;
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
    }
    .trace-pill:hover { color: var(--text-secondary); }
    .trace-pill.open { color: var(--text-secondary); background: var(--bubble-strong); }
    .trace-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        flex-shrink: 0;
    }
    .trace-verdict {
        font-size: 9px;
        font-weight: 700;
        padding: 1px 6px;
        border-radius: var(--radius-pill);
        background: var(--error);
        color: white;
        letter-spacing: 0.04em;
    }
    .trace-verdict.pass { background: var(--success); }

    /* ---- Trace cards: expandable detail ---- */
    .trace-card {
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: var(--radius);
        overflow: hidden;
        box-shadow: var(--bubble-glow);
        animation: slideUpSpring 300ms var(--spring-soft) both;
        max-width: 560px;
    }
    .trace-card.specialist-trace { border-left: 3px solid var(--specialist); }
    .trace-card.thinking-trace { border-left: 3px solid var(--brain); }
    .trace-card.validation-trace { border-left: 3px solid var(--warning); }
    .trace-section { padding: 14px 18px; }
    .trace-section + .trace-section {
        border-top: 1px solid rgba(255, 255, 255, 0.35);
    }
    .trace-label {
        display: block;
        font-size: 10px;
        font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin-bottom: 8px;
    }
    .trace-body {
        font-family: var(--font-mono);
        font-size: 12px;
        line-height: 1.6;
        color: var(--text-secondary);
        white-space: pre-wrap;
        word-break: break-word;
        margin: 0;
        padding: 14px 18px;
        background: none;
        border: none;
        border-radius: 0;
        max-height: 400px;
        overflow-y: auto;
    }
    .trace-section .trace-body { padding: 0; }
    .trace-issues {
        list-style: none;
        padding: 14px 18px;
        display: flex;
        flex-direction: column;
        gap: 4px;
    }
    .trace-issues li {
        font-size: 13px;
        color: var(--text-secondary);
        padding-left: 14px;
        position: relative;
        line-height: 1.5;
    }
    .trace-issues li::before {
        content: '\00d7';
        position: absolute;
        left: 0;
        color: var(--warning);
        font-weight: bold;
    }
    .trace-text {
        font-size: 13px;
        color: var(--text-secondary);
        line-height: 1.6;
        margin: 0;
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

    .warning-banner {
        max-width: 520px;
        margin: 8px auto;
        padding: 10px 16px;
        background: rgba(255, 180, 50, 0.12);
        border: 1px solid rgba(255, 180, 50, 0.25);
        border-radius: 10px;
        font-size: 13px;
        color: var(--text-secondary);
        text-align: center;
    }

    /* ---- Working/phase indicator cards ---- */
    .working-card {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 10px 16px;
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: var(--radius);
        box-shadow: var(--bubble-glow);
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
        align-self: flex-start;
        max-width: 320px;
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
    .dot-pulse.polish-dot {
        background: var(--success);
        box-shadow: 0 0 6px rgba(52, 199, 89, 0.4);
    }
    .working-card.polish-wc {
        border-left: 3px solid var(--success);
    }

    /* ---- Thinking details (collapsible) ---- */
    .thinking-details {
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-left: 3px solid var(--text-muted);
        border-radius: var(--radius);
        overflow: hidden;
        box-shadow: var(--bubble-glow);
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
        max-width: 560px;
    }
    .thinking-summary {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 14px;
        cursor: pointer;
        font-size: 11px;
        font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        list-style: none;
        user-select: none;
    }
    .thinking-summary::-webkit-details-marker { display: none; }
    .thinking-summary::after {
        content: '\25BE';
        margin-left: auto;
        font-size: 10px;
        transition: transform var(--transition);
    }
    .thinking-details[open] .thinking-summary::after {
        transform: rotate(180deg);
    }
    .thinking-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: var(--text-muted);
        animation: pulse 2s ease-in-out infinite;
    }
    .thinking-len {
        font-family: var(--font-mono);
        font-size: 10px;
        font-weight: 400;
        color: var(--text-muted);
        opacity: 0.7;
    }
    .thinking-body {
        font-family: var(--font-mono);
        font-size: 11px;
        line-height: 1.55;
        color: var(--text-muted);
        white-space: pre-wrap;
        word-break: break-word;
        margin: 0;
        padding: 8px 14px 12px;
        border-top: 1px solid rgba(255, 255, 255, 0.35);
        background: none;
        border-left: none;
        border-right: none;
        border-bottom: none;
        border-radius: 0;
        max-height: 200px;
        overflow-y: auto;
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
        max-width: 520px;
    }
    .stream-card.brain { border-left: 3px solid var(--brain); }
    .stream-card.polish-sc { border-left: 3px solid var(--success); }
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
    .stream-indicator.brain {
        background: var(--brain);
        box-shadow: 0 0 6px rgba(232, 133, 12, 0.4);
    }
    .stream-indicator.polish-ind {
        background: var(--success);
        box-shadow: 0 0 6px rgba(52, 199, 89, 0.4);
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
        padding: 14px 16px;
        box-shadow: var(--bubble-glow);
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
        max-width: 520px;
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
