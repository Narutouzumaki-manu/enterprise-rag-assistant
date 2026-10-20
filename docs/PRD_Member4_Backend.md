# Product Requirements Document (PRD)
## Module: Backend / API (FastAPI + Infra)
### Owner: Member 4 — Backend / API Engineer
### Project: Enterprise RAG Assistant
### Version: v0.2 (Session 21 preparation, October 2026; supersedes the September v0.1)

> **Status of this document.** The backend is not built yet. Every number below is a **target or a starting value** unless it is marked "measured". Measured numbers come from Member 2's and Member 3's evaluations (one 118-chunk document, 10 to 17 questions, one free model) and are signs, not rates.

---

## 0. What changed from v0.1

v0.1 was written before Members 1 to 3 finished. Their hand-offs (`MEMBER3_HANDOFF.md`, `MEMBER4_5_HANDOFF.md`, `MEMBER3_DECISIONS.md`, `MEMBER2_DECISIONS.md`) change what this module must do.

| # | Change | Why |
|---|---|---|
| 1 | The agent and the retriever are built **once at startup**; agent calls are synchronous and run in a thread (FR 12, 13) | Model loading takes seconds; `run()` blocks for 12 to 36 s per model call and would stall every other request in an async server |
| 2 | Streaming sends the agent's trace steps live, then streams the **final, verified answer** word by word (FR 7) | The agent does not stream model tokens; the answer exists only after verification, so a retry never shows text that is later retracted |
| 3 | New: a **concurrency cap** with a busy response (FR 13) | One question is 3 to 7 sequential model calls on a rate-limited free model |
| 4 | New: a rate-limited or failed model is a **normal `unverified` response**, not a server error (FR 14) | The agent never raises; it returns "I couldn't write an answer right now. Please try again." |
| 5 | `ChatResponse` gains `verification_status`; citations gain `source_file` (FR 6) | The UI must show the trust level and "[Finance Report, p.12]"; both gaps were agreed in the team sync |
| 6 | Ingestion requirements rewritten: OCR is not built, the duplicate registry must be persisted, and document ids are derived from the filename (FR 2, 3; Risks) | See Member 1's checklist and PRD Section 8 |
| 7 | New document state `indexing`; deletion also removes chunks from the retrieval index (FR 3, 5) | A document is only usable once it is searchable |
| 8 | MVP runs **one API replica** with the vector index embedded in the process | Member 2's retriever uses a local ChromaDB directory, not a server |
| 9 | Documents are one **shared corpus** for all signed-in users in the MVP (Non-goals, Risks) | The agent sends no retrieval filters |
| 10 | New: a `feedback` table and a `GET /documents/{id}` endpoint (FR 4, 11) | `POST /feedback` existed in v0.1 without any storage |
| 11 | Success metrics reworded as targets (Section 7) | Nothing in this module has been measured |

---

## 1. Purpose

The Backend module is the "nervous system" of the project: every other module's work reaches a client only through the API this module builds. It exposes document upload, chat and streaming, authentication, history and health endpoints, and owns the persistence layer (Postgres for durable data, Redis for rate limiting and short-lived state).

If this module is unreliable, none of the other members' work is reachable by an end user.

---

## 2. Problem Statement

The modules below this one are finished libraries. Without this layer they remain scripts:
- Documents must be uploaded, checked for duplicates, processed in the background and made searchable, with a visible status at every step
- Answers take a long time (measured on 10 golden questions: 22 to 158 seconds per question, 12 to 36 seconds per model call, 3 to 7 calls per question), so the API must stream progress and must not block other requests while a question runs
- The free model is rate-limited (about 20 requests a minute, about 50 a day), so concurrency must be capped and a rate-limited answer must degrade gracefully
- Chat history, citations and agent traces must be stored, because the UI re-renders past answers
- Basic security and observability are expected: authentication, upload validation, rate limiting, structured logs, health checks

---

## 3. Goals

| Goal | Description |
|---|---|
| G1 | Async FastAPI endpoints for upload, document listing and deletion, chat (blocking and streaming), sessions, feedback, auth and health |
| G2 | Stream trace steps as they happen, then the verified answer, citations and trust level, over Server-Sent Events (SSE) |
| G3 | Persist documents, chunk metadata, sessions, messages, citations, agent traces, feedback and audit events in PostgreSQL |
| G4 | Use Redis for rate limiting and short-lived job status, degrading gracefully when it is unavailable |
| G5 | Process uploads in the background (ingest, then index) so the request returns immediately |
| G6 | Build the retriever and the agent once, run the agent off the event loop, and cap concurrent agent runs |
| G7 | Authenticate users with JWT and never store plaintext passwords |
| G8 | Never leak raw stack traces: every error is structured and human-readable |
| G9 | Make every stream end with a `done` or `error` event, never a silent hang |
| G10 | `docker compose up` runs the whole system with no manual steps |

---

## 4. Non-Goals

- Parsing, chunking, retrieval ranking, agent reasoning or fact-checking: this module only calls Members 1, 2 and 3
- Any user interface: this module serves JSON and SSE to Member 5
- Per-user document visibility: the agent sends no retrieval filters, so all signed-in users search the same corpus (see Risks)
- Cancelling a running agent: the agent cannot be cancelled mid-run
- Horizontal scaling in the MVP (see Risks)
- OCR for scanned PDFs: not built in Member 1's module

---

## 5. Users of This Module

| User | How they use it |
|---|---|
| Member 1 (Ingestion) | `ingest_document()` is called from this module's background task; this module persists its `IngestionResult` |
| Member 2 (Retrieval) | `index_chunks()` and `delete_document()` are called from the upload and delete flows; `retrieve()` is called indirectly by the agent |
| Member 3 (Agents) | `build_agent()` at startup; `run()` and `run_streaming()` from the chat endpoints |
| Member 5 (Frontend / Eval) | The only consumer of the REST and SSE API; also runs E2E tests against it |
| End users (indirect) | Interact with the whole system through this module |

---

## 6. Functional Requirements

1. **`POST /documents/upload`**: multipart; accepts only PDF, DOCX and CSV within a configurable size limit; stores the file under a generated name (never the client's filename); returns `202 Accepted` with `{document_id, status: "queued"}`
2. **Duplicates**: compute SHA-256 of the file bytes; if a non-deleted document with the same hash exists, return `200` with that document and status `duplicate`; do not reprocess. The duplicate lookup uses the `documents.content_hash` column, because Member 1's in-memory registry does not survive a restart
3. **Background ingestion**: call Member 1's `ingest_document()`, persist the `IngestionResult`, set status `indexing`, call Member 2's `index_chunks()`, then set the final status (`success`, `partial`) or `failed` with a readable `error_message`. A failure in indexing is `failed`, not `success`
4. **`GET /documents`** and **`GET /documents/{id}`**: list or fetch documents with their current status and `error_message`; safe to poll
5. **`DELETE /documents/{id}`**: remove the document's chunks from Member 2's index (`delete_document`), then soft-delete the document row; returns `204`
6. **`POST /chat`** (blocking): returns a `ChatResponse` with `answer`, `citations` (each with `source_file`), `verification_status`, `confidence` and `latency_ms`
7. **`POST /chat/stream`** (SSE): emits `status` events as trace steps finish, then `source` (one per citation), `token` (the final answer word by word), `verification`, and `done`. A failure ends the stream with an `error` event
8. **`GET /sessions`** and **`GET /sessions/{id}`**: list sessions and return a session's messages with citations and agent traces; only the owner can read a session
9. **`POST /auth/login`**: issues a JWT (claims `sub`, `exp`, `iat` only). Every endpoint except `/auth/login` and `/health` requires it
10. **`GET /health`**: liveness plus a per-dependency `checks` map (Postgres, Redis, retriever with embedding model and chunk count)
11. **`POST /feedback`**: stores a rating and optional comment for a message
12. **Startup**: build the retriever once (`build_default_retriever(persist_path=...)`) and the agent once (`build_agent(...)`); if the retriever refuses the saved index (different embedding model), fail fast with a clear message instead of serving
13. **Agent execution**: run the agent off the event loop (a thread), cap concurrent runs per process (starting value 2), and when the cap is full wait up to a configurable time, then return `503` with code `AGENT_BUSY` and a `Retry-After` header
14. **Model failure is a normal answer**: when the agent returns an `unverified` response because the model was rate-limited or failed, return `200`, store it, and stream it like any other answer. Do not turn it into a 5xx
15. **Streaming reliability**: an SSE comment heartbeat about every 15 seconds, a total stream limit of at least 5 minutes, disconnect detection, and always a final `done` or `error`
16. **Validation**: `ChatRequest.top_k` between 1 and 20 (the agent clamps to the same range); a non-blank `query` up to a configurable maximum length; blank queries get `422` before the agent is called
17. **Errors**: every error response is `{"error": "<human readable>", "code": "<SOME_CODE>"}`; never a stack trace
18. **Observability**: structured logs with a request id on every line; an `audit_events` row for uploads, queries and authentication failures; no passwords, tokens or API keys in logs
19. **Security**: Argon2 or bcrypt password hashing; upload validation (type, size, path traversal); rate limiting; no secrets in the repository; the model key only through environment variables

---

## 7. Success Metrics (targets, not results)

| Metric | Target |
|---|---|
| `/health` and other endpoints stay responsive while an agent run is in progress | 100% in a test with a slow mocked agent |
| Concurrent agent runs never exceed the cap | 100% in a test |
| Every stream ends with `done` or `error` | 100% in tests, including client disconnect and agent failure |
| SSE tokens arrive progressively through Nginx (no buffering) | Verified in a compose test, not only in local dev |
| Duplicate upload is not reprocessed | 100% |
| Dependency failure (Postgres) returns a controlled `503`, never a crash | 100% |
| Redis failure degrades rate limiting and job status but does not block chat | Demonstrated |
| Plaintext passwords stored | 0 |
| `docker compose up` from a clean clone | Zero manual steps |
| p95 API latency excluding the agent | Benchmarked and reported; no fixed target yet |

---

## 8. Risks & Open Questions

- **Document ids are derived from the filename** (Member 1's `ingest_document(file_path)` produced `tcs_annual_report` from the file name). Two different files with the same stem would collide, and chunk ids are derived from the document id. Needs a decision with Member 1: let the API pass an explicit id, or generate a unique upload filename so the stem is unique
- **OCR is not built.** Scanned PDFs are expected to fail or come back empty, and the `ocr_fallback` status will not occur yet. Embedded images in DOCX files are also ignored. The upload response must say so clearly, not pretend success
- **Member 1's duplicate registry is in memory** and is lost on restart. This module's `documents.content_hash` lookup is the real source of truth
- **Single replica.** The vector index is a local ChromaDB directory held by the API process, and Member 2's BM25 index is in memory. Two processes (a second API replica, or a separate Celery worker) writing to the same directory is unsafe, so MVP indexing runs inside the API process. Whether the Chroma client is safe for a concurrent `retrieve()` and `index_chunks()` in different threads is **untested** and must be tested
- **The concurrency cap is per process.** With more than one replica the cap multiplies, and the free model's limit (about 20 requests a minute, about 50 a day) is account-wide
- **No cancellation.** If a client disconnects, the agent run continues for up to about three minutes and holds its slot
- **Shared corpus.** Any signed-in user can get answers drawn from any uploaded document. Per-user visibility would need the agent to send a `document_id` filter, which is a Member 3 change
- **"Verified" means faithful to the passages, not true.** The agent repeats a false fact in an uploaded document as verified. Controlling who may upload is this module's job
- **Latency is long.** The first streamed word appears only after verification (22 to 158 s measured on the golden set). The trace events fill the wait; if the wait proves too long, revisit the streaming policy with Members 3 and 5
- **Free-tier model limits** may block evaluation and demos; the cache and a replay-only model exist for that, but must never run on the production server
- **SSE through a reverse proxy** can silently buffer; it needs an explicit compose test

---

## 9. Dependencies on Other Members

- **Member 1:** `ingest_document(file_path) -> IngestionResult`, which never raises. Statuses `success`, `partial`, `failed`, `duplicate`. Table chunks are already rewritten as sentences. Sync needed on the document id and on adding the API-owned `indexing` status
- **Member 2:** `build_default_retriever`, `index_chunks`, `delete_document`, `retrieve`. Build once. The first run downloads the embedding model (about 130 MB): bake it into the Docker image or cache it. A saved index built with a different model raises `ValueError`
- **Member 3:** `build_agent`, `run`, `run_streaming`, never raises, always returns a valid `AgentResponse`. Needs the model key in the environment (`OPENROUTER_API_KEY`, optionally `OPENROUTER_MODEL`, `OPENROUTER_FALLBACK_MODELS`)
- **Member 5:** consumes the REST and SSE contracts; the changed `status` event shape and the new `error` event in the TRD need their sign-off
