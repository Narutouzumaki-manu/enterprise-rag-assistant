# Backend Schema Document
## Module: Retrieval & Vector Search
### Owner: Member 2 — Retrieval & Vector Search Engineer
### Project: Enterprise RAG Assistant
### Date: September 2026

---

## 1. Purpose

This document defines the data schemas owned by the Retrieval module — the Pydantic contracts for query/response, and the vector/sparse index structures needed to support hybrid search.

---

## 2. Pydantic Schemas (Application Layer)

Location: `app/schemas/retrieval.py`
Status: **Frozen once confirmed — v0.1-contracts**. Changes require team sync (Members 3, 4, 5 depend on this).

```python
from pydantic import BaseModel


class RetrievedChunk(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    dense_score: float | None = None
    sparse_score: float | None = None
    fused_score: float | None = None
    rerank_score: float | None = None
    page_number: int | None = None
    section_title: str | None = None


class RetrievalRequest(BaseModel):
    query: str
    top_k: int = 5
    filters: dict | None = None


class RetrievalResponse(BaseModel):
    query: str
    results: list[RetrievedChunk]
    embedding_model: str
    reranker_model: str
    latency_ms: float
```

### Field Notes

| Field | Type | Notes |
|---|---|---|
| `chunk_id`, `document_id` | `str` | Directly carried over from Member 1's `Chunk` schema — never regenerated here |
| `dense_score` | `float \| None` | Raw cosine/dot-product similarity from the vector store; `None` if this chunk only matched via BM25 |
| `sparse_score` | `float \| None` | Raw BM25 score; `None` if this chunk only matched via dense search |
| `fused_score` | `float \| None` | RRF combined score; always present after fusion, before rerank |
| `rerank_score` | `float \| None` | Cross-encoder score; `None` until the reranking stage runs |
| `page_number`, `section_title` | inherited from `ChunkMetadata` | Passed through unchanged from Member 1's ingestion metadata — enables accurate citations |
| `embedding_model` | `str` | Recorded per-response so downstream consumers/evaluators know exactly which model produced these results |

---

## 3. Vector Index Structure (ChromaDB, dev)

Each vector entry stores:

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | Same as `chunk_id` — enables upsert-by-id for idempotent indexing |
| `embedding` | `vector[float]` | Dimension fixed by the chosen model (e.g., 384 for MiniLM, 768 for bge-base) |
| `document` | `str` | The chunk's text (Chroma's term for the indexed content) |
| `metadata` | `dict` | `document_id`, `source_type`, `page_number`, `section_title`, `content_hash`, `embedding_model`, `embedding_dimension` |

**Critical invariant**: every entry in a given collection must share the same `embedding_model` / `embedding_dimension`. Mixing models silently produces meaningless similarity scores — this must be validated at index-write time, not discovered later during debugging.

---

## 4. BM25 Sparse Index Structure

| Field | Type | Notes |
|---|---|---|
| `chunk_id` | `str` | Same as dense index — the join key between both indexes |
| `tokenized_text` | `list[str]` | Tokenized form of chunk text, used to build the BM25 corpus |

The BM25 index (via `rank_bm25`) is typically held in memory and rebuilt or incrementally updated as chunks are added/removed. Unlike the vector store, it does not need embedding-dimension bookkeeping — but it **does** need to stay in sync with the vector store's contents, or dense/sparse result sets will silently diverge (e.g., a deleted document still surfacing via BM25).

---

## 5. Persistent Metadata (co-owned with Member 4, future)

Once Member 4's Postgres layer is live, the retrieval module should record, per collection/index:

### Table: `retrieval_index_metadata`

| Column | Type | Notes |
|---|---|---|
| `embedding_model` | `str` | e.g. "bge-base-en-v1.5" |
| `embedding_dimension` | `int` | e.g. 768 |
| `reranker_model` | `str` | e.g. "bge-reranker-base" |
| `chunk_count` | `int` | Running count, useful for health checks / dashboards |
| `last_updated` | `timestamp` | |

This lets the system detect and warn if, say, someone tries to query an index built with a different embedding model than the one currently configured.

---

## 6. Index Update Data Flow

```
New Chunk objects from Member 1's IngestionResult
      │
      ▼
embed_documents(chunks) -> vectors
      │
      ├──────────────────────┐
      ▼                      ▼
Upsert into ChromaDB    Add to BM25 corpus
(by chunk_id)           (rebuild or incremental)
      │                      │
      └──────────┬───────────┘
                  ▼
        Both indexes in sync


Document deletion (document_id)
      │
      ▼
Delete all chunks with matching document_id
      │
      ├──────────────────────┐
      ▼                      ▼
Remove from ChromaDB    Remove from BM25 corpus
```

---

## 7. Open Items for Future Iteration

- Decide on ChromaDB → Qdrant migration trigger (e.g., once metadata filtering complexity or corpus size demands it)
- Consider persisting BM25 index to disk rather than rebuilding in-memory on every restart, once corpus size grows
- Add embedding-model version checks at query time (reject or warn if a query embedding's dimension doesn't match the index)
