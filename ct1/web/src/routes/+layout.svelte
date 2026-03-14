<script>
    import '../app.css';
    import { page } from '$app/stores';
    let { children } = $props();
</script>

<div class="shell">
    <header>
        <a href="/" class="logo">CT-1</a>
        <nav>
            <a href="/" class:active={$page.url.pathname === '/'}>Chat</a>
            <a href="/journal" class:active={$page.url.pathname === '/journal'}>Journal</a>
            <a href="/settings" class:active={$page.url.pathname === '/settings'}>Settings</a>
        </nav>
    </header>
    <main>
        {@render children()}
    </main>
</div>

<style>
    .shell {
        display: flex;
        flex-direction: column;
        height: 100vh;
    }
    header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 24px;
        height: 52px;
        border-bottom: 1px solid var(--border);
        flex-shrink: 0;
    }
    .logo {
        font-size: 17px;
        font-weight: 600;
        letter-spacing: -0.03em;
        color: var(--text);
    }
    nav {
        display: flex;
        gap: 24px;
    }
    nav a {
        color: var(--text-secondary);
        font-size: 14px;
        font-weight: 500;
        transition: color var(--transition);
    }
    nav a:hover, nav :global(a.active) {
        color: var(--text);
        opacity: 1;
    }
    main {
        flex: 1;
        overflow-y: auto;
        padding: 24px;
    }
</style>
