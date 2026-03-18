# CT-2 Pipeline Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix edit detection (too aggressive), fix image blank responses, add text file attachments.

**Architecture:** Three independent fixes. (1) Replace `_detect_edit_mode()` with intent-gated `_detect_conversation_mode()` that checks both code context AND user intent keywords. (2) Add `vision_supported` config flag; strip images from LLM messages if false. (3) Expand `ChatInput` to accept text files, inline their content as text context.

**Tech Stack:** Python (FastAPI backend), SvelteKit 5 (frontend), llama-server (LLM inference)

---

### Task 1: Rework Edit Detection in Orchestrator

**Files:**
- Modify: `ct1/core/orchestrator.py:88-109` (replace `_detect_edit_mode`)
- Modify: `ct1/core/orchestrator.py:242-310` (update `_pipeline` to use new mode)

**Step 1: Replace `_detect_edit_mode` with `_detect_conversation_mode`**

In `ct1/core/orchestrator.py`, replace the `_detect_edit_mode` method (lines 88-109) with:

```python
_EDIT_INTENT = {
    "change", "modify", "update", "edit", "fix", "add", "remove",
    "replace", "swap", "move", "resize", "make it", "make the",
    "adjust", "tweak", "set the", "turn the", "switch",
    "rename", "recolor", "restyle", "redesign", "redo",
    "bigger", "smaller", "wider", "narrower", "taller", "shorter",
    "darker", "lighter", "brighter", "bolder",
    "add a", "add the", "put a", "put the", "insert",
    "delete", "drop", "hide", "show",
}

_QUESTION_STARTS = (
    "what", "why", "how", "explain", "describe", "tell me",
    "is there", "is this", "is it", "are there", "can you explain",
    "which", "where", "when", "who", "does", "do you",
    "could you explain", "what's", "what is", "how does",
    "how do", "how is", "how are", "can i", "should",
)

@classmethod
def _detect_conversation_mode(cls, goal_text: str,
                               conversation: list[dict]) -> tuple[str, str]:
    """Detect conversation mode based on code context + user intent.
    Returns (mode, previous_code) where mode is 'edit', 'question', or 'new'.
    """
    if not conversation:
        return "new", ""

    # Find the last assistant message
    previous_code = ""
    has_code = False
    for msg in reversed(conversation):
        if msg["role"] == "assistant":
            content = msg.get("content", "")
            if not isinstance(content, str):
                break
            stripped = content.strip()
            is_html = (stripped.startswith("<!DOCTYPE")
                       or stripped.startswith("<html")
                       or stripped.startswith("<!doctype"))
            is_python = ("def " in content and "import " in content
                         and len(content) > 500)
            is_js = ("function " in content and len(content) > 500)
            if is_html or is_python or is_js:
                has_code = True
                previous_code = content
            break

    if not has_code:
        return "new", ""

    # Code exists — check user intent
    gl = goal_text.lower().strip()

    # Question detection (check first — questions take priority)
    if gl.startswith(_QUESTION_STARTS) or gl.endswith("?"):
        return "question", previous_code

    # Edit intent detection
    if any(kw in gl for kw in cls._EDIT_INTENT):
        return "edit", previous_code

    # Ambiguous — default to new (let specialist route normally)
    return "new", ""
```

Note: Also move `_EDIT_INTENT` and `_QUESTION_STARTS` to class-level or module-level (like `_FIX_KEYWORDS`).

**Step 2: Update `_pipeline` to use the new mode**

In `ct1/core/orchestrator.py`, replace the edit detection and routing section of `_pipeline` (lines 254-265) with:

```python
# Detect conversation mode (edit / question / new)
mode, previous_code = self._detect_conversation_mode(goal_text, conversation)
is_edit = mode == "edit"

# ── Phase 1: ROUTE ────────────────────────────────────
if is_edit:
    route = "ROUTE_CODE"
    emit("routing")
    emit("routed", route=route)
elif mode == "question":
    route = "ROUTE_DIRECT"
    emit("routing")
    emit("routed", route=route)
else:
    emit("routing")
    route = await self.specialist.route(goal_text, conversation=conversation)
    emit("routed", route=route)
```

**Step 3: Remove the old `_detect_edit_mode` reference**

The old `is_edit, previous_code = self._detect_edit_mode(conversation)` on line 255 should already be replaced by step 2. Verify no other references exist.

**Step 4: Commit**

```bash
git add ct1/core/orchestrator.py
git commit -m "fix: intent-gated edit detection — questions about code no longer trigger edit mode"
```

---

### Task 2: Add "Discuss Code" Mode to Director

**Files:**
- Modify: `ct1/core/director.py:82-87` (add new system prompt)
- Modify: `ct1/core/director.py:327-397` (add question-about-code branch in `generate()`)

**Step 1: Add discuss system prompt**

In `ct1/core/director.py`, after `_GENERATOR_TEXT_SYSTEM` (line 87), add:

```python
_GENERATOR_DISCUSS_SYSTEM = (
    "You are the CT-2 Director, an expert developer.\n"
    "The user is asking about code you generated previously.\n"
    "Answer their question clearly and concisely. "
    "Reference specific parts of the code when relevant.\n"
    "Do NOT output modified code unless the user explicitly asks for changes."
)
```

**Step 2: Add code context injection in `generate()`**

In `ct1/core/director.py`, the `generate()` method (line 327). Add a new parameter `code_context: str = None` and handle it.

Update the method signature:

```python
async def generate(self, goal, route: str,
                   specialist_data: dict = None,
                   plan: dict = None,
                   conversation: list[dict] = None,
                   on_token=None,
                   is_edit: bool = False,
                   code_context: str = None) -> dict:
```

Then, after the `is_direct` assignment (line 340), add the "discuss code" branch. Insert before the existing `if is_edit and is_code:` block (line 364):

```python
    # "Question about code" mode — answer about previously generated code
    if code_context and is_direct:
        truncated = self._truncate_context(code_context, 6000)
        prompt = (
            f"[Previously generated code for reference]\n{truncated}\n\n"
            f"User question: {goal_text}"
        )
        system = _GENERATOR_DISCUSS_SYSTEM
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        if on_token:
            return await self._call_stream(
                messages, on_token=on_token,
                max_tokens=2048,
                presence_penalty=0.0,
                conversation=conversation,
                enable_thinking=False,
            )
        return await self._call(
            messages, max_tokens=2048,
            conversation=conversation,
            enable_thinking=False,
        )
```

**Step 3: Pass code_context from orchestrator**

In `ct1/core/orchestrator.py`, in the `_pipeline` method, update the generation call for the `mode == "question"` case. After the routing section, in the generate call (around line 301), pass `code_context`:

```python
    result = await self.director.generate(
        goal, route,
        specialist_data=specialist_data,
        plan=plan,
        conversation=conversation,
        on_token=on_token,
        code_context=previous_code if mode == "question" else None,
    )
```

**Step 4: Commit**

```bash
git add ct1/core/director.py ct1/core/orchestrator.py
git commit -m "feat: add discuss-code mode — AI answers questions about generated code"
```

---

### Task 3: Fix Image Handling (Vision Config Flag)

**Files:**
- Modify: `ct1/server/model_config.yaml:19-26` (add vision_supported flag)
- Modify: `ct1/core/orchestrator.py:40-67` (read vision flag, pass to director)
- Modify: `ct1/core/director.py:97-107` (store vision flag)
- Modify: `ct1/core/director.py:124-164` (strip images in `_call` if no vision)
- Modify: `ct1/core/director.py:207-268` (strip images in `_call_stream` if no vision)

**Step 1: Add vision flag to config**

In `ct1/server/model_config.yaml`, under `models.director` (after line 26), add:

```yaml
    vision_supported: false
```

**Step 2: Read and pass vision flag in orchestrator**

In `ct1/core/orchestrator.py`, in `__init__` (around line 51), pass the flag:

```python
self.director = Director(
    base_url=director_url,
    temperature=dc["temperature"],
    top_p=dc["top_p"],
    top_k=dc["top_k"],
    presence_penalty=dc["presence_penalty"],
    max_tokens=dc["max_tokens"],
    vision_supported=dc.get("vision_supported", False),
)
```

**Step 3: Store vision flag in Director**

In `ct1/core/director.py`, update `__init__` (line 98) to accept and store it:

```python
def __init__(self, base_url: str, temperature: float = 0.6,
             top_p: float = 0.9, top_k: int = 40,
             presence_penalty: float = 1.0, max_tokens: int = 100000,
             vision_supported: bool = False):
    self.base_url = base_url
    self.temperature = temperature
    self.top_p = top_p
    self.top_k = top_k
    self.presence_penalty = presence_penalty
    self.max_tokens = max_tokens
    self.vision_supported = vision_supported
    self.client = httpx.AsyncClient(timeout=600.0)
    self.lessons: list[str] = []
    self.last_session: str = ""
```

**Step 4: Add image-stripping helper**

In `ct1/core/director.py`, add a helper method after `__init__`:

```python
def _sanitize_messages(self, messages: list[dict]) -> list[dict]:
    """Strip image content from messages if vision is not supported."""
    if self.vision_supported:
        return messages
    sanitized = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            # Multimodal: keep only text parts
            text_parts = [p.get("text", "") for p in content
                          if p.get("type") == "text"]
            sanitized.append({
                **msg,
                "content": " ".join(text_parts) or "(image attachment — vision not available)",
            })
        else:
            sanitized.append(msg)
    return sanitized
```

**Step 5: Apply sanitization in `_call` and `_call_stream`**

In `_call` (line 124), after the conversation insertion (line 132), add:

```python
messages = self._sanitize_messages(messages)
```

In `_call_stream` (line 207), after the conversation insertion (line 216), add the same:

```python
messages = self._sanitize_messages(messages)
```

**Step 6: Emit warning event when images stripped**

In `ct1/core/orchestrator.py`, in `_pipeline`, after extracting `goal_text` (line 248), check for images:

```python
# Warn if images attached but vision not supported
has_images = (isinstance(goal, list) and
              any(p.get("type") == "image_url" for p in goal))
if has_images and not self.director.vision_supported:
    emit("warning", message="Image attached but vision is not available with current model. The image will be ignored.")
```

**Step 7: Handle warning event in frontend**

In `ct1/web/src/lib/stores/chat.ts`, add a `warning` field to `ChatState` (after line 76):

```typescript
    warning: string;
```

Add to initial state (after line 97):

```typescript
    warning: '',
```

In `handleEvent`, add a case (after the `error` case, around line 202):

```typescript
            case 'warning':
                s.warning = data.message || '';
                break;
```

In `sendThink`, reset warning on new message (add after line 247):

```typescript
        s.warning = '';
```

**Step 8: Display warning in +page.svelte**

In `ct1/web/src/routes/+page.svelte`, after the route badge section (around line 251), add:

```svelte
{#if $chat.warning}
    <div class="warning-banner">{$chat.warning}</div>
{/if}
```

Add CSS for `.warning-banner` in the style block:

```css
.warning-banner {
    max-width: 520px;
    margin: 8px auto;
    padding: 10px 16px;
    background: rgba(255, 180, 50, 0.12);
    border: 1px solid rgba(255, 180, 50, 0.25);
    border-radius: 10px;
    font-size: 13px;
    color: var(--text-secondary);
    text-align: center;
}
```

**Step 9: Commit**

```bash
git add ct1/server/model_config.yaml ct1/core/orchestrator.py ct1/core/director.py ct1/web/src/lib/stores/chat.ts ct1/web/src/routes/+page.svelte
git commit -m "fix: add vision_supported flag, strip images when vision unavailable, show warning"
```

---

### Task 4: Add Text File Attachments — Frontend

**Files:**
- Modify: `ct1/web/src/lib/stores/chat.ts:4-9` (extend Attachment interface)
- Modify: `ct1/web/src/lib/components/ChatInput.svelte:34-47` (accept text files, read as text)
- Modify: `ct1/web/src/lib/components/ChatInput.svelte:99-112` (display file badges)
- Modify: `ct1/web/src/lib/components/ChatInput.svelte:116-119` (expand accept attribute)

**Step 1: Extend Attachment interface**

In `ct1/web/src/lib/stores/chat.ts`, replace the Attachment interface (lines 4-9) with:

```typescript
export interface Attachment {
    type: 'image' | 'file';
    name: string;
    /** data:image/...;base64,... — only for images */
    dataUrl: string;
    /** text content — only for text files */
    textContent?: string;
}
```

**Step 2: Update readFiles to handle text files**

In `ct1/web/src/lib/components/ChatInput.svelte`, replace the `readFiles` function (lines 34-48) with:

```typescript
const TEXT_EXTENSIONS = new Set([
    'txt', 'html', 'htm', 'css', 'js', 'ts', 'py', 'json', 'md',
    'csv', 'xml', 'yaml', 'yml', 'svg', 'sh', 'bat', 'sql', 'rb',
    'go', 'rs', 'java', 'c', 'cpp', 'h', 'hpp', 'toml', 'ini', 'cfg',
]);

function getExtension(name: string): string {
    const i = name.lastIndexOf('.');
    return i >= 0 ? name.slice(i + 1).toLowerCase() : '';
}

function readFiles(files: FileList | File[]) {
    for (const file of files) {
        if (attachments.length >= 4) break;
        const ext = getExtension(file.name);

        if (file.type.startsWith('image/')) {
            const reader = new FileReader();
            reader.onload = () => {
                attachments = [...attachments, {
                    type: 'image',
                    name: file.name,
                    dataUrl: reader.result as string,
                }];
            };
            reader.readAsDataURL(file);
        } else if (TEXT_EXTENSIONS.has(ext) || file.type.startsWith('text/')) {
            const reader = new FileReader();
            reader.onload = () => {
                const text = reader.result as string;
                // Limit file size to ~8000 chars to protect context window
                const truncated = text.length > 8000
                    ? text.slice(0, 8000) + '\n\n[... truncated, file too large ...]'
                    : text;
                attachments = [...attachments, {
                    type: 'file',
                    name: file.name,
                    dataUrl: '',
                    textContent: truncated,
                }];
            };
            reader.readAsText(file);
        }
    }
}
```

**Step 3: Update file input accept attribute**

In `ChatInput.svelte`, change the `accept` attribute (line 119) from:

```html
accept="image/*"
```

to:

```html
accept="image/*,.txt,.html,.htm,.css,.js,.ts,.py,.json,.md,.csv,.xml,.yaml,.yml,.svg,.sh,.sql,.go,.rs,.java,.c,.cpp,.h,.toml,.ini"
```

Also update the button labels (lines 128-129):

```html
aria-label="Attach file"
title="Attach file"
```

**Step 4: Update attachment display to show file badges**

In `ChatInput.svelte`, replace the attachments rendering (lines 99-112) with:

```svelte
{#if attachments.length > 0}
    <div class="attachments-bar">
        {#each attachments as att, i}
            <div class="attachment-island">
                {#if att.type === 'image'}
                    <img src={att.dataUrl} alt={att.name} class="att-thumb" />
                {:else}
                    <div class="att-file-icon">
                        <svg width="18" height="18" viewBox="0 0 16 16" fill="none">
                            <path d="M4 1h5.5L13 4.5V14a1 1 0 01-1 1H4a1 1 0 01-1-1V2a1 1 0 011-1z" stroke="currentColor" stroke-width="1.2"/>
                            <path d="M9 1v4h4" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
                        </svg>
                    </div>
                {/if}
                <span class="att-name">{att.name.length > 18 ? att.name.slice(0, 15) + '...' : att.name}</span>
                {#if att.type === 'file' && att.textContent}
                    <span class="att-size">{(att.textContent.length / 1000).toFixed(1)}k</span>
                {/if}
                <button class="att-remove" onclick={() => removeAttachment(i)} aria-label="Remove {att.name}">
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                        <path d="M3 3l6 6M9 3l-6 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                    </svg>
                </button>
            </div>
        {/each}
    </div>
{/if}
```

Add CSS for the file icon and size badge (in the `<style>` block):

```css
.att-file-icon {
    width: 36px;
    height: 36px;
    border-radius: 8px;
    background: rgba(0, 0, 0, 0.04);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    color: var(--text-muted);
}

.att-size {
    font-size: 11px;
    color: var(--text-muted);
    opacity: 0.7;
}
```

**Step 5: Update paste handler to ignore non-image pastes**

The existing `onPaste` handler (lines 75-89) already only handles images — no change needed.

**Step 6: Commit**

```bash
git add ct1/web/src/lib/stores/chat.ts ct1/web/src/lib/components/ChatInput.svelte
git commit -m "feat: text file attachments — accept txt/html/css/js/py/json and more"
```

---

### Task 5: Text File Attachments — Backend Integration

**Files:**
- Modify: `ct1/web/src/lib/stores/chat.ts:252-272` (inline text files in goal)
- Modify: `ct1/web/src/routes/+page.svelte:169-175` (render file badges in user bubbles)

**Step 1: Inline text file content in sendThink**

In `ct1/web/src/lib/stores/chat.ts`, replace the goal-building section in `sendThink` (lines 264-272) with:

```typescript
    // Build current message content
    // Text files: inline as text context (works with text-only models)
    // Images: use multimodal format (only if vision supported)
    let textPrefix = '';
    const imageAtts: Attachment[] = [];
    for (const att of attachments) {
        if (att.type === 'file' && att.textContent) {
            textPrefix += `[File: ${att.name}]\n${att.textContent}\n\n`;
        } else if (att.type === 'image') {
            imageAtts.push(att);
        }
    }

    const fullGoal = textPrefix ? `${textPrefix}${goal}` : goal;

    let goalContent: any = fullGoal;
    if (imageAtts.length > 0) {
        const parts: any[] = [{ type: 'text', text: fullGoal }];
        for (const att of imageAtts) {
            parts.push({ type: 'image_url', image_url: { url: att.dataUrl } });
        }
        goalContent = parts;
    }
```

Also update the backendConv builder (lines 253-262) to handle text file attachments in conversation history:

```typescript
    const backendConv = conv.map(t => {
        if (t.attachments && t.attachments.length > 0) {
            // Inline text files, keep images as multimodal
            let text = t.content;
            const images: Attachment[] = [];
            for (const att of t.attachments) {
                if (att.type === 'file' && att.textContent) {
                    text = `[File: ${att.name}]\n${att.textContent}\n\n${text}`;
                } else if (att.type === 'image') {
                    images.push(att);
                }
            }
            if (images.length > 0) {
                const content: any[] = [{ type: 'text', text }];
                for (const att of images) {
                    content.push({ type: 'image_url', image_url: { url: att.dataUrl } });
                }
                return { role: t.role, content };
            }
            return { role: t.role, content: text };
        }
        return { role: t.role, content: t.content };
    });
```

**Step 2: Update user bubble rendering for file attachments**

In `ct1/web/src/routes/+page.svelte`, update the bubble-images section (lines 169-175 and 232-237) to handle both image and file attachments. Replace both instances:

```svelte
{#if turn.attachments && turn.attachments.length > 0}
    <div class="bubble-attachments">
        {#each turn.attachments as att}
            {#if att.type === 'image'}
                <img src={att.dataUrl} alt={att.name} class="bubble-img" />
            {:else}
                <span class="bubble-file-badge">
                    <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                        <path d="M4 1h5.5L13 4.5V14a1 1 0 01-1 1H4a1 1 0 01-1-1V2a1 1 0 011-1z" stroke="currentColor" stroke-width="1.2"/>
                        <path d="M9 1v4h4" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
                    </svg>
                    {att.name}
                </span>
            {/if}
        {/each}
    </div>
{/if}
```

Add CSS for the file badge in the style block:

```css
.bubble-attachments {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    margin-bottom: 6px;
}

.bubble-file-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    font-weight: 500;
    color: var(--text-secondary);
    background: rgba(0, 0, 0, 0.05);
    padding: 3px 8px;
    border-radius: 6px;
}
.bubble-file-badge svg {
    opacity: 0.6;
}
```

**Step 3: Update submit fallback text**

In `ChatInput.svelte`, update the submit function (line 15) to handle file-only messages:

```typescript
sendThink(text || (attachments.some(a => a.type === 'image') ? '(image attached)' : '(file attached)'), [...attachments]);
```

**Step 4: Commit**

```bash
git add ct1/web/src/lib/stores/chat.ts ct1/web/src/routes/+page.svelte ct1/web/src/lib/components/ChatInput.svelte
git commit -m "feat: inline text file content in messages, render file badges in chat"
```

---

### Task 6: Build and Verify

**Step 1: Build the frontend**

```bash
cd ct1/web && npm run build
```

Expected: Build succeeds with no errors (warnings about unused CSS selectors are OK).

**Step 2: Manual verification checklist**

Start the backend: `python -m ct1.server.api`

Test these scenarios:
1. Generate HTML code → ask "what does this code do?" → should get a text answer, NOT code modification
2. Generate HTML code → say "make the background blue" → should trigger edit mode normally
3. Attach a `.txt` file → send with a message → file content should appear in the prompt
4. Attach an image → send → should see warning banner "vision not available"
5. Fresh conversation with no code → normal routing works as before

**Step 3: Final commit**

```bash
git add -A
git commit -m "build: rebuild frontend with pipeline fixes"
```
