<script lang="ts">
    import { chat, setFeedback, regenerate, setAltIndex, undo, setWorkspaceId, stopGeneration, restoreWorkspace, clearPendingCommands, revertToTurn, pendingInputPrompt } from '$lib/stores/chat';
    import type { SearchActivity, SearchResult } from '$lib/stores/chat';
    import { getLangMeta } from '$lib/langMap';
    import { render } from '$lib/markdown';
    import hljs from '$lib/highlight';
    import ChatInput from '$lib/components/ChatInput.svelte';
    import SearchActivities from '$lib/components/SearchActivities.svelte';
    import SpecialistCard from '$lib/components/SpecialistCard.svelte';

    import PlanCard from '$lib/components/PlanCard.svelte';
    import PreviewPanel from '$lib/components/PreviewPanel.svelte';
    import TerminalPanel from '$lib/components/TerminalPanel.svelte';
    import FileTree from '$lib/components/FileTree.svelte';
    import AtlasProgress from '$lib/components/AtlasProgress.svelte';

    let isComputerRoute = $derived($chat.route === 'ROUTE_COMPUTER');
    let isCode = $derived(
        $chat.route === 'ROUTE_DESIGN' || $chat.route === 'ROUTE_CODE'
    );
    // Preview is only meaningful for HTML output. Design mode always produces HTML.
    // Code mode only qualifies when the plan explicitly says html_page.
    let isHtmlOutput = $derived(
        $chat.route === 'ROUTE_DESIGN' || $chat.plan?.output_type === 'html_page'
    );
    let isComputerMode = $derived(
        !!$chat.workspaceId || $chat.modeOverride === 'computer' || isComputerRoute
    );

    let showPreview = $state(false);
    let previewOverride = $state<string | null>(null);
    function stripFences(code: string): string {
        // Strip opening ```html\n and trailing ```
        return code.replace(/^```\w*\s*\n/, '').replace(/\n?```\s*$/, '');
    }
    let previewCode = $derived(
        ($chat.phase === 'generating' || $chat.phase === 'fixing' || $chat.phase === 'polishing') && $chat.streamingText
            ? stripFences($chat.streamingText)
            : previewOverride || $chat.response || $chat.streamingText || ''
    );
    let codeExpanded = $state(false);

    let traceOpen = $state<string | null>(null);
    function toggleTrace(key: string) { traceOpen = traceOpen === key ? null : key; }
    let hasThinking = $derived(!!$chat.thinking || !!$chat.draftThinking);

    type WorkspaceFileView = { path: string; content: string };

    let hasValidation = $derived(!!$chat.review || $chat.validationIssues.length > 0);

    let previewWidth = $state(Math.min(Math.round(window.innerWidth * 0.44), 700));
    let resizing = $state(false);
    let previewEntered = $state(false);

    // Computer mode state
    // Derive from the chat store so workspace ID survives navigation (settings → chat → back)
    let activeWorkspaceId = $derived($chat.workspaceId);
    let showTerminal = $state(false);
    let panelUserClosed = $state(false);   // user explicitly closed via arrow — don't auto-reopen
    let lastPanelWorkspaceId = $state<string | null>(null); // track workspace changes to reset flag
    let fileTreeRef = $state<FileTree>();
    let viewingFile = $state<WorkspaceFileView | null>(null);
    let activeWorkspaceFile = $derived(((viewingFile as WorkspaceFileView | null)?.path) ?? '');
    let computerTab = $state<'files' | 'terminal'>('files');
    let fileRequestId = $state(0);

    function getTurnSearches(turn: {
        activeSearches?: SearchActivity[];
        webSearchResults?: SearchResult[];
        webSearchQuery?: string;
    }): SearchActivity[] {
        if (turn.activeSearches?.length) {
            return turn.activeSearches;
        }
        if (turn.webSearchResults?.length) {
            return [{
                query: turn.webSearchQuery ?? '',
                results: turn.webSearchResults,
                done: true,
                error: null,
            }];
        }
        return [];
    }

    $effect(() => {
        // On mount: try to restore workspace from localStorage (survives server restarts)
        restoreWorkspace();
    });

    $effect(() => {
        // Auto-create workspace when entering computer mode for the first time
        if (isComputerMode && !$chat.workspaceId) {
            createDefaultWorkspace();
        }
        const wsId = $chat.workspaceId;
        // Reset user-close flag whenever the workspace changes (different workspace or cleared)
        if (wsId !== lastPanelWorkspaceId) {
            lastPanelWorkspaceId = wsId;
            fileRequestId += 1;
            viewingFile = null;
            computerTab = 'files';
            if (wsId) {
                panelUserClosed = false;
                showTerminal = true;
            } else {
                showTerminal = false;
            }
        }
        // Restore terminal panel on navigation back — but not if user manually closed it
        if (wsId && isComputerMode && !showTerminal && !panelUserClosed) {
            showTerminal = true;
        }
    });

    // Auto-switch to terminal tab when AI sends commands to run
    $effect(() => {
        if ($chat.pendingCommands.length > 0 && isComputerMode) {
            computerTab = 'terminal';
            showTerminal = true;
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
                showTerminal = true;
                setWorkspaceId(data.id); // persists to chat store → activeWorkspaceId updates
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
        const wsId = activeWorkspaceId;
        if (!wsId) return;
        const requestId = ++fileRequestId;
        fetch(`/api/workspaces/${wsId}/files/${path}`)
            .then(r => r.json())
            .then(data => {
                if (requestId !== fileRequestId || wsId !== activeWorkspaceId) return;
                if (data.content == null) return;
                viewingFile = { path, content: data.content };
                computerTab = 'files';
            });
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

    function downloadBlob(code: string, lang: string = 'text') {
        if (!code) return;
        if (lang === 'multi') return; // multi-file: already saved to workspace
        const [ext, mime] = getLangMeta(lang);
        const filename = lang === 'html' ? 'index.html' : `output${ext}`;
        const blob = new Blob([code], { type: mime });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
    }

    function downloadCode() {
        const lang = $chat.conversation[$chat.conversation.length - 1]?.detectedLang ?? 'text';
        downloadBlob($chat.response, lang);
    }

    let previewOutputType = $state<string>('other');
    function previewHistoryCode(code: string, outputType: string = 'other') {
        previewOverride = code;
        previewOutputType = outputType;
        showPreview = true;
    }

    // Per-history-card inline code expansion
    let expandedHistoryCards = $state(new Set<number>());
    function toggleHistoryCard(idx: number) {
        const next = new Set(expandedHistoryCards);
        if (next.has(idx)) next.delete(idx); else next.add(idx);
        expandedHistoryCards = next;
    }

    let didGenerate = $state(false);
    let userClosedPreview = $state(false);

    $effect(() => {
        if ($chat.phase === 'generating' || $chat.phase === 'fixing') {
            didGenerate = true;
        }
        // Close preview whenever generating non-HTML output.
        // showPreview carries over from previous turns, so without this a Python request
        // after an HTML design would keep the preview open and render Python-as-HTML.
        if (($chat.phase === 'generating' || $chat.phase === 'polishing') && !isHtmlOutput && !isComputerRoute && showPreview) {
            showPreview = false;
        }
        // Auto-open preview only for HTML output (design mode always HTML; code mode only when plan says html_page)
        if (($chat.phase === 'generating' || $chat.phase === 'polishing') && isHtmlOutput && !isComputerRoute && !userClosedPreview) {
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
        previewOutputType = 'other';
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

        $chat.response;
        $chat.phase;
        $chat.checklist;
        $chat.validationIssues;
        $chat.warning;
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
        'ROUTE_DIRECT': 'Chat',
        'ROUTE_COMPUTER': 'Computer',
    };
    const routeColors: Record<string, string> = {
        'ROUTE_DESIGN': 'var(--specialist)',
        'ROUTE_CODE': '#5B8DEF',
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

    function planTypeToExt(type: string | undefined | null): string {
        switch (type) {
            case 'html_page':     return 'html';
            case 'python_script': return 'py';
            case 'javascript':    return 'js';
            case 'typescript':    return 'ts';
            case 'cpp':           return 'cpp';
            case 'go':            return 'go';
            case 'rust':          return 'rs';
            case 'shell':         return 'sh';
            case 'sql':           return 'sql';
            default:              return 'txt';
        }
    }

    function outputExt(): string {
        return planTypeToExt($chat.plan?.output_type);
    }

    /** Parse [FILE: path] markers from computer mode response (with legacy fallback) */
    function parseFileList(text: string): string[] {
        let matches = [...text.matchAll(/\[FILE:\s*(.+?)\]/g)];
        if (matches.length === 0) {
            matches = [...text.matchAll(/<!--\s*FILE:\s*(.+?)\s*-->/g)];
        }
        return matches.map(m => m[1].trim());
    }

    function formatChars(n: number): string {
        return n >= 1000 ? `${Math.round(n / 1000)}k` : `${n}`;
    }

    let copyFeedback = $state<string | null>(null);
    function copyToClipboard(text: string) {
        navigator.clipboard.writeText(text).then(() => {
            copyFeedback = 'Copied!';
            setTimeout(() => { copyFeedback = null; }, 1500);
        });
    }

    function highlightCode(code: string, ext: string): string {
        const langMap: Record<string, string> = {
            html: 'xml', htm: 'xml', css: 'css', js: 'javascript',
            ts: 'typescript', py: 'python', json: 'json', svg: 'xml',
        };
        const lang = langMap[ext];
        if (lang && hljs.getLanguage(lang)) {
            return hljs.highlight(code, { language: lang }).value;
        }
        return hljs.highlightAuto(code).value;
    }
</script>

<div class="page">
    <div class="chat-panel" class:resizing-layout={resizing} style={(previewVisible || (isComputerMode && showTerminal)) ? `margin-right: ${previewWidth}px` : ''}>
        <div class="messages" bind:this={messagesEl} onscroll={onMessagesScroll}>
            <div class="messages-inner">
                <!-- ==================== WELCOME SCREEN ==================== -->
                {#if $chat.conversation.length === 0 && $chat.phase === 'idle'}
                    <div class="welcome">
                        <h1 class="welcome-title">CT-2</h1>
                        <p class="welcome-sub">What would you like to build today?</p>
                        <div class="welcome-chips">
                            {#each [
                                { label: 'Design a landing page', icon: '✦' },
                                { label: 'Write a Python script', icon: '⌥' },
                                { label: 'Explain a concept', icon: '◎' },
                                { label: 'Help me debug code', icon: '◈' },
                            ] as chip}
                                <button class="welcome-chip" onclick={() => pendingInputPrompt.set(chip.label)}>
                                    <span class="chip-icon">{chip.icon}</span>
                                    <span>{chip.label}</span>
                                </button>
                            {/each}
                        </div>
                    </div>
                {/if}

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
                        <div class="user-actions" style="animation-delay: {idx * 30 + 60}ms">
                            <button class="user-action-btn" onclick={() => revertToTurn(idx)} title="Revert conversation to this point">
                                <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                                    <path d="M3 8a5 5 0 1 0 5-5H5M3 8L5.5 5.5M3 8L5.5 10.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
                                </svg>
                                Revert here
                            </button>
                        </div>
                    {:else if turn.isCode && turn.route !== 'ROUTE_COMPUTER'}
                        {@const hLang = turn.detectedLang ?? 'text'}
                        {@const hExt = hLang !== 'text' ? getLangMeta(hLang)[0].slice(1) : planTypeToExt(turn.plan?.output_type)}
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
                            {#if turn.fetchedContent?.length}
                                {#each turn.fetchedContent as fc}
                                    <details class="fetch-card">
                                        <summary class="fetch-card-header">
                                            <span class="fetch-card-icon">W</span>
                                            <span class="fetch-card-title">{fc.title || fc.url}</span>
                                            <span class="fetch-card-meta">{formatChars(fc.contentLength)}</span>
                                            {#if fc.truncated}
                                                <span class="fetch-card-trunc">truncated</span>
                                            {/if}
                                        </summary>
                                        <pre class="fetch-card-body">{fc.content}</pre>
                                    </details>
                                {/each}
                            {/if}
                            <SearchActivities searches={getTurnSearches(turn)} />
                            {#if turn.explanation}
                                <div class="code-explanation">{turn.explanation}</div>
                            {/if}
                            <div class="output-card" style="animation-delay: {idx * 30}ms">
                                <div class="output-bar">
                                    <span class="ext-badge" style="--ec: {extColor(hExt)}">{hExt.toUpperCase()}</span>
                                    <span class="output-name">output.{hExt}</span>
                                    <span class="output-meta">{formatChars(turn.content.length)}</span>
                                    <div class="output-actions">
                                        <button class="act-btn" onclick={() => toggleHistoryCard(idx)} title="View code" class:active={expandedHistoryCards.has(idx)}>
                                            <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M5.5 3.5L2.5 7.5l3 4M9.5 3.5l3 4-3 4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                                        </button>
                                        {#if hExt === 'html'}
                                        <button class="act-btn" onclick={() => previewHistoryCode(turn.content, 'html_page')} title="Preview">
                                            <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M2 3.5A1.5 1.5 0 013.5 2h8A1.5 1.5 0 0113 3.5v8a1.5 1.5 0 01-1.5 1.5h-8A1.5 1.5 0 012 11.5v-8z" stroke="currentColor" stroke-width="1.1"/><path d="M6 6l3 1.5-3 1.5V6z" fill="currentColor" opacity="0.6"/></svg>
                                        </button>
                                        {/if}
                                        <button class="act-btn" onclick={() => copyToClipboard(turn.content)} title="Copy code">
                                            <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><rect x="5" y="5" width="7.5" height="7.5" rx="1.2" stroke="currentColor" stroke-width="1.1"/><path d="M3 10V3.5A.5.5 0 013.5 3H10" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/></svg>
                                        </button>
                                        {#if hLang !== 'multi'}
                                        <button class="act-btn" onclick={() => downloadBlob(turn.content, hLang)} title="Download">
                                            <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M7.5 2.5v7M5 7.5l2.5 2.5L10 7.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/><path d="M3 11.5h9" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
                                        </button>
                                        {/if}
                                    </div>
                                </div>
                                {#if expandedHistoryCards.has(idx)}
                                    <pre class="output-source"><code class="hljs">{@html highlightCode(turn.content, hExt)}</code></pre>
                                {/if}
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
                                <button class="feedback-btn regen" onclick={() => regenerate(idx)} title="Retry — get a new response">
                                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                                        <path d="M1 8a7 7 0 0112.3-4.5M15 8a7 7 0 01-12.3 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                                        <path d="M13 1v3h-3M3 15v-3h3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                                    </svg>
                                </button>
                                <button class="feedback-btn copy-resp" onclick={() => copyToClipboard(turn.content)} title="Copy response">
                                    <svg width="14" height="14" viewBox="0 0 15 15" fill="none"><rect x="5" y="5" width="7.5" height="7.5" rx="1.2" stroke="currentColor" stroke-width="1.1"/><path d="M3 10V3.5A.5.5 0 013.5 3H10" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/></svg>
                                </button>
                            </div>
                        </div>
                    {:else if turn.route === 'ROUTE_COMPUTER'}
                        {@const hFiles = parseFileList(turn.content)}
                        <div class="bubble-row">
                            <div class="route-row">
                                <span class="route-tag" style="--rc: var(--brain)">Computer</span>
                            </div>
                            {#if turn.fetchedContent?.length}
                                {#each turn.fetchedContent as fc}
                                    <details class="fetch-card">
                                        <summary class="fetch-card-header">
                                            <span class="fetch-card-icon">W</span>
                                            <span class="fetch-card-title">{fc.title || fc.url}</span>
                                            <span class="fetch-card-meta">{formatChars(fc.contentLength)}</span>
                                            {#if fc.truncated}
                                                <span class="fetch-card-trunc">truncated</span>
                                            {/if}
                                        </summary>
                                        <pre class="fetch-card-body">{fc.content}</pre>
                                    </details>
                                {/each}
                            {/if}
                            <SearchActivities searches={getTurnSearches(turn)} />
                            <div class="computer-result-card" style="animation-delay: {idx * 30}ms">
                                <div class="computer-result-header">
                                    <div class="computer-result-icon">
                                        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                                            <path d="M4 5.5l3 2.5-3 2.5M8.5 11H12" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
                                            <rect x="1.5" y="2" width="13" height="12" rx="2" stroke="currentColor" stroke-width="1.1"/>
                                        </svg>
                                    </div>
                                    <div class="computer-result-info">
                                        <span class="computer-result-title">{hFiles.length} file{hFiles.length !== 1 ? 's' : ''} written</span>
                                        <span class="computer-result-meta">{formatChars(turn.content.length)}</span>
                                    </div>
                                    <div class="computer-result-actions">
                                        <button class="act-btn" onclick={() => copyToClipboard(turn.content)} title="Copy all">
                                            <svg width="14" height="14" viewBox="0 0 15 15" fill="none"><rect x="5" y="5" width="7.5" height="7.5" rx="1.2" stroke="currentColor" stroke-width="1.1"/><path d="M3 10V3.5A.5.5 0 013.5 3H10" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/></svg>
                                        </button>
                                    </div>
                                </div>
                                {#if hFiles.length > 0}
                                    <div class="computer-file-grid">
                                        {#each hFiles as filePath}
                                            {@const hExt = extOf(filePath)}
                                            {@const hName = filePath.split('/').pop() || filePath}
                                            <span class="computer-file-item">
                                                <span class="computer-file-ext" style="--fc: {extColor(hExt)}">{hExt.toUpperCase().slice(0, 4)}</span>
                                                <span class="computer-file-name">{hName}</span>
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
                                <button class="feedback-btn regen" onclick={() => regenerate(idx)} title="Retry — get a new response">
                                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M1 8a7 7 0 0112.3-4.5M15 8a7 7 0 01-12.3 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M13 1v3h-3M3 15v-3h3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
                                </button>
                                <button class="feedback-btn copy-resp" onclick={() => copyToClipboard(turn.content)} title="Copy response">
                                    <svg width="14" height="14" viewBox="0 0 15 15" fill="none"><rect x="5" y="5" width="7.5" height="7.5" rx="1.2" stroke="currentColor" stroke-width="1.1"/><path d="M3 10V3.5A.5.5 0 013.5 3H10" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/></svg>
                                </button>
                            </div>
                        </div>
                    {:else}
                        {@const alts = turn.alternatives ?? []}
                        {@const currAltIdx = turn.altIndex ?? alts.length}
                        {@const shownContent = currAltIdx < alts.length ? alts[currAltIdx] : turn.content}
                        {@const totalVersions = alts.length + 1}
                        <div class="bubble-row">
                            {#if turn.fetchedContent?.length}
                                {#each turn.fetchedContent as fc}
                                    <details class="fetch-card">
                                        <summary class="fetch-card-header">
                                            <span class="fetch-card-icon">W</span>
                                            <span class="fetch-card-title">{fc.title || fc.url}</span>
                                            <span class="fetch-card-meta">{formatChars(fc.contentLength)}</span>
                                            {#if fc.truncated}
                                                <span class="fetch-card-trunc">truncated</span>
                                            {/if}
                                        </summary>
                                        <pre class="fetch-card-body">{fc.content}</pre>
                                    </details>
                                {/each}
                            {/if}
                            <SearchActivities searches={getTurnSearches(turn)} />
                            <div class="ai-bubble" style="animation-delay: {idx * 30}ms">
                                {@html render(shownContent)}
                            </div>
                            <div class="feedback-row">
                                {#if alts.length > 0}
                                    <div class="alt-nav">
                                        <button class="alt-btn" disabled={currAltIdx === 0}
                                            onclick={() => setAltIndex(idx, currAltIdx - 1)} title="Previous version">←</button>
                                        <span class="alt-counter">{currAltIdx + 1}/{totalVersions}</span>
                                        <button class="alt-btn" disabled={currAltIdx >= alts.length}
                                            onclick={() => setAltIndex(idx, currAltIdx + 1)} title="Next version">→</button>
                                    </div>
                                {/if}
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
                                <button class="feedback-btn regen" onclick={() => regenerate(idx)} title="Retry — get a new response">
                                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                                        <path d="M1 8a7 7 0 0112.3-4.5M15 8a7 7 0 01-12.3 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                                        <path d="M13 1v3h-3M3 15v-3h3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                                    </svg>
                                </button>
                                <button class="feedback-btn copy-resp" onclick={() => copyToClipboard(shownContent)} title="Copy response">
                                    <svg width="14" height="14" viewBox="0 0 15 15" fill="none"><rect x="5" y="5" width="7.5" height="7.5" rx="1.2" stroke="currentColor" stroke-width="1.1"/><path d="M3 10V3.5A.5.5 0 013.5 3H10" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/></svg>
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

                {#if $chat.plan && $chat.plan.components.length > 0}
                    <PlanCard plan={$chat.plan} />
                {/if}

                <!-- ==================== PIPELINE STEPS ==================== -->
                <!-- During Atlas mode, these are hidden — AtlasProgress handles status -->
                {#if !$chat.atlasActive}
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

                    {#if $chat.specialistData && $chat.route !== 'ROUTE_DESIGN'}
                        <SpecialistCard data={$chat.specialistData} />
                    {/if}

                    <!-- ==================== PRECISION-DESIGN PIPELINE ==================== -->
                    {#if $chat.phase === 'spec_generating' || ($chat.phase === 'spec_validated' && $chat.streamingThinking)}
                        <div class="planning-card">
                            <div class="planning-header">
                                <span class="planning-dot" class:pulse={$chat.phase === 'spec_generating'}></span>
                                <span class="planning-label">Planning{$chat.phase === 'spec_generating' ? '…' : ' complete'}</span>
                            </div>
                            {#if $chat.streamingThinking}
                                <pre class="planning-body">{$chat.streamingThinking}</pre>
                            {/if}
                        </div>
                    {/if}

                    {#if $chat.componentProgress.length > 0}
                        <div class="component-progress">
                            <div class="comp-header">
                                <span class="comp-title">Components</span>
                                <span class="comp-count">
                                    {$chat.componentProgress.filter(c => c.status === 'validated' || c.status === 'fallback').length}/{$chat.componentProgress[0]?.total ?? $chat.componentProgress.length}
                                </span>
                            </div>
                            <div class="comp-items">
                                {#each $chat.componentProgress as comp}
                                    <div class="comp-item"
                                         class:done={comp.status === 'validated'}
                                         class:patching={comp.status === 'patching'}
                                         class:fallback={comp.status === 'fallback'}>
                                        <span class="comp-dot" class:pulse={comp.status === 'generating'}></span>
                                        <span class="comp-name">{comp.id}</span>
                                        <span class="comp-status">{comp.status}</span>
                                    </div>
                                {/each}
                            </div>
                        </div>
                    {/if}

                    {#if $chat.phase === 'assembling'}
                        <div class="step">
                            <span class="step-dot pulse"></span>
                            <span class="step-text">Assembling page...</span>
                        </div>
                    {/if}
                {/if}

                <SearchActivities searches={$chat.activeSearches} showStatus={true} />

                {#if $chat.fetchingUrls.length > 0}
                    <div class="fetch-status">
                        {#each $chat.fetchingUrls as fu}
                            <div class="fetch-row" class:done={fu.status === 'done'} class:failed={fu.status === 'failed'}>
                                <span class="fetch-dot" class:pulse={fu.status === 'fetching'}></span>
                                <span class="fetch-label">
                                    {fu.status === 'fetching' ? 'Fetching' : fu.status === 'done' ? 'Fetched' : 'Failed'}
                                </span>
                                <span class="fetch-url">{fu.url.length > 60 ? fu.url.slice(0, 57) + '...' : fu.url}</span>
                                {#if fu.status === 'failed' && fu.error}
                                    <span class="fetch-error">— {fu.error}</span>
                                {/if}
                            </div>
                        {/each}
                    </div>
                {/if}

                {#if $chat.fetchedContent.length > 0}
                    {#each $chat.fetchedContent as fc}
                        <details class="fetch-card">
                            <summary class="fetch-card-header">
                                <span class="fetch-card-icon">W</span>
                                <span class="fetch-card-title">{fc.title || fc.url}</span>
                                <span class="fetch-card-meta">{formatChars(fc.contentLength)}</span>
                                {#if fc.truncated}
                                    <span class="fetch-card-trunc">truncated</span>
                                {/if}
                            </summary>
                            <pre class="fetch-card-body">{fc.content}</pre>
                        </details>
                    {/each}
                {/if}

                <!-- ==================== ATLAS PROGRESS ==================== -->
                <AtlasProgress />

                <!-- ==================== GENERATION ==================== -->
                {#if $chat.phase === 'generating' || $chat.phase === 'fixing'}
                    <div class="gen-card" class:fixing={$chat.phase === 'fixing'}>
                        <div class="gen-bar">
                            <span class="gen-indicator"></span>
                            <span class="gen-title">
                                {$chat.phase === 'fixing' ? 'Fixing' : $chat.editing ? 'Editing' : isComputerRoute ? 'Creating files' : isCode ? 'Generating' : 'Writing'}
                            </span>
                            <div class="gen-stats">
                                <span class="gen-meta">
                                    {#if $chat.editing}
                                        patching
                                    {:else if $chat.streamingText}
                                        {formatChars($chat.streamingText.length)}
                                    {:else}
                                        ...
                                    {/if}
                                </span>
                                {#if $chat.tokensPerSec > 0}
                                    <span class="gen-speed">{$chat.tokensPerSec} t/s</span>
                                {/if}
                            </div>
                            {#if isHtmlOutput && !$chat.editing && $chat.streamingText.length > 200}
                                <button class="preview-btn" onclick={previewCurrentCode}>
                                    {showPreview ? 'Hide' : 'Preview'}
                                </button>
                            {/if}
                            <button class="stop-btn" onclick={stopGeneration} title="Stop generation">
                                <svg width="10" height="10" viewBox="0 0 12 12" fill="none"><rect x="1" y="1" width="10" height="10" rx="2" fill="currentColor"/></svg>
                            </button>
                        </div>
                        {#if !isCode && !isComputerRoute && $chat.streamingText}
                            <div class="gen-body">
                                {@html render($chat.streamingText)}<span class="stream-cursor"></span>
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

                {#if $chat.checklist.length > 0}
                    {@const done = $chat.checklist.filter(c => c.done).length}
                    {@const total = $chat.checklist.length}
                    {@const allDone = done === total}
                    <div class="checklist-card" class:all-done={allDone}>
                        <div class="checklist-header">
                            <span class="checklist-icon">{allDone ? '✓' : '⋯'}</span>
                            <span class="checklist-title">Checklist</span>
                            <span class="checklist-count" class:complete={allDone}>{done}/{total}</span>
                        </div>
                        <div class="checklist-items">
                            {#each $chat.checklist as item}
                                <div class="checklist-row" class:done={item.done}>
                                    <span class="check-mark">
                                        {#if item.done}
                                            <svg width="10" height="10" viewBox="0 0 16 16" fill="none">
                                                <path d="M3 8.5L6.5 12L13 4" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
                                            </svg>
                                        {:else}
                                            <span class="check-empty"></span>
                                        {/if}
                                    </span>
                                    <span class="check-label">{item.item}</span>
                                </div>
                            {/each}
                        </div>
                    </div>
                {/if}

                {#if $chat.warning}
                    <div class="step warning-step">
                        <span class="step-dot pulse"></span>
                        <span class="step-text">{$chat.warning}</span>
                    </div>
                {/if}

                {#if $chat.phase === 'refining'}
                    <div class="refine-card">
                        <div class="refine-bar">
                            <span class="refine-icon">
                                <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                                    <path d="M8 1L10 6L15 6.5L11.5 10L12.5 15L8 12.5L3.5 15L4.5 10L1 6.5L6 6L8 1Z" fill="currentColor" opacity="0.7"/>
                                </svg>
                            </span>
                            <span class="refine-title">Refining design</span>
                            <span class="refine-sub">Reviewing spacing, colors, polish...</span>
                        </div>
                        <div class="refine-progress">
                            <div class="refine-bar-fill"></div>
                        </div>
                    </div>
                {/if}

                {#if $chat.phase === 'polishing' && isHtmlOutput && !isComputerRoute}
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
                    {@const _respLang = $chat.conversation[$chat.conversation.length - 1]?.detectedLang ?? 'text'}
                    {@const ext = _respLang !== 'text' ? getLangMeta(_respLang)[0].slice(1) : outputExt()}
                    <div class="output-card">
                        <div class="output-bar">
                            <span class="ext-badge" style="--ec: {extColor(ext)}">{ext.toUpperCase()}</span>
                            <span class="output-name">{_respLang === 'html' ? 'index.html' : `output.${ext}`}</span>
                            <span class="output-meta">
                                {formatChars($chat.response.length)}{#if $chat.tokenCount > 0}&ensp;·&ensp;{$chat.tokenCount} tok{#if $chat.tokensPerSec > 0} · {$chat.tokensPerSec}/s{/if}{/if}
                            </span>
                            <div class="output-actions">
                                <button class="act-btn" onclick={() => codeExpanded = !codeExpanded} title="Source" class:active={codeExpanded}>
                                    <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M5.5 3.5L2.5 7.5l3 4M9.5 3.5l3 4-3 4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                                </button>
                                {#if ext === 'html'}
                                    <button class="act-btn" onclick={previewCurrentCode} title={showPreview ? 'Hide preview' : 'Preview'} class:active={showPreview}>
                                        <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M2 3.5A1.5 1.5 0 013.5 2h8A1.5 1.5 0 0113 3.5v8a1.5 1.5 0 01-1.5 1.5h-8A1.5 1.5 0 012 11.5v-8z" stroke="currentColor" stroke-width="1.1"/><path d="M6 6l3 1.5-3 1.5V6z" fill="currentColor" opacity="0.6"/></svg>
                                    </button>
                                {/if}
                                <button class="act-btn" onclick={() => copyToClipboard($chat.response)} title="Copy code">
                                    <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><rect x="5" y="5" width="7.5" height="7.5" rx="1.2" stroke="currentColor" stroke-width="1.1"/><path d="M3 10V3.5A.5.5 0 013.5 3H10" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/></svg>
                                </button>
                                {#if _respLang !== 'multi'}
                                <button class="act-btn" onclick={downloadCode} title="Download">
                                    <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M7.5 2.5v7M5 7.5l2.5 2.5L10 7.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/><path d="M3 11.5h9" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
                                </button>
                                {/if}
                                {#if $chat.undoStack.length > 0}
                                    <button class="act-btn undo" onclick={undo} title="Undo last edit ({$chat.undoStack.length})">
                                        <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M3 7.5h9M3 7.5l3-3M3 7.5l3 3" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                                    </button>
                                {/if}
                            </div>
                        </div>
                        {#if codeExpanded}
                            <pre class="output-source"><code class="hljs">{@html highlightCode($chat.response, ext)}</code></pre>
                        {/if}
                    </div>
                {/if}

                <!-- Computer mode: files-created card -->
                {#if $chat.response && isComputerRoute}
                    {@const createdFiles = $chat.savedFiles.length > 0 ? $chat.savedFiles : parseFileList($chat.response)}
                    <div class="computer-result-card">
                        <div class="computer-result-header">
                            <div class="computer-result-icon">
                                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                                    <path d="M4 5.5l3 2.5-3 2.5M8.5 11H12" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
                                    <rect x="1.5" y="2" width="13" height="12" rx="2" stroke="currentColor" stroke-width="1.1"/>
                                </svg>
                            </div>
                            <div class="computer-result-info">
                                <span class="computer-result-title">{createdFiles.length} file{createdFiles.length !== 1 ? 's' : ''} written</span>
                                <span class="computer-result-meta">{formatChars($chat.response.length)}</span>
                            </div>
                            <div class="computer-result-actions">
                                <button class="act-btn" onclick={() => codeExpanded = !codeExpanded} title="View source" class:active={codeExpanded}>
                                    <svg width="14" height="14" viewBox="0 0 15 15" fill="none"><path d="M5.5 3.5L2.5 7.5l3 4M9.5 3.5l3 4-3 4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                                </button>
                                <button class="act-btn" onclick={() => copyToClipboard($chat.response)} title="Copy all">
                                    <svg width="14" height="14" viewBox="0 0 15 15" fill="none"><rect x="5" y="5" width="7.5" height="7.5" rx="1.2" stroke="currentColor" stroke-width="1.1"/><path d="M3 10V3.5A.5.5 0 013.5 3H10" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/></svg>
                                </button>
                            </div>
                        </div>
                        {#if createdFiles.length > 0}
                            <div class="computer-file-grid">
                                {#each createdFiles as filePath}
                                    {@const ext = extOf(filePath)}
                                    {@const name = filePath.split('/').pop() || filePath}
                                    <button class="computer-file-item" onclick={() => onFileSelect(filePath)}>
                                        <span class="computer-file-ext" style="--fc: {extColor(ext)}">{ext.toUpperCase().slice(0, 4)}</span>
                                        <span class="computer-file-name">{name}</span>
                                    </button>
                                {/each}
                            </div>
                        {/if}
                        {#if codeExpanded}
                            <pre class="output-source"><code class="hljs">{@html highlightCode($chat.response, 'html')}</code></pre>
                        {/if}
                    </div>
                {/if}

                <!-- Feedback row for the active (most recent) response -->
                {#if $chat.phase === 'done' && $chat.response}
                    {@const _lastIdx = $chat.conversation.length - 1}
                    {@const _lastTurn = $chat.conversation[_lastIdx]}
                    <div class="bubble-row">
                        <div class="feedback-row" style="opacity:1">
                            <button class="feedback-btn" class:active={_lastTurn?.feedback === 1}
                                onclick={() => setFeedback(_lastIdx, _lastTurn?.feedback === 1 ? 0 : 1)} title="Good response">
                                <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M2 9.5h2V14H2zM4 9.5l2.5-7A1.5 1.5 0 018 1.5v0a1.5 1.5 0 011.5 1.5V6h3.84a1.5 1.5 0 011.48 1.75l-.93 5.5A1.5 1.5 0 0112.41 14.5H4z" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>
                            </button>
                            <button class="feedback-btn bad" class:active={_lastTurn?.feedback === -1}
                                onclick={() => setFeedback(_lastIdx, _lastTurn?.feedback === -1 ? 0 : -1)} title="Bad response">
                                <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M2 6.5h2V1.5H2zM4 6.5l2.5 7A1.5 1.5 0 008 14.5v0a1.5 1.5 0 001.5-1.5V10h3.84a1.5 1.5 0 001.48-1.75l-.93-5.5A1.5 1.5 0 0012.41 1.5H4z" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>
                            </button>
                            <button class="feedback-btn regen" onclick={() => regenerate(_lastIdx)} title="Retry — get a new response">
                                <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M1 8a7 7 0 0112.3-4.5M15 8a7 7 0 01-12.3 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M13 1v3h-3M3 15v-3h3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
                            </button>
                            <button class="feedback-btn copy-resp" onclick={() => copyToClipboard($chat.response)} title="Copy response">
                                <svg width="14" height="14" viewBox="0 0 15 15" fill="none"><rect x="5" y="5" width="7.5" height="7.5" rx="1.2" stroke="currentColor" stroke-width="1.1"/><path d="M3 10V3.5A.5.5 0 013.5 3H10" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/></svg>
                            </button>
                        </div>
                    </div>
                {/if}

                <!-- Summary + Trace -->
                {#if hasThinking || hasValidation || ($chat.reflection && $chat.reflection.self_score > 0)}
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
                    {@const hasBothDistinct = !!$chat.draftThinking && !!$chat.thinking && $chat.draftThinking !== $chat.thinking}
                    <div class="trace-card" style="--tbc: var(--brain)">
                        {#if hasBothDistinct}
                            <div class="trace-section">
                                <span class="trace-label">Draft reasoning</span>
                                <pre class="trace-pre">{$chat.draftThinking}</pre>
                            </div>
                            <div class="trace-section">
                                <span class="trace-label">Final reasoning</span>
                                <pre class="trace-pre">{$chat.thinking}</pre>
                            </div>
                        {:else}
                            <div class="trace-section">
                                <span class="trace-label">Thinking</span>
                                <pre class="trace-pre">{$chat.thinking || $chat.draftThinking}</pre>
                            </div>
                        {/if}
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

        <div class="input-with-terminal">
            <ChatInput />
            {#if isComputerMode && activeWorkspaceId && !showTerminal}
                <button class="reopen-computer" onclick={() => { showTerminal = true; }}>
                    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                        <path d="M4 5.5l3 2.5-3 2.5M8.5 11H12" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
                        <rect x="1.5" y="2" width="13" height="12" rx="2" stroke="currentColor" stroke-width="1.1"/>
                    </svg>
                    <span>Terminal</span>
                </button>
            {/if}
        </div>
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
                outputType={previewOverride ? previewOutputType : (isHtmlOutput ? 'html_page' : ($chat.plan?.output_type ?? 'other'))}
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

            <!-- Tab bar -->
            <div class="computer-tabs">
                <button class="computer-tab" class:active={computerTab === 'files'} onclick={() => { computerTab = 'files'; viewingFile = null; }}>
                    <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                        <path d="M2 4.5A1.5 1.5 0 013.5 3h3.379a1.5 1.5 0 011.06.44l.622.62a1.5 1.5 0 001.06.44H12.5A1.5 1.5 0 0114 6v5.5a1.5 1.5 0 01-1.5 1.5h-9A1.5 1.5 0 012 11.5v-7z" stroke="currentColor" stroke-width="1.1"/>
                    </svg>
                    Files
                </button>
                <button class="computer-tab" class:active={computerTab === 'terminal'} onclick={() => { computerTab = 'terminal'; }}>
                    <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                        <path d="M4 5.5l3 2.5-3 2.5M8.5 11H12" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
                        <rect x="1.5" y="2" width="13" height="12" rx="2" stroke="currentColor" stroke-width="1.1"/>
                    </svg>
                    Terminal
                </button>
                <div class="tab-spacer"></div>
                <button class="computer-tab-action" onclick={() => { showTerminal = false; panelUserClosed = true; }} title="Close panel">
                    <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                        <path d="M10 3l-7 5 7 5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                </button>
            </div>

            <!-- Panel content -->
            <div class="computer-content">
                {#if viewingFile}
                    <div class="computer-fileview">
                        <div class="fileview-breadcrumb">
                            <button class="fileview-back" onclick={() => { viewingFile = null; }} title="Back to files">
                                <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                                    <path d="M10 3L5 8l5 5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
                                </svg>
                            </button>
                            <span class="fileview-dot" style="background: {extColor(extOf(viewingFile.path))}"></span>
                            <span class="fileview-crumb">{viewingFile.path}</span>
                            <button class="fileview-copy" onclick={() => copyToClipboard(viewingFile?.content ?? '')} title="Copy file">
                                <svg width="12" height="12" viewBox="0 0 15 15" fill="none"><rect x="5" y="5" width="7.5" height="7.5" rx="1.2" stroke="currentColor" stroke-width="1.1"/><path d="M3 10V3.5A.5.5 0 013.5 3H10" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/></svg>
                            </button>
                        </div>
                        <pre class="fileview-code"><code class="hljs">{@html highlightCode(viewingFile.content, extOf(viewingFile.path))}</code></pre>
                    </div>
                {:else if computerTab === 'files'}
                    <FileTree
                        bind:this={fileTreeRef}
                        workspaceId={activeWorkspaceId}
                        {onFileSelect}
                        activeFile={activeWorkspaceFile}

                    />
                {:else}
                    <TerminalPanel
                        workspaceId={activeWorkspaceId}
                        onClose={() => { showTerminal = false; panelUserClosed = true; }}
                        externalOutput={$chat.terminalOutput}
                        pendingCommands={$chat.pendingCommands}
                        onCommandsConsumed={clearPendingCommands}
                    />
                {/if}
            </div>
        </div>
    {/if}

    {#if copyFeedback}
        <div class="copy-toast">{copyFeedback}</div>
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
        width: min(100%, 1040px);
        max-width: none;
        margin: 0 auto;
        padding: 30px clamp(20px, 3vw, 40px) 24px;
    }

    /* ================================================================
       WELCOME SCREEN
       ================================================================ */
    .welcome {
        display: flex; flex-direction: column; align-items: center;
        justify-content: center;
        min-height: 58vh;
        padding: 0 24px 40px;
        gap: 16px;
        animation: fadeIn 0.5s ease both;
    }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }

    .welcome-title {
        font-size: 32px; font-weight: 700;
        color: var(--text);
        letter-spacing: -0.02em;
        margin: 0;
    }

    .welcome-sub {
        font-size: 15px; color: var(--text-secondary);
        margin: 0 0 8px;
    }

    .welcome-chips {
        display: flex; flex-wrap: wrap; gap: 10px;
        justify-content: center;
        max-width: 560px;
    }

    .welcome-chip {
        display: inline-flex; align-items: center; gap: 8px;
        padding: 10px 18px;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: var(--radius-pill);
        font-size: 13.5px; font-weight: 500;
        color: var(--text-secondary);
        cursor: pointer;
        transition: color 0.15s, border-color 0.15s, background 0.15s;
    }
    .welcome-chip:hover {
        color: var(--text);
        background: var(--surface-hover);
        border-color: var(--border-strong, var(--border));
    }
    .chip-icon {
        font-size: 14px;
        color: var(--accent);
        line-height: 1;
    }

    /* ================================================================
       USER BUBBLE
       ================================================================ */
    .user-bubble {
        align-self: flex-end;
        background: #1A1A1A;
        color: #FAFAF9;
        padding: 12px 20px;
        border-radius: 20px 20px 6px 20px;
        max-width: min(68%, 720px);
        font-size: 15px;
        font-weight: 400;
        line-height: 1.55;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.10), 0 1px 2px rgba(0, 0, 0, 0.06);
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
    }
    :global([data-theme="dark"]) .user-bubble {
        background: rgba(255, 255, 255, 0.18);
        color: #F0F0F0;
        box-shadow: 0 2px 12px rgba(0, 0, 0, 0.4);
    }
    .user-bubble p { margin: 0; }

    .user-actions {
        align-self: flex-end;
        display: flex; gap: 6px;
        opacity: 0;
        transition: opacity 0.15s;
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
    }
    .user-bubble:hover ~ .user-actions,
    .user-actions:hover { opacity: 1; }

    .user-action-btn {
        display: inline-flex; align-items: center; gap: 5px;
        padding: 4px 10px;
        font-size: 11.5px; font-weight: 500;
        color: var(--text-muted);
        background: transparent;
        border: 1px solid transparent;
        border-radius: 20px;
        cursor: pointer;
        transition: color 0.12s, background 0.12s, border-color 0.12s;
    }
    .user-action-btn:hover {
        color: var(--text-secondary);
        background: var(--surface);
        border-color: var(--border);
    }

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
        padding: 17px 22px;
        color: var(--text);
        font-size: 15px;
        line-height: 1.7;
        max-width: min(92%, 860px);
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
    /* Bare <pre> (not wrapped by our renderer) */
    .ai-bubble :global(pre) {
        margin: 10px 0; overflow-x: auto;
        background: var(--code-bg);
        border: 1px solid var(--border-subtle);
        border-radius: 10px; padding: 11px 14px;
    }
    .ai-bubble :global(code) { font-size: 12.5px; }
    .ai-bubble :global(p code), .ai-bubble :global(li code) {
        background: var(--code-inline-bg); padding: 1px 5px; border-radius: 4px; font-size: 12.5px;
    }
    /* ── Code block wrapper (injected by markdown renderer) ── */
    .ai-bubble :global(.cb) {
        margin: 12px 0;
        border: 1px solid var(--border);
        border-radius: 10px;
        overflow: hidden;
        background: var(--code-bg);
    }
    .ai-bubble :global(.cb:first-child) { margin-top: 0; }
    .ai-bubble :global(.cb:last-child) { margin-bottom: 0; }
    .ai-bubble :global(.cb pre) {
        margin: 0;
        border: none;
        border-radius: 0;
        background: transparent;
        padding: 13px 16px;
        overflow-x: auto;
    }
    .ai-bubble :global(.cb-head) {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 6px 12px;
        border-bottom: 1px solid var(--border);
        background: var(--accent-subtle);
        min-height: 32px;
    }
    .ai-bubble :global(.cb-lang) {
        font-size: 11px;
        font-family: var(--font-mono);
        color: var(--text-secondary);
        font-weight: 500;
        letter-spacing: 0.02em;
    }
    .ai-bubble :global(.cb-copy) {
        font-size: 11px;
        font-weight: 500;
        padding: 2px 9px;
        border-radius: 5px;
        border: 1px solid var(--border);
        background: transparent;
        color: var(--text-secondary);
        cursor: pointer;
        font-family: inherit;
        transition: background 0.12s, color 0.12s;
        line-height: 1.6;
    }
    .ai-bubble :global(.cb-copy:hover) {
        background: var(--surface);
        color: var(--text);
        border-color: var(--border-strong);
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
        max-width: min(420px, 82%);
    }
    .step.polish { border-left: 2px solid var(--success); }

    .step-dot {
        width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0;
        background: var(--brain);
    }
    .step-dot.polish { background: var(--success); }
    .step-dot.pulse { animation: pulse 6s ease-in-out infinite; }

    .step-text {
        font-size: 12.5px; font-weight: 500;
        color: var(--text-secondary);
        letter-spacing: 0.01em;
    }
    .step-meta {
        font-size: 11px; font-family: var(--font-mono);
        color: var(--text-muted); margin-left: auto;
    }

    /* ---- Planning card (spec thinking stream) ---- */
    .planning-card {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 14px;
        overflow: hidden;
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
        align-self: flex-start;
        max-width: min(560px, 92%);
    }
    .planning-header {
        display: flex; align-items: center; gap: 8px;
        padding: 8px 14px;
        border-bottom: 1px solid var(--border);
    }
    .planning-dot {
        width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0;
        background: var(--brain);
    }
    .planning-dot.pulse { animation: pulse 6s ease-in-out infinite; }
    .planning-label {
        font-size: 12.5px; font-weight: 500;
        color: var(--text-secondary); letter-spacing: 0.01em;
    }
    .planning-body {
        margin: 0;
        padding: 10px 14px;
        font-family: var(--font-mono);
        font-size: 11.5px;
        line-height: 1.6;
        color: var(--text-muted);
        white-space: pre-wrap;
        word-break: break-word;
        max-height: 220px;
        overflow-y: auto;
        background: none;
        border: none;
        border-radius: 0;
        box-shadow: none;
    }

    .spec-stream {
        background: var(--card); border: 1px solid var(--border); border-radius: 8px;
        margin: 4px 0; max-height: 200px; overflow-y: auto;
    }
    .spec-stream-pre {
        padding: 10px 12px; margin: 0; font-size: 0.75rem; color: var(--text-2);
        white-space: pre-wrap; word-break: break-word; font-family: var(--font-mono);
    }

    /* ================================================================
       COMPONENT PROGRESS (Precision-Design pipeline)
       ================================================================ */
    .component-progress {
        background: var(--surface);
        border: 1px solid var(--border);
        border-left: 2px solid var(--brain);
        border-radius: var(--radius);
        padding: 10px 14px;
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
        max-width: min(520px, 84%);
    }
    .comp-header {
        display: flex; align-items: center; justify-content: space-between;
        margin-bottom: 8px;
    }
    .comp-title {
        font-size: 12px; font-weight: 600;
        color: var(--text-secondary);
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .comp-count {
        font-size: 11px; font-family: var(--font-mono);
        color: var(--text-muted);
    }
    .comp-items { display: flex; flex-direction: column; gap: 4px; }
    .comp-item {
        display: flex; align-items: center; gap: 8px;
        font-size: 12px; color: var(--text-secondary);
    }
    .comp-item.done { color: var(--success, #22c55e); }
    .comp-item.patching { color: var(--warning, #f59e0b); }
    .comp-item.fallback { color: var(--text-muted); opacity: 0.7; }
    .comp-dot {
        width: 5px; height: 5px; border-radius: 50%;
        background: var(--text-muted); flex-shrink: 0;
    }
    .comp-item.done .comp-dot { background: var(--success, #22c55e); }
    .comp-item.patching .comp-dot { background: var(--warning, #f59e0b); }
    .comp-dot.pulse { animation: pulse 6s ease-in-out infinite; background: var(--brain); }
    .comp-name { font-family: var(--font-mono); }
    .comp-status {
        margin-left: auto; font-size: 10px;
        font-family: var(--font-mono);
        opacity: 0.6;
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
        max-width: min(760px, 92%);
    }
    .gen-card.fixing { border-left-color: var(--warning); }

    .gen-bar {
        display: flex; align-items: center; gap: 10px;
        padding: 9px 16px;
    }
    .gen-indicator {
        width: 6px; height: 6px; border-radius: 50%;
        background: var(--brain);
        box-shadow: 0 0 6px rgba(232, 133, 12, 0.25);
        animation: pulse 6s ease-in-out infinite;
    }
    .gen-title {
        font-size: 12px; font-weight: 600;
        color: var(--text-secondary);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .gen-stats {
        display: flex; align-items: center; gap: 8px;
        margin-left: auto;
    }
    .gen-meta {
        font-size: 11px; font-family: var(--font-mono);
        color: var(--text-muted);
    }
    .gen-speed {
        font-size: 10px; font-family: var(--font-mono);
        color: var(--text-muted);
        background: var(--accent-subtle);
        padding: 1px 7px;
        border-radius: var(--radius-pill);
        border: 1px solid var(--border-subtle);
        opacity: 0.7;
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

    .stream-cursor {
        display: inline-block;
        width: 2px; height: 14px;
        background: var(--accent);
        border-radius: 1px;
        margin-left: 2px;
        vertical-align: middle;
        animation: cursorBlink 0.75s step-end infinite;
    }
    @keyframes cursorBlink {
        0%, 100% { opacity: 1; }
        50% { opacity: 0; }
    }

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

    .stop-btn {
        display: flex; align-items: center; justify-content: center;
        width: 26px; height: 26px;
        background: rgba(239, 68, 68, 0.08);
        border: 1px solid rgba(239, 68, 68, 0.15);
        border-radius: 7px;
        color: var(--error); cursor: pointer;
        transition: all var(--transition); flex-shrink: 0;
    }
    .stop-btn:hover {
        background: rgba(239, 68, 68, 0.18);
        border-color: rgba(239, 68, 68, 0.30);
    }
    /* ================================================================
       REFINE CARD
       ================================================================ */
    .refine-card {
        background: var(--surface-solid);
        border: 1px solid var(--border);
        border-left: 2px solid var(--brain);
        border-radius: 12px;
        overflow: hidden;
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
        max-width: min(520px, 84%);
    }
    .refine-bar {
        display: flex; align-items: center; gap: 8px;
        padding: 10px 14px;
    }
    .refine-icon {
        color: var(--brain);
        display: flex; align-items: center;
        animation: refine-spin 4s linear infinite;
    }
    .refine-title {
        font-size: 12px; font-weight: 600;
        color: var(--text-secondary);
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .refine-sub {
        font-size: 11px;
        color: var(--text-muted);
        margin-left: auto;
    }
    .refine-progress {
        height: 2px;
        background: var(--border-subtle);
    }
    .refine-bar-fill {
        height: 100%;
        background: var(--brain);
        border-radius: 2px;
        animation: refine-progress 12s ease-out forwards;
    }
    @keyframes refine-spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
    }
    @keyframes refine-progress {
        0% { width: 0%; }
        30% { width: 40%; }
        60% { width: 70%; }
        90% { width: 88%; }
        100% { width: 95%; }
    }

    /* ================================================================
       CHECKLIST CARD
       ================================================================ */
    .checklist-card {
        background: var(--surface-solid);
        border: 1px solid var(--border);
        border-left: 2px solid var(--warning);
        border-radius: 14px;
        overflow: hidden;
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
        max-width: min(640px, 88%);
    }
    .checklist-card.all-done { border-left-color: var(--success); }

    .checklist-header {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 9px 14px;
        border-bottom: 1px solid var(--border-subtle);
    }
    .checklist-icon {
        font-size: 9px;
        color: var(--warning);
    }
    .checklist-card.all-done .checklist-icon { color: var(--success); }
    .checklist-title {
        font-size: 11px;
        font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        flex: 1;
    }
    .checklist-count {
        font-size: 11px;
        font-family: var(--font-mono);
        font-weight: 600;
        color: var(--warning);
    }
    .checklist-count.complete { color: var(--success); }

    .checklist-items {
        padding: 8px 14px 10px;
        display: flex;
        flex-direction: column;
        gap: 0;
    }
    .checklist-row {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 5px 0;
        border-bottom: 1px solid var(--border-subtle);
    }
    .checklist-row:last-child { border-bottom: none; }

    .check-mark {
        width: 16px; height: 16px;
        flex-shrink: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--success);
    }
    .check-empty {
        width: 7px; height: 7px;
        border-radius: 50%;
        border: 1.5px solid var(--text-muted);
        opacity: 0.4;
    }
    .check-label {
        font-size: 12px;
        font-weight: 500;
        color: var(--text-secondary);
        line-height: 1.35;
    }
    .checklist-row.done .check-label {
        text-decoration: line-through;
        color: var(--text-muted);
    }

    /* ================================================================
       THINKING BLOCK
       ================================================================ */
    .think-block {
        background: var(--surface-solid);
        border: 1px solid var(--border);
        border-left: 2px solid var(--text-muted);
        border-radius: 12px;
        overflow: hidden;
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
        max-width: min(760px, 92%);
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
        width: 6px; height: 6px; border-radius: 50%;
        background: var(--text-muted);
        animation: pulse 6s ease-in-out infinite;
    }
    .think-meta {
        font-family: var(--font-mono); font-size: 10px;
        font-weight: 400; color: var(--text-muted); opacity: 0.6;
    }
    .think-body {
        font-family: var(--font-mono); font-size: 11px; line-height: 1.55;
        color: var(--text-secondary); white-space: pre-wrap; word-break: break-word;
        margin: 0; padding: 10px 14px 12px;
        border-top: 1px solid var(--border-subtle);
        background: none; border-left: none; border-right: none; border-bottom: none; border-radius: 0;
        max-height: 320px; overflow-y: auto;
        scrollbar-width: thin;
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
        max-width: min(760px, 92%);
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
    .code-explanation {
        font-size: 13.5px;
        line-height: 1.6;
        color: var(--text-primary);
        padding: 4px 2px 8px;
        white-space: pre-wrap;
    }
    .output-card {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 14px;
        overflow: hidden;
        box-shadow: var(--bubble-glow);
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
        max-width: min(760px, 92%);
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
        max-height: 400px; overflow-y: auto; margin: 0; border-radius: 0;
    }
    .output-source :global(code.hljs) {
        background: transparent; padding: 0; font-size: inherit;
        font-family: inherit; line-height: inherit;
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
        background: var(--surface-solid, #0A0A0A);
        border: 1px solid var(--border-strong);
        border-left: 2px solid var(--tbc, var(--text-muted));
        border-radius: 12px;
        overflow: hidden;
        animation: slideUpSpring 280ms var(--spring-soft) both;
        max-width: min(760px, 92%);
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
    @media (hover: none) {
        .feedback-row {
            opacity: 1;
        }
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
    .feedback-btn.copy-resp:hover {
        color: var(--text-secondary);
        background: var(--accent-subtle);
    }

    /* ── Alt version navigation (← 1/2 →) ── */
    .alt-nav {
        display: flex; align-items: center; gap: 1px;
        margin-right: 4px;
    }
    .alt-btn {
        background: none; border: none;
        color: var(--text-muted); cursor: pointer;
        padding: 3px 5px; border-radius: 5px;
        font-size: 13px; line-height: 1;
        transition: color var(--transition), background var(--transition);
    }
    .alt-btn:hover:not(:disabled) {
        background: var(--accent-subtle);
        color: var(--text-secondary);
    }
    .alt-btn:disabled { opacity: 0.25; cursor: default; }
    .alt-counter {
        font-size: 10px; font-family: var(--font-mono);
        color: var(--text-muted);
        min-width: 26px; text-align: center;
    }

    /* ================================================================
       REOPEN COMPUTER PANEL BUTTON
       ================================================================ */
    .input-with-terminal {
        display: flex;
        align-items: flex-end;
        gap: 8px;
        width: 100%;
    }
    .input-with-terminal > :global(:first-child) {
        flex: 1;
        min-width: 0;
    }
    .reopen-computer {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 8px 14px;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 12px;
        color: var(--text-secondary);
        font-family: var(--font-body);
        font-size: 12px;
        font-weight: 500;
        cursor: pointer;
        transition: all var(--transition);
        white-space: nowrap;
        flex-shrink: 0;
        margin-bottom: 8px;
    }
    .reopen-computer:hover {
        background: var(--surface-hover);
        color: var(--text);
        border-color: var(--border-strong);
    }

    /* ================================================================
       COMPUTER MODE PANEL
       ================================================================ */
    .computer-panel {
        top: 56px;
        background: var(--surface-solid);
        border-left: none;
        box-shadow: -8px 0 24px rgba(0, 0, 0, 0.03);
        display: flex;
        flex-direction: column;
    }
    :global([data-theme="dark"]) .computer-panel {
        background: #0a0a0e;
        box-shadow: -8px 0 24px rgba(0, 0, 0, 0.3);
    }

    .computer-tabs {
        display: flex;
        align-items: center;
        height: 40px;
        padding: 0 8px;
        gap: 2px;
        background: transparent;
        border-bottom: 1px solid var(--border-subtle);
        flex-shrink: 0;
        overflow-x: auto;
    }
    .computer-tab {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 6px 14px;
        border: none;
        background: none;
        cursor: pointer;
        font-family: var(--font-body);
        font-size: 11.5px;
        font-weight: 500;
        color: var(--text-muted);
        border-radius: 8px;
        transition: all var(--transition);
        white-space: nowrap;
        position: relative;
    }
    .computer-tab:hover {
        color: var(--text-secondary);
        background: var(--accent-subtle);
    }
    .computer-tab.active {
        color: var(--text);
        background: var(--surface);
        font-weight: 600;
    }
    .tab-spacer { flex: 1; }
    .computer-tab-action {
        width: 28px; height: 28px;
        border: none; background: none;
        cursor: pointer;
        display: flex; align-items: center; justify-content: center;
        color: var(--text-muted);
        border-radius: 6px;
        transition: all var(--transition);
        flex-shrink: 0;
    }
    .computer-tab-action:hover {
        background: var(--accent-subtle);
        color: var(--text);
    }

    .computer-content {
        flex: 1;
        overflow: hidden;
    }

    .computer-fileview {
        display: flex;
        flex-direction: column;
        height: 100%;
        overflow: hidden;
    }
    .fileview-breadcrumb {
        height: 36px;
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 0 10px;
        background: transparent;
        border-bottom: 1px solid var(--border-subtle);
        flex-shrink: 0;
    }
    .fileview-back {
        width: 24px; height: 24px;
        border: none; background: none;
        cursor: pointer;
        display: flex; align-items: center; justify-content: center;
        color: var(--text-muted);
        border-radius: 6px;
        transition: all var(--transition);
        flex-shrink: 0;
    }
    .fileview-back:hover {
        background: var(--accent-subtle);
        color: var(--text);
    }
    .fileview-dot {
        width: 6px; height: 6px;
        border-radius: 50%;
        flex-shrink: 0;
    }
    .fileview-crumb {
        flex: 1;
        font-family: var(--font-mono);
        font-size: 11px;
        color: var(--text-secondary);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .fileview-copy {
        width: 24px; height: 24px;
        border: none; background: none;
        cursor: pointer;
        display: flex; align-items: center; justify-content: center;
        color: var(--text-muted);
        border-radius: 6px;
        transition: all var(--transition);
        flex-shrink: 0;
    }
    .fileview-copy:hover {
        background: var(--accent-subtle);
        color: var(--text);
    }
    .fileview-code {
        flex: 1;
        overflow: auto;
        padding: 14px 16px;
        margin: 0;
        font-family: var(--font-mono);
        font-size: 12px;
        line-height: 1.65;
        color: var(--text);
        background: transparent;
        white-space: pre-wrap;
        word-break: break-all;
        scrollbar-width: thin;
        tab-size: 4;
        border: none; border-radius: 0;
    }
    .fileview-code :global(code.hljs) {
        background: transparent; padding: 0;
        font-size: inherit; font-family: inherit;
        line-height: inherit;
    }

    .act-btn.undo {
        color: var(--brain);
    }
    .act-btn.undo:hover {
        background: rgba(232, 133, 12, 0.08);
    }

    /* ================================================================
       COMPUTER MODE RESULT CARD (in chat)
       ================================================================ */
    .computer-result-card {
        background: var(--surface);
        border: 1px solid var(--border);
        border-left: 2px solid var(--brain);
        border-radius: 14px;
        overflow: hidden;
        box-shadow: var(--bubble-glow);
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
        max-width: min(760px, 92%);
    }
    .computer-result-header {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px 16px;
    }
    .computer-result-icon {
        width: 34px; height: 34px;
        display: flex; align-items: center; justify-content: center;
        background: rgba(232, 133, 12, 0.14);
        border: 1px solid rgba(232, 133, 12, 0.25);
        border-radius: 10px;
        color: var(--brain);
        flex-shrink: 0;
    }
    .computer-result-info {
        flex: 1;
        display: flex;
        flex-direction: column;
        gap: 2px;
    }
    .computer-result-title {
        font-family: var(--font-body);
        font-size: 13px;
        font-weight: 600;
        color: var(--text);
    }
    .computer-result-meta {
        font-family: var(--font-mono);
        font-size: 10.5px;
        color: var(--text-muted);
    }
    .computer-result-actions {
        display: flex; gap: 3px;
    }
    .computer-file-grid {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        padding: 0 16px 14px;
    }
    .computer-file-item {
        display: flex;
        align-items: center;
        gap: 7px;
        padding: 5px 12px 5px 6px;
        background: var(--accent-subtle);
        border: 1px solid var(--border-subtle);
        border-radius: 8px;
        cursor: pointer;
        transition: all var(--transition);
        font-family: var(--font-mono);
        font-size: 11.5px;
        color: var(--text);
    }
    .computer-file-item:hover {
        background: var(--surface-hover);
        border-color: var(--border);
    }
    .computer-file-ext {
        font-size: 8px;
        font-weight: 700;
        letter-spacing: 0.02em;
        color: var(--fc);
        background: color-mix(in srgb, var(--fc) 10%, transparent);
        padding: 2px 5px;
        border-radius: 4px;
        min-width: 22px;
        text-align: center;
    }
    .computer-file-name {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        max-width: 160px;
    }

    .copy-toast {
        position: fixed; bottom: 80px; left: 50%;
        transform: translateX(-50%);
        padding: 6px 18px;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: var(--radius-pill);
        font-size: 12px; font-weight: 600;
        color: var(--success);
        box-shadow: 0 4px 16px rgba(0,0,0,0.12);
        z-index: 1000;
        animation: slideUpSpring var(--spring-duration) var(--spring-soft) both;
    }

    .fetch-status { display: flex; flex-direction: column; gap: 4px; margin: 6px 0; }
    .fetch-row { display: flex; align-items: center; gap: 6px; font-size: 0.78rem; color: var(--text-2); }
    .fetch-row.done { color: var(--text-2); }
    .fetch-row.failed { color: var(--warning); }
    .fetch-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); flex-shrink: 0; }
    .fetch-dot.pulse { animation: pulse 1s infinite; }
    .fetch-url { opacity: 0.7; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 400px; }
    .fetch-error { opacity: 0.8; font-style: italic; }
    .fetch-label { font-weight: 500; min-width: 52px; }

    .fetch-card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; margin: 4px 0; overflow: hidden; }
    .fetch-card-header { display: flex; align-items: center; gap: 8px; padding: 8px 12px; cursor: pointer; font-size: 0.8rem; color: var(--text-2); }
    .fetch-card-header::-webkit-details-marker { display: none; }
    .fetch-card-icon { font-weight: 700; font-size: 0.7rem; background: var(--accent); color: var(--bg); width: 18px; height: 18px; border-radius: 4px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
    .fetch-card-title { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .fetch-card-meta { margin-left: auto; opacity: 0.6; flex-shrink: 0; }
    .fetch-card-trunc { font-size: 0.7rem; opacity: 0.5; font-style: italic; }
    .fetch-card-body { padding: 8px 12px; font-size: 0.75rem; color: var(--text-2); max-height: 200px; overflow-y: auto; white-space: pre-wrap; word-break: break-word; border-top: 1px solid var(--border); margin: 0; }

</style>
