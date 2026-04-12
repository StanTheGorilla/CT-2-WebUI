# STATE — CT-2 WebUI

## ✅ Done (2026-04-12)

| Item | Notes |
| --- | --- |
| Web search integration | DuckDuckGo via `ddgs`, globe toggle, search results card |
| LLM query extraction | `Engine.extract_search_query` with conversation history context |
| URL fetcher hardening | Browser headers, 20s timeout, typed error messages |
| UI redesign — composer | Tool-pill row below mode-bar; stop button box-sizing fix |
| URL double-fetch bug | URL scanner now reads original `goal`, not post-injection `actual_goal` |
| Context loss across turns | `recent_history[-6:]` passed to query extractor |
| Raw content leaking | Context wrapped with "Do NOT reproduce verbatim" + `--- END ---` footer |
| Garbled characters | Regex strips non-printable / replacement chars before injection |
| Domain prioritization | Skip-list (TikTok, Instagram, Pinterest…); priority-list (Wikipedia, BBC…) |
| Fetch/search count match | All non-skip-listed results fetched, priority domains first; 24k chars each |
| UI scale | `zoom: 0.8` on `html` in `app.css` |

## Validation
- `python -m pytest ct1/tests/test_web_fetcher.py -q` → 20 passed, 1 skipped
- `npm run check` → 0 errors, 0 warnings (179 files)

## Next
- Rebuild frontend (`npm run build`) and restart backend to pick up all 2026-04-12 changes.
- Verify web search end-to-end: pronoun resolution, domain prioritization, no raw content leakage.
- Archive older entries → `CONTEXT/ARCHIVE/2026-04-10.md` ✅
