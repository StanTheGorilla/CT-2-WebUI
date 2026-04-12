# STATE — CT-2 WebUI

## ✅ Done (2026-04-12)

| Item | Notes |
| --- | --- |
| Web search integration | DuckDuckGo via `ddgs`, globe toggle, search results card |
| LLM query extraction | `Engine.extract_search_query` with conversation history context |
| URL fetcher hardening | Browser headers, 20s timeout, typed error messages |
| URL double-fetch bug | URL scanner reads original `goal`, not post-injection `actual_goal` |
| Context loss across turns | `recent_history[-6:]` passed to query extractor |
| Raw content leaking | Context wrapped with "Do NOT reproduce verbatim" + `--- END ---` footer |
| Garbled characters | Regex strips non-printable / replacement chars before injection |
| Domain prioritization | Skip-list (TikTok, Instagram…); priority-list expanded with news sources |
| Search accuracy — current events | Date injected into query-extraction prompt; year appended for news queries |
| Search timestamp in context | `format_results_as_context` stamps search date/time so model knows freshness |
| max_results 5 → 8 | More results improves breaking-news coverage |
| UI scale | `zoom: 0.8` on `body` (125vw×125vh) in `app.css` |
| Donut background | `position: absolute` on `.donut-bg`; capped at 120×60 chars |
| Text rendering | Removed `-webkit-font-smoothing` to restore Windows ClearType |
| Restart button persists | `updateStatus = {}` clears it after successful server restart |
| Web search toggle design | Globe circle button inside island-actions (right side) |
| Web search toggle visibility | Off state: surface bg + border-strong border at 75% opacity (was 35% transparent) |

## Validation
- `python -m pytest ct1/tests/ tests/ -q --ignore=ct1/tests/test_evolution.py`
- `npm run check` → 0 errors (179 files)

## Next
- Rebuild frontend (`npm run build`) and restart backend to pick up all changes.
- Verify web search end-to-end with current events query (e.g. Iran/Israel/USA war).
