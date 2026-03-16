<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { chat, connect, disconnect } from '$lib/stores/chat';
    import { render } from '$lib/markdown';
    import ChatInput from '$lib/components/ChatInput.svelte';
    import SpecialistCard from '$lib/components/SpecialistCard.svelte';
    import ReflectionBar from '$lib/components/ReflectionBar.svelte';
    import PlanCard from '$lib/components/PlanCard.svelte';
    import SplitPane from '$lib/components/SplitPane.svelte';
    import PreviewPanel from '$lib/components/PreviewPanel.svelte';

    onMount(() => connect());
    onDestroy(() => disconnect());

    let isCode = $derived(
        $chat.route === 'ROUTE_DESIGN' || $chat.route === 'ROUTE_CODE'
    );

    let showPreview = $state(false);
    let previewCode = $derived($chat.response || $chat.streamingText || '');
    let codeExpanded = $state(false);

    // Don't auto-open preview — user opens it from the code attachment
    $effect(() => {
        if ($chat.phase === 'routing') {
            showPreview = false;
            codeExpanded = false;
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

<SplitPane showRight={showPreview}>
    {#snippet left()}
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

                {#if $chat.phase === 'consulting' && $chat.specialistStream}
                    <div class="stream-card specialist">
                        <div class="stream-bar">
                            <span class="stream-indicator specialist"></span>
                            <span class="stream-title">Specialist</span>
                        </div>
                        <pre class="stream-body">{$chat.specialistStream}</pre>
                    </div>
                {/if}

                {#if $chat.specialistData}
                    <SpecialistCard data={$chat.specialistData} />
                {/if}

                {#if ($chat.phase === 'generating' || $chat.phase === 'fixing') && ($chat.streamingThinking || $chat.streamingText)}
                    {#if $chat.streamingThinking}
                        <div class="stream-card muted">
                            <div class="stream-bar">
                                <span class="stream-title">Thinking</span>
                            </div>
                            <pre class="stream-body">{$chat.streamingThinking}</pre>
                        </div>
                    {/if}

                    {#if $chat.streamingText}
                        <div class="stream-card brain">
                            <div class="stream-bar">
                                <span class="stream-indicator brain"></span>
                                <span class="stream-title">{isCode ? 'Generating code' : 'Response'}</span>
                                <span class="stream-meta">{$chat.streamingText.length} chars</span>
                            </div>
                            {#if !isCode}
                                <pre class="stream-body">{$chat.streamingText}</pre>
                            {/if}
                        </div>
                    {/if}
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
                            <p class="response-note">Here's the generated code:</p>
                        {:else}
                            {@html render($chat.response)}
                        {/if}

                        <!-- Code attachment for code routes -->
                        {#if isCode}
                            <div class="code-attachment">
                                <button class="attachment-header" onclick={() => codeExpanded = !codeExpanded}>
                                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                                        <path d="M4.5 1.5L8.5 7L4.5 12.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"
                                            style="transform-origin: center; transform: rotate({codeExpanded ? 90 : 0}deg); transition: transform 200ms ease"/>
                                    </svg>
                                    <span class="attachment-label">Code</span>
                                    <span class="attachment-size">{$chat.response.length} chars</span>
                                </button>
                                {#if codeExpanded}
                                    <pre class="attachment-code">{$chat.response}</pre>
                                {/if}
                                <button class="preview-btn" onclick={() => showPreview = !showPreview}>
                                    {showPreview ? 'Hide preview' : 'Open live preview'}
                                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                                        <path d="M5 3l4 4-4 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
                                    </svg>
                                </button>
                            </div>
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
    {/snippet}

    {#snippet right()}
    {#if showPreview}
        <PreviewPanel
            code={previewCode}
            onClose={() => { showPreview = false; }}
        />
    {/if}
    {/snippet}
</SplitPane>

<style>
    .chat-panel {
        display: flex;
        flex-direction: column;
        height: 100%;
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
        margin-left: auto;
        font-size: 11px;
        font-family: var(--font-mono);
        color: var(--text-muted);
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
