<script lang="ts">
    import { authStatus, setPassword, disableAuth, logout } from '$lib/stores/auth';
    import { showToast } from '$lib/stores/toasts';

    // ── Security tab state ────────────────────────────────────────────
    let secCurrentPw = $state('');
    let secNewPw = $state('');
    let secConfirmPw = $state('');
    let secDisablePw = $state('');
    let secBusy = $state(false);
    let secShowDisable = $state(false);

    async function secEnableOrChangePassword() {
        if (secBusy) return;
        if (secNewPw.length < 6) { showToast('Password must be at least 6 characters.', { variant: 'error' }); return; }
        if (secNewPw !== secConfirmPw) { showToast('Passwords do not match.', { variant: 'error' }); return; }
        const isFirstTime = $authStatus.mode === 'none';
        if (!isFirstTime && !secCurrentPw) { showToast('Enter your current password.', { variant: 'error' }); return; }
        secBusy = true;
        const r = await setPassword({
            new_password: secNewPw,
            current_password: isFirstTime ? undefined : secCurrentPw,
            enable: true,
        });
        secBusy = false;
        if (!r.ok) { showToast(r.error || 'Could not save.', { variant: 'error', title: 'Password change failed' }); return; }
        secCurrentPw = ''; secNewPw = ''; secConfirmPw = '';
        showToast(isFirstTime ? 'Password set. Other devices need to sign in.' : 'Password changed. Other sessions are signed out.', {
            variant: 'success',
            title: isFirstTime ? 'Multi-user mode enabled' : 'Password updated',
        });
    }

    async function secDisablePassword() {
        if (secBusy) return;
        if (!secDisablePw) { showToast('Enter your current password to disable.', { variant: 'error' }); return; }
        secBusy = true;
        const r = await disableAuth(secDisablePw);
        secBusy = false;
        if (!r.ok) { showToast(r.error || 'Could not disable.', { variant: 'error' }); return; }
        secDisablePw = ''; secShowDisable = false;
        showToast('Multi-user mode disabled. Bind reverts to localhost on next start.', { variant: 'info' });
    }

</script>

                <div class="c2-sh">
                    <h1 class="c2-sh-title">Security</h1>
                    <p class="c2-sh-sub">By default CT-2 WebUI runs single-user and binds to <code>localhost</code> only. Enable a shared password to let other devices on your home network reach it — they'll all use the same password.</p>
                </div>

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Current mode</div>
                        <div class="c2-row-desc">
                            {#if $authStatus.mode === 'none'}
                                <span class="c2-tag">Single-user (none)</span> &nbsp; Bind: <code>127.0.0.1:8000</code>. Only your machine can connect. Web search and RAG still work.
                            {:else if $authStatus.mode === 'password'}
                                <span class="c2-tag c2-tag-active">Shared password</span> &nbsp; Bind: <code>0.0.0.0:8000</code>. Devices on your network can sign in with the password below. Sessions last 30 days.
                            {:else}
                                <span class="c2-tag">{$authStatus.mode}</span>
                            {/if}
                        </div>
                    </div>
                </div>

                {#if $authStatus.mode === 'none'}
                    <div class="c2-row" style="flex-direction:column;align-items:stretch;gap:12px;">
                        <div class="c2-row-label">
                            <div class="c2-row-name">Enable shared password</div>
                            <div class="c2-row-desc">Pick a password and turn on multi-user mode. After saving, restart CT-2 — the bind will widen to <code>0.0.0.0</code> so other devices can reach it. Pair this with a reverse proxy (Caddy, Tailscale) if you expose it beyond the home network.</div>
                        </div>
                        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                            <input type="password" class="c2-input" placeholder="New password" bind:value={secNewPw} autocomplete="new-password" disabled={secBusy} />
                            <input type="password" class="c2-input" placeholder="Confirm" bind:value={secConfirmPw} autocomplete="new-password" disabled={secBusy} />
                        </div>
                        <button class="c2-btn-primary" style="align-self:flex-start;" onclick={secEnableOrChangePassword} disabled={secBusy || !secNewPw}>
                            {secBusy ? 'Saving…' : 'Enable password'}
                        </button>
                    </div>
                {:else if $authStatus.mode === 'password'}
                    <div class="c2-row" style="flex-direction:column;align-items:stretch;gap:12px;">
                        <div class="c2-row-label">
                            <div class="c2-row-name">Change password</div>
                            <div class="c2-row-desc">All other devices will be signed out — they'll need to enter the new password.</div>
                        </div>
                        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;">
                            <input type="password" class="c2-input" placeholder="Current password" bind:value={secCurrentPw} autocomplete="current-password" disabled={secBusy} />
                            <input type="password" class="c2-input" placeholder="New password" bind:value={secNewPw} autocomplete="new-password" disabled={secBusy} />
                            <input type="password" class="c2-input" placeholder="Confirm" bind:value={secConfirmPw} autocomplete="new-password" disabled={secBusy} />
                        </div>
                        <button class="c2-btn-primary" style="align-self:flex-start;" onclick={secEnableOrChangePassword} disabled={secBusy || !secCurrentPw || !secNewPw}>
                            {secBusy ? 'Saving…' : 'Change password'}
                        </button>
                    </div>

                    <div class="c2-row" style="flex-direction:column;align-items:stretch;gap:12px;">
                        <div class="c2-row-label">
                            <div class="c2-row-name">Sign out this device</div>
                            <div class="c2-row-desc">Clears the session cookie on this browser. You'll be sent to the login screen.</div>
                        </div>
                        <button class="c2-btn-outline" style="align-self:flex-start;" onclick={() => logout()}>Sign out</button>
                    </div>

                    <div class="c2-row" style="flex-direction:column;align-items:stretch;gap:12px;">
                        <div class="c2-row-label">
                            <div class="c2-row-name">Disable multi-user mode</div>
                            <div class="c2-row-desc">Switch back to single-user. The bind reverts to <code>localhost</code> on next start; everyone else loses access.</div>
                        </div>
                        {#if !secShowDisable}
                            <button class="c2-btn-outline c2-btn-err" style="align-self:flex-start;" onclick={() => secShowDisable = true}>Disable…</button>
                        {:else}
                            <div style="display:grid;grid-template-columns:1fr auto auto;gap:10px;align-items:center;">
                                <input type="password" class="c2-input" placeholder="Current password to confirm" bind:value={secDisablePw} autocomplete="current-password" disabled={secBusy} />
                                <button class="c2-btn-ghost" onclick={() => { secShowDisable = false; secDisablePw = ''; }}>Cancel</button>
                                <button class="c2-btn-danger" onclick={secDisablePassword} disabled={secBusy || !secDisablePw}>
                                    {secBusy ? 'Disabling…' : 'Yes, disable'}
                                </button>
                            </div>
                        {/if}
                    </div>
                {/if}

                <div class="c2-row">
                    <div class="c2-row-label">
                        <div class="c2-row-name">Per-user accounts</div>
                        <div class="c2-row-desc">Coming in a future release: each family member gets their own login and isolated chat history. Today everyone shares one account in password mode.</div>
                    </div>
                    <div class="c2-row-control">
                        <span class="c2-tag">Roadmap</span>
                    </div>
                </div>
