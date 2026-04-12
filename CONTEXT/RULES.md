# RULES — CT-2 WebUI

## UI / Frontend
- **Target audience**: non-technical users — no AI jargon without explanation
- **Polish standard**: Apple/NVIDIA-level — spacious, clear hierarchy, no cramped layouts
- **Settings UI**: show both friendly label AND technical param name together
- **Scale**: `zoom: 0.8` on `body` with `width: 125vw; height: 125vh` in `app.css`; do not remove without user confirmation
- **SvelteKit 5 patterns**: runes (`$state`, `$derived`, `$effect`) in `.svelte`; writable stores in `.ts`; use `$effect` guard flags to avoid re-entrant UI state
- **Text rendering**: no `-webkit-font-smoothing: antialiased` — lets Windows ClearType work
- **Donut background**: `position: absolute` (not `fixed`) on `.donut-bg`; grid capped at 120×60

## Web Search
- Web search toggle is a circle button inside `.island-actions` (right of input)
- Off state: `background: var(--surface)`, `border: 1.5px solid var(--border-strong)`, `opacity: 0.75`
- On state: solid blue `#3b82f6`, white icon, glow ring
- Query extraction injects today's date + instructs year-append for current-events queries
- `format_results_as_context` stamps search datetime so model knows result freshness
- `max_results=8` for better breaking-news coverage
- Domain skip-list blocks fetch on: TikTok, Instagram, Facebook, Twitter/X, Pinterest, LinkedIn, Reddit
- Snippets from skip-listed domains still appear in the search results card
- Priority domains (fetched first): wire services (Reuters, AP, AFP), broadcasters (BBC, Al Jazeera, CNN, NBC, ABC, CBS, NPR), newspapers (Guardian, NYT, WaPo, WSJ, FT, Politico, Axios), Middle East (Haaretz, Times of Israel, Jerusalem Post, Middle East Eye)

## Git / Deployment
- **Never push** without explicit "push" instruction from Stan
- All commits stay local until approved
- Test commands: `python -m pytest ct1/tests/ tests/ -q --ignore=ct1/tests/test_evolution.py`
- `active_model: null` in `model_config.yaml` — do not commit personal model paths

## Backend
- `extract_search_query` must receive `recent_history` for pronoun resolution
- URL scanner must read from original `goal`, not post-injection `actual_goal`
- Fetched content must be cleaned (strip `\ufffd` and non-printable chars) before context injection
- Context injection format: `--- WEB SEARCH CONTEXT ---` / `--- END WEB SEARCH CONTEXT ---`
