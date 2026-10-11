# Technical Requirements Document (TRD)
## Module: Retrieval & Vector Search
### Owner: Member 2 — Retrieval & Vector Search Engineer
### Project: Enterprise RAG Assistant
### Date: September 2026

---

## 1. Scope

Technical design for the retrieval pipeline: embedding generation, dense vector indexing, BM25 sparse indexing, Reciprocal Rank Fusion, and cross-encoder reranking.

---

## 2. Architecture Overview

```
Chunk objects (from Member 1's IngestionResult)
      │
      ▼
Embedding service (sentence-transformers)
      │
      ├──────────────────────┐
      ▼                      ▼
Dense Vector Index      BM25 Sparse Index
(ChromaDB, dev)         (rank_bm25)
      │                      │
      └──────────┬───────────┘
                  ▼
     Reciprocal Rank Fusion (RRF)
                  │
                  ▼
        Top-N fused candidates
                  │
                  ▼
      Cross-Encoder Reranker
        (bge-reranker-base)
                  │
                  ▼
      Top-K RetrievedChunk results
                  │
                  ▼
          RetrievalResponse
```

---

## 3. Tech Stack

| Component | Tool | Reason |
|---|---|---|
| Language | Python 3.11+ | Matches Member 1's environment; async support, ecosystem |
| Embeddings | `sentence-transformers` (bge-base or e5-large) | Local, open-source, reproducible, no external API dependency |
| Vector store | ChromaDB (dev) → Qdrant (prod-style) | Chroma = fast iteration; Qdrant = filters + payload + prod credibility |
| Sparse search | `rank_bm25` | Lightweight, no extra infra needed for MVP |
| Fusion | Reciprocal Rank Fusion (custom implementation) | No score normalization needed across heterogeneous distributions |
| Reranker | `sentence-transformers` CrossEncoder (`bge-reranker-base`) | High-quality second-stage ranking; slower but more accurate than bi-encoder similarity alone |
| Schema validation | Pydantic v2 | Matches Member 1's shared contract style |
| Testing | `pytest` + fixtures | Consistent with Member 1's testing approach |

---

## 4. Module Breakdown

```
app/retrieval/
├── embeddings.py       — wraps sentence-transformers: embed_documents(chunks), embed_query(query)
├── vector_store.py     — ChromaDB collection manager: upsert(chunks), delete(document_id), search(query, k)
├── bm25_index.py       — BM25 index: build, add, remove, search
├── fusion.py           — Reciprocal Rank Fusion implementation
├── reranker.py         — Cross-encoder reranking stage
└── hybrid_search.py    — orchestrates: embed query -> dense search + sparse search -> RRF -> rerank -> RetrievalResponse
```

---

## 5. Interface Contract (frozen, shared with Members 1, 3, 4, 5)

Input side (consumed from Member 1 — already frozen, do not modify):
```python
# app/schemas/document.py (Member 1's contract — reference only)
class Chunk(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    token_count: int
    metadata: ChunkMetadata
```

Output side (this module's new contract):
```python
# app/schemas/retrieval.py

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
    filters: dict | None = None   # e.g. {"document_id": "abc123"}


class RetrievalResponse(BaseModel):
    query: str
    results: list[RetrievedChunk]
    embedding_model: str
    reranker_model: str
    latency_ms: float
```

Any change to this schema requires a team sync — Members 3, 4, and 5 all depend on it.

---

## 6. Embedding Strategy

- Benchmark at least: `all-MiniLM-L6-v2` (fast baseline), `bge-base` / `bge-small` family, `multi-qa-mpnet-base-dot-v1`
- Store `embedding_model` and `embedding_dimension` alongside the index — never mix vectors from two different models in the same collection
- Batch embedding calls for ingestion (don't embed one chunk at a time)
- Use the model's dedicated query/document encoding methods where the model supports asymmetric encoding (e.g., `encode_query()` vs `encode_document()`)

---

## 7. Hybrid Search & Fusion

```python
# app/retrieval/fusion.py (sketch)

def reciprocal_rank_fusion(dense_results: list[str], sparse_results: list[str], k: int = 60) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for rank, chunk_id in enumerate(dense_results):
        scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (k + rank + 1)
    for rank, chunk_id in enumerate(sparse_results):
        scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
```

- Fetch broad from each source (e.g., top-30 to top-50 per method) before fusing
- RRF avoids needing to normalize dense cosine-similarity scores against BM25's unbounded scores — this is why RRF is preferred over a naive weighted sum

---

## 8. Reranking

- Retrieve broad (top-30) cheaply via dense+sparse+RRF, then rerank narrow (top-5 to top-8) with the cross-encoder — never rerank the full corpus (too slow)
- Cross-encoders jointly process `(query, passage)` pairs — more accurate than bi-encoder cosine similarity, but significantly more expensive per comparison, hence the fetch-broad/rerank-narrow split

---

## 9. Error Handling

| Failure case | Behavior |
|---|---|
| Empty index (no documents ingested yet) | Return `RetrievalResponse(results=[])`, not an error |
| Empty query string | Return `RetrievalResponse(results=[])`, not an error |
| Embedding model fails to load | Raise a clear startup-time error (fail fast, not silently) — this is a configuration issue, not a per-query one |
| `document_id` filter matches nothing | Return `RetrievalResponse(results=[])`, not an error |
| Reranker unavailable/slow (future: timeout) | Fall back to fused (pre-rerank) ordering rather than failing the whole request |

---

## 10. Testing Plan

Unit tests required for:
- Embedding a batch of chunks produces vectors of the expected dimension
- Dense search returns results ordered by similarity
- BM25 search correctly favors exact keyword matches over semantically-similar-but-lexically-different text
- RRF fusion correctly combines two ranked lists (verify against a hand-computed example)
- Reranker reorders candidates sensibly for a known query/passage pair
- `delete(document_id)` removes chunks from both dense and sparse indexes
- Empty index / empty query returns empty results, not an exception
- Metadata filtering (`document_id`) correctly restricts search scope

---

## 11. Performance Considerations (future scaling)

- Tune vector index parameters (e.g., HNSW `ef_construction`, `M`) once corpus size is realistic — don't over-tune on a toy dataset
- Consider batching reranker calls if latency becomes a bottleneck
- Revisit ChromaDB → Qdrant migration once metadata filtering or scale needs grow beyond Chroma's dev-friendly defaults
