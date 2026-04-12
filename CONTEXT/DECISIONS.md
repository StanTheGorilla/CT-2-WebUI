# DECISIONS — CT-2 WebUI

## 2026-04-12 — Web Search (continued)

| Decision | Why |
| --- | --- |
| `ddgs` package (renamed from `duckduckgo-search`) | Free, no API key, no hard rate limits |
| DDGS runs in `asyncio.to_thread` | v9 is sync-only; avoids blocking the event loop |
| `!search ` prefix OR `web_search: true` WS flag | Prefix works with voice input; flag drives the UI toggle |
| LLM query extraction (`extract_search_query`) | Full sentences make poor DDG queries; 3-8 keywords are better |
| `recent_history[-6:]` passed to query extractor | Resolves pronouns ("his", "it") against prior turns |
| Today's date injected into query-extraction system prompt | LLM appends current year for news/current-events queries |
| Search timestamp in `format_results_as_context` header | Model knows how fresh results are; can say "as of today" accurately |
| `max_results=8` | 5 was too few for breaking news with many sources covering same event |
| Expanded priority domain list | Added Al Jazeera, AP, AFP, CNN, NBC, ABC, CBS, NPR, Politico, Axios, WSJ, FT, Middle East sources |
| URL scanner reads original `goal`, not `actual_goal` | Prevents double-fetching URLs that appear only in injected search snippets |
| Context block framed with "Do NOT reproduce verbatim" | Prevents local models from dumping raw fetched content as their reply |
| Non-printable chars stripped from fetched content | Removes `\ufffd` / garbled bytes before injection |
| 24k chars per fetched page | 12k was too shallow; 24k covers most full-length articles |
| Domain skip-list (TikTok, Instagram, Pinterest, FB…) | Login walls / JS-only; snippets still shown |
| Domain priority-list (Wikipedia, BBC, Reuters…) | Content-rich pages fetched first |

## 2026-04-12 — UI

| Decision | Why |
| --- | --- |
| `zoom: 0.8` on `body` with `125vw×125vh` | User requested 80% scale; zoom on body (not html) fills viewport correctly |
| `position: absolute` on `.donut-bg` | `position: fixed` escapes body zoom containing block → misplaced donut |
| Remove `-webkit-font-smoothing: antialiased` | Disabled Windows ClearType, causing pixelation |
| Web search toggle: circle button in island-actions | Cleaner than toolbar pill; always visible; on = solid blue, off = surface+border |
| Off-state opacity 75% + surface bg + border | Was 35%/transparent → barely visible in dark mode |

## 2026-04-10 — (archived → CONTEXT/ARCHIVE/2026-04-10.md)
