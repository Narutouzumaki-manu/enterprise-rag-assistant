# UI/UX Notes
## Module: Backend / API (FastAPI + Infra)
### Owner: Member 4 — Backend / API Engineer
### Project: Enterprise RAG Assistant
### Date: September 2026

---

## 1. Scope Note

This module has no visual interface itself, but unlike the earlier modules, **it is the entire contract Member 5's frontend builds against** — every button, loading state, and error message in the UI is only as good as what this module exposes. This document is really about *API ergonomics as UX* — designing responses that make it easy for Member 5 to build a good experience.

---

## 2. Developer-Facing Interface (the actual "UX" for Member 5)

Member 5 interacts with this module purely through HTTP/SSE:

```
POST /documents/upload        -> 202 Accepted, {document_id, status: "queued"}
GET  /documents                -> [{document_id, filename, status, ...}]
DELETE /documents/{id}         -> 204 No Content
POST /chat                     -> ChatResponse (blocking, for simple integrations/testing)
POST /chat/stream               -> SSE stream (status/source/token/verification/done)
GET  /sessions                  -> [{session_id, created_at, ...}]
GET  /sessions/{id}             -> full session with message history
GET  /health                    -> {status: "ok" | "degraded", checks: {...}}
```

Design principles:
- **Predictable status codes**: `202` for accepted-but-processing, `200` for success, `4xx` for client error, `503` for degraded dependency — never a generic `500` with no explanation
- **Every error response is structured**: `{"error": "human readable message", "code": "SOME_ERROR_CODE"}` — never a raw stack trace
- **Polling-friendly**: `GET /documents` always reflects current status, so Member 5 can poll it for upload progress without needing websockets

---

## 3. Status Signals Exposed to the Frontend

Directly relaying Member 1's ingestion states (see Member 1's UI/UX doc) plus this module's own layer:

| Status | Meaning | Suggested frontend treatment |
|---|---|---|
| `202` on upload | Accepted, processing started | Show spinner immediately, don't block the UI |
| `queued` / `parsing` / `ocr_fallback` / `success` / `partial` / `failed` / `duplicate` | Relayed from Member 1 via `GET /documents` or SSE `status` events | See Member 1's UI/UX doc for suggested treatments |
| SSE `status: "retrieving"` | Agent is searching for evidence | "Searching documents..." |
| SSE `status: "reranking"` | Agent is refining results | "Refining results..." |
| SSE `verification: "verified"` / `"partially_verified"` / `"unverified"` | Final answer's trust level | Confident display / caution icon / warning banner respectively |
| `503` from `/health` or any endpoint | A dependency (Redis/Postgres) is down | Show a clear "service temporarily unavailable" state, not a blank screen or console error |

---

## 4. Recommended UX Behaviors (for Member 5 to consider)

- Treat `202 Accepted` on upload as the start of a *process*, not a completed action — show ongoing status, don't just say "Uploaded!" and stop
- SSE disconnects should be handled gracefully client-side — reconnect or show "connection lost, retrying..." rather than a silent hang
- Never surface raw error codes/stack traces from a `5xx` response directly to the user — this module guarantees a human-readable `error` message specifically so Member 5 doesn't have to translate technical errors itself
- For `/chat/stream`, render tokens as they arrive (true streaming feel) rather than buffering the whole response before displaying anything

---

## 5. What This Module Guarantees (so Member 5 doesn't have to defend against it)

- Every endpoint returns a Pydantic-validated, typed response — no unexpected missing fields
- Authentication failures are always `401`, never silently return empty/wrong data
- A slow or failed LLM/agent call still results in a graceful SSE `done` event or clear error — the stream never just hangs forever with no signal

---

## 6. Out of Scope for This Module

- Actual chat UI, upload widget, citation rendering, agent trace visualization — Member 5
- Deciding retrieval ranking or agent reasoning — Members 2 and 3
- Deciding chunk/section/table extraction logic — Member 1
