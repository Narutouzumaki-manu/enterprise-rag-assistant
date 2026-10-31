# QA Test Report: Enterprise RAG Assistant

**Tested Date:** 2026-10-31  
**Target Environment:** Local (`http://127.0.0.1:8000` via mock server, `http://localhost:5173` via Vite dev proxy)  
**Authentication Note:** Login with `manu@examaple` and `manu@example` failed (HTTP 401 Unauthorized, "Incorrect email or password"). Login with `manu@example.com` / `manu2006` succeeded. Document `d:\testfiles\a_sales.csv` uploaded and active.

---

## Test Results

| # | Pass / Fail / Not testable | Notes |
|---|---|---|
| 1 | Pass | Events arrived one by one over ~8 s (chunks at +1639ms, +3237ms, +4838ms, +6439ms, +8061ms). Content Download was 6423 ms; 5 distinct arrival times. No proxy buffering. |
| 2 | Pass | Badge: "Found in your documents". Steps progressed live with spinner, timer, and note. Answer streamed word by word. Sources displayed excerpt. 0 occurrences of "0.9", "%", or "confidence". |
| 3 | Pass | 0 red console errors after clicking "Stop waiting". Waited 10 s and pressed F5: saved user question and answer loaded from database. |
| 4 | Pass | Exactly 2 POST `/feedback` requests fired. Thumbs buttons enabled within ~1.2 s. UI shows only thumbs down active (`text-rose-600 bg-rose-50`). |
| 5 | Pass | Still logged in on `/chat/<id>` after F5. Messages and sources reloaded cleanly; empty-state example questions never flashed or appeared. |
| 6 | Pass | Navigating to `/chat/does-not-exist` (422) or `/chat/<unknown-uuid>` (404) immediately redirects to a clean `/chat` via replace with no error screen, displaying starter example questions. |
| 7 | Pass | Clicking example question filled `#chat-query-input` immediately. 0 network requests fired to `/chat/stream` until Send was clicked. |
| 8 | Pass | When backend was stopped, asking a question displayed "Connection lost. Please check your connection and try again." with "Retry" button (no blank screen, no endless spinner). Question was preserved in input box. After restarting backend on 8000, clicking "Retry" resent the question and streamed the answer. |
| 9 | Pass | Tested with temporary settings (agent_max_concurrent=1, agent_wait_seconds=1.0s). Tab 1 acquired sole slot; Tab 2 sent within 1.5s and was rejected with HTTP 503 AGENT_BUSY ("The service is busy. Please try again shortly.", Retry-After: 5). Tab 2 showed inline busy notice, countdown, and question preserved in input box. After Tab 1 finished and countdown expired, clicking "Try again" in Tab 2 resent the question and streamed answer normally. Config verified reverted cleanly (git diff clean). |
| 10 | Pass | Steps panel remained visible and updated live through URL change from `/chat` to `/chat/<new-id>`. Answer streamed progressively. |
| 11 | Pass | Conversation B finished with only B's steps and answer; no tokens or questions from A leaked into B. Reloading A showed A's own saved answer. |
| 12 | Pass | Exactly 1 assistant response article and 1 match for "Mock answer." on screen (match count: 1). |
| 13 | Pass | Landed on `/login?from=...&expired=1` with notice "Your session expired. Please log in again." Session Storage `rag_token` was cleared. Logging in returned to the original conversation page. |

---

## Attachments

### Check 6 Note
Check 6 previously failed because FastAPI returned 422 for non-UUID session IDs while the frontend only redirected on 404. Both 404 and 422 are now treated as "conversation not found" and redirect to `/chat` (replace: true). Re-tested and verified PASS.

