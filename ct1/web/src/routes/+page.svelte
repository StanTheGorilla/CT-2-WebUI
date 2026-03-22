<script lang="ts">
    import { chat, setFeedback, regenerate, undo, setWorkspaceId } from '$lib/stores/chat';
    import { render } from '$lib/markdown';
    import ChatInput from '$lib/components/ChatInput.svelte';
    import SpecialistCard from '$lib/components/SpecialistCard.svelte';

    import PlanCard from '$lib/components/PlanCard.svelte';
    import PreviewPanel from '$lib/components/PreviewPanel.svelte';
    import TerminalPanel from '$lib/components/TerminalPanel.svelte';
    import FileTree from '$lib/components/FileTree.svelte';

    let isComputerRoute = $derived($chat.route === 'ROUTE_COMPUTER');
    let isCode = $derived(
        $chat.route === 'ROUTE_DESIGN' || $chat.route === 'ROUTE_CODE'
    );
    let isComputerMode = $derived(
        $chat.modeOverride === 'computer' || isComputerRoute
    );

    let showPreview = $state(false);
    let previewOverride = $state<string | null>(null);
    let previewCode = $derived(
        ($chat.phase === 'generating' || $chat.phase === 'fixing' || $chat.phase === 'polishing') && $chat.streamingText
            ? $chat.streamingText
            : previewOverride || $chat.response || $chat.streamingText || ''
    );
    let codeExpanded = $state(false);

    let traceOpen = $state<string | null>(null);
    function toggleTrace(key: string) { traceOpen = traceOpen === key ? null : key; }
    let hasThinking = $derived(!!$chat.thinking || !!$chat.draftThinking);
    let hasSpecialistTrace = $derived(!!$chat.specialistStream);
    let hasValidation = $derived(!!$chat.review || $chat.validationIssues.length > 0);

    let previewWidth = $state(Math.min(Math.round(window.innerWidth * 0.44), 700));
    let resizing = $state(false);
    let previewEntered = $state(false);

    // Computer mode state
    let activeWorkspaceId = $state<string | null>(null);
    let showTerminal = $state(false);
    let fileTreeRef = $state<FileTree>();

    $effect(() => {
        // Auto-create workspace when entering computer mode
        if (isComputerMode && !activeWorkspaceId) {
            createDefaultWorkspace();
        }
    });

    async function createDefaultWorkspace() {
        try {
            const res = await fetch('/api/workspaces', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: 'project' }),
            });
            const data = await res.json();
            if (data.id) {
                activeWorkspaceId = data.id;
                showTerminal = true;
                setWorkspaceId(data.id);
            }
        } catch (e) {
            console.error('Workspace create error:', e);
        }
    }

    // Refresh file tree when files are saved
    $effect(() => {
        const lastEvent = $chat.events[$chat.events.length - 1];
        if (lastEvent?.event === 'file_saved' && fileTreeRef) {
            fileTreeRef.refresh();
        }
    });

    function onFileSelect(path: string) {
        // Preview HTML files, otherwise just log for now
        if (path.endsWith('.html') || path.endsWith('.htm')) {
            fetch(`/api/workspaces/${activeWorkspaceId}/files/${path}`)
                .then(r => r.json())
                .then(data => {
                    if (data.content) {
                        previewOverride = data.content;
                        showPreview = true;
                    }
                });
        }
    }

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

    let didGenerate = $state(false);
    let userClosedPreview = $state(false);

    $effect(() => {
        if ($chat.phase === 'generating' || $chat.phase === 'fixing') {
            didGenerate = true;
        }
        // Auto-open preview when streaming code reaches enough content (not computer mode)
        if (($chat.phase === 'generating' || $chat.phase === 'polishing') && isCode && !isComputerRoute && !userClosedPreview) {
            if ($chat.streamingText.length > 300 && !showPreview) {
                showPreview = true;
                previewOverride = null;
            }
        }
        if ($chat.phase === 'done' && isCode && !isComputerRoute && $chat.response && didGenerate) {
            previewOverride = null;
            didGenerate = false;
        }
        if ($chat.phase === 'routing') {
            if (showPreview && !previewOverride) {
                const lastCode = $chat.response || $chat.streamingText;
                if (lastCode) previewOverride = lastCode;
            }
            codeExpanded = false;
            didGenerate = false;
            userClosedPreview = false;
            traceOpen = null;
        }
    });

    function previewCurrentCode() {
        previewOverride = null;
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

    $effect(() => {
        if ($chat.phase === 'routing') {
            userNearBottom = true;
        }
    });

    let history = $derived(() => {
        const conv = $chat.conversation;
        // During generation: hide last user msg (it's in the "active turn" section)
        if ($chat.phase !== 'idle' && $chat.phase !== 'done') {
            return conv.slice(0, -1);
        }
        // Idle = loaded from history or fresh start — show ALL turns
        // (the "active turn" and "response" sections are inactive)
        if ($chat.phase === 'idle') {
            return conv;
        }
        // Done = just finished generating — exclude the latest exchange
        // (it's rendered by the active route/plan/response sections)
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
        'ROUTE_COMPUTER': 'Computer',
    };
    const routeColors: Record<string, string> = {
        'ROUTE_DESIGN': 'var(--specialist)',
        'ROUTE_CODE': 'var(--text)',
        'ROUTE_DIRECT': 'var(--success)',
        'ROUTE_COMPUTER': 'var(--brain)',
    };

    function extOf(name: string): string {
        const i = name.lastIndexOf('.');
        return i >= 0 ? name.slice(i + 1).toLowerCase() : '';
    }

    function extColor(ext: string): string {
        const map: Record<string, string> = {
            html: '#E8850C', htm: '#E8850C',
            css: '#5B8DEF', scss: '#5B8DEF', less: '#5B8DEF',
            js: '#D4AA00', ts: '#3178C6', jsx: '#D4AA00', tsx: '#3178C6',
            py: '#2DA44E',
            json: '#9E9E96', yaml: '#9E9E96', yml: '#9E9E96', toml: '#9E9E96',
            md: '#9E9E96', txt: '#9E9E96',
            svg: '#E8850C', xml: '#9E9E96',
            sql: '#5B8DEF',
            go: '#00ADD8', rs: '#CE422B', java: '#B07219', rb: '#CC342D',
            c: '#555555', cpp: '#F34B7D', h: '#555555', hpp: '#F34B7D',
        };
        return map[ext] || '#9E9E96';
    }

    function outputExt(): string {
        return $chat.plan?.output_type === 'python_script' ? 'py'
            : $chat.plan?.output_type === 'javascript' ? 'js' : 'html';
    }

    /** Parse <!-- FILE: path --> markers from computer mode response */
    function parseFileList(text: string): string[] {
        const matches = text.matchAll(/<!--\s*FILE:\s*(.+?)\s*-->/g);
        return [...matches].map(m => m[1].trim());
    }

    function formatChars(n: number): string {
        return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`;
    }
</script>

<div class="page">
    <div class="chat-panel" class:resizing-layout={resizing} style={(previewVisible || (isComputerMode && showTerminal)) ? `margin-right: ${previewWidth}px` : ''}>
        <div class="messages" bind:this={messagesEl} onscroll={onMessagesScroll}>
            <div class="messages-inner">
                <!-- ==================== HISTORY ==================== -->
                {#each history() as turn, idx}
                    {#if turn.role === 'user'}
                        {#if turn.attachments && turn.attachments.length > 0}
                            <div class="att-row" style="animation-delay: {idx * 30}ms">
                                {#each turn.attachments as att}
                                    {#if att.type === 'image'}
                                        <img src={att.dataUrl} alt={att.name} class="att-img" />
                                    {:else}
                                        {@const ext = extOf(att.name)}
                                        <span class="file-chip">
                                            <span class="ext-dot" style="background: {extColor(ext)}"></span>
                                            <span class="chip-name">{att.name}</span>
                                        </span>
                                    {/if}
                                {/each}
                            </div>
                        {/if}
                        <div class="user-bubble" style="animation-delay: {idx * 30}ms">
                            <p>{turn.content}</p>
                        </div>
                    {:else if turn.isCode && turn.route !== 'ROUTE_COMPUTER'}
                        <div class="bubble-row">
                            {#if turn.route}
                                <div class="route-row">
                                    <span class="route-tag" style="--rc: {routeColors[turn.route] || 'var(--accent)'}">
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
                            <div class="output-card" style="animation-delay: {idx * 30}ms">
                                <div class="output-bar">
                                    <span class="ext-badge" style="--ec: {extColor('html')}">HTML</span>
                                    <span class="output-name">output.html</span>
                                    <span class="output-meta">{formatChars(turn.content.length)}</span>
                                    <div class="output-actions">
                                        <button class="act-btn" onclick={() => previewHistoryCode(turn.content)} title="Preview">
                                            <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M2 3.5A1.5 1.5 0 013.5 2h8A1.5 1.5 0 0113 3.5v8a1.5 1.5 0 01-1.5 1.5h-8A1.5 1.5 0 012 11.5v-8z" stroke="currentColor" stroke-width="1.1"/><path d="M6 6l3 1.5-3 1.5V6z" fill="currentColor" opacity="0.6"/></svg>
                                        </button>
                                        <button class="act-btn" onclick={() => downloadBlob(turn.content)} title="Download">
                                            <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M7.5 2.5v7M5 7.5l2.5 2.5L10 7.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/><path d="M3 11.5h9" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
                                        </button>
                                    </div>
                                </div>
                            </div>
                            {#if turn.reflection && turn.reflection.self_score > 0}
                                {@const hsc = turn.reflection.self_score ?? 0.5}
                                {@const hscColor = hsc >= 0.7 ? 'var(--success)' : hsc >= 0.4 ? 'var(--warning)' : 'var(--error)'}
                                <div class="summary-row">
                                    <span class="summary-chip" style="--sc: {hscColor}">
                                        <span class="summary-dot" style="background: {hscColor}"></span>
                                        {(hsc * 100).toFixed(0)}%
                                    </span>
                                </div>
                            {/if}
                            <div class="feedback-row">
                                <button
                                    class="feedback-btn"
                                    class:active={turn.feedback === 1}
                                    onclick={() => setFeedback(idx, turn.feedback === 1 ? 0 : 1)}
                                    title="Good response"
                                >
                                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                                        <path d="M2 9.5h2V14H2zM4 9.5l2.5-7A1.5 1.5 0 018 1.5v0a1.5 1.5 0 011.5 1.5V6h3.84a1.5 1.5 0 011.48 1.75l-.93 5.5A1.5 1.5 0 0112.41 14.5H4z" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
                                    </svg>
                                </button>
                                <button
                                    class="feedback-btn bad"
                                    class:active={turn.feedback === -1}
                                    onclick={() => setFeedback(idx, turn.feedback === -1 ? 0 : -1)}
                                    title="Bad response"
                                >
                                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                                        <path d="M2 6.5h2V1.5H2zM4 6.5l2.5 7A1.5 1.5 0 008 14.5v0a1.5 1.5 0 001.5-1.5V10h3.84a1.5 1.5 0 001.48-1.75l-.93-5.5A1.5 1.5 0 0012.41 1.5H4z" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
                                    </svg>
                                </button>
                                <button class="feedback-btn regen" onclick={regenerate} title="Regenerate response">
                                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                                        <path d="M1 8a7 7 0 0112.3-4.5M15 8a7 7 0 01-12.3 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                                        <path d="M13 1v3h-3M3 15v-3h3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                                    </svg>
                                </button>
                            </div>
                        </div>
                    {:else if turn.route === 'ROUTE_COMPUTER'}
                        {@const hFiles = parseFileList(turn.content)}
                        <div class="bubble-row">
                            <div class="route-row">
                                <span class="route-tag" style="--rc: var(--brain)">Computer</span>
                            </div>
                            <div class="computer-files-card" style="animation-delay: {idx * 30}ms">
                                <div class="computer-files-header">
                                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                                        <rect x="2" y="3" width="12" height="8" rx="1.5" stroke="currentColor" stroke-width="1.2"/>
                                        <path d="M5.5 14h5M8 11v3" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
                                    </svg>
                                    <span>{hFiles.length} file{hFiles.length !== 1 ? 's' : ''} created</span>
                                </div>
                                {#if hFiles.length > 0}
                                    <div class="computer-files-list">
                                        {#each hFiles as filePath}
                                            {@const hExt = extOf(filePath)}
                                            <span class="computer-file-chip">
                                                <span class="ext-dot" style="background: {extColor(hExt)}"></span>
                                                {filePath}
                                            </span>
                                        {/each}
                                    </div>
                                {/if}
                            </div>
                            <div class="feedback-row">
                                <button class="feedback-btn" class:active={turn.feedback === 1}
                                    onclick={() => setFeedback(idx, turn.feedback === 1 ? 0 : 1)} title="Good response">
                                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M2 9.5h2V14H2zM4 9.5l2.5-7A1.5 1.5 0 018 1.5v0a1.5 1.5 0 011.5 1.5V6h3.84a1.5 1.5 0 011.48 1.75l-.93 5.5A1.5 1.5 0 0112.41 14.5H4z" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>
                                </button>
                                <button class="feedback-btn bad" class:active={turn.feedback === -1}
                                    onclick={() => setFeedback(idx, turn.feedback === -1 ? 0 : -1)} title="Bad response">
                                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M2 6.5h2V1.5H2zM4 6.5l2.5 7A1.5 1.5 0 008 14.5v0a1.5 1.5 0 001.5-1.5V10h3.84a1.5 1.5 0 001.48-1.75l-.93-5.5A1.5 1.5 0 0012.41 1.5H4z" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>
                                </button>
                                <button class="feedback-btn regen" onclick={regenerate} title="Regenerate">
                                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M1 8a7 7 0 0112.3-4.5M15 8a7 7 0 01-12.3 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M13 1v3h-3M3 15v-3h3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
                                </button>
                            </div>
                        </div>
                    {:else}
                        <div class="bubble-row">
                            <div class="ai-bubble" style="animation-delay: {idx * 30}ms">
                                {@html render(turn.content)}
                            </div>
                            <div class="feedback-row">
                                <button
                                    class="feedback-btn"
                                    class:active={turn.feedback === 1}
                                    onclick={() => setFeedback(idx, turn.feedback === 1 ? 0 : 1)}
                                    title="Good response"
                                >
                                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                                        <path d="M2 9.5h2V14H2zM4 9.5l2.5-7A1.5 1.5 0 018 1.5v0a1.5 1.5 0 011.5 1.5V6h3.84a1.5 1.5 0 011.48 1.75l-.93 5.5A1.5 1.5 0 0112.41 14.5H4z" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
                                    </svg>
                                </button>
                                <button
                                    class="feedback-btn bad"
                                    class:active={turn.feedback === -1}
                                    onclick={() => setFeedback(idx, turn.feedback === -1 ? 0 : -1)}
                                    title="Bad response"
                                >
                                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                                        <path d="M2 6.5h2V1.5H2zM4 6.5l2.5 7A1.5 1.5 0 008 14.5v0a1.5 1.5 0 001.5-1.5V10h3.84a1.5 1.5 0 001.48-1.75l-.93-5.5A1.5 1.5 0 0012.41 1.5H4z" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
                                    </svg>
                                </button>
                                <button class="feedback-btn regen" onclick={regenerate} title="Regenerate response">
                                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                                        <path d="M1 8a7 7 0 0112.3-4.5M15 8a7 7 0 01-12.3 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                                        <path d="M13 1v3h-3M3 15v-3h3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                                    </svg>
                                </button>
                            </div>
                        </div>
                    {/if}
                {/each}

                <!-- ==================== ACTIVE TURN ==================== -->
                {#if $chat.phase !== 'idle'}
                    {#each $chat.conversation as turn, i}
                        {#if turn.role === 'user' && i >= history().length}
                            {#if turn.attachments && turn.attachments.length > 0}
                                <div class="att-row">
                                    {#each turn.attachments as att}
                                        {#if att.type === 'image'}
                                            <img src={att.dataUrl} alt={att.name} class="att-img" />
                                        {:else}
                                            {@const ext = extOf(att.name)}
                                            <span class="file-chip">
                                                <span class="ext-dot" style="background: {extColor(ext)}"></span>
                                                <span class="chip-name">{att.name}</span>
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

                <!-- Route badge -->
                {#if $chat.route}
                    <div class="route-row">
                        <span class="route-tag" style="--rc: {routeColors[$chat.route] || 'var(--accent)'}">
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

                <!-- ==================== PIPELINE STEPS ==================== -->
                {#if $chat.phase === 'routing'}
                    <div class="step">
                        <span class="step-dot pulse"></span>
                        <span class="step-text">Classifying...</span>
                    </div>
                {/if}

                {#if $chat.phase === 'planning'}
                    <div class="step">
                        <span class="step-dot pulse"></span>
                        <span class="step-text">Planning...</span>
                    </div>
                {/if}

                {#if $chat.phase === 'consulting'}
                    <div class="step specialist">
                        <span class="step-dot pulse specialist"></span>
                        <span class="step-text">Consulting specialist...</span>
                    </div>
                {/if}

                {#if $chat.specialistData}
                    <SpecialistCard data={$chat.specialistData} />
                {/if}

                <!-- ==================== GENERATION ==================== -->
                {#if $chat.phase === 'generating' || $chat.phase === 'fixing'}
                    <div class="gen-card" class:fixing={$chat.phase === 'fixing'}>
                        <div class="gen-bar">
                            <span class="gen-indicator"></span>
                            <span class="gen-title">
                                {$chat.phase === 'fixing' ? 'Fixing' : $chat.editing ? 'Editing' : isComputerRoute ? 'Creating files' : isCode ? 'Generating' : 'Writing'}
                            </span>
                            <span class="gen-meta">
                                {#if $chat.editing}
                                    patching
                                {:else if $chat.streamingText}
                                    {formatChars($chat.streamingText.length)}
                                {:else}
                                    ...
                                {/if}
                            </span>
                            {#if isCode && !isComputerRoute && !$chat.editing && $chat.streamingText.length > 200}
                                <button class="preview-btn" onclick={previewCurrentCode}>
                                    {showPreview ? 'Hide' : 'Preview'}
                                </button>
                            {/if}
                        </div>
                        {#if !isCode && !isComputerRoute && $chat.streamingText}
                            <div class="gen-body">
                                {@html render($chat.streamingText)}
                            </div>
                        {/if}
                    </div>

                    {#if $chat.streamingThinking}
                        <details class="think-block" open>
                            <summary class="think-header">
                                <span class="think-dot"></span>
                                Thinking
                                <span class="think-meta">{formatChars($chat.streamingThinking.length)}</span>
                            </summary>
                            <pre class="think-body">{$chat.streamingThinking}</pre>
                        </details>
                    {/if}
                {/if}

                {#if $chat.phase === 'polishing' && !isComputerRoute}
                    <div class="step polish">
                        <span class="step-dot pulse polish"></span>
                        <span class="step-text">Polishing CSS...</span>
                        <span class="step-meta">{formatChars($chat.streamingText.length)}</span>
                        {#if $chat.streamingText.length > 200}
                            <button class="preview-btn sm" onclick={previewCurrentCode}>
                                {showPreview ? 'Hide' : 'Preview'}
                            </button>
                        {/if}
                    </div>
                {/if}

                {#if $chat.phase === 'validating' && !isComputerRoute}
                    <div class="step">
                        <span class="step-dot pulse"></span>
                        <span class="step-text">Validating...</span>
                    </div>
                {/if}

                {#if !isComputerRoute && $chat.validationIssues.length > 0 && ($chat.phase === 'validating' || $chat.phase === 'fixing')}
                    <div class="issues-card">
                        <div class="issues-header">
                            <span class="issues-label">Issues found</span>
                            {#if $chat.review}
                                <span class="verdict" class:pass={$chat.review.pass}>{$chat.review.pass ? 'PASS' : 'FAIL'}</span>
                            {/if}
                        </div>
                        <ul class="issues-list">
                            {#each $chat.validationIssues as issue}
                                <li>{issue}</li>
                            {/each}
                        </ul>
                    </div>
                {/if}

                <!-- ==================== TEXT RESPONSE ==================== -->
                {#if $chat.response && !isCode && !isComputerRoute}
                    <div class="ai-bubble">
                        {@html render($chat.response)}
                    </div>
                {/if}

                <!-- ==================== POST-RESPONSE ==================== -->

                <!-- Output file card (code responses — not computer mode) -->
                {#if $chat.response && isCode && !isComputerRoute}
                    {@const ext = outputExt()}
                    <div class="output-card">
                        <div class="output-bar">
                            <span class="ext-badge" style="--ec: {extColor(ext)}">{ext.toUpperCase()}</span>
                            <span class="output-name">output.{ext}</span>
                            <span class="output-meta">{formatChars($chat.response.length)}</span>
                            <div class="output-actions">
                                <button class="act-btn" onclick={() => codeExpanded = !codeExpanded} title="Source" class:active={codeExpanded}>
                                    <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M5.5 3.5L2.5 7.5l3 4M9.5 3.5l3 4-3 4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                                </button>
                                {#if ext !== 'py'}
                                    <button class="act-btn" onclick={previewCurrentCode} title={showPreview ? 'Hide preview' : 'Preview'} class:active={showPreview}>
                                        <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M2 3.5A1.5 1.5 0 013.5 2h8A1.5 1.5 0 0113 3.5v8a1.5 1.5 0 01-1.5 1.5h-8A1.5 1.5 0 012 11.5v-8z" stroke="currentColor" stroke-width="1.1"/><path d="M6 6l3 1.5-3 1.5V6z" fill="currentColor" opacity="0.6"/></svg>
                                    </button>
                                {/if}
                                <button class="act-btn" onclick={downloadCode} title="Download">
                                    <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M7.5 2.5v7M5 7.5l2.5 2.5L10 7.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/><path d="M3 11.5h9" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
                                </button>
                                {#if $chat.undoStack.length > 0}
                                    <button class="act-btn undo" onclick={undo} title="Undo last edit ({$chat.undoStack.length})">
                                        <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M3 7.5h9M3 7.5l3-3M3 7.5l3 3" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                                    </button>
                                {/if}
                            </div>
                        </div>
                        {#if codeExpanded}
                            <pre class="output-source">{$chat.response}</pre>
                        {/if}
                    </div>
                {/if}

                <!-- Computer mode: files-created card -->
                {#if $chat.response && isComputerRoute}
                    {@const createdFiles = parseFileList($chat.response)}
                    <div class="computer-files-card">
                        <div class="computer-files-header">
                            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                                <rect x="2" y="3" width="12" height="8" rx="1.5" stroke="currentColor" stroke-width="1.2"/>
                                <path d="M5.5 14h5M8 11v3" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
                            </svg>
                            <span>{createdFiles.length} file{createdFiles.length !== 1 ? 's' : ''} created</span>
                        </div>
                        {#if createdFiles.length > 0}
                            <div class="computer-files-list">
                                {#each createdFiles as filePath}
                                    {@const ext = extOf(filePath)}
                                    <span class="computer-file-chip">
                                        <span class="ext-dot" style="background: {extColor(ext)}"></span>
                                        {filePath}
                                    </span>
                                {/each}
                            </div>
                        {/if}
                        <button class="act-btn" onclick={() => codeExpanded = !codeExpanded} title="View raw output" class:active={codeExpanded}>
                            <svg width="14" height="14" viewBox="0 0 15 15" fill="none"><path d="M5.5 3.5L2.5 7.5l3 4M9.5 3.5l3 4-3 4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                        </button>
                        {#if codeExpanded}
                            <pre class="output-source">{$chat.response}</pre>
                        {/if}
                    </div>
                {/if}

                <!-- Summary + Trace -->
                {#if hasSpecialistTrace || hasThinking || hasValidation || ($chat.reflection && $chat.reflection.self_score > 0)}
                    <div class="trace-row">
                        {#if $chat.reflection && $chat.reflection.self_score > 0}
                            {@const sc = $chat.reflection.self_score ?? 0.5}
                            {@const scColor = sc >= 0.7 ? 'var(--success)' : sc >= 0.4 ? 'var(--warning)' : 'var(--error)'}
                            <button class="trace-pill score" class:open={traceOpen === 'reflection'} onclick={() => toggleTrace('reflection')} style="--tc: {scColor}">
                                <span class="trace-dot" style="background: {scColor}"></span>
                                {(sc * 100).toFixed(0)}%
                            </button>
                        {/if}
                        {#if hasThinking}
                            <button class="trace-pill" class:open={traceOpen === 'thinking'} onclick={() => toggleTrace('thinking')} style="--tc: var(--brain)">
                                <span class="trace-dot" style="background: var(--brain)"></span>
                                Thinking
                            </button>
                        {/if}
                        {#if hasSpecialistTrace}
                            <button class="trace-pill" class:open={traceOpen === 'specialist'} onclick={() => toggleTrace('specialist')} style="--tc: var(--specialist)">
                                <span class="trace-dot" style="background: var(--specialist)"></span>
                                Specialist
                            </button>
                        {/if}
                        {#if hasValidation}
                            <button class="trace-pill" class:open={traceOpen === 'validation'} onclick={() => toggleTrace('validation')} style="--tc: var(--warning)">
                                <span class="trace-dot" style="background: var(--warning)"></span>
                                Validation
                                {#if $chat.review}
                                    <span class="trace-verdict" class:pass={$chat.review.pass}>{$chat.review.pass ? 'OK' : 'FAIL'}</span>
                                {/if}
                            </button>
                        {/if}
                    </div>
                {/if}

                {#if traceOpen === 'thinking' && hasThinking}
                    <div class="trace-card" style="--tbc: var(--brain)">
                        {#if $chat.draftThinking}
                            <div class="trace-section">
                                <span class="trace-label">Draft reasoning</span>
                                <pre class="trace-pre">{$chat.draftThinking}</pre>
                            </div>
                        {/if}
                        {#if $chat.thinking}
                            <div class="trace-section">
                                <span class="trace-label">Final reasoning</span>
                                <pre class="trace-pre">{$chat.thinking}</pre>
                            </div>
                        {/if}
                    </div>
                {/if}

                {#if traceOpen === 'specialist' && hasSpecialistTrace}
                    <div class="trace-card" style="--tbc: var(--specialist)">
                        <pre class="trace-pre">{$chat.specialistStream}</pre>
                    </div>
                {/if}

                {#if traceOpen === 'validation' && hasValidation}
                    <div class="trace-card" style="--tbc: var(--warning)">
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

                {#if traceOpen === 'reflection' && $chat.reflection?.lesson}
                    <div class="trace-card" style="--tbc: var(--success)">
                        <div class="trace-section">
                            <span class="trace-label">Lesson</span>
                            <p class="trace-text">{$chat.reflection.lesson}</p>
                        </div>
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
                onClose={() => { showPreview = false; userClosedPreview = true; }}
            />
        </div>
    {/if}

    {#if isComputerMode && activeWorkspaceId && showTerminal}
        <div
            class="preview-panel computer-panel"
            class:entering={!previewEntered}
            class:resizing
            style="width: {previewWidth}px"
            onanimationend={() => { previewEntered = true; }}
        >
            <div
                class="resize-handle"
                role="separator"
                aria-label="Resize panel"
                onpointerdown={onResizeStart}
                onpointermove={onResizeMove}
                onpointerup={onResizeEnd}
            ></div>
            <div class="computer-split">
                <div class="computer-files">
                    <FileTree
                        bind:this={fileTreeRef}
                        workspaceId={activeWorkspaceId}
                        {onFileSelect}
                    />
                </div>
                <div class="computer-term">
                    <TerminalPanel
                        workspaceId={activeWorkspaceId}
                        onClose={() => { showTerminal = false; }}
                        externalOutput={$chat.terminalOutput}
                    />
                </div>
            </div>
        </div>
    {/if}
</div>

<style>
    /* ================================================================
       PAGE LAYOUT
       ================================================================ */
    .page { height: 100%; position: relative; }

    .chat-panel {
        display: flex;
        flex-direction: column;
        height: 100%;
        transition: margin-right 350ms cubic-bezier(0.4, 0, 0.2, 1);
    }
    .chat-panel.resizing-layout { transition: none; }

    .preview-panel {
        position: fixed;
        top: 56px; right: 0; bottom: 0;
        z-index: 50;
    }
    .preview-panel.entering {
        animation: slideInRight 350ms cubic-bezier(0.4, 0, 0.2, 1) both;
    }
    .preview-panel.resizing { user-select: none; }
    .preview-panel.resizing :global(*) { pointer-events: none; }

    .resize-handle {
        position: absolute; left: 0; top: 0; bottom: 0;
        width: 6px; cursor: col-resize; z-index: 10;
        background: transparent;
        transition: background var(--transition);
    }
    .resize-handle::after {
        content: '';
        position: absolute; left: 2px; top: 50%; transform: translateY(-50%);
        width: 2px; height: 32px; border-radius: 1px;
        background: rgba(0, 0, 0, 0.10);
        transition: background var(--transition), height var(--transition);
    }
    .resize-handle:hover::after, .resizing .resize-handle::after {
        background: rgba(0, 0, 0, 0.24); height: 48px;
    }

    .messages {
        flex: 1; overflow-y: auto; scroll-behavior: smooth;
        position: relative; z-index: 1;
        scrollbar-width: none; -ms-overflow-style: none;
    }
    .messages::-webkit-scrollbar { display: none; }

    .messages-inner {
        display: flex; flex-direction: column; gap: 12px;
        max-width: 780px; margin: 0 auto;
        padding: 28px 28px 24px;
    }

    /* ================================================================
       USER BUBBLE
       ================================================================ */
    .user-bubble {
        align-self: flex-end;
        background: #1A1A1A;
        color: #FAFAF9;
        padding: 11px 20px;
        border-radius: 20px 20px 6px 20px;
        max-width: 60%;
        font-size: 14.5px;
        font-weight: 400;
        line-height: 1.55;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.10), 0 1px 2px rgba(0, 0, 0, 0.06);
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
    }
    :global([data-theme="dark"]) .user-bubble {
        background: rgba(255, 255, 255, 0.14);
        color: #F0F0F0;
        box-shadow: 0 2px 12px rgba(0, 0, 0, 0.4);
    }
    .user-bubble p { margin: 0; }

    /* ================================================================
       ATTACHMENTS (in messages)
       ================================================================ */
    .att-row {
        display: flex; gap: 8px; flex-wrap: wrap;
        justify-content: flex-end;
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
    }

    .att-img {
        max-width: 200px; max-height: 140px;
        border-radius: 12px; object-fit: cover;
        border: 1px solid var(--border-subtle);
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
    }

    .file-chip {
        display: inline-flex; align-items: center; gap: 7px;
        padding: 5px 14px 5px 10px;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 20px;
        box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
        font-size: 12px;
        font-weight: 500;
        color: var(--text-secondary);
        transition: box-shadow var(--transition);
    }
    .file-chip:hover { box-shadow: 0 2px 8px rgba(0, 0, 0, 0.07); }

    .ext-dot {
        width: 7px; height: 7px;
        border-radius: 50%; flex-shrink: 0;
    }

    .chip-name {
        max-width: 140px;
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }

    /* ================================================================
       AI BUBBLE
       ================================================================ */
    .ai-bubble {
        align-self: flex-start;
        background: var(--bubble);
        backdrop-filter: var(--bubble-blur);
        -webkit-backdrop-filter: var(--bubble-blur);
        border: var(--bubble-border);
        border-radius: 6px 20px 20px 20px;
        padding: 16px 20px;
        color: var(--text);
        font-size: 14.5px;
        line-height: 1.7;
        max-width: 85%;
        box-shadow: var(--bubble-glow);
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
    }
    .ai-bubble :global(h1) { font-size: 19px; font-weight: 700; margin: 18px 0 6px; line-height: 1.3; }
    .ai-bubble :global(h2) { font-size: 16px; font-weight: 600; margin: 16px 0 5px; line-height: 1.35; }
    .ai-bubble :global(h3) { font-size: 14.5px; font-weight: 600; margin: 12px 0 4px; line-height: 1.4; }
    .ai-bubble :global(h1:first-child),
    .ai-bubble :global(h2:first-child),
    .ai-bubble :global(h3:first-child) { margin-top: 0; }
    .ai-bubble :global(p) { margin-bottom: 8px; }
    .ai-bubble :global(p:last-child) { margin-bottom: 0; }
    .ai-bubble :global(ul), .ai-bubble :global(ol) { margin: 6px 0 10px; padding-left: 20px; }
    .ai-bubble :global(li) { margin-bottom: 3px; line-height: 1.6; }
    .ai-bubble :global(li:last-child) { margin-bottom: 0; }
    .ai-bubble :global(li > ul), .ai-bubble :global(li > ol) { margin: 3px 0; }
    .ai-bubble :global(strong) { font-weight: 600; }
    .ai-bubble :global(pre) {
        margin: 10px 0; overflow-x: auto;
        background: var(--code-bg);
        border: 1px solid var(--border-subtle);
        border-radius: 8px; padding: 11px 14px;
    }
    .ai-bubble :global(code) { font-size: 12.5px; }
    .ai-bubble :global(p code), .ai-bubble :global(li code) {
        background: var(--code-inline-bg); padding: 1px 5px; border-radius: 4px; font-size: 12.5px;
    }
    .ai-bubble :global(hr) { border: none; border-top: 1px solid var(--border-subtle); margin: 14px 0; }
    .ai-bubble :global(blockquote) {
        border-left: 3px solid var(--border);
        padding-left: 14px; margin: 8px 0;
        color: var(--text-secondary);
    }
    /* Markdown tables */
    .ai-bubble :global(table) {
        width: 100%; border-collapse: collapse; margin: 12px 0;
        font-size: 13px; line-height: 1.5;
        display: block; overflow-x: auto;
    }
    .ai-bubble :global(thead),
    .ai-bubble :global(tbody) { display: table; width: 100%; table-layout: fixed; }
    .ai-bubble :global(thead) {
        background: var(--accent-subtle);
    }
    .ai-bubble :global(th) {
        font-weight: 600; text-align: left;
        padding: 8px 12px;
        border-bottom: 2px solid var(--border);
        color: var(--text);
        word-wrap: break-word; overflow-wrap: break-word;
    }
    .ai-bubble :global(td) {
        padding: 6px 12px;
        border-bottom: 1px solid var(--border-subtle);
        color: var(--text-secondary);
        vertical-align: top;
        word-wrap: break-word; overflow-wrap: break-word;
    }
    .ai-bubble :global(tr:last-child td) { border-bottom: none; }
    .ai-bubble :global(tr:hover td) { background: var(--accent-subtle); }

    /* ================================================================
       ROUTE TAG
       ================================================================ */
    .route-row { display: flex; }
    .route-tag {
        color: white;
        font-size: 10px; font-weight: 700;
        text-transform: uppercase; letter-spacing: 0.08em;
        padding: 3px 14px;
        border-radius: var(--radius-pill);
        background: var(--rc);
        animation: springPop var(--spring-duration) var(--spring) both;
    }

    .warning-banner {
        max-width: 520px; margin: 4px auto;
        padding: 8px 14px;
        background: rgba(255, 180, 50, 0.10);
        border: 1px solid rgba(255, 180, 50, 0.20);
        border-radius: 10px;
        font-size: 12.5px; color: var(--text-secondary); text-align: center;
    }

    /* ================================================================
       PIPELINE STEPS (slim inline indicators)
       ================================================================ */
    .step {
        display: flex; align-items: center; gap: 10px;
        padding: 7px 14px;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 12px;
        box-shadow: 0 1px 4px rgba(0, 0, 0, 0.03);
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
        align-self: flex-start;
        max-width: 300px;
    }
    .step.specialist { border-left: 2px solid var(--specialist); }
    .step.polish { border-left: 2px solid var(--success); }

    .step-dot {
        width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0;
        background: var(--brain);
    }
    .step-dot.specialist { background: var(--specialist); }
    .step-dot.polish { background: var(--success); }
    .step-dot.pulse { animation: pulse 1.4s ease-in-out infinite; }

    .step-text {
        font-size: 12.5px; font-weight: 500;
        color: var(--text-secondary);
        letter-spacing: 0.01em;
    }
    .step-meta {
        font-size: 11px; font-family: var(--font-mono);
        color: var(--text-muted); margin-left: auto;
    }

    /* ================================================================
       GENERATION CARD
       ================================================================ */
    .gen-card {
        background: var(--surface);
        border: 1px solid var(--border);
        border-left: 2px solid var(--brain);
        border-radius: var(--radius);
        overflow: hidden;
        box-shadow: var(--bubble-glow);
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
        max-width: 560px;
    }
    .gen-card.fixing { border-left-color: var(--warning); }

    .gen-bar {
        display: flex; align-items: center; gap: 10px;
        padding: 9px 16px;
    }
    .gen-indicator {
        width: 6px; height: 6px; border-radius: 50%;
        background: var(--brain);
        box-shadow: 0 0 8px rgba(232, 133, 12, 0.35);
        animation: pulse 1.4s ease-in-out infinite;
    }
    .gen-title {
        font-size: 12px; font-weight: 600;
        color: var(--text-secondary);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .gen-meta {
        font-size: 11px; font-family: var(--font-mono);
        color: var(--text-muted); margin-left: auto;
    }

    .gen-body {
        padding: 12px 18px;
        border-top: 1px solid var(--border-subtle);
        font-size: 14.5px;
        line-height: 1.65;
        color: var(--text);
        max-height: 600px; overflow-y: auto;
    }
    .gen-body :global(p) { margin-bottom: 8px; }
    .gen-body :global(p:last-child) { margin-bottom: 0; }
    .gen-body :global(ul), .gen-body :global(ol) { margin: 6px 0 10px; padding-left: 20px; }
    .gen-body :global(li) { margin-bottom: 3px; line-height: 1.6; }
    .gen-body :global(strong) { font-weight: 600; }
    .gen-body :global(code) { font-size: 12.5px; background: var(--code-inline-bg); padding: 1px 4px; border-radius: 3px; }
    .gen-body :global(pre) {
        margin: 10px 0; overflow-x: auto;
        background: var(--code-bg);
        border: 1px solid var(--border-subtle);
        border-radius: 8px; padding: 11px 14px;
    }
    .gen-body :global(table) {
        width: 100%; border-collapse: collapse; margin: 12px 0;
        font-size: 13px; line-height: 1.5;
    }
    .gen-body :global(th) {
        font-weight: 600; text-align: left; padding: 8px 12px;
        border-bottom: 2px solid var(--border); color: var(--text);
        background: var(--accent-subtle); white-space: nowrap;
    }
    .gen-body :global(td) {
        padding: 6px 12px; border-bottom: 1px solid var(--border-subtle);
        color: var(--text-secondary); vertical-align: top;
    }
    .gen-body :global(tr:last-child td) { border-bottom: none; }

    .preview-btn {
        padding: 3px 12px;
        background: rgba(232, 133, 12, 0.08);
        border: 1px solid rgba(232, 133, 12, 0.18);
        border-radius: var(--radius-pill);
        font-family: var(--font-body);
        font-size: 11px; font-weight: 600;
        color: var(--brain); cursor: pointer;
        transition: all var(--transition); flex-shrink: 0;
    }
    .preview-btn:hover {
        background: rgba(232, 133, 12, 0.14);
        border-color: rgba(232, 133, 12, 0.30);
    }
    .preview-btn.sm { font-size: 10px; padding: 2px 10px; }

    /* ================================================================
       THINKING BLOCK
       ================================================================ */
    .think-block {
        background: var(--surface);
        border: 1px solid var(--border);
        border-left: 2px solid var(--text-muted);
        border-radius: 12px;
        overflow: hidden;
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
        max-width: 560px;
    }
    .think-header {
        display: flex; align-items: center; gap: 8px;
        padding: 7px 14px; cursor: pointer;
        font-size: 10.5px; font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase; letter-spacing: 0.06em;
        list-style: none; user-select: none;
    }
    .think-header::-webkit-details-marker { display: none; }
    .think-header::after {
        content: '\25BE'; margin-left: auto; font-size: 10px;
        transition: transform var(--transition);
    }
    .think-block[open] .think-header::after { transform: rotate(180deg); }

    .think-dot {
        width: 5px; height: 5px; border-radius: 50%;
        background: var(--text-muted);
        animation: pulse 2s ease-in-out infinite;
    }
    .think-meta {
        font-family: var(--font-mono); font-size: 10px;
        font-weight: 400; color: var(--text-muted); opacity: 0.6;
    }
    .think-body {
        font-family: var(--font-mono); font-size: 11px; line-height: 1.55;
        color: var(--text-muted); white-space: pre-wrap; word-break: break-word;
        margin: 0; padding: 8px 14px 10px;
        border-top: 1px solid var(--border-subtle);
        background: none; border-left: none; border-right: none; border-bottom: none; border-radius: 0;
        max-height: 200px; overflow-y: auto;
    }

    /* ================================================================
       ISSUES CARD (validation)
       ================================================================ */
    .issues-card {
        background: var(--surface);
        border: 1px solid var(--border);
        border-left: 2px solid var(--warning);
        border-radius: 12px;
        padding: 12px 16px;
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
        max-width: 520px;
    }
    .issues-header {
        display: flex; align-items: center; gap: 10px;
        margin-bottom: 8px;
    }
    .issues-label {
        font-size: 11px; font-weight: 600;
        color: var(--warning); text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .verdict {
        margin-left: auto;
        font-size: 10px; font-weight: 700; letter-spacing: 0.04em;
        padding: 2px 8px; border-radius: 6px;
        background: var(--error); color: white;
    }
    .verdict.pass { background: var(--success); }
    .issues-list {
        list-style: none; display: flex; flex-direction: column; gap: 3px;
    }
    .issues-list li {
        font-size: 12.5px; color: var(--text-secondary);
        padding-left: 14px; position: relative; line-height: 1.5;
    }
    .issues-list li::before {
        content: '\2022'; position: absolute; left: 2px;
        color: var(--warning); font-weight: bold;
    }

    /* ================================================================
       OUTPUT FILE CARD
       ================================================================ */
    .output-card {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 14px;
        overflow: hidden;
        box-shadow: var(--bubble-glow);
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
        max-width: 520px;
    }
    .output-bar {
        display: flex; align-items: center; gap: 10px;
        padding: 10px 16px;
    }
    .ext-badge {
        font-size: 10px; font-weight: 700;
        color: white; letter-spacing: 0.04em;
        padding: 2px 8px;
        border-radius: 6px;
        background: var(--ec);
    }
    .output-name {
        font-size: 13.5px; font-weight: 600;
        color: var(--text); letter-spacing: -0.01em;
    }
    .output-meta {
        font-size: 11px; font-family: var(--font-mono);
        color: var(--text-muted);
    }
    .output-actions {
        margin-left: auto; display: flex; gap: 3px;
    }
    .act-btn {
        display: flex; align-items: center; justify-content: center;
        width: 30px; height: 30px;
        background: var(--accent-subtle);
        border: 1px solid var(--border-subtle);
        border-radius: 8px;
        color: var(--text-muted); cursor: pointer;
        transition: all var(--transition);
    }
    .act-btn:hover { background: var(--surface); color: var(--text-secondary); }
    .act-btn.active { background: var(--surface); color: var(--text); }

    .output-source {
        font-family: var(--font-mono); font-size: 11.5px; line-height: 1.55;
        color: var(--text-secondary);
        background: var(--code-bg);
        border-top: 1px solid var(--border-subtle);
        padding: 14px 18px;
        white-space: pre-wrap; word-break: break-all;
        max-height: 300px; overflow-y: auto; margin: 0; border-radius: 0;
    }

    /* ================================================================
       SUMMARY + TRACE PILLS
       ================================================================ */
    .summary-row {
        display: flex; gap: 8px; flex-wrap: wrap;
    }
    .summary-chip {
        display: inline-flex; align-items: center; gap: 6px;
        padding: 4px 12px;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 20px;
        font-size: 12.5px; font-weight: 600;
        font-variant-numeric: tabular-nums;
        color: var(--text-secondary);
    }
    .summary-dot {
        width: 6px; height: 6px; border-radius: 50%;
    }

    .trace-row {
        display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
    }
    .trace-pill {
        display: inline-flex; align-items: center; gap: 6px;
        padding: 6px 14px;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 20px;
        font-family: var(--font-body);
        font-size: 11px; font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase; letter-spacing: 0.04em;
        cursor: pointer;
        transition: all var(--transition);
        white-space: nowrap; flex-shrink: 0;
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
    }
    .trace-pill:hover { color: var(--text-secondary); border-color: var(--border-subtle); }
    .trace-pill.open {
        color: var(--text-secondary);
        background: var(--bubble-strong);
        border-color: var(--border);
        box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
    }
    .trace-pill.score {
        font-variant-numeric: tabular-nums;
        font-size: 12px;
    }

    .trace-dot {
        width: 5px; height: 5px; border-radius: 50%; flex-shrink: 0;
    }
    .trace-verdict {
        font-size: 9px; font-weight: 700;
        padding: 1px 5px; border-radius: 4px;
        background: var(--error); color: white; letter-spacing: 0.03em;
    }
    .trace-verdict.pass { background: var(--success); }

    /* ================================================================
       TRACE CARDS (expanded details)
       ================================================================ */
    .trace-card {
        background: var(--surface);
        border: 1px solid var(--border);
        border-left: 2px solid var(--tbc, var(--text-muted));
        border-radius: 12px;
        overflow: hidden;
        animation: slideUpSpring 280ms var(--spring-soft) both;
        max-width: 560px;
    }
    .trace-section { padding: 12px 16px; }
    .trace-section + .trace-section { border-top: 1px solid var(--border-subtle); }
    .trace-label {
        display: block;
        font-size: 10px; font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase; letter-spacing: 0.06em;
        margin-bottom: 6px;
    }
    .trace-pre {
        font-family: var(--font-mono);
        font-size: 11.5px; line-height: 1.6;
        color: var(--text-secondary);
        white-space: pre-wrap; word-break: break-word;
        margin: 0; padding: 12px 16px;
        background: none; border: none; border-radius: 0;
        max-height: 400px; overflow-y: auto;
    }
    .trace-section .trace-pre { padding: 0; }
    .trace-issues {
        list-style: none; padding: 12px 16px;
        display: flex; flex-direction: column; gap: 3px;
    }
    .trace-issues li {
        font-size: 12.5px; color: var(--text-secondary);
        padding-left: 14px; position: relative; line-height: 1.5;
    }
    .trace-issues li::before {
        content: '\00d7'; position: absolute; left: 0;
        color: var(--warning); font-weight: bold;
    }
    .trace-text {
        font-size: 13px; color: var(--text-secondary);
        line-height: 1.6; margin: 0;
    }

    /* ================================================================
       FEEDBACK BUTTONS
       ================================================================ */
    .bubble-row {
        display: flex; flex-direction: column; gap: 12px;
    }
    .feedback-row {
        display: flex;
        gap: 4px;
        margin-top: 4px;
        opacity: 0;
        transition: opacity var(--transition);
    }
    .bubble-row:hover .feedback-row,
    .feedback-row:has(.active) {
        opacity: 1;
    }
    .feedback-btn {
        background: none;
        border: none;
        color: var(--text-muted);
        cursor: pointer;
        padding: 4px 6px;
        border-radius: 6px;
        transition: color var(--transition), background var(--transition);
    }
    .feedback-btn:hover {
        background: var(--accent-subtle);
        color: var(--text-secondary);
    }
    .feedback-btn.active {
        color: var(--success);
        background: rgba(45, 164, 78, 0.08);
    }
    .feedback-btn.bad.active {
        color: var(--error);
        background: rgba(207, 34, 46, 0.08);
    }
    .feedback-btn.regen:hover {
        color: var(--brain);
        background: rgba(232, 133, 12, 0.08);
    }

    /* ================================================================
       COMPUTER MODE PANEL
       ================================================================ */
    .computer-panel {
        top: 56px;
        background: var(--surface-solid);
        border-left: var(--bubble-border-light);
    }
    .computer-split {
        display: flex;
        flex-direction: column;
        height: 100%;
    }
    .computer-files {
        height: 220px;
        flex-shrink: 0;
        overflow: hidden;
        border-bottom: var(--bubble-border-light);
    }
    .computer-term {
        flex: 1;
        overflow: hidden;
    }

    .act-btn.undo {
        color: var(--brain);
    }
    .act-btn.undo:hover {
        background: rgba(232, 133, 12, 0.08);
    }

    /* ================================================================
       COMPUTER MODE FILES CARD (in chat)
       ================================================================ */
    .computer-files-card {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: var(--radius-lg);
        padding: 14px 16px;
        display: flex;
        flex-direction: column;
        gap: 10px;
    }
    .computer-files-header {
        display: flex;
        align-items: center;
        gap: 8px;
        font-family: var(--font-body);
        font-size: 13px;
        font-weight: 600;
        color: var(--text-secondary);
    }
    .computer-files-header svg {
        color: var(--brain);
        opacity: 0.8;
    }
    .computer-files-list {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
    }
    .computer-file-chip {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 12px;
        background: var(--accent-subtle);
        border: 1px solid var(--border);
        border-radius: var(--radius-pill);
        font-family: var(--font-mono);
        font-size: 12px;
        color: var(--text);
    }
</style>
