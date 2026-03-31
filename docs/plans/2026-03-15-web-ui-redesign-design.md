# CT-2 Web UI Redesign — Design Document

## Goal

Rebuild the CT-2 frontend from a dark, single-column chat layout into a light-themed, Apple-inspired split-pane interface with live code preview, elastic animations, and proper output readability. No backend changes.

## Architecture

Full layout rebuild of SvelteKit 5 components. The `chat.ts` store, `ws.ts` WebSocket client, and all backend (orchestrator, director, specialist, API) remain untouched. Only `.svelte` components, `app.css`, and `markdown.ts` are modified.

## Design System

### Palette
```
--bg:              #F5F5F7    (apple warm off-white)
--surface:         #FFFFFF    (white cards/panels)
--surface-hover:   #E8E8ED    (hover state)
--border:          #D1D1D6    (light gray borders)
--text:            #1D1D1F    (near-black text)
--text-secondary:  #6E6E73    (medium gray)
--text-muted:      #AEAEB2    (light gray labels)

--accent:          #007AFF    (apple blue)
--specialist:      #AF52DE    (apple purple)
--brain:           #FF9500    (apple orange)
--success:         #34C759    (apple green)
--warning:         #FF9F0A
--error:           #FF3B30

--shadow-sm:       0 1px 3px rgba(0,0,0,0.08)
--shadow-md:       0 4px 12px rgba(0,0,0,0.08)
--shadow-lg:       0 8px 30px rgba(0,0,0,0.12)
```

### Typography
- Body: Inter, 14px, weight 400
- Medium: weight 500
- Semibold: weight 600
- Code: JetBrains Mono, 13px, line-height 1.6

### Border Radius
- Cards: 12px
- Pills/buttons: 20px
- Inputs: 8px

### Spring Animations
```css
--spring: cubic-bezier(0.34, 1.56, 0.64, 1);
--spring-duration: 400ms;
--spring-soft: cubic-bezier(0.34, 1.3, 0.64, 1);
```

## Page Layout

Full-width split pane. No 800px max-width.

```
┌─────────────────────────────────────────────────────┐
│ CT-2            ● routing...            Journal  ⚙  │  44px status strip
├───────────────────────┬─┬───────────────────────────┤
│                       │▐│                           │
│   Chat Panel          │▐│   Preview Panel           │
│   (messages +         │▐│   [Preview | Code]  [✕]   │
│    streaming)         │▐│                           │
│                       │▐│   iframe / highlighted    │
│                       │▐│   code with copy button   │
│                       │▐│                           │
├───────────────────────┤▐├───────────────────────────┤
│ [textarea        ] ⏎  │▐│                           │
└───────────────────────┴─┴───────────────────────────┘
                        ↔ draggable divider (6px)
```

### Key Behaviors
- **Default:** Chat full-width, no preview panel
- **Code generated:** Preview slides in from right (spring-soft, 500ms), chat compresses to ~50%
- **Divider:** Min 30% / max 70%, drag handle visible on hover, col-resize cursor
- **Close (✕):** Preview slides out, chat goes full-width again
- **Non-code responses:** Preview stays hidden, chat stays full-width

## Status Strip (Top Bar)

44px tall, replaces the old navigation header.
- Left: "CT-2" logo
- Center: phase indicator pill — transitions between routing → consulting → generating → validating → done. Pulse dot for active phase, text slides between states.
- Right: Journal + Settings links

## Chat Panel

### User Messages
- Align right, blue (#007AFF) background, white text
- Gum bubble radius: 20px 20px 6px 20px
- Max-width: 65%, shadow-sm
- Entrance: spring scale 0.92→1.0, 300ms

### Assistant Messages
- Align left, white background, 1px border
- Gum bubble radius: 6px 20px 20px 20px
- Max-width: 80%, shadow-sm
- Entrance: spring scale 0.92→1.0, 300ms

### Route Badge
- Small inline pill, spring pop-in (scale 0.5→1.0)

### Specialist Card
- White card, purple left accent, collapsible
- Spring expand/collapse with scaleY overshoot
- Palette swatches, typography grid, section pills, rationale

### Streaming Output
- White card, left accent border (orange=director, purple=specialist)
- NO max-height cutoff — scrolls with the chat (eliminates double-scroll)
- Live char counter in header
- Monospace, 13px

### Chat Input
- Sticky bottom of chat panel
- Pill-shaped (20px radius), white background
- Auto-grow textarea, max 200px
- Focus: blue border + soft blue glow
- Send button: filled blue pill

## Preview Panel

### Tab Bar (40px)
- Segmented control: [Preview] [Code]
- Active: white pill with shadow
- Inactive: transparent, gray text
- Close (✕) button on right

### Preview Tab
- `<iframe srcdoc={code}>` renders HTML live
- Fills remaining height
- sandbox="allow-scripts allow-same-origin"
- Updates on final response + debounced during streaming (~500ms)

### Code Tab
- highlight.js with `github` (light) theme
- Line numbers (gray gutter, 40px)
- Copy button: top-right pill, "Copy" → "Copied ✓" with bounce
- Full height scroll, no truncation
- pre-wrap to avoid horizontal scroll

## Animations

### Element Entrances
- Chat bubbles: scale(0.92)→1.0 + opacity, spring, 300ms
- Route badge: scale(0.5)→1.0, spring (big overshoot), 400ms
- Specialist card: scaleY(0.95) translateY(8px)→identity, spring, 400ms
- Status pill: text slides out left, new text in from right, 250ms

### Preview Panel
- Slide in: translateX(100%)→0, spring-soft, 500ms
- Slide out: reverse, 400ms
- Chat width animates smoothly during open/close

### Divider
- Instant during drag (60fps)
- Tiny spring settle on release (100ms)
- Handle widens + shows grab dots on hover

### Collapsible Sections
- Height via scaleY + transform-origin: top
- Elastic overshoot on open
- Content fades in 100ms after height animation starts

### Micro-interactions
- Copy button: scale(0.9)→1.05→1.0 bounce on click
- Cards: translateY(-1px) + shadow deepens on hover, 200ms
- Buttons: subtle brightness shift on hover

## Components Summary

| Component | Status | Notes |
|-----------|--------|-------|
| app.css | Rewrite | Light theme, spring variables |
| +layout.svelte | Rewrite | Status strip replaces nav header |
| +page.svelte | Rewrite | Split pane layout, conditional preview |
| SplitPane.svelte | New | Draggable divider, min/max constraints |
| PreviewPanel.svelte | New | Tabs, iframe, code view, copy button |
| StatusStrip.svelte | New | Phase indicator with animations |
| ChatInput.svelte | Restyle | Pill shape, light theme |
| ResponsePanel.svelte | Restyle | Light theme, gum radius |
| SpecialistCard.svelte | Restyle | Light theme, purple accent |
| ReflectionBar.svelte | Restyle | Light theme |
| markdown.ts | Modify | Switch highlight.js to github (light) theme |

## What Does NOT Change
- `chat.ts` store (all state management)
- `ws.ts` WebSocket client
- All backend Python code (director, specialist, orchestrator, API)
- `model_config.yaml`
- Journal and Settings pages (minor restyle only)
