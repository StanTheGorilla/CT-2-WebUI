# CT-2 Pipeline Fixes Design
**Date:** 2026-03-18

## Problems

### 1. Edit Detection Too Aggressive
`_detect_edit_mode()` in orchestrator.py checks if the last assistant message contains code (HTML/Python/JS). If it does, EVERY subsequent user message forces `ROUTE_CODE` + edit mode — even questions like "what does this code do?" or "explain the header section." The user cannot discuss or ask about generated code without the system trying to modify it.

### 2. Images Produce Blank Response
When the user attaches an image and sends a message, the pipeline runs to completion (reflection + journal write happens), but the generated text is empty. The GGUF models are loaded via llama-server without `--mmproj` or vision configuration. Even though Qwen3.5 has vision built into the architecture, llama-server may not process multimodal content arrays correctly with the current setup. Need to verify and fix or disable gracefully.

### 3. No Text File Attachments
ChatInput only accepts `image/*` files. Users want to attach `.txt`, `.html`, `.css`, `.js`, `.py` files as context for the AI.

## Solutions

### Fix 1: Intent-Gated Edit Detection

**Current flow:**
```
last assistant message is code? → YES → edit mode (always)
```

**New flow:**
```
last assistant message is code?
  → YES → does user message contain edit intent?
            → YES (change, modify, add, remove, make it...) → edit mode
            → NO  → is it a question? (what, why, how, explain...)
                      → YES → ROUTE_DIRECT with code as context
                      → NO  → normal routing via specialist
  → NO → normal routing via specialist
```

**Changes to orchestrator.py:**

1. Add `_has_edit_intent(goal_text)` method:
   - Check for edit keywords (reuse from specialist's `_EDIT_KEYWORDS`)
   - Check for question patterns (starts with what/why/how/explain/describe/tell me/is there/can you explain)
   - Returns: `"edit"`, `"question"`, or `"ambiguous"`

2. Modify `_detect_edit_mode()` → rename to `_detect_conversation_mode()`:
   - Returns `("edit", previous_code)` — user wants to modify code
   - Returns `("question", previous_code)` — user is asking about the code
   - Returns `("new", "")` — no code context, fresh request

3. Update `_pipeline()`:
   - `mode == "edit"`: current edit behavior (ROUTE_CODE, skip planning, edit prompts)
   - `mode == "question"`: use ROUTE_DIRECT, inject truncated code as system context so the AI can reference it while answering
   - `mode == "new"`: current normal behavior (specialist routing)

**Changes to director.py:**

4. Add a "discuss code" system prompt for when the user asks questions about generated code:
   ```
   _GENERATOR_DISCUSS_SYSTEM = (
       "You are the CT-2 Director, an expert developer.\n"
       "The user is asking about code from a previous response.\n"
       "Answer their question clearly and concisely. Reference specific parts of the code.\n"
       "Do NOT output code unless the user explicitly asks for modifications."
   )
   ```

5. In `generate()`, handle the "question about code" case:
   - Use `_GENERATOR_DISCUSS_SYSTEM` as system prompt
   - Inject truncated previous code as context
   - Use `enable_thinking=False`, `max_tokens=2048` (short answer mode)

### Fix 2: Image Handling

**Step 1: Test vision support**
- Make a test call to llama-server with multimodal content and check the response
- Check if llama-server b8292 supports Qwen3.5 integrated vision or needs `--mmproj`

**Step 2: If vision doesn't work with current config:**
- In `director.py` `_call()` and `_call_stream()`: strip image parts from messages before sending to llama-server (keep only text parts)
- In the orchestrator: if goal contains images but vision is not supported, emit a warning event
- Add a `vision_supported: false` flag to model_config.yaml
- Frontend shows a toast/notice: "Image attached but vision not available with current model"

**Step 3: If vision works:**
- Keep current multimodal flow
- Add context window budget check — warn if base64 image is too large (>5000 chars ≈ 1500+ tokens)

### Fix 3: Text File Attachments

**Changes to ChatInput.svelte:**

1. Expand file input `accept` attribute:
   ```
   accept="image/*,.txt,.html,.htm,.css,.js,.ts,.py,.json,.md,.csv,.xml,.yaml,.yml,.svg"
   ```

2. Add a new attachment type:
   ```typescript
   export interface Attachment {
       type: 'image' | 'file';
       name: string;
       dataUrl: string;     // for images
       textContent?: string; // for text files
   }
   ```

3. In `readFiles()`: detect file type:
   - `file.type.startsWith('image/')` → read as dataURL (existing)
   - Otherwise → read as text via `reader.readAsText(file)`
   - Store in `textContent` field

4. Update attachment display:
   - Images: thumbnail (existing)
   - Text files: file icon + name + size badge

**Changes to chat.ts:**

5. In `sendThink()`: build goal content differently for text files:
   - Text file attachments get inlined into the text: `[File: filename.html]\n<content>\n\n`
   - Image attachments stay as multimodal content arrays (existing)
   - This means text files work perfectly with text-only models — no vision needed

**Changes to +page.svelte:**

6. User bubbles: show file attachment badges (filename + size) instead of image thumbnails for text files

## Non-Goals

- Screenshot capture of generated HTML (good idea but impractical with 16K context + 4B model)
- AI-based intent classification for edit detection (specialist 2B is unreliable for this)
- Image resizing/compression (defer until vision is confirmed working)

## File Change Summary

| File | Changes |
|------|---------|
| `ct1/core/orchestrator.py` | Rework `_detect_edit_mode` → `_detect_conversation_mode`, add `_has_edit_intent`, update pipeline flow |
| `ct1/core/director.py` | Add `_GENERATOR_DISCUSS_SYSTEM` prompt, handle "question about code" in `generate()` |
| `ct1/web/src/lib/components/ChatInput.svelte` | Accept text files, read as text, display file badges |
| `ct1/web/src/lib/stores/chat.ts` | Extend Attachment interface, inline text files in goal, handle vision flag |
| `ct1/web/src/routes/+page.svelte` | Render file attachment badges in user bubbles |
| `ct1/server/model_config.yaml` | Add `vision_supported: false` flag |
| `ct1/core/director.py` (`_call`/`_call_stream`) | Strip image parts from messages if vision not supported |
