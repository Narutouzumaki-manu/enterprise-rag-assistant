# Technical Requirements Document (TRD)
## Module: Backend / API (FastAPI + Infra)
### Owner: Member 4 — Backend / API Engineer
### Project: Enterprise RAG Assistant
### Version: v0.2 (Session 21 preparation, October 2026; supersedes the September v0.1)

> **Status.** Design only: the backend is not built. Numbers are starting values or targets unless marked "measured" (Member 2 and Member 3 evaluations: one 118-chunk document, 10 to 17 questions, one free model). Nothing in this document has been checked against Member 4 code, because none exists yet.

---

## 0. What changed from v0.1

| # | Change | Section |
|---|---|---|
| 1 | Agent and retriever built once; agent calls run in a thread behind a semaphore | 5, 8 |
| 2 | Streaming bridge (worker thread, `asyncio.Queue`) and the final verified answer streamed as words | 7 |
| 3 | SSE `status` event carries `step_type` and `content` (was `stage`); new `error` event | 6, 7 |
| 4 | `ChatResponse` gains `verification_status`; citations gain `source_file` | 6 |
| 5 | Ingestion lifecycle: `indexing` state, persisted duplicate check, soft delete, no OCR yet | 9 |
| 6 | MVP is a single replica with an embedded vector index; v0.1's "stateless API replicas" claim removed | 8, 15 |
| 7 | New tables: `feedback`; new columns: `documents.deleted_at`, `citations.source_file`; ids are UUIDs | 10 |
| 8 | Failure behaviour rewritten: model failure is a 200 `unverified` answer; busy is 503 `AGENT_BUSY`; Redis failure degrades | 13 |
| 9 | Testing plan rewritten around a `MockAgent`, event-loop responsiveness and the stream guarantees | 14 |
| 10 | Docker Compose: no separate worker or vector server for the MVP | 15 |
| 11 | Open decisions table | 16 |

---

## 1. Scope

Technical design of the FastAPI application: routing, async endpoints, the agent runtime (startup, thread pool, concurrency cap), SSE streaming, the ingestion and indexing lifecycle, the Postgres and Redis layers, authentication, and deployment.

---

## 2. Architecture Overview

```
Client (Member 5's React UI)
  |
  v
Nginx  (SSE route: proxy_buffering off, read timeout >= 300 s)
  |
  v
FastAPI process  (ONE replica in the MVP)
  |
  +-- Auth (JWT) ----------------------------+
  |                                          |
  +-- Document routes --> background task ---+--> Member 1: ingest_document()
  |                         (sync function,  |        |
  |                          thread pool)    |        v
  |                                          +--> Member 2: index_chunks()  (embedded ChromaDB on disk)
  |
  +-- Chat routes --> AgentRuntime (semaphore, thread) --> Member 3: agent.run / run_streaming
  |                                                              |
  |                                                              +--> Member 2: retrieve()
  |                                                              +--> Model API (OpenRouter)
  |
  +-- PostgreSQL  (durable: users, sessions, documents, chunks, messages, citations, traces, feedback, audit)
  +-- Redis       (rate limiting, short-lived job status; optional for chat)
```

---

## 3. Tech Stack

| Component | Tool | Reason |
|---|---|---|
| Language | Python 3.11+ | Matches the rest of the team |
| Web framework | FastAPI + Pydantic v2 | Async native, typed, automatic OpenAPI docs |
| Database | PostgreSQL, SQLAlchemy 2.0 async, Alembic | Real migrations, relational history |
| Cache / limits | Redis | Rate-limit counters, job status |
| Background work | FastAPI `BackgroundTasks` with a **sync** function (runs in the thread pool) | The embedded index forbids a second process (Section 8); upgrade path in Section 16 |
| Streaming | SSE through the framework's SSE response if the pinned FastAPI version has one, otherwise `sse-starlette`; **verify which** | Browsers consume SSE natively |
| Auth | JWT (`sub`, `exp`, `iat` only), Argon2 or bcrypt | Standard |
| Rate limiting | `slowapi` backed by Redis | FastAPI-native |
| Logging | `structlog` | Structured, request-scoped |
| Testing | `pytest`, `pytest-asyncio`, `httpx.AsyncClient` | Matches the team |
| Proxy | Nginx | SSE-aware config |

---

## 4. Module Breakdown

```
app/api/
├── main.py                  — app factory, lifespan (startup builds retriever + agent), middleware
├── runtime.py               — AgentRuntime: holds the agent, the semaphore; run() and stream() wrappers
├── ingestion_service.py     — upload handling, duplicate check, background ingest + index, delete
├── routes/
│   ├── documents.py         — POST /documents/upload, GET /documents, GET /documents/{id}, DELETE /documents/{id}
│   ├── chat.py              — POST /chat, POST /chat/stream, GET /sessions, GET /sessions/{id}, POST /feedback
│   ├── auth.py              — POST /auth/login
│   └── health.py            — GET /health
└── dependencies/            — auth check, DB session, current user, session-ownership check
app/db/
├── models.py                — SQLAlchemy models
├── session.py               — async session management
└── migrations/              — Alembic
app/core/
├── config.py                — 12-factor settings (all limits and timeouts live here)
├── security.py              — JWT, password hashing
└── logging.py               — structlog setup, request id
tests/unit/api/
└── mocks.py                 — MockAgent, MockRetriever, MockIngestion
```

---

## 5. Interfaces to Members 1, 2 and 3

### 5.1 Startup (once per process)

```python
# in the FastAPI lifespan
config = AgentConfig()
retriever = build_default_retriever(persist_path=settings.chroma_path)   # may raise ValueError: model mismatch -> fail fast
llm = OpenRouterLLM.from_env(retries=config.llm_retries)                 # NOT CachingLLM in production
agent = build_agent(retriever, llm, config)
runtime = AgentRuntime(agent, max_concurrent=settings.agent_max_concurrent)
```

- Environment: `OPENROUTER_API_KEY` (required, never committed), optional `OPENROUTER_MODEL`, `OPENROUTER_FALLBACK_MODELS`
- The retriever is shared by ingestion (`index_chunks`, `delete_document`) and by the agent (`retrieve`), so there is exactly one index handle in the process
- First start downloads the embedding model (about 130 MB): bake it into the Docker image or mount a cache volume

### 5.2 Calling the agent

`run()` and `run_streaming()` are **synchronous** and block for the whole question (measured: 12 to 36 s per model call, 3 to 7 calls, 22 to 158 s per golden question). They must never run on the event loop:

```python
async def run_agent(question: str, top_k: int) -> AgentResponse:
    async with runtime.slot():                       # semaphore, with wait timeout -> AGENT_BUSY
        return await run_in_threadpool(agent.run, question, top_k=top_k)
```

`top_k` is clamped by the agent to 1 to 20; a blank question is answered "Please enter a question." without a model call (the API rejects blank queries first with `422`). `session_context` is accepted by the agent and unused.

### 5.3 Ingestion and indexing

```python
result: IngestionResult = ingest_document(path)     # never raises; status success | partial | failed | duplicate
retriever.index_chunks(result.chunks)               # idempotent upsert by chunk_id
retriever.delete_document(document_id)              # removes from the vector and keyword indexes
```

---

## 6. Interface Contracts

Frozen request shape (`app/schemas/api.py`), with the agreed additions marked **new**:

```python
from pydantic import BaseModel, Field
from uuid import UUID
from app.schemas.agent import Citation


class ChatRequest(BaseModel):
    session_id: UUID
    query: str
    top_k: int = Field(default=8, ge=1, le=20)     # validation added; shape unchanged


class ApiCitation(Citation):                       # Citation from Member 3, unchanged
    source_file: str | None = None                 # new: resolved from documents by document_id


class ChatResponse(BaseModel):
    request_id: UUID
    answer: str
    citations: list[ApiCitation]                   # was list
    verification_status: str                       # new: "verified" | "partially_verified" | "unverified"
    confidence: float
    latency_ms: int


class DocumentStatusResponse(BaseModel):
    document_id: str
    filename: str
    status: str            # queued | parsing | ocr_fallback | indexing | success | partial | failed | duplicate
    error_message: str | None = None


class HealthResponse(BaseModel):
    status: str            # "ok" | "degraded"
    checks: dict           # {"postgres": "ok", "redis": "ok", "retriever": "ok", ...}


class ErrorResponse(BaseModel):
    error: str             # human readable
    code: str              # e.g. AGENT_BUSY
```

**SSE events** (`POST /chat/stream`):

| Event | Data | When |
|---|---|---|
| `status` | `{"step_type": "plan" \| "retrieve" \| "synthesize" \| "fact_check", "content": "<trace wording>"}` | Once per agent trace step, as it finishes (**changed** from v0.1's `{"stage": ...}`) |
| `source` | `{"chunk_id", "document_id", "source_file", "page_number", "text_snippet"}` | One per citation of the final answer |
| `token` | `{"text": "<word plus trailing space>"}` | The final answer, word by word, after verification |
| `verification` | `{"status": "<verification_status>", "confidence": <float>}` | After the tokens |
| `done` | `{"request_id": "...", "confidence": <float>, "latency_ms": <int>}` | Last event of a successful stream |
| `error` | `{"error": "<human readable>", "code": "<CODE>"}` | **New.** Last event when the stream fails; replaces `done` |

The `status` change and the `error` event need Member 5's sign-off (their TypeScript mirror must change in the same PR). Any further change to a shape requires a team sync.

---

## 7. Streaming Design

The agent yields `AgentStep` objects as each step finishes and one `AgentResponse` at the end. It does **not** stream model tokens, so the answer is complete only after verification. The bridge from the blocking generator to async SSE:

```python
async def agent_events(question, top_k):
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def worker():
        try:
            for event in agent.run_streaming(question, top_k=top_k):
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except Exception as exc:                      # the agent should not raise; defence in depth
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=worker, daemon=True).start()
    while (event := await queue.get()) is not None:
        yield event       # AgentStep objects, then one AgentResponse (or an exception object)
```

Mapping to SSE:
- each `AgentStep` becomes a `status` event (`step_type` and `content` only; counts and labels in `metadata` are stored, not sent)
- on the final `AgentResponse`: one `source` per citation (with `source_file`), then `token` events (split the answer with `re.findall(r"\S+\s*", answer)` so spacing is preserved), then `verification`, then `done`
- **Why the wait is long:** the first word appears only after verification and any retry (measured 22 to 158 s per golden question). The `status` events fill the wait, so the stream is never silent

Reliability requirements:
- **Heartbeat:** an SSE comment (`: keep-alive`) about every 15 seconds, because a single model call can take 12 to 36 seconds with no event
- **Limits:** allow at least 5 minutes in Nginx, the client and the server (`proxy_read_timeout`)
- **Buffering:** `proxy_buffering off` on the SSE route and the response header `X-Accel-Buffering: no`; test through Nginx
- **Disconnect:** stop forwarding events and release the HTTP resources. The agent **cannot be cancelled**, so the worker thread runs to completion (up to about three minutes) and holds its semaphore slot until it finishes. The completed answer is still persisted (the run was already paid for), so the history shows it. This is a starting decision (Section 16)
- **Always terminate:** every path ends with `done` or `error`

---

## 8. Concurrency and Capacity

- **Semaphore:** at most `agent_max_concurrent` (starting value 2) agent runs per process. A question is 3 to 7 sequential model calls (3 typical; 5 with a retry; 2 for the one unanswerable golden question) on a model limited to about 20 requests a minute and about 50 a day
- **Waiting:** a request waits up to `agent_wait_seconds` (configurable); then `503` with `code: AGENT_BUSY` and a `Retry-After` header
- **Rate-limited model:** the agent returns an `unverified` response ("I couldn't write an answer right now. Please try again."). The API returns `200` and stores it. It is a normal answer, not a server error
- **Single replica (MVP):** the vector index is a local ChromaDB directory opened by this process and Member 2's keyword index is in memory. A second process writing to the same directory is unsafe. So: one API replica, ingestion and indexing inside that process, no separate Celery worker, no per-replica load balancing. The semaphore is also per process: with more replicas the cap multiplies, and the model's limit is account-wide
- **Thread safety is unverified:** whether a `retrieve()` running in one thread is safe while `index_chunks()` runs in another (upload during a question) is **untested** and must be tested before the MVP is called done. If unsafe, serialise index writes behind a lock
- **Event loop:** every blocking call (`agent.run`, `ingest_document`, `index_chunks`) runs in a thread, never directly in an `async def`

---

## 9. Ingestion and Document Lifecycle

```
POST /documents/upload
  |  validate: type (pdf, docx, csv), size limit, generated storage name (no client filename in paths)
  |  SHA-256 of the bytes
  |
  +-- hash already in documents (not deleted) --> 200 {document_id, status: "duplicate"}   (no reprocessing)
  |
  v
INSERT documents (status "queued")  --> 202 {document_id, status: "queued"}
  |
  v   background task (sync function, thread pool)
status "parsing"  --> Member 1: ingest_document()
  |  result.status failed ------------------------------> documents.status "failed" + error_message
  |  result.status success | partial
  v
INSERT chunks rows;  status "indexing" --> Member 2: index_chunks(result.chunks)
  |  raises -----------------------------------------------> status "failed", error_message "Indexing failed"
  v
status "success" | "partial"     (searchable from this point)
```

- **Status vocabulary:** Member 1's `queued`, `parsing`, `ocr_fallback`, `success`, `partial`, `failed`, `duplicate`, plus this module's `indexing`. `ocr_fallback` will **not** occur yet: OCR is not built, so a scanned PDF is expected to fail or come back empty. Member 1's `error_message` is passed through to the UI; confirm its wording for the scanned case. Embedded DOCX images are ignored silently
- **Document id:** Member 1's `ingest_document(file_path)` derives the id from the filename (the test report became `tcs_annual_report`), and chunk ids derive from the document id. Two uploads with the same stem would collide. Decide with Member 1: pass an explicit id, or store each upload under a unique generated name so the stem is unique
- **Duplicate source of truth:** `documents.content_hash` (unique, indexed), not Member 1's in-memory registry
- **Delete:** `delete_document(document_id)` on the retriever first, then soft-delete the row (`deleted_at`) and keep chunks for audit; if the index step fails, return an error and do not mark the row deleted
- **Restart:** a persisted index built with a different embedding model makes startup fail with a clear message; delete `data/chroma` and re-index from the stored chunk rows
- **Prompt injection:** the agent treats document text as data and removes passages that address the AI, but "verified" means faithful to the passages, not true. This module controls who may upload (authenticated users only, type and size limits)

---

## 10. Database Schema

Types: ids are Postgres `uuid` (the contracts carry them as strings or `UUID`); v0.1's `str` primary keys are replaced.

**Own tables**

| Table | Columns |
|---|---|
| `users` | `id` uuid PK, `email` unique, `password_hash` (Argon2 or bcrypt), `created_at` |
| `sessions` | `id` uuid PK, `user_id` FK, `created_at`, `updated_at`, `deleted_at` null |
| `audit_events` | `id` PK, `request_id`, `event_type` (upload, query, auth_failure, ...), `payload` JSON, `timestamp` |
| `feedback` | `id` PK, `message_id` FK, `user_id` FK, `rating` (small integer, -1 or 1), `comment` text null, `created_at` |

**Co-owned tables** (shapes owned by the producing module; this module writes the migrations)

| Table | Owner | This module's change |
|---|---|---|
| `documents` | Member 1 | Add `deleted_at` null; unique index on `content_hash`; `status` values include `indexing`. Needs Member 1's sign-off |
| `chunks` | Member 1 | Unchanged. Kept so an index can be rebuilt without re-parsing |
| `messages`, `citations`, `agent_traces` | Member 3 | `citations` gains nullable `source_file` (written at insert time so history survives a document deletion). Needs Member 3's sign-off |
| `retrieval_index_metadata` | Member 2 | Unchanged; read-only through `/health` |

**Indexes:** `documents.content_hash` (unique), `chunks.document_id`, `citations.message_id`, `agent_traces(message_id, step_order)`, `sessions.user_id`.

**What gets persisted per answer** (one transaction after the run completes; the user message is stored when the request starts): the assistant message (answer, `verification_status`, `confidence`, `latency_ms`), one `citations` row per citation, one `agent_traces` row per step (`step_order`, `step_type`, `content`, `metadata` JSON). Do not store prompts or passage text in trace metadata (the agent already keeps it to counts and labels).

---

## 11. Redis

| Key pattern | Value | TTL | Purpose |
|---|---|---|---|
| `ratelimit:{user_id}:{endpoint}` | request count | rolling window | Backing store for `slowapi` |
| `job:{document_id}:status` | current ingestion status | until the job completes | Fast polling before the Postgres row is final |

`session:{session_id}:active` from v0.1 is dropped for the MVP: Postgres is enough for session lookups, and a second source of truth adds failure modes. Redis is not required for chat to work (Section 13).

---

## 12. Authentication and Security

- `POST /auth/login` verifies the password hash and issues a JWT with `sub`, `exp` and `iat` only; expiry is configurable. Users are created by a seed script in the MVP (no public registration)
- Every route except `/auth/login` and `/health` needs a valid token; a session may be read only by its owner (return `404`, not `403`, so ids are not enumerable)
- Uploads: allow-list of types, size limit, generated storage names, no client path in the filesystem (path traversal test)
- No secrets in the repository; `.env.example` with blank values; the model key only in the environment
- Logs and audit payloads never contain passwords, tokens or the API key
- **Shared corpus:** all signed-in users search all uploaded documents. Per-user visibility needs a Member 3 change (the agent sends no filters). Documented as a known limitation

---

## 13. Error Handling

| Failure case | Behaviour |
|---|---|
| Model rate-limited or failed | Agent returns `unverified` ("I couldn't write an answer right now. Please try again."); API returns `200`, stores it, streams it normally |
| Agent concurrency cap full beyond the wait | `503`, `code: AGENT_BUSY`, `Retry-After` |
| Agent raises (should not happen) | `500` is never returned raw: structured `INTERNAL_ERROR`; in a stream, an `error` event |
| Client disconnects mid-stream | Stop sending; the agent run finishes in its thread, the answer is stored, the slot is released at the end |
| Duplicate upload | `200` with the existing document and status `duplicate` |
| Unsupported type / too large | `415 UNSUPPORTED_FILE_TYPE` / `413 FILE_TOO_LARGE`, human-readable message |
| Scanned or empty PDF (no OCR) | Document ends `failed` with Member 1's `error_message`; the upload response itself is still `202` |
| Postgres unavailable | `503 DEPENDENCY_UNAVAILABLE`, never a traceback |
| Redis unavailable | Rate limiting and job status degrade (logged, fall back to Postgres or skip); chat and auth keep working. A starting decision (Section 16) |
| Retriever refuses a saved index at startup | The process does not start; the message says to delete `data/chroma` and re-index |
| Embedding model files missing offline | Startup failure with a clear message (bake the model into the image) |
| Invalid or expired JWT | `401 UNAUTHENTICATED` |
| Session belongs to someone else | `404 NOT_FOUND` |
| Race on a concurrent session update | Transaction; optimistic version column or row lock where needed |

---

## 14. Testing Plan

All unit tests use `MockAgent`, `MockRetriever` and `MockIngestion`: no model, no network.

- Each endpoint returns the right status code and schema for valid input; blank query gives `422`; `top_k` outside 1 to 20 gives `422`
- **Event-loop responsiveness:** while a mocked agent sleeps for several seconds, `/health` still answers quickly
- **Cap:** more simultaneous chats than `agent_max_concurrent` never run at once; the extra request gets `AGENT_BUSY` after the wait
- **Stream order and ending:** `status` events, then `source`, `token`s, `verification`, `done`; an agent failure and a client disconnect both end with `error` or a stored answer, never a hang
- **Heartbeat** is sent while the mock agent is silent
- **Rate-limited model:** a mocked `unverified` response returns `200` and is stored
- **`ChatResponse`** carries `verification_status` and `source_file` on every citation
- **Upload:** returns `202` immediately; duplicate returns the existing document without calling `ingest_document`; wrong type and too large rejected; a path-traversal filename cannot escape the upload directory; two files with the same stem do not collide (once the id decision is made)
- **Lifecycle:** statuses move `queued`, `parsing`, `indexing`, `success`; an indexing error ends `failed`; deleting a document calls `delete_document` and soft-deletes the row
- **Auth:** invalid or expired JWT rejected; session ownership enforced; a user cannot read another user's session
- **Rate limiting** triggers under excessive requests
- **Redis down:** chat still works; **Postgres down:** controlled `503`
- **Migrations:** upgrade and downgrade run; ids are UUIDs
- **Thread safety:** a concurrent `retrieve()` and `index_chunks()` test with the real retriever (Section 8)
- **Through Nginx (compose test):** tokens arrive progressively, no buffering
- **E2E with Member 5:** upload a real PDF, wait for `success`, ask a question, assert citations and a status; this uses the real model and counts against the free quota, so run it rarely or against a replay cache

---

## 15. Deployment

Compose services for the MVP: `frontend`, `api`, `postgres`, `redis`, `nginx`. There is **no separate `worker` and no vector-database server**, because the index is embedded in the API process (Section 8). Member 5's compose skeleton lists both; agree with Members 2 and 5 whether Member 2's factory should gain a Chroma-server option before they are added.

- Healthchecks and `depends_on: condition: service_healthy` for Postgres and Redis
- Persistent volumes for Postgres and for the Chroma directory and uploaded files
- The embedding model baked into the API image, or a cache volume
- Multi-stage Dockerfile; `python:3.12-slim` where compatible
- Nginx: SSE route with `proxy_buffering off`, `proxy_read_timeout` of at least 300 s, `X-Accel-Buffering: no`
- Secrets through environment variables or GitHub Secrets, never in the repository

---

## 16. Open Decisions and Limits

| Decision | Owner | Needed by |
|---|---|---|
| Document id: explicit id from the API or unique stored filename | Members 1 and 4 | Before the upload route is built |
| Add `indexing` to `documents.status` and `deleted_at` to `documents` | Member 1 | Before the migrations |
| `citations.source_file` column | Member 3 | Before the migrations |
| New `status` event shape and the `error` event | Member 5 | Before the stream route is built |
| Is the Chroma client safe for concurrent `retrieve()` and `index_chunks()`? | Members 2 and 4 | Before the MVP is called done |
| Redis down: degrade (starting decision) or fail closed | Member 4 | Before the rate limiter is wired |
| Persist the answer after a client disconnect (starting decision: yes) | Member 4 | Before the stream route is built |
| Per-user document visibility | Members 3 and 4 | After the MVP; needs the agent to send a `document_id` filter |
| Upgrade path to Celery and a vector-database server for horizontal scaling | Members 2, 4, 5 | Only if load demands it |
| Concrete values: upload size limit, query length limit, semaphore size, wait time, JWT expiry, rate limits | Member 4 | Tune from real usage; do not guess limits upfront |

**Limits to state in the README:** one API replica; shared corpus; no OCR; the first word of an answer appears only after verification; "verified" means found in the documents, not true.
