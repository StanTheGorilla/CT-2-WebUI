# RULES — CT-2 WebUI

## UI / Frontend
- **Target audience**: non-technical users — no AI jargon without explanation
- **Polish standard**: Apple/NVIDIA-level — spacious, clear hierarchy, no cramped layouts
- **Settings UI**: show both friendly label AND technical param name together
- **Scale**: `zoom: 0.8` on `html` (set 2026-04-12); do not remove without user confirmation
- **SvelteKit 5 patterns**: runes (`$state`, `$derived`, `$effect`) in `.svelte`; writable stores in `.ts`; use `$effect` guard flags to avoid re-entrant UI state

## Web Search
- Web search toggle is always visible (composer toolbar outside workspace guard)
- Query extraction uses conversation history to resolve pronouns
- Domain skip-list blocks fetch on: TikTok, Instagram, Facebook, Twitter/X, Pinterest, LinkedIn
- Snippets from skip-listed domains still appear in the search results card
- Context injection format: `--- WEB SEARCH CONTEXT ---` / `--- END WEB SEARCH CONTEXT ---` with "Do NOT reproduce verbatim" instruction

## Git / Deployment
- **Never push** without explicit "push" instruction from Stan
- All commits stay local until approved
- Test commands: `python -m pytest ct1/tests/ tests/ -q --ignore=ct1/tests/test_evolution.py`

## Backend
- `extract_search_query` must receive `recent_history` for pronoun resolution
- URL scanner must read from original `goal`, not post-injection `actual_goal`
- Fetched content must be cleaned (strip `\ufffd` and non-printable chars) before context injection
