<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { chat, connect, disconnect } from '$lib/stores/chat';
    import ChatInput from '$lib/components/ChatInput.svelte';
    import IntentCard from '$lib/components/IntentCard.svelte';
    import DeliberationPanel from '$lib/components/DeliberationPanel.svelte';
    import ResponsePanel from '$lib/components/ResponsePanel.svelte';
    import ReflectionBar from '$lib/components/ReflectionBar.svelte';

    onMount(() => connect());
    onDestroy(() => disconnect());
</script>

<div class="chat-page">
    <div class="messages">
        {#each $chat.conversation as turn}
            {#if turn.role === 'user'}
                <div class="user-msg"><p>{turn.content}</p></div>
            {/if}
        {/each}

        {#if $chat.phase === 'framing'}
            <div class="status"><span class="pulse"></span> Extracting intent...</div>
        {/if}

        {#if $chat.intent}
            <IntentCard intent={$chat.intent} />
        {/if}

        {#if $chat.phase === 'deliberating' && $chat.dialogue.length === 0}
            <div class="status"><span class="pulse mind"></span> Minds deliberating...</div>
        {/if}

        {#if $chat.dialogue.length > 0}
            <DeliberationPanel
                dialogue={$chat.dialogue}
                phase={$chat.phase}
                currentRound={$chat.currentRound}
            />
        {/if}

        {#if $chat.phase === 'synthesizing'}
            <div class="status"><span class="pulse brain"></span> Synthesizing response...</div>
        {/if}

        {#if $chat.response}
            <ResponsePanel response={$chat.response} thinking={$chat.thinking} />
        {/if}

        {#if $chat.reflection}
            <ReflectionBar reflection={$chat.reflection} />
        {/if}
    </div>

    <ChatInput />
</div>

<style>
    .chat-page {
        display: flex;
        flex-direction: column;
        height: 100%;
        max-width: 800px;
        margin: 0 auto;
    }
    .messages {
        flex: 1;
        overflow-y: auto;
        scroll-behavior: smooth;
        display: flex;
        flex-direction: column;
        gap: 16px;
        padding-bottom: 16px;
    }
    .user-msg {
        align-self: flex-end;
        background: var(--accent);
        color: white;
        padding: 10px 16px;
        border-radius: 16px 16px 4px 16px;
        max-width: 70%;
        font-size: 15px;
    }
    .user-msg p { margin: 0; }
    .status {
        display: flex; align-items: center; gap: 10px;
        color: var(--text-secondary); font-size: 14px; padding: 8px 0;
    }
    .pulse {
        width: 8px; height: 8px; border-radius: 50%;
        background: var(--accent); animation: pulse 1.5s ease-in-out infinite;
    }
    .pulse.brain { background: var(--brain); }
    .pulse.mind { background: var(--alpha); }
    @keyframes pulse { 0%, 100% { opacity: 0.3; } 50% { opacity: 1; } }
</style>
