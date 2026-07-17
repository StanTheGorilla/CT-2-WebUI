<script lang="ts">
    import '../app.css';
    import { connect, disconnect } from '$lib/stores/chat';
    import { page } from '$app/stores';
    import { goto } from '$app/navigation';
    import { onMount, onDestroy } from 'svelte';
    import Ct2Layout from '$lib/ct2/Layout.svelte';
    import { authStatus, authReady, refreshAuthStatus, needsLoginScreen } from '$lib/stores/auth';

    onMount(async () => {
        // Resolve auth state BEFORE opening the chat WS.
        // In `password` mode an unauthed WS is rejected with 4401, so opening it
        // pre-login would just churn. In `none` mode this resolves instantly.
        const s = await refreshAuthStatus();
        const onLogin = $page.url.pathname === '/login';
        if (needsLoginScreen(s) && !onLogin) {
            await goto('/login', { replaceState: true });
            return;
        }
        if (!needsLoginScreen(s) && onLogin) {
            await goto('/', { replaceState: true });
        }
        connect();
    });
    onDestroy(() => disconnect());

    // 401 from any fetch in the app should bounce us to the login page.
    // Re-checking auth status is cheap and self-healing if a session expired.
    $effect(() => {
        if (!$authReady) return;
        if (needsLoginScreen($authStatus) && $page.url.pathname !== '/login') {
            goto('/login', { replaceState: true });
        }
    });

    let { children } = $props();
</script>

{#if $page.url.pathname === '/login'}
    {@render children()}
{:else}
    <Ct2Layout>
        {@render children()}
    </Ct2Layout>
{/if}
