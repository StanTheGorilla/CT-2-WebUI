<script lang="ts">
    import { chat, sendThink } from '$lib/stores/chat';

    let input = $state('');
    let textarea: HTMLTextAreaElement;

    const disabled = $derived($chat.phase !== 'idle' && $chat.phase !== 'done');

    function submit() {
        const text = input.trim();
        if (!text || disabled) return;
        sendThink(text);
        input = '';
        if (textarea) textarea.style.height = 'auto';
    }

    function onKeydown(e: KeyboardEvent) {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            submit();
        }
    }

    function autoGrow() {
        if (!textarea) return;
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
    }
</script>

<div class="chat-input">
    <textarea
        bind:this={textarea}
        bind:value={input}
        onkeydown={onKeydown}
        oninput={autoGrow}
        placeholder="Ask CT-1 anything... (Ctrl+Enter to send)"
        rows="1"
        {disabled}
    ></textarea>
    <button onclick={submit} {disabled}>Send</button>
</div>

<style>
    .chat-input {
        display: flex;
        gap: 12px;
        align-items: flex-end;
        padding: 16px 0;
        border-top: 1px solid var(--border);
    }
    textarea {
        flex: 1;
        background: var(--surface);
        color: var(--text);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        padding: 12px 16px;
        font-family: var(--font-body);
        font-size: 15px;
        line-height: 1.5;
        resize: none;
        outline: none;
        transition: border-color var(--transition);
    }
    textarea:focus {
        border-color: var(--accent);
        box-shadow: 0 0 0 3px rgba(10, 132, 255, 0.15);
    }
    textarea:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
    button {
        background: var(--accent);
        color: white;
        border: none;
        border-radius: 20px;
        padding: 10px 24px;
        font-family: var(--font-body);
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        transition: opacity var(--transition);
        white-space: nowrap;
    }
    button:hover:not(:disabled) { opacity: 0.85; }
    button:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
