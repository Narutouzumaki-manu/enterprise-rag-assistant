# Product Requirements Document (PRD)
## Module: Retrieval & Vector Search
### Owner: Member 2 — Retrieval & Vector Search Engineer
### Project: Enterprise RAG Assistant
### Date: September 2026

---

## 1. Purpose

The Retrieval module is the second stage of the pipeline. It takes the `Chunk` objects produced by Member 1's ingestion module and makes them **searchable** — combining dense (semantic) and sparse (keyword) search, then reranking results so the Agent layer (Member 3) receives the most relevant evidence for answering a user's question.

If this module returns poor or irrelevant chunks, the agent layer has nothing good to reason over — no amount of clever prompting downstream can fix bad retrieval.

---

## 2. Problem Statement

Naive retrieval (embed the query, cosine-similarity against all chunks, take top-k) fails in predictable ways:
- Misses exact keyword/entity/acronym matches (e.g., product codes, legal clause numbers, "SOC 2 Type II") that dense embeddings blur over
- Returns semantically-similar-but-irrelevant chunks when the corpus is large
- Has no mechanism to re-rank candidates for precision — top-k by raw similarity is a weak relevance signal
- Cannot explain *why* a chunk was retrieved, making debugging and evaluation difficult

A hybrid, evaluated retrieval pipeline (dense + sparse + fusion + rerank) is required to meet the project's "not a tutorial" bar.

---

## 3. Goals

| Goal | Description |
|---|---|
| G1 | Build a dense vector index over all ingested `Chunk` objects using sentence-transformer embeddings |
| G2 | Build a BM25 sparse keyword index over the same corpus |
| G3 | Combine dense + sparse rankings via Reciprocal Rank Fusion (RRF) |
| G4 | Apply a cross-encoder reranker to the fused top-N candidates before returning final top-K |
| G5 | Support metadata filtering (e.g., by `document_id`, `source_type`) alongside semantic search |
| G6 | Expose a single, stable interface (`RetrievalRequest` → `RetrievalResponse`) for the Agent layer to consume |
| G7 | Keep the index updatable — support adding new chunks (on ingestion) and removing chunks (on document deletion) without a full rebuild |
| G8 | Measure retrieval quality quantitatively (Recall@K, MRR, NDCG) — not just "it looks relevant" |

---

## 4. Non-Goals

- This module does **not** parse or chunk documents (Member 1's responsibility) — it only consumes finished `Chunk` objects
- This module does **not** decide the final answer or perform fact-checking (Member 3's responsibility)
- This module does **not** own the API layer or database persistence of chat/session data (Member 4's responsibility)
- No UI — this module is called internally by the Agent layer, not directly by end users

---

## 5. Users of This Module

| User | How they use it |
|---|---|
| Member 1 (Ingestion) | Supplies `Chunk` objects via `IngestionResult` after a document is ingested |
| Member 3 (Agents) | Calls the retrieval interface with a query, receives ranked `RetrievedChunk` results with scores and citations |
| Member 4 (Backend/API) | May trigger index updates (add/delete) when documents are uploaded or removed via the API |
| Member 5 (Eval/QA) | Uses this module's outputs to compute Context Precision / Context Recall in the RAGAS harness |

---

## 6. Functional Requirements

1. Accept a list of `Chunk` objects (from Member 1) and index them into both a dense vector store and a BM25 sparse index
2. Compute embeddings for chunk text using a local sentence-transformers model (no hard dependency on a paid API)
3. Given a query string, retrieve top-N candidates from both dense and sparse indexes independently
4. Fuse the two ranked lists using Reciprocal Rank Fusion (RRF), without requiring score normalization
5. Rerank the fused candidates using a cross-encoder model, returning the final top-K
6. Support optional metadata filters (e.g., restrict search to one `document_id`)
7. Support removing all chunks belonging to a given `document_id` (for document deletion / re-ingestion)
8. Track and store `embedding_model` and `embedding_dimension` alongside the index, to prevent silently mixing incompatible embeddings later
9. Return a structured `RetrievalResponse` including per-chunk dense/sparse/fused/rerank scores and latency
10. Never crash on an empty index or empty query — fail gracefully with an empty result set

---

## 7. Success Metrics

| Metric | Target |
|---|---|
| Recall@10 (hybrid, vs. dense-only baseline) | Meaningful improvement over dense-only (document actual delta, not a fixed target) |
| Context Precision (RAGAS, post-rerank) | ≥ 0.80 |
| Context Recall (RAGAS) | ≥ 0.80 |
| p95 retrieval latency (dense + sparse + fusion + rerank) | Benchmarked and reported — no fixed target until real corpus size is known |
| Index consistency after delete | 100% — no orphaned chunks in either index after a document is removed |

---

## 8. Risks & Open Questions

- Embedding model choice affects both quality and dimension — must be frozen early and versioned (`embedding_model`, `embedding_dimension` stored in index metadata) so a future model swap doesn't silently corrupt the index
- BM25 index must be kept in sync with deletions — if a document is removed but BM25 isn't updated, stale chunks can still surface in sparse search results
- Reranker latency (cross-encoder is slower than embedding lookup) — needs benchmarking to decide fetch-broad/rerank-narrow parameters (e.g., top-30 → rerank → top-5)
- Chunk size assumptions from Member 1 (300–500 tokens) directly affect embedding quality and retrieval granularity — should be benchmarked together, not assumed independently

---

## 9. Dependencies on Other Members

- **Member 1**: supplies the frozen `Chunk` / `ChunkMetadata` / `IngestionResult` schema this module consumes directly — any schema change requires a team sync
- **Member 3**: consumes this module's `RetrievalResponse` as the tool call inside the agent graph's retrieval step
- **Member 4**: wires index add/delete operations into the `/ingest` and document-deletion API endpoints
- **Member 5**: uses this module's output for RAGAS Context Precision/Recall evaluation
