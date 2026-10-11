# Backend Schema Document
## Module: Document Ingestion & Data Pipeline
### Owner: Member 1 — Document Ingestion & Data Pipeline Engineer
### Project: Enterprise RAG Assistant
### Date: September 2026

---

## 1. Purpose

This document defines the data schemas owned or co-owned by the Ingestion module — both the in-memory Pydantic contracts used between modules, and the persistent database tables needed to track ingestion state.

---

## 2. Pydantic Schemas (Application Layer)

Location: `app/schemas/document.py`
Status: **Frozen — v0.1-contracts**. Changes require team sync.

```python
from pydantic import BaseModel
from datetime import datetime
from enum import Enum


class SourceType(str, Enum):
    PDF = "pdf"
    DOCX = "docx"
    CSV = "csv"


class ChunkMetadata(BaseModel):
    document_id: str
    source_type: SourceType
    page_number: int | None = None
    section_title: str | None = None
    row_range: tuple[int, int] | None = None   # for CSV/table chunks
    content_hash: str
    ingested_at: datetime


class Chunk(BaseModel):
    chunk_id: str            # deterministic hash of (document_id, position)
    document_id: str
    text: str
    token_count: int
    metadata: ChunkMetadata


class IngestionResult(BaseModel):
    document_id: str
    filename: str
    status: str               # "success" | "failed" | "partial"
    chunks: list[Chunk]
    error_message: str | None = None
```

### Field Notes

| Field | Type | Notes |
|---|---|---|
| `chunk_id` | `str` | Must be deterministic — same input always produces same ID (important for dedup + idempotency) |
| `document_id` | `str` | Derived from filename or explicit ID at upload time |
| `content_hash` | `str` | SHA-256 of raw file bytes — primary dedup key |
| `token_count` | `int` | Computed via `tiktoken`, not word count, in production version |
| `row_range` | `tuple[int, int] \| None` | Only populated for CSV/table-derived chunks |
| `status` | `str` | Should eventually become a proper `Enum` (`success`, `failed`, `partial`) rather than a free string — flagged as a future improvement |

---

## 3. Persistent Database Schema (owned jointly with Member 4)

While Member 4 owns the actual FastAPI/Postgres implementation, Ingestion defines the **data it needs persisted** so document state survives across requests and restarts.

### Table: `documents`

| Column | Type | Notes |
|---|---|---|
| `document_id` | `str` (PK) | Unique per logical document |
| `filename` | `str` | Original uploaded filename |
| `content_hash` | `str` | SHA-256 — indexed, used for dedup lookups |
| `source_type` | `str` | pdf / docx / csv |
| `version` | `int` | Incremented when same logical doc is re-uploaded with different content |
| `status` | `str` | queued / parsing / ocr_fallback / success / partial / failed |
| `error_message` | `str \| null` | Populated only on failure |
| `created_at` | `timestamp` | |
| `updated_at` | `timestamp` | |

### Table: `chunks`

| Column | Type | Notes |
|---|---|---|
| `chunk_id` | `str` (PK) | Deterministic hash |
| `document_id` | `str` (FK → documents) | |
| `text` | `text` | Chunk content |
| `token_count` | `int` | |
| `page_number` | `int \| null` | |
| `section_title` | `str \| null` | |
| `row_range_start` | `int \| null` | For CSV chunks |
| `row_range_end` | `int \| null` | For CSV chunks |
| `extraction_method` | `str` | "native" or "ocr" |
| `ocr_confidence` | `float \| null` | Only populated when `extraction_method = "ocr"` |
| `ingested_at` | `timestamp` | |

**Indexing recommendations:**
- Index `documents.content_hash` — this is the hot path for dedup checks on every upload
- Index `chunks.document_id` — needed for fast lookup of all chunks belonging to a document (e.g., on document deletion)

---

## 4. Deduplication Data Flow

```
New file uploaded
      │
      ▼
Compute SHA-256(file_bytes)
      │
      ▼
Query documents table WHERE content_hash = ?
      │
   ┌──┴──┐
  Found   Not found
   │         │
   ▼         ▼
Return    Proceed with new
cached    ingestion, insert
result    new document + chunk rows
```

---

## 5. Open Items for Future Iteration

- Replace `status: str` with a proper Pydantic `Enum` for type safety
- Add `embedding_model` / `embedding_version` awareness at the chunk level once Member 2's retrieval schema stabilizes (needed to avoid mixing incompatible embedding dimensions later)
- Consider soft-delete (`deleted_at`) on `documents` rather than hard delete, to preserve audit trail
