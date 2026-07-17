<script lang="ts">
    import { onMount } from 'svelte';

    let { switching, restartModel }: {
        switching: boolean;
        restartModel: () => Promise<void>;
    } = $props();

    // ── System prompts ────────────────────────────────────────────
    const BEHAVIOR_KEYS = ['generator_text', 'generator_code', 'generator_design', 'generator_computer'];
    const PIPELINE_KEYS = ['generator_text_base', 'generator_code_base', 'generator_design_base', 'generator_computer_base', 'spec_generator'];
    const PROMPT_DANGER = new Set(['spec_generator']);
    const PROMPT_LABELS: Record<string, string> = {
        generator_text:          'Chat & Direct Answers',
        generator_code:          'Code Generator',
        generator_design:        'Design Generator',
        generator_computer:      'Computer Mode',
        generator_text_base:     'Chat — Core Instructions',
        generator_code_base:     'Code — Core Instructions',
        generator_design_base:   'Design — Core Instructions',
        generator_computer_base: 'Computer — Core Instructions',
        spec_generator:          'Design — Visual Spec Generator',
    };
    const PROMPT_DESCRIPTIONS: Record<string, string> = {
        generator_text:          'Tone, format, and response style for chat and direct answers.',
        generator_code:          'Instructions for writing, explaining, and editing code.',
        generator_design:        'Appearance and style guidance layered on top of the core pipeline for website and UI generation.',
        generator_computer:      'How the AI behaves when using tools to control your computer.',
        generator_text_base:     'Core pipeline instructions for chat mode. Always applied before your custom instructions.',
        generator_code_base:     'Core pipeline instructions for code mode. Always applied before your custom instructions.',
        generator_design_base:   'Core pipeline instructions for design mode. Always applied before your custom instructions.',
        generator_computer_base: 'Core pipeline instructions for computer mode. Always applied before your custom instructions.',
        spec_generator:          'Generates the visual plan — colors, fonts, and layout — before building a design. The server reads specific JSON field names from its output.',
    };

    let prompts = $state<Record<string, string>>({});
    let promptEdits = $state<Record<string, string>>({});
    let promptsDirty = $state<Record<string, boolean>>({});
    let promptsSaving = $state<Record<string, boolean>>({});
    let promptsSaved = $state<Record<string, boolean>>({});
    let promptsResetting = $state<Record<string, boolean>>({});
    let promptsSaveError = $state<Record<string, string>>({});

    async function loadPrompts() {
        try {
            const res = await fetch('/api/prompts');
            if (!res.ok) return;
            const data = await res.json();
            prompts = data.prompts ?? {};
            promptEdits = { ...prompts };
        } catch {}
    }

    function editPrompt(key: string, val: string) {
        promptEdits[key] = val;
        promptsDirty[key] = promptEdits[key] !== prompts[key];
        promptsSaved[key] = false;
        promptsSaveError[key] = '';
    }

    async function savePrompt(key: string) {
        promptsSaving[key] = true;
        promptsSaveError[key] = '';
        try {
            const res = await fetch(`/api/prompts/${key}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: promptEdits[key] }),
            });
            const d = await res.json();
            if (d.error) throw new Error(d.error);
            prompts[key] = promptEdits[key];
            promptsDirty[key] = false;
            promptsSaved[key] = true;
        } catch (e: any) {
            promptsSaveError[key] = e.message || 'Failed to save';
        } finally {
            promptsSaving[key] = false;
        }
    }

    async function resetPrompt(key: string) {
        promptsResetting[key] = true;
        promptsSaveError[key] = '';
        try {
            const res = await fetch(`/api/prompts/${key}/reset`, { method: 'POST' });
            const d = await res.json();
            if (!res.ok) throw new Error(d.detail || 'Failed to reset');
            prompts[key] = d.content;
            promptEdits[key] = d.content;
            promptsDirty[key] = false;
            promptsSaved[key] = true;
        } catch (e: any) {
            promptsSaveError[key] = e.message || 'Failed to reset';
        } finally {
            promptsResetting[key] = false;
        }
    }

    async function restartServer() {
        promptsSaved = {};  // restart applies the saved prompts — clear the badges
        await restartModel();
    }

    onMount(() => { loadPrompts(); });
</script>

                <div class="c2-sh">
                    <h1 class="c2-sh-title">System prompts</h1>
                    <p class="c2-sh-sub">Instructions that guide the AI in each mode. Everything is editable. Prompts marked with a warning affect how the server processes output — edit those carefully.</p>
                </div>
                <div class="c2-prompts-restart-row">
                    <span>Changes take effect after restarting the server.</span>
                    <button class="c2-btn-outline c2-btn-warn" onclick={restartServer} disabled={switching}>
                        {switching ? 'Restarting…' : 'Restart server'}
                    </button>
                </div>

                <!-- Behavior group -->
                <div class="c2-prompt-group-header">
                    <span class="c2-prompt-group-label">Behavior</span>
                    <span class="c2-prompt-group-desc">How the AI talks and responds in each mode. Edit freely.</span>
                </div>
                {#each BEHAVIOR_KEYS.filter(k => k in prompts) as key}
                    <div class="c2-prompt-card">
                        <div class="c2-prompt-card-header">
                            <span class="c2-prompt-card-name">{PROMPT_LABELS[key] ?? key}</span>
                            {#if PROMPT_DESCRIPTIONS[key]}
                                <span class="c2-prompt-card-desc">{PROMPT_DESCRIPTIONS[key]}</span>
                            {/if}
                            <span class="c2-prompt-card-key">{key}</span>
                        </div>
                        <textarea
                            class="c2-prompt-textarea"
                            rows="10"
                            value={promptEdits[key] ?? ''}
                            oninput={(e) => editPrompt(key, (e.target as HTMLTextAreaElement).value)}
                            spellcheck={false}
                            placeholder="Enter custom instructions..."
                        ></textarea>
                        {#if promptsSaved[key]}
                            <div class="c2-prompt-saved-notice">
                                Saved — restart the server to apply changes.
                                <button class="c2-prompt-restart-inline" onclick={restartServer} disabled={switching}>{switching ? 'Restarting…' : 'Restart now'}</button>
                            </div>
                        {/if}
                        {#if promptsSaveError[key]}
                            <div class="c2-inline-err">{promptsSaveError[key]}</div>
                        {/if}
                        <div class="c2-prompt-footer">
                            <button
                                class="c2-btn-ghost"
                                onclick={() => resetPrompt(key)}
                                disabled={promptsResetting[key] || promptsSaving[key]}
                            >{promptsResetting[key] ? 'Resetting…' : 'Reset to default'}</button>
                            {#if promptsDirty[key] || promptsSaveError[key]}
                                <button
                                    class="c2-btn-primary"
                                    onclick={() => savePrompt(key)}
                                    disabled={promptsSaving[key]}
                                >{promptsSaving[key] ? 'Saving…' : 'Save'}</button>
                            {/if}
                        </div>
                    </div>
                {/each}

                <!-- Pipeline group -->
                <div class="c2-prompt-group-header" style="margin-top:8px;">
                    <span class="c2-prompt-group-label">Pipeline</span>
                    <span class="c2-prompt-group-desc">Core instructions always active in each mode, plus the design planner. Edit only if you understand how the pipeline works.</span>
                </div>
                {#each PIPELINE_KEYS.filter(k => k in prompts) as key}
                    {@const isDanger = PROMPT_DANGER.has(key)}
                    <div class="c2-prompt-card">
                        <div class="c2-prompt-card-header">
                            <span class="c2-prompt-card-name">
                                {PROMPT_LABELS[key] ?? key}
                                {#if isDanger}<span class="c2-prompt-danger-badge">⚠ breaking if changed</span>{/if}
                            </span>
                            {#if PROMPT_DESCRIPTIONS[key]}
                                <span class="c2-prompt-card-desc">{PROMPT_DESCRIPTIONS[key]}</span>
                            {/if}
                            <span class="c2-prompt-card-key">{key}</span>
                        </div>
                        {#if isDanger}
                            <div class="c2-prompt-danger-notice">
                                ⚠ Warning: This prompt's output is read by the server as JSON. You can change the wording, but do not rename, add, or remove any output field names — that will break design mode generation.
                            </div>
                        {/if}
                        <textarea
                            class="c2-prompt-textarea"
                            rows="10"
                            value={promptEdits[key] ?? ''}
                            oninput={(e) => editPrompt(key, (e.target as HTMLTextAreaElement).value)}
                            spellcheck={false}
                        ></textarea>
                        {#if promptsSaved[key]}
                            <div class="c2-prompt-saved-notice">
                                Saved — restart the server to apply changes.
                                <button class="c2-prompt-restart-inline" onclick={restartServer} disabled={switching}>{switching ? 'Restarting…' : 'Restart now'}</button>
                            </div>
                        {/if}
                        {#if promptsSaveError[key]}
                            <div class="c2-inline-err">{promptsSaveError[key]}</div>
                        {/if}
                        <div class="c2-prompt-footer">
                            <button
                                class="c2-btn-ghost"
                                onclick={() => resetPrompt(key)}
                                disabled={promptsResetting[key] || promptsSaving[key]}
                            >{promptsResetting[key] ? 'Resetting…' : 'Reset to default'}</button>
                            {#if promptsDirty[key] || promptsSaveError[key]}
                                <button
                                    class="c2-btn-primary"
                                    onclick={() => savePrompt(key)}
                                    disabled={promptsSaving[key]}
                                >{promptsSaving[key] ? 'Saving…' : 'Save'}</button>
                            {/if}
                        </div>
                    </div>
                {/each}
