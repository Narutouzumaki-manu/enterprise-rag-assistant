# Backend Schema Document
## Module: Backend / API (FastAPI + Infra)
### Owner: Member 4 — Backend / API Engineer
### Project: Enterprise RAG Assistant
### Version: v0.2 (Session 21 preparation, October 2026; supersedes the September v0.1)

> **Status.** Design only: the backend is not built, so nothing here has been checked against code. The Member 3 documents are checked mechanically against their code by `scripts/check_docs_against_code.py`; this one should get the same treatment once `app/schemas/api.py` exists.

---

## 0. What changed from v0.1

| # | Change | Section |
|---|---|---|
| 1 | `ChatResponse` gains `verification_status`; citations are `ApiCitation` with `source_file` | 2 |
| 2 | `ChatRequest.top_k` validated to 1 to 20 (shape unchanged) | 2 |
| 3 | New `ErrorResponse` and an error-code list | 2 |
| 4 | `DocumentStatusResponse.status` vocabulary written out, including `indexing` | 2 |
| 5 | SSE event payloads written out: `status` changed, `error` added | 3 |
| 6 | Primary keys are UUIDs; new `feedback` table; `sessions.deleted_at` | 4 |
| 7 | Co-owned tables: `documents` (`deleted_at`, unique `content_hash`, `indexing`), `citations` (`source_file`) | 5 |
| 8 | Redis: the `session:{id}:active` key is dropped | 6 |
| 9 | Data flows redrawn: upload to indexed, chat with the agent runtime | 7 |
| 10 | Open items updated | 8 |

---

## 1. Purpose

This document defines the API-layer Pydantic contracts and the persistent database schema this module owns or migrates on behalf of the team. Co-owned tables are cross-referenced to the module that defines their shape.

---

## 2. Pydantic Schemas (Application Layer)

Location: `app/schemas/api.py`
Status: **Frozen once confirmed — v0.1-contracts, with the additions marked new.** Member 5 depends on this directly; any change needs a team sync and the matching TypeScript change in the same PR.

```python
from pydantic import BaseModel, Field
from uuid import UUID
from app.schemas.agent import Citation


class ChatRequest(BaseModel):
    session_id: UUID
    query: str
    top_k: int = Field(default=8, ge=1, le=20)


class ApiCitation(Citation):
    source_file: str | None = None      # new: filename resolved from document_id


class ChatResponse(BaseModel):
    request_id: UUID
    answer: str
    citations: list[ApiCitation]
    verification_status: str            # new: "verified" | "partially_verified" | "unverified"
    confidence: float
    latency_ms: int


class DocumentStatusResponse(BaseModel):
    document_id: str
    filename: str
    status: str
    error_message: str | None = None


class HealthResponse(BaseModel):
    status: str             # "ok" | "degraded"
    checks: dict            # {"postgres": "ok", "redis": "ok", "retriever": "ok"}


class ErrorResponse(BaseModel):
    error: str              # human readable, never a stack trace
    code: str
```

### Field Notes

| Field | Type | Notes |
|---|---|---|
| `session_id` | `UUID` | Ties a chat request to a persisted `sessions` row owned by the signed-in user |
| `top_k` | `int` | 1 to 20; passed through to the agent, which clamps to the same range and uses 8 when omitted |
| `ApiCitation` | extends Member 3's `Citation` | Inherits `chunk_id`, `document_id`, `page_number`, `text_snippet` (at most 200 characters, may start with "..."). `source_file` is looked up by `document_id` when the response is built and stored on the citation row |
| `verification_status` | `str` | Relayed unchanged from Member 3's `AgentResponse`. Can become a `str` Enum later with identical JSON |
| `confidence` | `float` | 0 to 1; relayed. On the golden set every `verified` answer was 0.95 (the cap) and every `unverified` one 0, so the UI should show the status, not the number |
| `answer` | `str` | For `unverified` outcomes this may be exactly "I don't have sufficient evidence in the provided documents.", "I couldn't search the documents right now. Please try again." or "I couldn't write an answer right now. Please try again." |
| `status` (DocumentStatusResponse) | `str` | `queued`, `parsing`, `ocr_fallback`, `indexing`, `success`, `partial`, `failed`, `duplicate`. Member 1's states plus this module's `indexing`. `ocr_fallback` does not occur yet (OCR is not built) |
| `checks` (HealthResponse) | `dict` | One key per dependency; the retriever entry can include the embedding model and chunk count from `retrieval_index_metadata` |

**Error codes** (`ErrorResponse.code`): `VALIDATION_ERROR` (422), `UNAUTHENTICATED` (401), `NOT_FOUND` (404), `FILE_TOO_LARGE` (413), `UNSUPPORTED_FILE_TYPE` (415), `RATE_LIMITED` (429), `AGENT_BUSY` (503, with `Retry-After`), `DEPENDENCY_UNAVAILABLE` (503), `INTERNAL_ERROR` (500).

---

## 3. SSE Event Payloads (`POST /chat/stream`)

```
event: status
data: {"step_type": "retrieve", "content": "Retrieved 8 passages across 1 sub-query"}

event: source
data: {"chunk_id": "...", "document_id": "...", "source_file": "tcs_annual_report.pdf", "page_number": 15, "text_snippet": "..."}

event: token
data: {"text": "TCS's "}

event: verification
data: {"status": "verified", "confidence": 0.95}

event: done
data: {"request_id": "...", "confidence": 0.95, "latency_ms": 31500}

event: error
data: {"error": "The service is busy. Please try again shortly.", "code": "AGENT_BUSY"}
```

- `status`: one per agent trace step; `step_type` is `plan`, `retrieve`, `synthesize` or `fact_check`; `content` is the agent's own UI wording (the exact strings are listed in Member 3's UI/UX notes). **Changed** from v0.1's `{"stage": ...}`
- `token`: the final, verified answer split into words with their trailing spaces. The agent does not stream model tokens
- `error` is **new** and replaces `done` when a stream fails; every stream ends with exactly one of `done` or `error`
- A comment line `: keep-alive` is sent about every 15 seconds; it is not an event and the client ignores it

---

## 4. Persistent Database Schema (this module's own tables)

Primary keys are Postgres `uuid` (v0.1's `str` keys are replaced; contracts carry them as `UUID` or strings).

### Table: `users`

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` (PK) | |
| `email` | `str` | Unique, indexed |
| `password_hash` | `str` | Argon2 or bcrypt; never plaintext, never logged |
| `created_at` | `timestamp` | |

### Table: `sessions`

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` (PK) | |
| `user_id` | `uuid` (FK → users) | Indexed; ownership is checked on every read |
| `created_at` | `timestamp` | |
| `updated_at` | `timestamp` | |
| `deleted_at` | `timestamp \| null` | Soft delete, to preserve the audit trail |

### Table: `feedback` (new)

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` (PK) | |
| `message_id` | `uuid` (FK → messages) | The assistant message being rated |
| `user_id` | `uuid` (FK → users) | |
| `rating` | `smallint` | -1 or 1 |
| `comment` | `text \| null` | |
| `created_at` | `timestamp` | |

### Table: `audit_events`

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` (PK) | |
| `request_id` | `str` | Correlates to one API request across logs |
| `event_type` | `str` | `upload`, `query`, `auth_failure`, `document_delete`, ... |
| `payload` | JSON | No passwords, tokens, API keys or passage text |
| `timestamp` | `timestamp` | |

---

## 5. Co-Owned Tables (this module writes the migrations; the producing module owns the shape)

| Table | Defined in | This module's role and changes |
|---|---|---|
| `documents` | Member 1's Backend Schema | Adds `deleted_at` (soft delete) and a **unique** index on `content_hash` (the duplicate check); `status` also takes `indexing`. **Needs Member 1's sign-off** |
| `chunks` | Member 1's Backend Schema | Unchanged. Kept so an index can be rebuilt without re-parsing |
| `messages`, `agent_traces` | Member 3's Backend Schema | Unchanged; one `messages` row per assistant answer, one `agent_traces` row per step |
| `citations` | Member 3's Backend Schema | Adds nullable `source_file`, written when the row is inserted so history survives a document deletion. **Needs Member 3's sign-off** |
| `retrieval_index_metadata` | Member 2's Backend Schema | Unchanged; exposed read-only through `/health` |

**Any change to a co-owned table's shape requires a sync with the owning module**, not a unilateral migration.

Indexes this module relies on: `documents.content_hash` (unique), `chunks.document_id`, `citations.message_id`, `agent_traces(message_id, step_order)`, `sessions.user_id`.

---

## 6. Redis Key Structure

| Key pattern | Value | TTL | Purpose |
|---|---|---|---|
| `ratelimit:{user_id}:{endpoint}` | request count | Rolling window | Backing store for `slowapi` |
| `job:{document_id}:status` | current ingestion status | Until the job completes | Fast polling target for `GET /documents` before the Postgres row is final |

v0.1's `session:{session_id}:active` is dropped for the MVP: Postgres is enough. Redis is optional for chat; if it is down, rate limiting and job status degrade and chat continues.

---

## 7. Data Flows

### Upload to searchable

```
Client -> POST /documents/upload
      |
      v  validate type + size; SHA-256 of the bytes
      +-- hash found in documents (not deleted) --> 200 {document_id, status: "duplicate"}
      |
      v
documents row inserted, status "queued"  --> 202 {document_id, status: "queued"}
      |
      v  background task (sync function in the thread pool)
status "parsing"  -> Member 1: ingest_document()
      +-- failed ------------------------------------> status "failed" + error_message
      v   success | partial
chunks rows inserted; status "indexing" -> Member 2: index_chunks(chunks)
      +-- raises ------------------------------------> status "failed", "Indexing failed"
      v
status "success" | "partial"      (searchable)
```

### One question, streamed

```
Client -> POST /chat/stream {session_id, query, top_k}
      |
      v  auth, session ownership, validation (blank -> 422), rate limit
user message stored
      |
      v  semaphore (cap per process; wait -> else 503 AGENT_BUSY)
worker thread: agent.run_streaming()  ----->  AgentStep ... AgentResponse
      |                                               |
      v  each AgentStep -> SSE "status"               v
      |                                    final AgentResponse
      |                                               |
      |                      citations get source_file (lookup by document_id)
      |                                               |
      |            SSE: source (each), token (words), verification, done
      v
one transaction: assistant message + citations rows + agent_traces rows
```

Every path ends in `done` or `error`. A rate-limited model arrives as a normal `unverified` response and is stored like any other answer.

---

## 8. Open Items for Future Iteration

- Replace `verification_status: str` and the document `status` string with Enums once the team agrees (identical JSON)
- **Document id source:** Member 1 derives it from the filename; decide with Member 1 whether the API passes an explicit id or stores uploads under unique names (collision risk on same-stem files)
- Sign-offs needed: Member 1 (`documents` changes), Member 3 (`citations.source_file`), Member 5 (`status` event shape, `error` event)
- Per-user document visibility needs a `document_id` filter from the agent (a Member 3 change); the MVP shares one corpus
- Tune per-endpoint rate limits and the upload size limit from real usage instead of guessing
- Decide the Celery plus vector-database-server migration trigger (single replica with an embedded index in the MVP)
- Soft-delete for `messages` (matching `sessions.deleted_at`) if the audit trail needs it
