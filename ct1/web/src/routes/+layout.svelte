<script lang="ts">
    import '../app.css';
    import { chat, connect, disconnect, newConversation } from '$lib/stores/chat';
    import { page } from '$app/stores';
    import { goto } from '$app/navigation';
    import { onMount, onDestroy } from 'svelte';
    import Sidebar from '$lib/components/Sidebar.svelte';
    import ShortcutOverlay from '$lib/components/ShortcutOverlay.svelte';
    import ModelSwitcher from '$lib/components/ModelSwitcher.svelte';
    import Ct2Layout from '$lib/ct2/Layout.svelte';
    import { backgroundTasks } from '$lib/stores/backgroundTasks';
    import { fly } from 'svelte/transition';
    import { sidebarOpen } from '$lib/stores/conversations';
    import { preferences, toggleTheme } from '$lib/stores/preferences';
    import { getPhaseLabel } from '$lib/chatUi';

    function startNewChat() {
        newConversation();
        sidebarOpen.set(false);
        goto('/');
    }

    onMount(() => connect());
    onDestroy(() => disconnect());

    let { children } = $props();

    let shortcutOverlayOpen = $state(false);
    let isCt2 = $derived($preferences.uiStyle === 'ct2');
    let classicBg = $derived($preferences.classicBg ?? 'default');

    function handleKeydown(e: KeyboardEvent) {
        if (e.ctrlKey && e.key === 'n') {
            e.preventDefault();
            startNewChat();
        }
        if (e.ctrlKey && e.shiftKey && (e.key === 'S' || e.key === 's')) {
            e.preventDefault();
            sidebarOpen.update(v => !v);
        }
        if (e.ctrlKey && e.key === '/') {
            e.preventDefault();
            shortcutOverlayOpen = !shortcutOverlayOpen;
        }
        if (e.key === 'Escape') {
            shortcutOverlayOpen = false;
        }
    }

    // ── Classic UI notification tray ──────────────────────────────
    let dismissedIds = $state(new Set<string>());
    let visibleTasks = $derived($backgroundTasks.filter(t => !dismissedIds.has(t.id)));
    function dismissTask(id: string) { dismissedIds = new Set([...dismissedIds, id]); }
    $effect(() => {
        const active = new Set($backgroundTasks.map(t => t.id));
        const pruned = [...dismissedIds].filter(id => active.has(id));
        if (pruned.length !== dismissedIds.size) dismissedIds = new Set(pruned);
    });

    let phaseText = $derived(getPhaseLabel($chat.phase));
    let isActive = $derived($chat.phase !== 'idle' && $chat.phase !== 'done');

    let pre = $state<HTMLPreElement | null>(null);

    onMount(() => {
        if (!pre) return;

        const R1 = 1, R2 = 2, K2 = 5;
        const charW = 8.4, charH = 14;
        const screenW = Math.min(120, Math.floor(window.innerWidth / charW));
        const screenH = Math.min(60, Math.floor(window.innerHeight / charH));
        const K1 = screenW * K2 * 3 / (8 * (R1 + R2));

        let A = 0, B = 0;
        const luminanceChars = '.,-~:;=!*#$@';

        function renderFrame() {
            if (!pre) return;
            const output: string[] = new Array(screenW * screenH).fill(' ');
            const zbuffer: number[] = new Array(screenW * screenH).fill(0);

            const cosA = Math.cos(A), sinA = Math.sin(A);
            const cosB = Math.cos(B), sinB = Math.sin(B);

            for (let theta = 0; theta < 6.28; theta += 0.07) {
                const cosTheta = Math.cos(theta), sinTheta = Math.sin(theta);
                for (let phi = 0; phi < 6.28; phi += 0.02) {
                    const cosPhi = Math.cos(phi), sinPhi = Math.sin(phi);
                    const circleX = R2 + R1 * cosTheta;
                    const circleY = R1 * sinTheta;
                    const x = circleX * (cosB * cosPhi + sinA * sinB * sinPhi) - circleY * cosA * sinB;
                    const y = circleX * (sinB * cosPhi - sinA * cosB * sinPhi) + circleY * cosA * cosB;
                    const z = K2 + cosA * circleX * sinPhi + circleY * sinA;
                    const ooz = 1 / z;
                    const xp = Math.floor(screenW / 2 + K1 * ooz * x);
                    const yp = Math.floor(screenH / 2 - K1 * ooz * y * 0.5);
                    const L = cosPhi * cosTheta * sinB - cosA * cosTheta * sinPhi - sinA * sinTheta + cosB * (cosA * sinTheta - cosTheta * sinA * sinPhi);
                    if (yp >= 0 && yp < screenH && xp >= 0 && xp < screenW && ooz > zbuffer[yp * screenW + xp]) {
                        zbuffer[yp * screenW + xp] = ooz;
                        const lIdx = Math.max(0, Math.floor(L * 8));
                        output[yp * screenW + xp] = luminanceChars[Math.min(lIdx, luminanceChars.length - 1)];
                    }
                }
            }

            let frame = '';
            for (let j = 0; j < screenH; j++) {
                for (let i = 0; i < screenW; i++) {
                    frame += output[j * screenW + i];
                }
                frame += '\n';
            }
            pre.textContent = frame;
            A += 0.03;
            B += 0.015;
        }

        const id = setInterval(renderFrame, 100);
        renderFrame();
        return () => clearInterval(id);
    });
</script>

<svelte:window onkeydown={handleKeydown} />

{#if isCt2}
    <Ct2Layout>
        {@render children()}
    </Ct2Layout>
{:else}
    <div class="app" class:has-image-bg={classicBg === 'image'}>
        {#if classicBg === 'image'}
            <div class="classic-img-bg" aria-hidden="true"></div>
        {:else}
            <div class="donut-bg" aria-hidden="true">
                <pre class="donut" bind:this={pre}></pre>
            </div>
        {/if}

        <header class="topbar">
            <div class="topbar-left">
                <button class="tb-btn" class:active={$sidebarOpen} onclick={() => sidebarOpen.update(v => !v)} aria-label="Toggle sidebar" title="History (Ctrl+Shift+S)">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                        <path d="M3 6h18M3 12h18M3 18h18" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
                    </svg>
                </button>

                <a href="/" class="logo">
                    <span class="logo-ct">CT</span>
                    <span class="logo-divider"></span>
                    <span class="logo-num">2</span>
                </a>
            </div>

            <div class="topbar-center">
                {#if isActive && phaseText}
                    <div class="phase-pill">
                        <div class="phase-dot"></div>
                        <span class="phase-label">{phaseText}</span>
                    </div>
                {:else}
                    <ModelSwitcher />
                {/if}
            </div>

            <nav class="topbar-right">
                <button class="tb-btn" onclick={toggleTheme} title="Toggle theme">
                    {#if $preferences.theme === 'dark'}
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                            <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    {:else}
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                            <circle cx="12" cy="12" r="5" stroke="currentColor" stroke-width="1.6"/>
                            <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M17.36 17.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M17.36 6.64l1.42-1.42" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
                        </svg>
                    {/if}
                </button>

                <div class="tb-sep"></div>

                <a href="/journal" class="tb-text-btn" class:active={$page.url.pathname === '/journal'}>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                        <path d="M4 19.5A2.5 2.5 0 016.5 17H20" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
                        <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                    <span>Journal</span>
                </a>

                <a href="/settings" class="tb-text-btn" class:active={$page.url.pathname === '/settings'}>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                        <path d="M12.22 2h-.44a2 2 0 00-2 2v.18a2 2 0 01-1 1.73l-.43.25a2 2 0 01-2 0l-.15-.08a2 2 0 00-2.73.73l-.22.38a2 2 0 00.73 2.73l.15.1a2 2 0 011 1.72v.51a2 2 0 01-1 1.74l-.15.09a2 2 0 00-.73 2.73l.22.38a2 2 0 002.73.73l.15-.08a2 2 0 012 0l.43.25a2 2 0 011 1.73V20a2 2 0 002 2h.44a2 2 0 002-2v-.18a2 2 0 011-1.73l.43-.25a2 2 0 012 0l.15.08a2 2 0 002.73-.73l.22-.39a2 2 0 00-.73-2.73l-.15-.08a2 2 0 01-1-1.74v-.5a2 2 0 011-1.74l.15-.09a2 2 0 00.73-2.73l-.22-.38a2 2 0 00-2.73-.73l-.15.08a2 2 0 01-2 0l-.43-.25a2 2 0 01-1-1.73V4a2 2 0 00-2-2z" stroke="currentColor" stroke-width="1.5"/>
                        <circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="1.5"/>
                    </svg>
                    <span>Settings</span>
                </a>
            </nav>
        </header>

        <!-- ── Notification bubbles (top-right) ──────────────────── -->
        {#if visibleTasks.length > 0}
            <div class="classic-notif-tray" role="status" aria-live="polite">
                {#each visibleTasks as task (task.id)}
                    <div
                        class="classic-notif"
                        class:classic-notif-done={task.progress === 100}
                        transition:fly={{ x: 48, duration: 200 }}
                    >
                        <div class="classic-notif-head">
                            <div class="classic-notif-icon-label">
                                {#if task.variant === 'pulse' || task.progress < 0}
                                    <span class="classic-spinner classic-spinner-sm"></span>
                                {:else if task.progress === 100}
                                    <svg class="classic-notif-ok" width="13" height="13" viewBox="0 0 24 24" fill="none">
                                        <path d="M20 6L9 17l-5-5" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
                                    </svg>
                                {:else}
                                    <span class="classic-notif-pct">{task.progress}%</span>
                                {/if}
                                <span class="classic-notif-label">{task.label}</span>
                            </div>
                            <button class="classic-notif-close" onclick={() => dismissTask(task.id)} aria-label="Dismiss">
                                <svg width="10" height="10" viewBox="0 0 24 24" fill="none">
                                    <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>
                                </svg>
                            </button>
                        </div>
                        {#if task.detail}
                            <p class="classic-notif-detail">{task.detail}</p>
                        {/if}
                        {#if task.progress >= 0 && task.progress < 100}
                            <div class="classic-notif-bar">
                                <div class="classic-notif-fill" style="width: {task.progress}%"></div>
                            </div>
                        {/if}
                    </div>
                {/each}
            </div>
        {/if}

        <Sidebar />

        <main>
            {@render children()}
        </main>

        <ShortcutOverlay bind:open={shortcutOverlayOpen} />
    </div>
{/if}

<style>
    .app {
        display: flex;
        flex-direction: column;
        width: 100%;
        height: 100%;
        overflow: hidden;
        position: relative;
        background: var(--bg);
    }
    .app.has-image-bg {
        background: #080808;
    }
    :global([data-theme="light"]) .app.has-image-bg {
        background: #F0ECE5;
    }

    /* Frosted topbar over the image so icons stay legible */
    .app.has-image-bg .topbar {
        background: rgba(0, 0, 0, 0.20);
        backdrop-filter: blur(16px) saturate(1.2);
        -webkit-backdrop-filter: blur(16px) saturate(1.2);
    }
    :global([data-theme="light"]) .app.has-image-bg .topbar {
        background: rgba(255, 255, 255, 0.55);
        backdrop-filter: blur(16px) saturate(1.4);
        -webkit-backdrop-filter: blur(16px) saturate(1.4);
    }

    /* ---- Image background ---- */
    .classic-img-bg {
        position: absolute;
        inset: 0;
        z-index: 0;
        pointer-events: none;
        background:
            linear-gradient(rgba(7, 7, 7, 0.72), rgba(7, 7, 7, 0.72)),
            url('/ascii-art-bg.jpg') center / cover no-repeat;
    }
    :global([data-theme="light"]) .classic-img-bg {
        background:
            linear-gradient(rgba(240, 236, 229, 0.55), rgba(235, 230, 222, 0.65)),
            url('/ascii-art-bg.jpg') center / cover no-repeat;
    }

    /* ---- Spinning donut background ---- */
    .donut-bg {
        position: absolute;
        inset: 0;
        z-index: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        pointer-events: none;
        overflow: hidden;
    }
    .donut {
        font-family: var(--font-mono);
        font-size: 14px;
        line-height: 1.0;
        letter-spacing: 0.06em;
        color: rgba(0, 0, 0, 0.09);
        white-space: pre;
        margin: 0;
        padding: 0;
        background: none;
        border: none;
        border-radius: 0;
        outline: none;
        overflow: hidden;
        box-shadow: none;
        user-select: none;
        scrollbar-width: none;
    }

    /* ================================================================
       TOP BAR — transparent, floating
       ================================================================ */
    .topbar {
        height: 56px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 20px;
        background: transparent;
        flex-shrink: 0;
        z-index: 100;
        position: relative;
    }

    .topbar-left,
    .topbar-right {
        display: flex;
        align-items: center;
        gap: 6px;
        flex: 1;
    }
    .topbar-right { justify-content: flex-end; }

    .topbar-center {
        flex: none;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    /* ---- Icon button ---- */
    .tb-btn {
        width: 36px;
        height: 36px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: none;
        border: 1px solid transparent;
        border-radius: 10px;
        color: var(--text-muted);
        cursor: pointer;
        transition: color 150ms ease, background 150ms ease, border-color 150ms ease;
        flex-shrink: 0;
    }
    .tb-btn:hover {
        color: var(--text);
        background: var(--surface);
        border-color: var(--border);
    }
    .tb-btn.active {
        color: var(--text);
        background: var(--surface);
        border-color: var(--border);
    }

    /* ---- Text button (icon + label) ---- */
    .tb-text-btn {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 6px 14px 6px 10px;
        border-radius: 10px;
        border: 1px solid transparent;
        font-size: 13px;
        font-weight: 500;
        color: var(--text-muted);
        text-decoration: none;
        transition: color 150ms ease, background 150ms ease, border-color 150ms ease;
        white-space: nowrap;
    }
    .tb-text-btn:hover {
        color: var(--text);
        background: var(--surface);
        border-color: var(--border);
    }
    .tb-text-btn.active {
        color: var(--text);
        background: var(--surface);
        border-color: var(--border);
    }

    /* ---- Separator ---- */
    .tb-sep {
        width: 1px;
        height: 20px;
        background: var(--border);
        margin: 0 6px;
        opacity: 0.6;
    }

    /* ---- Logo ---- */
    .logo {
        display: flex;
        align-items: center;
        gap: 0;
        text-decoration: none;
        margin-left: 10px;
    }
    .logo:hover { opacity: 1; }
    .logo-ct {
        font-size: 18px;
        font-weight: 700;
        color: var(--text);
        letter-spacing: -0.03em;
    }
    .logo-divider {
        width: 1px;
        height: 16px;
        background: var(--text-muted);
        margin: 0 6px;
        opacity: 0.4;
        transform: rotate(16deg);
    }
    .logo-num {
        font-size: 16px;
        font-weight: 500;
        color: var(--text-secondary);
    }

    /* ---- Phase indicator ---- */
    .phase-pill {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 6px 18px 6px 12px;
        border-radius: 999px;
        border: 1px solid var(--border);
        background: var(--surface);
        animation: phaseIn 250ms var(--spring-soft) both;
    }
    .phase-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: var(--brain);
        box-shadow: 0 0 6px rgba(232, 133, 12, 0.3);
        animation: pulse 6s ease-in-out infinite;
    }
    .phase-label {
        font-size: 12.5px;
        font-weight: 500;
        color: var(--text-secondary);
        letter-spacing: 0.02em;
    }

    @keyframes phaseIn {
        from { opacity: 0; transform: scale(0.9) translateY(-2px); }
        to { opacity: 1; transform: scale(1) translateY(0); }
    }

    /* ---- Main content ---- */
    main {
        flex: 1;
        overflow: hidden;
        position: relative;
        z-index: 1;
    }

    /* ── Notification bubbles (top-right) ────────────────── */
    .classic-notif-tray {
        position: fixed;
        top: 68px;
        right: 16px;
        z-index: 200;
        display: flex;
        flex-direction: column;
        gap: 8px;
        pointer-events: none;
        max-width: 320px;
    }
    .classic-notif {
        pointer-events: auto;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 11px 13px;
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.18);
        min-width: 240px;
        display: flex;
        flex-direction: column;
        gap: 6px;
        transition: opacity 200ms;
    }
    .classic-notif-done { opacity: 0.55; }
    .classic-notif-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
    }
    .classic-notif-icon-label {
        display: flex;
        align-items: center;
        gap: 8px;
        min-width: 0;
        flex: 1;
    }
    .classic-notif-label {
        font-size: 12.5px;
        font-weight: 500;
        color: var(--text);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .classic-notif-pct {
        font-family: var(--font-mono);
        font-size: 11px;
        font-weight: 600;
        color: var(--accent);
        min-width: 30px;
        font-variant-numeric: tabular-nums;
        flex-shrink: 0;
    }
    .classic-notif-ok {
        color: var(--ok, #4caf50);
        flex-shrink: 0;
    }
    .classic-notif-close {
        width: 20px;
        height: 20px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 5px;
        border: none;
        background: none;
        color: var(--text-muted);
        cursor: pointer;
        flex-shrink: 0;
        transition: background 120ms, color 120ms;
    }
    .classic-notif-close:hover { background: var(--border); color: var(--text); }
    .classic-notif-detail {
        font-family: var(--font-mono);
        font-size: 11px;
        color: var(--text-muted);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        margin: 0;
        padding-left: 21px;
    }
    .classic-notif-bar {
        height: 3px;
        border-radius: 999px;
        background: var(--border);
        overflow: hidden;
        margin-top: 2px;
    }
    .classic-notif-fill {
        height: 100%;
        border-radius: 999px;
        background: var(--accent);
        transition: width 300ms ease;
    }
    .classic-spinner {
        border: 2px solid var(--border);
        border-top-color: var(--accent);
        border-radius: 50%;
        animation: spin 0.7s linear infinite;
        flex-shrink: 0;
    }
    .classic-spinner-sm {
        width: 12px;
        height: 12px;
    }
    @keyframes spin {
        to { transform: rotate(360deg); }
    }
</style>
