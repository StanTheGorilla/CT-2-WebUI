<script lang="ts">
    import { goto } from '$app/navigation';
    import { onMount } from 'svelte';
    import { authStatus, login, refreshAuthStatus, setPassword } from '$lib/stores/auth';

    let password = $state('');
    let confirmPassword = $state('');
    let busy = $state(false);
    let error = $state('');
    let info = $state('');
    let inputEl = $state<HTMLInputElement | null>(null);

    onMount(async () => {
        const s = await refreshAuthStatus();
        if (s.mode === 'none' || s.authenticated) {
            // Nothing to do here — bounce to home.
            goto('/');
            return;
        }
        if (inputEl) inputEl.focus();
    });

    const isSetup = $derived($authStatus.needs_setup);

    async function submit() {
        if (busy) return;
        error = '';
        if (!password) { error = 'Enter a password.'; return; }
        if (isSetup) {
            if (password.length < 6) { error = 'At least 6 characters.'; return; }
            if (password !== confirmPassword) { error = 'Passwords do not match.'; return; }
            busy = true;
            const r = await setPassword({ new_password: password, enable: true });
            busy = false;
            if (!r.ok) { error = r.error || 'Could not set password.'; return; }
            info = 'Password set. Loading…';
            goto('/');
        } else {
            busy = true;
            const r = await login(password);
            busy = false;
            if (!r.ok) { error = r.error || 'Login failed.'; password = ''; return; }
            goto('/');
        }
    }

    function onKey(e: KeyboardEvent) {
        if (e.key === 'Enter') { e.preventDefault(); submit(); }
    }
</script>

<svelte:head>
    <title>{isSetup ? 'Set password' : 'Sign in'} — CT-2 WebUI</title>
</svelte:head>

<div class="auth-shell">
    <div class="auth-card">
        <div class="auth-brand">
            <span class="auth-logo-ct">CT</span>
            <span class="auth-logo-divider"></span>
            <span class="auth-logo-num">2</span>
        </div>

        <h1 class="auth-title">
            {#if isSetup}Set a shared password{:else}Sign in{/if}
        </h1>

        <p class="auth-sub">
            {#if isSetup}
                CT-2 WebUI is in <b>password mode</b>. Choose a password —
                everyone who connects on the home network will use the same one.
            {:else}
                Enter the shared password to use CT-2 WebUI on this network.
            {/if}
        </p>

        <div class="auth-field">
            <label class="auth-label" for="auth-password">Password</label>
            <input
                id="auth-password"
                type="password"
                class="auth-input"
                bind:this={inputEl}
                bind:value={password}
                onkeydown={onKey}
                autocomplete={isSetup ? 'new-password' : 'current-password'}
                placeholder="••••••••"
                disabled={busy}
            />
        </div>

        {#if isSetup}
            <div class="auth-field">
                <label class="auth-label" for="auth-confirm">Confirm password</label>
                <input
                    id="auth-confirm"
                    type="password"
                    class="auth-input"
                    bind:value={confirmPassword}
                    onkeydown={onKey}
                    autocomplete="new-password"
                    placeholder="••••••••"
                    disabled={busy}
                />
            </div>
        {/if}

        {#if error}
            <div class="auth-error" role="alert">{error}</div>
        {/if}
        {#if info && !error}
            <div class="auth-info">{info}</div>
        {/if}

        <button class="auth-btn" onclick={submit} disabled={busy}>
            {#if busy}
                <span class="auth-spinner"></span>
                {isSetup ? 'Saving…' : 'Signing in…'}
            {:else}
                {isSetup ? 'Save password' : 'Sign in'}
            {/if}
        </button>

        <p class="auth-foot">
            Local · Private · GPU. Sessions last 30 days on this device.
        </p>
    </div>
</div>

<style>
    :global(html), :global(body) {
        background: #0d0e10;
    }
    .auth-shell {
        position: fixed;
        inset: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 24px;
        font-family: 'Geist', ui-sans-serif, system-ui, sans-serif;
        color: #e8e9eb;
        background: radial-gradient(ellipse at top, #1a1c20 0%, #0d0e10 60%);
    }
    .auth-card {
        width: min(420px, 100%);
        background: #16181c;
        border: 1px solid #26282d;
        border-radius: 16px;
        padding: 36px 32px 28px;
        box-shadow: 0 24px 60px -12px rgba(0, 0, 0, 0.6);
        animation: pop-in 320ms cubic-bezier(0.34, 1.4, 0.64, 1) both;
    }
    @keyframes pop-in {
        from { opacity: 0; transform: translateY(8px) scale(0.98); }
        to { opacity: 1; transform: translateY(0) scale(1); }
    }
    .auth-brand {
        display: flex;
        align-items: center;
        gap: 6px;
        margin-bottom: 18px;
        font-family: 'Geist Mono', monospace;
        font-weight: 600;
    }
    .auth-logo-ct {
        font-size: 18px;
        letter-spacing: 0.04em;
        color: #e8e9eb;
    }
    .auth-logo-divider {
        width: 3px;
        height: 14px;
        background: #e8a000;
        border-radius: 1px;
    }
    .auth-logo-num {
        font-size: 18px;
        color: #e8a000;
    }
    .auth-title {
        margin: 0 0 8px;
        font-size: 22px;
        font-weight: 600;
        letter-spacing: -0.01em;
    }
    .auth-sub {
        margin: 0 0 22px;
        font-size: 13px;
        color: #9aa0a6;
        line-height: 1.55;
    }
    .auth-sub b { color: #e8e9eb; font-weight: 600; }
    .auth-field {
        margin-bottom: 14px;
    }
    .auth-label {
        display: block;
        margin-bottom: 6px;
        font-size: 11.5px;
        font-weight: 600;
        color: #9aa0a6;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }
    .auth-input {
        width: 100%;
        height: 40px;
        padding: 0 14px;
        background: #1a1c20;
        border: 1px solid #2c2f35;
        border-radius: 8px;
        color: #e8e9eb;
        font: inherit;
        font-size: 14px;
        outline: none;
        transition: border-color 140ms, background 140ms;
    }
    .auth-input:focus {
        border-color: #e8a000;
        background: #1d2025;
    }
    .auth-input:disabled { opacity: 0.6; cursor: not-allowed; }
    .auth-btn {
        width: 100%;
        height: 42px;
        margin-top: 10px;
        background: #e8a000;
        color: #1a1300;
        border: none;
        border-radius: 9px;
        font: inherit;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        transition: opacity 140ms, transform 140ms;
    }
    .auth-btn:hover:not(:disabled) { opacity: 0.92; transform: translateY(-1px); }
    .auth-btn:active:not(:disabled) { transform: translateY(0); }
    .auth-btn:disabled { opacity: 0.6; cursor: not-allowed; }
    .auth-error {
        margin-bottom: 12px;
        padding: 10px 12px;
        background: rgba(232, 70, 50, 0.10);
        border: 1px solid rgba(232, 70, 50, 0.4);
        border-radius: 8px;
        color: #ff8a78;
        font-size: 12.5px;
    }
    .auth-info {
        margin-bottom: 12px;
        font-size: 12.5px;
        color: #9aa0a6;
    }
    .auth-foot {
        margin: 22px 0 0;
        font-size: 11px;
        color: #6f7480;
        text-align: center;
        letter-spacing: 0.02em;
    }
    .auth-spinner {
        width: 13px; height: 13px;
        border: 2px solid rgba(0, 0, 0, 0.3);
        border-top-color: #1a1300;
        border-radius: 50%;
        animation: spin 700ms linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
</style>
