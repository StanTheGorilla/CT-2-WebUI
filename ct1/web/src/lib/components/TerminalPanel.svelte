<script lang="ts">
    let { workspaceId, onClose, externalOutput = '', pendingCommands = [], onCommandsConsumed,
          pendingApproval = null, onApprovalHandled }:
        { workspaceId: string; onClose: () => void; externalOutput?: string;
          pendingCommands?: string[]; onCommandsConsumed?: () => void;
          pendingApproval?: { id: string; command: string } | null;
          onApprovalHandled?: () => void } = $props();

    let output = $state('');
    let inputText = $state('');
    let outputEl: HTMLPreElement;
    let ws: WebSocket | null = null;
    let connected = $state(false);
    let inputEl: HTMLInputElement;
    let lastExternalLen = 0;
    let cmdCount = $state(0);
    let lastPendingLen = 0;
    let lastWorkspaceId: string | null = null;

    $effect(() => {
        if (!workspaceId) {
            lastWorkspaceId = null;
            return;
        }
        if (workspaceId !== lastWorkspaceId) {
            lastWorkspaceId = workspaceId;
            output = '';
            inputText = '';
            connected = false;
            lastExternalLen = 0;
            lastPendingLen = 0;
            cmdCount = 0;
        }
        connectTerminal();
        return () => {
            ws?.close();
            ws = null;
        };
    });

    // Append new external output (from AI auto-run subprocess)
    $effect(() => {
        if (externalOutput.length < lastExternalLen) {
            lastExternalLen = 0;
        }
        if (externalOutput && externalOutput.length > lastExternalLen) {
            output += externalOutput.slice(lastExternalLen);
            lastExternalLen = externalOutput.length;
            scrollBottom();
        }
    });

    // Run AI-requested commands through the interactive shell
    $effect(() => {
        if (pendingCommands.length === 0) {
            lastPendingLen = 0;  // queue was cleared; reset so next batch works
        } else if (pendingCommands.length > lastPendingLen && ws && connected) {
            for (let i = lastPendingLen; i < pendingCommands.length; i++) {
                const cmd = pendingCommands[i].trim();
                if (!cmd) continue;
                output += `\n$ ${cmd}\n`;
                ws.send(JSON.stringify({ type: 'input', text: cmd + '\n' }));
                cmdCount++;
            }
            lastPendingLen = pendingCommands.length;
            scrollBottom();
            onCommandsConsumed?.();  // tell store to clear so next batch gets a fresh start
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
            output += `--- workspace connected ---\n`;
        };

        ws.onmessage = (e) => {
            try {
                const msg = JSON.parse(e.data);
                if (msg.type === 'output' || msg.type === 'error') {
                    output += msg.text;
                    scrollBottom();
                } else if (msg.type === 'exit') {
                    output += `\n[exit ${msg.code}]\n`;
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
        output += `\n$ ${cmd}\n`;
        ws.send(JSON.stringify({ type: 'input', text: cmd + '\n' }));
        inputText = '';
        cmdCount++;
        scrollBottom();
    }

    function clearTerminal() {
        output = '';
    }

    function onKeydown(e: KeyboardEvent) {
        if (e.key === 'Enter') {
            e.preventDefault();
            sendCommand();
        }
    }

    async function respondToApproval(approved: boolean) {
        if (!pendingApproval) return;
        const { id, command } = pendingApproval;
        onApprovalHandled?.();
        output += approved
            ? `\n$ ${command}\n`
            : `\n[command rejected: ${command}]\n`;
        scrollBottom();
        try {
            await fetch(`/api/command-approve/${id}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ approved }),
            });
        } catch {}
    }

</script>

<div class="terminal">
    <div class="term-toolbar">
        <div class="term-left">
            <span class="term-label">Terminal</span>
            {#if connected}
                <span class="term-status">connected</span>
            {/if}
            {#if cmdCount > 0}
                <span class="term-counter">{cmdCount}</span>
            {/if}
        </div>
        <div class="term-right">
            <button class="term-action" onclick={clearTerminal} title="Clear">
                <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                    <path d="M2 4h12M5.333 4V2.667a.667.667 0 01.667-.667h4a.667.667 0 01.667.667V4M12 4v8.667a1.333 1.333 0 01-1.333 1.333H5.333A1.333 1.333 0 014 12.667V4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            </button>
            <button class="term-action" onclick={onClose} title="Close terminal">
                <svg width="10" height="10" viewBox="0 0 12 12" fill="none">
                    <path d="M2.5 2.5l7 7M9.5 2.5l-7 7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
                </svg>
            </button>
        </div>
    </div>
    <pre class="term-output" bind:this={outputEl}>{output}{#if !output}<span class="term-welcome">workspace ready — type a command below</span>{/if}</pre>
    {#if pendingApproval}
        <div class="term-approval">
            <div class="term-approval-cmd">
                <svg width="10" height="10" viewBox="0 0 12 12" fill="none"><path d="M2 9l4-3-4-3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
                <code class="term-approval-text">{pendingApproval.command}</code>
            </div>
            <div class="term-approval-actions">
                <button class="term-approve-btn term-approve-reject" onclick={() => respondToApproval(false)}>Reject</button>
                <button class="term-approve-btn term-approve-ok" onclick={() => respondToApproval(true)}>Approve</button>
            </div>
        </div>
    {/if}
    <div class="term-input-row">
        <span class="term-prompt">
            <svg width="10" height="10" viewBox="0 0 12 12" fill="none"><path d="M2 9l4-3-4-3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </span>
        <input
            bind:this={inputEl}
            bind:value={inputText}
            onkeydown={onKeydown}
            placeholder={connected ? 'command...' : 'disconnected'}
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
        background: var(--surface-solid, #0A0A0A);
        color: var(--text-secondary, #999);
        font-family: var(--font-mono);
        font-size: 12px;
        border-radius: 0 0 0 12px;
        overflow: hidden;
    }
    .term-toolbar {
        height: 38px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 14px;
        background: transparent;
        border-bottom: 1px solid var(--border-subtle, rgba(255,255,255,0.05));
        flex-shrink: 0;
    }
    .term-left {
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .term-label {
        font-family: var(--font-body);
        font-size: 11px;
        font-weight: 600;
        color: var(--text-muted, #555);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .term-status {
        font-family: var(--font-mono);
        font-size: 10px;
        color: var(--text-muted, #555);
    }
    .term-counter {
        font-family: var(--font-mono);
        font-size: 10px;
        color: var(--text-muted, #555);
        background: rgba(255,255,255,0.06);
        padding: 1px 6px;
        border-radius: 999px;
    }
    .term-right {
        display: flex;
        gap: 2px;
    }
    .term-action {
        width: 26px;
        height: 26px;
        border: none;
        background: none;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--text-muted, #555);
        border-radius: 6px;
        transition: all 200ms ease;
    }
    .term-action:hover {
        background: rgba(255,255,255,0.08);
        color: var(--text-secondary, #999);
    }
    .term-output {
        flex: 1;
        overflow: auto;
        padding: 14px 16px;
        margin: 0;
        border: none;
        font: inherit;
        color: var(--text-secondary, #999);
        line-height: 1.6;
        white-space: pre-wrap;
        word-break: break-all;
        scrollbar-width: thin;
        background: transparent;
    }
    .term-welcome {
        color: var(--text-muted, #444);
        font-style: italic;
    }
    .term-input-row {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 10px 16px;
        background: transparent;
        border-top: 1px solid var(--border-subtle, rgba(255,255,255,0.05));
        flex-shrink: 0;
    }
    .term-prompt {
        display: flex;
        align-items: center;
        color: var(--text-muted, #555);
        flex-shrink: 0;
    }
    .term-input {
        flex: 1;
        background: none;
        border: none;
        color: var(--text, #e0e0e0);
        font: inherit;
        outline: none;
        padding: 2px 0;
        caret-color: var(--text-secondary, #999);
    }
    .term-input::placeholder { color: var(--text-muted, #333); }
    .term-input:disabled { opacity: 0.3; }

    .term-output::-webkit-scrollbar { width: 4px; }
    .term-output::-webkit-scrollbar-track { background: transparent; }
    .term-output::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 2px; }

    .term-approval {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 8px 14px;
        background: rgba(255, 165, 0, 0.07);
        border-top: 1px solid rgba(255, 165, 0, 0.18);
        flex-shrink: 0;
    }
    .term-approval-cmd {
        display: flex;
        align-items: center;
        gap: 6px;
        color: rgba(255, 165, 0, 0.7);
        min-width: 0;
        overflow: hidden;
    }
    .term-approval-text {
        font: inherit;
        font-size: 11.5px;
        color: rgba(255, 200, 100, 0.9);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .term-approval-actions {
        display: flex;
        gap: 6px;
        flex-shrink: 0;
    }
    .term-approve-btn {
        height: 24px;
        padding: 0 10px;
        border-radius: 5px;
        font-size: 11.5px;
        font-family: inherit;
        cursor: pointer;
        font-weight: 500;
        transition: opacity 120ms;
    }
    .term-approve-reject {
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.12);
        color: rgba(255,255,255,0.5);
    }
    .term-approve-reject:hover { opacity: 0.75; }
    .term-approve-ok {
        background: rgba(255, 165, 0, 0.22);
        border: 1px solid rgba(255, 165, 0, 0.4);
        color: rgba(255, 200, 80, 0.95);
    }
    .term-approve-ok:hover { opacity: 0.85; }
</style>
