<script lang="ts">
    import '../app.css';
    import { chat } from '$lib/stores/chat';
    import { page } from '$app/stores';
    import { onMount } from 'svelte';

    let { children } = $props();

    const phaseLabels: Record<string, string> = {
        idle: '',
        routing: 'Classifying...',
        planning: 'Planning...',
        consulting: 'Consulting design...',
        generating: 'Generating...',
        validating: 'Validating...',
        fixing: 'Fixing issues...',
        done: 'Done',
    };

    let phaseText = $derived(phaseLabels[$chat.phase] || '');
    let isActive = $derived($chat.phase !== 'idle' && $chat.phase !== 'done');

    let pre: HTMLPreElement;

    onMount(() => {
        if (!pre) return;

        // Spinning 3D ASCII donut (based on donut.c by Andy Sloane)
        const R1 = 1, R2 = 2, K2 = 5;
        // Size to fill the viewport
        const charW = 8.4, charH = 14;
        const screenW = Math.min(180, Math.floor(window.innerWidth / charW));
        const screenH = Math.min(90, Math.floor(window.innerHeight / charH));
        const K1 = screenW * K2 * 3 / (8 * (R1 + R2));

        let A = 0, B = 0;
        const luminanceChars = '.,-~:;=!*#$@';

        function renderFrame() {
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

        const id = setInterval(renderFrame, 50);
        renderFrame();

        return () => clearInterval(id);
    });
</script>

<div class="app">
    <div class="donut-bg" aria-hidden="true">
        <pre class="donut" bind:this={pre}></pre>
    </div>

    <header class="topbar">
        <a href="/" class="logo">
            <span class="logo-mark">CT</span><span class="logo-sep">/</span><span class="logo-ver">2</span>
        </a>

        <div class="phase-area">
            {#if isActive}
                <div class="phase-dot"></div>
            {/if}
            {#if phaseText}
                <span class="phase-text" class:active={isActive}>{phaseText}</span>
            {/if}
        </div>

        <nav class="nav">
            <a href="/journal" class="nav-link" class:active={$page.url.pathname === '/journal'}>Journal</a>
            <a href="/settings" class="nav-link" class:active={$page.url.pathname === '/settings'}>Settings</a>
        </nav>
    </header>

    <main>
        {@render children()}
    </main>
</div>

<style>
    .app {
        display: flex;
        flex-direction: column;
        height: 100vh;
        overflow: hidden;
        position: relative;
        background: var(--bg);
    }

    /* ---- Spinning donut background ---- */
    .donut-bg {
        position: fixed;
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
        user-select: none;
    }

    /* ---- Top bar — frosted glass bubble ---- */
    .topbar {
        height: 56px;
        display: flex;
        align-items: center;
        padding: 0 28px;
        gap: 16px;
        background: rgba(255, 255, 255, 0.6);
        backdrop-filter: blur(48px) saturate(1.4);
        -webkit-backdrop-filter: blur(48px) saturate(1.4);
        border-bottom: 1px solid rgba(255, 255, 255, 0.7);
        box-shadow:
            0 1px 0 rgba(255, 255, 255, 0.5),
            0 4px 24px rgba(0, 0, 0, 0.04);
        flex-shrink: 0;
        z-index: 100;
        position: relative;
    }

    .logo {
        display: flex;
        align-items: baseline;
        gap: 1px;
        text-decoration: none;
    }
    .logo:hover { opacity: 1; }
    .logo-mark {
        font-size: 18px;
        font-weight: 700;
        color: var(--text);
        letter-spacing: -0.04em;
    }
    .logo-sep {
        font-size: 16px;
        font-weight: 300;
        color: var(--text-muted);
        margin: 0 2px;
    }
    .logo-ver {
        font-size: 16px;
        font-weight: 500;
        color: var(--text-secondary);
    }

    .phase-area {
        flex: 1;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 10px;
    }

    .phase-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: var(--brain);
        box-shadow: 0 0 8px rgba(232, 133, 12, 0.4);
        animation: pulse 2s ease-in-out infinite;
    }

    .phase-text {
        font-size: 13px;
        font-weight: 500;
        color: var(--text-muted);
        transition: color var(--transition);
    }
    .phase-text.active {
        color: var(--text-secondary);
    }

    .nav {
        display: flex;
        gap: 2px;
    }

    .nav-link {
        font-size: 13px;
        font-weight: 500;
        color: var(--text-muted);
        padding: 7px 16px;
        border-radius: var(--radius-pill);
        transition: color var(--transition), background var(--transition);
    }
    .nav-link:hover {
        color: var(--text);
        background: rgba(0, 0, 0, 0.04);
        opacity: 1;
    }
    .nav-link.active {
        color: var(--text);
        background: rgba(0, 0, 0, 0.05);
    }

    main {
        flex: 1;
        overflow: hidden;
        position: relative;
        z-index: 1;
    }
</style>
