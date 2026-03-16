# CT-2 Web UI Glassmorphism + ASCII Art Redesign

**Date:** 2026-03-16
**Status:** Approved

## Overview

Redesign the CT-2 web UI from flat Apple-light style to a glassmorphism aesthetic with a fullscreen ASCII art background, cool greige accent palette, floating input island, and medium-frost blur on all panels.

## 1. Color Palette

Replace blue accent with cool greige. Warm the grays.

| Variable | Old | New |
|---|---|---|
| `--accent` | `#007AFF` | `#A8A0A0` (cool greige) |
| `--bg` | `#F5F5F7` | `#EDEAE6` (warm off-white) |
| `--surface` | `#FFFFFF` | `rgba(255, 255, 255, 0.80)` |
| `--surface-hover` | `#E8E8ED` | `rgba(255, 255, 255, 0.90)` |
| `--border` | `#D1D1D6` | `rgba(168, 160, 160, 0.25)` |
| `--text` | `#1D1D1F` | `#2C2A28` (warm dark) |
| `--text-secondary` | `#6E6E73` | `#7A7572` (warm gray) |
| `--text-muted` | `#AEAEB2` | `#B5B0AC` (warm muted) |

Keep specialist, brain, success, warning, error colors unchanged — they provide semantic contrast.

## 2. ASCII Art Background

- Fullscreen fixed-position `::after` pseudo-element on `.app` (or a dedicated div)
- Contains a large ASCII circuit-board/brain/geometric pattern
- Rendered in `#C8C2BC` (light greige) on `--bg` background
- `font-family: var(--font-mono)`, small font size (~10px)
- `overflow: hidden`, `pointer-events: none`, `z-index: 0`
- All other content at `z-index: 1+`
- The art is static, decorative, low contrast — reads as texture

## 3. Glassmorphism

All panels get frosted glass treatment:

```css
background: rgba(255, 255, 255, 0.80);
backdrop-filter: blur(16px);
-webkit-backdrop-filter: blur(16px);
border: 1px solid rgba(168, 160, 160, 0.25);
box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
```

Affected components:
- Status strip (header)
- Chat bubbles (user + assistant)
- Stream cards (specialist, thinking, response)
- Specialist card
- Response panel
- Reflection bar
- Validation card
- Input island
- Preview panel

## 4. Input Island

Transform input from bottom-docked bar to floating island:
- Detached from bottom with padding (~20px from bottom edge)
- `max-width: 680px; margin: 0 auto`
- `border-radius: 28px` (large pill)
- Stronger glass: `rgba(255, 255, 255, 0.85)`, `blur(20px)`
- Wider shadow: `0 8px 32px rgba(0, 0, 0, 0.08)`
- Focus ring: greige glow `0 0 0 3px rgba(168, 160, 160, 0.2)`
- Send button: greige background instead of blue

## 5. Preview Panel Sandbox Fix

Current: `sandbox="allow-scripts allow-same-origin"` — security risk, iframe can escape sandbox.
Fix: `sandbox="allow-scripts"` — scripts run but cannot access parent origin.

## Files to Modify

1. `src/app.css` — palette, glass variables, ASCII background keyframes
2. `src/routes/+layout.svelte` — ASCII art layer, glass header
3. `src/routes/+page.svelte` — glass bubbles, glass stream cards, glass validation
4. `src/lib/components/ChatInput.svelte` — floating island style
5. `src/lib/components/PreviewPanel.svelte` — sandbox fix, glass style
6. `src/lib/components/ResponsePanel.svelte` — glass style
7. `src/lib/components/SpecialistCard.svelte` — glass style
8. `src/lib/components/ReflectionBar.svelte` — glass style
9. `src/lib/components/SplitPane.svelte` — glass divider
