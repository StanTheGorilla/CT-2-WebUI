# DECISIONS — CT-2 WebUI

## 2026-04-12 — Web Search

| Decision | Why |
| --- | --- |
| `ddgs` package (renamed from `duckduckgo-search`) | Free, no API key, no hard rate limits |
| DDGS runs in `asyncio.to_thread` | v9 is sync-only; avoids blocking the event loop |
| `!search ` prefix OR `web_search: true` WS flag | Prefix works with voice input; flag drives the UI toggle |
| Search results stored on Turn | Keeps conversation history complete |
| LLM query extraction (`extract_search_query`) | Full sentences make poor DDG queries; 3-8 keywords are better |
| `recent_history[-6:]` passed to query extractor | Resolves pronouns ("his", "it") against prior turns |
| URL scanner reads original `goal`, not `actual_goal` | Prevents double-fetching URLs that appear only in injected search snippets |
| Context block framed with "Do NOT reproduce verbatim" | Prevents local models from dumping raw fetched content as their reply |
| Non-printable chars stripped from fetched content | Removes `\ufffd` / garbled bytes before injection |
| Domain skip-list (TikTok, Instagram, Pinterest, FB…) | These sites have login walls or no extractable text; snippets still shown |
| Domain priority-list (Wikipedia, BBC, Reuters…) | Content-rich pages fetched first to maximise useful context |
| 24k chars per fetched page | 12k was too shallow for real articles; 24k covers most full-length pages |
| `zoom: 0.8` on `html` | User requested 80% UI scale; zoom scales all px values uniformly |
| Composer toolbar outside workspace-session guard | Tool toggles visible in both chat and workspace modes |
| Stop button `box-sizing: border-box` + transparent border | Prevents 2px layout shift when toggling between send and stop states |

## 2026-04-10 — (archived → CONTEXT/ARCHIVE/2026-04-10.md)
