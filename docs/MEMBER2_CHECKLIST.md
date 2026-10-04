# Member 2 — Retrieval & Vector Search: Completion Checklist

**Status:** 🟡 IN PROGRESS — 11 of 19 Definition-of-Done items complete (Section 16)
**Last updated:** Session 10, October 2026
**Tests:** 148 retrieval tests written and passing (214 across the project including Member 1's 66); the full regression run is still to be confirmed (Section 16)

> **How completion is judged.** Member 2 is declared complete only when every item in Section 16 is true. An earlier version of this file called the module "done (core scope)" with the benchmarks deferred. The stricter list below replaces that: the module is built and tested, but the measured decisions (chunk size, embedding model, reranker model) and the team items are still open.

---

## 1. Environment & Package Foundation
- [x] `sentence-transformers`, `chromadb`, `rank_bm25` installed and in `requirements.txt`
- [x] `app/retrieval/` package created with `__init__.py`
- [x] `tests/unit/retrieval/` created and runnable

## 2. Retrieval Schema (`app/schemas/retrieval.py`)
- [x] `RetrievedChunk` (dense / sparse / fused / rerank scores, `page_number`, `section_title`)
- [x] `RetrievalRequest` (`query`, `top_k`, `filters`)
- [x] `RetrievalResponse` (results, `embedding_model`, `reranker_model`, `latency_ms`)
- [x] Schema unchanged since first commit (frozen contract respected)

## 3. Embeddings (`embeddings.py`)
- [x] `EmbeddingService` wraps `all-MiniLM-L6-v2` (384 dimensions), model loaded once
- [x] Batched `embed_documents`, single `embed_query`; vectors normalized
- [x] Empty and whitespace input returns `[]`
- [x] Model name is a parameter (swappable)
- [x] 9 unit tests passing

## 4. Vector Store (`vector_store.py`)
- [x] ChromaDB collection manager, in-memory or persisted to disk
- [x] `upsert` by `chunk_id` (idempotent), `search` with filters, `delete` by `document_id`
- [x] `embedding_model` / `embedding_dimension` stored; mixing models is rejected
- [x] `export_records` reads every chunk back out (used to rebuild BM25)
- [x] 16 unit tests passing

## 5. BM25 Keyword Index (`bm25_index.py`)
- [x] In-memory index with lazy rebuild after changes
- [x] `upsert`, `search`, `delete`, `count`, `restore`, `clear`
- [x] Same metadata filters as the vector store; returns only chunks sharing a word with the query
- [x] `sparse_score` set, `dense_score` left `None`
- [x] 22 unit tests passing

## 6. Filters (`filters.py`) — added after the gap review
- [x] One shared list of allowed filter keys for both indexes
- [x] Unknown keys raise a clear error; multi-key filters converted to ChromaDB's `$and` format
- [x] BM25 stores `content_hash`, so both indexes accept the same filters
- [x] 11 unit tests passing

## 7. Fusion (`fusion.py`)
- [x] Reciprocal Rank Fusion, k = 60; worked example verified by hand (A, C, B, D)
- [x] Works on copies; counts a chunk once per list; keeps both scores; `limit` supported
- [x] 9 unit tests passing

## 8. Reranker (`reranker.py`)
- [x] Cross-encoder reranking, works on copies, sorted best first, `top_k` supported
- [x] Empty query / empty candidates returns `[]`
- [x] 8 unit tests passing
- [ ] Uses `cross-encoder/ms-marco-MiniLM-L-6-v2`, not the TRD's `bge-reranker-base`; the comparison is still to be measured (Section 16)

## 9. Hybrid Retriever (`hybrid_search.py`)
- [x] `index_chunks` / `delete_document` act on both indexes
- [x] `retrieve(RetrievalRequest) -> RetrievalResponse`: fetch from each index, fuse, rerank to `top_k`
- [x] If the reranker fails, falls back to the fused order and says so in `reranker_model`
- [x] Empty query / empty index returns an empty response
- [x] 14 unit tests passing

## 10. Index Consistency After Restart — added after the gap review
- [x] Found by `scripts/check_gaps.py`: BM25 came back empty after a restart while ChromaDB kept its data
- [x] `HybridRetriever` rebuilds the keyword index from ChromaDB at startup when BM25 is empty
- [x] `rebuild_keyword_index()` available to force a rebuild
- [x] 14 unit tests passing

## 11. Measurement & Evaluation
- [x] `metrics.py`: Recall@K, reciprocal rank, NDCG@K, mean (25 tests)
- [x] Scoring by facts found, not chunks found: `score_against_needs` (20 tests)
- [x] Answer key on a real 40-page TCS annual report: 20 questions, 17 scorable, 3 unanswerable
- [x] `scripts/resolve_labels.py` turns evidence phrases into chunk IDs and checks the labels are fresh
- [x] `scripts/run_comparison.py`: five setups compared, saved to `data/eval/comparison_results.json`
- [x] `scripts/diagnose.py`: per-question diagnosis and rerank-score analysis
- [x] `scripts/pool_size_test.py`: pool sizes 5, 10, 20, 30 compared; a pool of 20 matches 30 for hybrid on this document
- [x] "No evidence" cutoff on rerank score tested: **no single cutoff works** on this data

> **Note:** On 17 questions, one question is worth about 0.06, so small differences are noise. Results and caveats are in the README and in `docs/MEMBER2_DECISIONS.md`.

## 12. PRD Functional Requirements (1–10)
- [x] 1. Index chunks into both a dense and a BM25 index
- [x] 2. Local embedding model, no paid API
- [x] 3. Retrieve candidates from both indexes independently
- [x] 4. Fuse with RRF, no score normalization
- [x] 5. Rerank with a cross-encoder, return top-K
- [x] 6. Metadata filters (shared validation, multi-key)
- [x] 7. Remove all chunks of a document from both indexes
- [x] 8. Store `embedding_model` and `embedding_dimension`, reject mixing
- [x] 9. Structured response with all scores and latency
- [x] 10. Never crash on an empty index or an empty query

## 13. PRD Success Metrics — status
| Metric | Status |
|---|---|
| Recall@10, hybrid vs dense-only | Documented: fusion alone 0.853 vs 0.853 (no gain); with the reranker 0.941 vs 0.853 (+0.088, about 1.5 of 17 questions) |
| Context Precision / Recall (RAGAS) ≥ 0.80 | Not measured here — Member 5's RAGAS harness |
| p95 retrieval latency | **Not measured.** Averages only: about 14 ms without the reranker, about 0.9 to 1.1 s with a 30-chunk pool (CPU, 118 chunks) |
| Index consistency after delete | ✅ Tested on both indexes |

## 14. Remaining Work (each item maps to Section 16)
| Open item | Definition-of-Done item | How it gets closed |
|---|---|---|
| Table chunks rank lower after reranking | Table-retrieval conclusion | `scripts/table_experiment.py` (original vs sentence-form table text), then write the conclusion |
| Average chunk is 88 tokens vs a 300–500 target | Chunk-size decision | Re-merge neighbouring chunks to several sizes, re-run the comparison, decide with Member 1 |
| Only `all-MiniLM-L6-v2` tested | Embedding-model decision | Benchmark at least `bge-small` and `multi-qa-mpnet-base-dot-v1` (TRD) |
| Small reranker used | Reranker-model decision | Benchmark `bge-reranker-base`, including latency |
| Trace counts (dense / keyword / fused / reranked) not exposed | Candidate counts finalized with the team | Team sync, because the schema is frozen |
| Not yet confirmed after the latest changes | Full regression suite passes | `pytest tests/ -v`, expect 214 passed |
| Settings documented as current, not final | Final retrieval configuration documented | Fill in after the decisions above |
| Doc written, walkthrough not yet held | Member 3 handoff completed | `docs/MEMBER3_HANDOFF.md` plus a short screen-share |

Other deferred items (not part of the 19): p95 latency percentiles, BM25 persistence/incremental update, the `retrieval_index_metadata` table (depends on Member 4), ChromaDB → Qdrant and HNSW tuning.

## 15. Hand-off Notes for Member 3
See `docs/MEMBER3_HANDOFF.md`.

## 16. Definition of Done
- [x] Embedding service implemented and tested
- [x] Vector retrieval implemented and tested
- [x] BM25 retrieval implemented and tested
- [x] RRF fusion implemented and tested
- [x] Reranking implemented and tested
- [x] Hybrid retrieval implemented and tested
- [x] Filtering implemented and tested
- [x] Retrieval metrics implemented
- [x] Evaluation dataset/labels reproducible
- [x] q19 has a documented diagnosis (`docs/MEMBER2_DECISIONS.md`, Section 1)
- [ ] Table-retrieval issue has a documented conclusion
- [x] Unanswerable/no-evidence behavior is defined (`docs/MEMBER2_DECISIONS.md`, Section 3)
- [ ] Chunk-size decision is measured and documented
- [ ] Embedding-model decision is measured and documented
- [ ] Reranker-model decision is measured and documented
- [ ] Candidate counts are finalized with the team
- [ ] Full regression suite passes
- [ ] Final retrieval configuration documented
- [ ] Member 3 handoff completed

---

**MEMBER 2 — RETRIEVAL STATUS:** 🟡 **IN PROGRESS** — built and tested; 8 Definition-of-Done items remain
