<script lang="ts">
    import type { Snippet } from 'svelte';

    let { showRight = false, initialRatio = 0.5, left, right }:
        { showRight?: boolean; initialRatio?: number; left: Snippet; right?: Snippet } = $props();

    let ratio = $state(0.5);
    $effect(() => { ratio = initialRatio; });
    let dragging = $state(false);
    let container: HTMLElement;

    function onPointerDown(e: PointerEvent) {
        dragging = true;
        (e.target as HTMLElement).setPointerCapture(e.pointerId);
    }

    function onPointerMove(e: PointerEvent) {
        if (!dragging || !container) return;
        const rect = container.getBoundingClientRect();
        let newRatio = (e.clientX - rect.left) / rect.width;
        newRatio = Math.max(0.3, Math.min(0.7, newRatio));
        ratio = newRatio;
    }

    function onPointerUp() {
        dragging = false;
    }
</script>

<div
    class="split-pane"
    class:has-right={showRight}
    class:dragging
    bind:this={container}
>
    <div
        class="pane left"
        style={showRight ? `width: ${ratio * 100}%` : 'width: 100%; transition: none'}
    >
        {@render left()}
    </div>

    {#if showRight}
        <div
            class="divider"
            role="separator"
            onpointerdown={onPointerDown}
            onpointermove={onPointerMove}
            onpointerup={onPointerUp}
        >
            <div class="divider-grip"></div>
        </div>

        <div
            class="pane right"
            style="width: {(1 - ratio) * 100}%"
        >
            {#if right}
                {@render right()}
            {/if}
        </div>
    {/if}
</div>

<style>
    .split-pane {
        display: flex;
        height: 100%;
        overflow: hidden;
    }
    .pane {
        height: 100%;
        overflow: hidden;
        transition: width 500ms var(--spring-soft);
    }
    .dragging .pane {
        transition: none;
        user-select: none;
    }
    .pane.right {
        animation: slideInRight 500ms var(--spring-soft) both;
    }
    .left { min-width: 0; }
    .right { min-width: 0; }
    .divider {
        width: 1px;
        flex-shrink: 0;
        cursor: col-resize;
        background: var(--border);
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background var(--transition);
        position: relative;
        z-index: 10;
    }
    .divider::before {
        content: '';
        position: absolute;
        inset: 0 -8px;
    }
    .divider:hover {
        background: var(--border-strong);
    }
    .divider-grip {
        width: 3px;
        height: 28px;
        border-radius: 2px;
        background: var(--text-muted);
        opacity: 0;
        transition: opacity var(--transition);
    }
    .divider:hover .divider-grip {
        opacity: 0.5;
    }
</style>
