<script lang="ts">
    let { workspaceId, onClose, externalOutput = '' }:
        { workspaceId: string; onClose: () => void; externalOutput?: string } = $props();

    let output = $state('');
    let inputText = $state('');
    let outputEl: HTMLPreElement;
    let ws: WebSocket | null = null;
    let connected = $state(false);
    let inputEl: HTMLInputElement;
    let lastExternalLen = 0;

    $effect(() => {
        if (workspaceId) {
            connectTerminal();
        }
        return () => {
            ws?.close();
            ws = null;
        };
    });

    // Append new external output (from AI command execution)
    $effect(() => {
        if (externalOutput && externalOutput.length > lastExternalLen) {
            output += externalOutput.slice(lastExternalLen);
            lastExternalLen = externalOutput.length;
            scrollBottom();
        }
    });

    function connectTerminal() {
        if (ws) ws.close();
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${protocol}//${window.location.host}/ws/terminal`;
        ws = new WebSocket(url);

        ws.onopen = () => {
            connected = true;
            ws?.send(JSON.stringify({ type: 'init', workspace_id: workspaceId }));
            output += `Connected to workspace: ${workspaceId}\r\n`;
        };

        ws.onmessage = (e) => {
            try {
                const msg = JSON.parse(e.data);
                if (msg.type === 'output' || msg.type === 'error') {
                    output += msg.text;
                    scrollBottom();
                } else if (msg.type === 'exit') {
                    output += `\r\n[Process exited with code ${msg.code}]\r\n`;
                    connected = false;
                }
            } catch {
                output += e.data;
            }
        };

        ws.onclose = () => { connected = false; };
        ws.onerror = () => { connected = false; };
    }

    function scrollBottom() {
        requestAnimationFrame(() => {
            if (outputEl) outputEl.scrollTop = outputEl.scrollHeight;
        });
    }

    function sendCommand() {
        const cmd = inputText.trim();
        if (!cmd || !ws || !connected) return;
        output += `$ ${cmd}\r\n`;
        ws.send(JSON.stringify({ type: 'input', text: cmd + '\n' }));
        inputText = '';
        scrollBottom();
    }

    function onKeydown(e: KeyboardEvent) {
        if (e.key === 'Enter') {
            e.preventDefault();
            sendCommand();
        }
    }
</script>

<div class="terminal">
    <div class="term-toolbar">
        <div class="term-status">
            <span class="term-dot" class:connected></span>
            <span class="term-label">Terminal</span>
        </div>
        <button class="term-close" onclick={onClose} aria-label="Close terminal">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                <path d="M2.5 2.5l7 7M9.5 2.5l-7 7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
            </svg>
            <span>Close</span>
        </button>
    </div>
    <pre class="term-output" bind:this={outputEl}>{output}</pre>
    <div class="term-input-row">
        <span class="term-prompt">$</span>
        <input
            bind:this={inputEl}
            bind:value={inputText}
            onkeydown={onKeydown}
            placeholder={connected ? 'Type a command...' : 'Disconnected'}
            disabled={!connected}
            class="term-input"
        />
    </div>
</div>

<style>
    .terminal {
        display: flex;
        flex-direction: column;
        height: 100%;
        background: var(--surface-solid);
        color: var(--text);
        font-family: var(--font-mono);
        font-size: 13px;
        border-radius: 0;
    }
    .term-toolbar {
        height: 44px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 16px;
        background: var(--surface);
        border-bottom: 1px solid var(--border);
        flex-shrink: 0;
    }
    .term-status {
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .term-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: var(--text-muted);
        transition: background var(--transition);
    }
    .term-dot.connected {
        background: var(--success);
        box-shadow: 0 0 6px rgba(45, 164, 78, 0.35);
    }
    .term-label {
        font-family: var(--font-body);
        font-size: 12px;
        font-weight: 600;
        color: var(--text-secondary);
        letter-spacing: 0.02em;
    }
    .term-close {
        display: flex;
        align-items: center;
        gap: 6px;
        height: 28px;
        padding: 0 12px 0 10px;
        border: 1px solid var(--border);
        border-radius: var(--radius-pill);
        background: var(--accent-subtle);
        color: var(--text-secondary);
        font-family: var(--font-body);
        font-size: 12px;
        font-weight: 500;
        cursor: pointer;
        transition: all var(--transition);
    }
    .term-close:hover {
        background: var(--surface);
        color: var(--text);
        border-color: var(--border-strong);
    }
    .term-output {
        flex: 1;
        overflow: auto;
        padding: 16px;
        margin: 0;
        background: var(--code-bg);
        border: none;
        font: inherit;
        color: var(--text);
        line-height: 1.6;
        white-space: pre-wrap;
        word-break: break-all;
        scrollbar-width: thin;
    }
    .term-input-row {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 10px 16px;
        background: var(--surface);
        border-top: 1px solid var(--border);
        flex-shrink: 0;
    }
    .term-prompt {
        color: var(--success);
        font-weight: 600;
        flex-shrink: 0;
        opacity: 0.8;
    }
    .term-input {
        flex: 1;
        background: none;
        border: none;
        color: var(--text);
        font: inherit;
        outline: none;
        padding: 4px 0;
    }
    .term-input::placeholder { color: var(--text-muted); }
    .term-input:disabled { opacity: 0.3; }
</style>
