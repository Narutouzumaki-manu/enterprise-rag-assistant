# UI/UX Notes
## Module: Evaluation, Frontend & DevOps/QA
### Owner: Member 5 — Evaluation, Frontend & DevOps/QA Lead
### Project: Enterprise RAG Assistant
### Version: v0.2 (written after Members 1 to 4 were built, October 2026; supersedes the September v0.1)

> **Status.** A design for the screens, written from the real API behaviour. The frontend is not built yet, so nothing here has been seen on screen. Wording in quotes is the exact text the backend sends (do not rewrite it); wording marked "suggested" is the UI's own.

---

## 0. What changed from v0.1

| # | Change | Section |
|---|---|---|
| 1 | Pages reduced to Login, Chat (with the session list) and Documents; History merged into the chat sidebar; Evaluation and Admin dropped from the first version | 2 |
| 2 | The steps panel shows the agent's real wording; there is no "reranked" or "candidates" count | 3 |
| 3 | Waiting is long (26 s to 147 s to the first word, measured) and the answer streams after verification | 3 |
| 4 | Answer states listed with their exact texts, including refusals and failures | 4 |
| 5 | Trust display: status only, never confidence | 5 |
| 6 | Citations: excerpts, `source_file`, no `section_title` | 6 |
| 7 | Document statuses match the built backend (`indexing` added, `ocr_fallback` does not occur) | 7 |
| 8 | New: sign-in expiry, rate limits, busy and unavailable states, feedback | 8, 9 |
| 9 | Accessibility and responsiveness made concrete | 10 |

---

## 1. Scope Note

This module owns the end-user interface. Everything the other modules built becomes real only through it. Two principles run through every screen: the system shows its work, and an answer is never presented as more trustworthy than it is.

---

## 2. Pages

| Page | Purpose |
|---|---|
| `/login` | Email and password; error under the form; back to the page the user came from |
| `/chat`, `/chat/:sessionId` | The main screen: sessions list on the left, conversation, question box |
| `/documents` | Upload area, per-file progress, list with statuses and delete |
| `/evaluation` (later, internal) | Scores and the baseline table, for the team and interviews; not in the first version |

The sessions list sorts by last update (do not rely on the server's order). A session title is the first question, shortened, and may be missing: show "New conversation".

---

## 3. The Chat Screen

```
+------------------+----------------------------------------------+
| Sessions         |  You: What was the closing headcount in Q2?   |
|  + New           |                                                |
|  Headcount Q2    |  Steps                                         |
|  Revenue by...   |   [done] Classified as simple; 1 sub-query    |
|                  |   [done] Retrieved 8 passages across 1 ...    |
|                  |   [done] Draft answer generated with 1 ...    |
|                  |   [now ] Checking the answer...               |
|                  |                                                |
|                  |  Answer  (badge: Found in your documents)     |
|                  |  593,314                                       |
|                  |                                                |
|                  |  Sources                                       |
|                  |   [TCS_Annual_Report.pdf, p. 28] "...Closing  |
|                  |    headcount: 593,314; Change in quarter..."  |
|                  |                                                |
|                  |  [helpful] [not helpful]                       |
|                  |  +------------------------------------------+ |
|                  |  | Ask a question                      [Send]| |
+------------------+----------------------------------------------+
```

- **Steps list (progressive).** One line per `status` event, as it arrives, using the agent's own text (examples: "Classified as multi-hop; 3 sub-queries", "Retrieved 18 passages across 3 sub-queries", "3 of 4 claims verified; searching again for 1 unsupported claim", "No new passages found; finalising with the best available answer"). The last line is marked in progress. Do not invent counts the API does not send
- **A retry is shown honestly** ("searching again") with a caution icon: a visible self-correction builds trust. It is not an error
- **Waiting.** The answer is checked before it is shown, so the first word can take 30 s to over 2 minutes (measured: 26 s, 34 s, 147 s), and a single step can take 12 to 36 s with no event. Show the elapsed time and a plain note ("Checking the answer before showing it"). Never an empty or infinite spinner. Allow "Stop waiting": the server still finishes and the answer will be in the history
- **After the answer arrives,** collapse the steps to "N steps" (expandable; the saved trace is available from the session). Do not show raw prompts, internal counters or error details
- **Rating** appears once the answer is saved (after `done` the UI reloads the session to get the message id). A second click replaces the first. An optional comment of up to 1000 characters
- **Long conversations:** load the saved messages from the session on open; only the newest answer streams

---

## 4. Answer States (each distinct, exact texts)

| Situation | Text shown | Status | Treatment |
|---|---|---|---|
| Found and supported | The answer, with sources | `verified` | Normal, with "Found in your documents" |
| Some parts unsupported | The answer, followed by "Could not be verified in the documents:" and the list | `partially_verified` or `verified` | Amber caution; keep the list as the server wrote it |
| Nothing supports an answer | "I don't have sufficient evidence in the provided documents." (no sources) | `unverified` | A calm, honest answer, not an error; offer to rephrase or upload more documents |
| The search failed | "I couldn't search the documents right now. Please try again." | `unverified` | "Try again" button (resends the same question) |
| The model failed | "I couldn't write an answer right now. Please try again." | `unverified` | "Try again" button |
| The check failed | The draft, marked unverified | `unverified` | Strong warning |
| Blank or too long question | "Query must not be blank." or "Query is too long (maximum 2000 characters)." | (a 422 before the stream) | Inline message under the input |
| No free slot | "The service is busy. Please try again shortly." | (503 `AGENT_BUSY`) | Retry with countdown |
| Too many requests | "Too many requests. Please wait a moment and try again." | (429) | Retry with countdown |
| Connection lost or stream ended without `done` | Suggested: "The connection was lost." | | Keep the question; retry |

Short answers, even a single number, are normal.

---

## 5. Trust Display (critical, not cosmetic)

| Status | Treatment |
|---|---|
| `verified` | Neutral or green badge, suggested "Found in your documents" |
| `partially_verified` | Amber caution banner, suggested "Some parts of this answer could not be fully verified" |
| `unverified` | Red or strong warning treatment; never the same look as `verified` |

- **Never show `confidence`.** It only took the values 0.95 (every verified answer) and 0 (every unverified one), so it carries nothing the status does not
- **"Verified" means found in the retrieved passages, not that the document is true.** Use "found in your documents". Never "correct", "accurate" or "guaranteed"
- Do not rely on colour alone: use an icon and text as well

---

## 6. Citations

- Show `source_file` and `page_number` ("TCS_Annual_Report.pdf, p. 28"). If `source_file` is missing (the document was deleted), show "Document no longer available". The API sends no `section_title`
- `text_snippet` is an excerpt of at most 200 characters; it may start with "..." and is not the whole passage. Present it as a quotation preview and offer a way to see more of the source if one exists
- Cards are keyboard-reachable; the list is in the order the server sends it

---

## 7. Documents Page

| Status | Text |
|---|---|
| `queued` | "Waiting to be processed..." |
| `parsing` | "Reading document..." |
| `indexing` | "Making it searchable..." |
| `success` | "Ready" |
| `partial` | "Partly processed: some pages could not be read" |
| `failed` | "Upload failed: " followed by the server's `error_message` |
| `duplicate` (upload response only) | "This document was already uploaded" |

- `ocr_fallback` does not occur yet (no OCR). A scanned PDF ends `failed` with an explanatory message; show it as is. Pictures embedded in DOCX files are ignored silently, so a DOCX that is mostly pictures may look empty
- After a server restart a document that was in progress becomes `failed` with "Processing was interrupted by a server restart. Please upload the file again.": show it, and let the user upload again
- Several files at once, each with its own progress bar and status: one failure never blocks the others. Check type (PDF, DOCX, CSV) and size (25 MB) before sending, with a clear message; the server also answers 415 and 413
- Poll while any document is in progress (about every 2 seconds), and stop when all are final
- **Delete** is shown only for the user's own documents (`uploaded_by_me`), with a confirmation. Possible answers: `409` ("still being processed"), `403`, `503` ("could not be removed from the search index": offer retry)
- All signed-in users search the same documents in this version; say so near the upload area

---

## 8. Sign-in, Limits and Outages

- **The token lasts one hour with no refresh.** A 401 means "log in again": go to the login page with a short message and return to the same place afterwards. Do not show an error screen
- **429 and `AGENT_BUSY`:** friendly message and a retry with the `Retry-After` countdown. The limits are 5 login attempts a minute, 10 questions a minute and 10 uploads an hour (starting values)
- **`DEPENDENCY_UNAVAILABLE` or an unreachable server:** a full-page "Service temporarily unavailable" with a retry button; never a blank screen or a console-only error
- Show the request id (the `X-Request-ID` response header) in a small "details" line on error screens so a problem can be traced in the server logs; it may be missing on a 500
- Never show raw status text or stack traces (the backend sends none)

---

## 9. Empty States

- **No documents yet:** the chat screen says "Upload a document first" with a link to Documents
- **A new session:** two or three example questions to click
- **No sessions:** only "New conversation"
- **No sources:** a refusal has none; show nothing, not an empty box

---

## 10. Accessibility and Responsiveness

- Everything reachable and operable by keyboard; visible focus; a label on every input and button
- The streaming answer in an `aria-live="polite"` region; announce the finished answer once, not every word
- Trust levels with icon plus text plus colour; sufficient contrast; dark mode via `prefers-color-scheme`
- Usable at 360 px wide (the sessions list becomes a drawer) and on a laptop
- Citation cards and rating buttons keyboard-navigable

---

## 11. Evaluation Dashboard (later, internal)

If built, it shows the current scores (Faithfulness, Answer Relevancy, Context Precision, Context Recall), the baseline tables, and **for every number the models used, the number of questions, and the limits** (one document, a small set, tuned labels). It is a team and interview tool and is hidden behind a separate route.

---

## 12. Out of Scope for This Document

- The API contract: `docs/MEMBER4_CONTRACT_NOTES_FOR_MEMBER5.md`
- What counts as "verified": Member 3's fact-checker
- Which metadata exists: Members 1 and 2
- Building the screens with an AI tool: `docs/FRONTEND_BUILD_PROMPT.md` (the nine-point acceptance checklist applies to either route)
