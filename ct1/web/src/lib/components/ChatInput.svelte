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

<div class="input-dock">
    <div class="island">
        <textarea
            bind:this={textarea}
            bind:value={input}
            onkeydown={onKeydown}
            oninput={autoGrow}
            placeholder="Ask CT-2 anything..."
            rows="1"
            {disabled}
        ></textarea>
        <div class="island-actions">
            <span class="hint">Ctrl+Enter</span>
            <button class="send" onclick={submit} {disabled} aria-label="Send message">
                <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                    <path d="M3.5 9h11M10 4.5L14.5 9 10 13.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            </button>
        </div>
    </div>
</div>

<style>
    .input-dock {
        padding: 8px 32px 28px;
        flex-shrink: 0;
        position: relative;
        z-index: 2;
    }

    .island {
        display: flex;
        align-items: center;
        gap: 8px;
        max-width: 720px;
        margin: 0 auto;
        /* Crisp, solid white — the clear focal point */
        background: rgba(255, 255, 255, 0.92);
        backdrop-filter: blur(48px) saturate(1.5);
        -webkit-backdrop-filter: blur(48px) saturate(1.5);
        border: 1px solid rgba(255, 255, 255, 0.9);
        border-radius: var(--radius-lg);
        padding: 10px 12px 10px 22px;
        box-shadow:
            0 0 0 1px rgba(0, 0, 0, 0.03),
            0 2px 4px rgba(0, 0, 0, 0.03),
            0 8px 40px rgba(0, 0, 0, 0.06),
            inset 0 1px 0 rgba(255, 255, 255, 0.9);
        transition: box-shadow var(--transition-slow), border-color var(--transition);
    }
    .island:focus-within {
        border-color: rgba(255, 255, 255, 1);
        box-shadow:
            0 0 0 1px rgba(0, 0, 0, 0.04),
            0 4px 8px rgba(0, 0, 0, 0.04),
            0 16px 56px rgba(0, 0, 0, 0.08),
            inset 0 1px 0 rgba(255, 255, 255, 1);
    }

    textarea {
        flex: 1;
        background: none;
        color: var(--text);
        border: none;
        font-family: var(--font-body);
        font-size: 15px;
        line-height: 1.5;
        resize: none;
        outline: none;
        padding: 4px 0;
    }
    textarea::placeholder {
        color: var(--text-muted);
        font-weight: 400;
    }
    textarea:disabled {
        opacity: 0.4;
        cursor: not-allowed;
    }

    .island-actions {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-shrink: 0;
    }

    .hint {
        font-size: 11px;
        font-weight: 500;
        color: var(--text-muted);
        letter-spacing: 0.02em;
        opacity: 0;
        transition: opacity var(--transition);
    }
    .island:focus-within .hint {
        opacity: 1;
    }

    .send {
        width: 38px;
        height: 38px;
        border: none;
        border-radius: 50%;
        background: var(--text);
        color: white;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        transition: transform var(--spring-duration) var(--spring), opacity var(--transition);
    }
    .send:hover:not(:disabled) {
        transform: scale(1.05);
    }
    .send:active:not(:disabled) {
        transform: scale(0.93);
    }
    .send:disabled {
        opacity: 0.15;
        cursor: not-allowed;
    }
</style>
