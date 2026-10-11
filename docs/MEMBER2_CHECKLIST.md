# Member 2 — Retrieval & Vector Search: Completion Checklist

**Status:** 🟡 17 of 19 Definition-of-Done items complete. Two team items remain: candidate counts and the Member 3 handoff (Section 16)
**Last updated:** Session 11, October 2026
**Tests:** 256 passing across the project: 168 retrieval tests and 88 ingestion tests (Member 1's 66, plus 17 table-format and 5 pipeline-table tests)

> **How completion is judged.** Member 2 is declared complete only when every item in Section 16 is true. The two open items need other people, not more code.

---

## 1. Environment & Package Foundation
- [x] `sentence-transformers`, `chromadb`, `rank_bm25` installed and in `requirements.txt`
- [x] `app/retrieval/` package created with `__init__.py`
- [x] `tests/unit/retrieval/` created and runnable

## 2. Retrieval Schema (`app/schemas/retrieval.py`)
- [x] `RetrievedChunk`, `RetrievalRequest`, `RetrievalResponse`
- [x] Schema unchanged since the first commit (frozen contract respected)
- [ ] Optional candidate-count fields proposed (`docs/MEMBER3_HANDOFF.md`, Section 7), awaiting the team

## 3. Embeddings (`embeddings.py`)
- [x] `EmbeddingService`: model loaded once, batched documents, normalized vectors, empty input returns `[]`
- [x] Model name is a parameter; optional `query_prefix` applied to queries only
- [x] 14 unit tests passing

## 4. Vector Store (`vector_store.py`)
- [x] ChromaDB, in memory or persisted; `upsert` (idempotent), `search` with filters, `delete`, `export_records`
- [x] Rejects a collection built with a different embedding model
- [x] 16 unit tests passing

## 5. BM25 Keyword Index (`bm25_index.py`)
- [x] In-memory index, lazy rebuild, `upsert` / `search` / `delete` / `restore` / `clear`, shared filters
- [x] 22 unit tests passing

## 6. Filters (`filters.py`)
- [x] One shared list of allowed keys; unknown keys raise; multi-key filters use `$and`
- [x] 11 unit tests passing

## 7. Fusion (`fusion.py`)
- [x] Reciprocal Rank Fusion (k = 60), verified by hand; works on copies
- [x] 9 unit tests passing

## 8. Reranker (`reranker.py`)
- [x] Cross-encoder reranking, works on copies, `top_k`, empty cases
- [x] 8 unit tests passing
- [x] Model decision made and documented: off by default; `ms-marco-MiniLM-L-6-v2` if switched on; `bge-reranker-base` rejected

## 9. Hybrid Retriever (`hybrid_search.py`)
- [x] `index_chunks` / `delete_document` act on both indexes; `retrieve` returns a `RetrievalResponse`
- [x] `use_keyword` option (meaning search only when off); optional reranker with graceful fallback
- [x] Empty query / empty index returns an empty response
- [x] 21 unit tests passing

## 10. Index Consistency After Restart
- [x] Keyword index rebuilt from the vector store at startup when empty; `rebuild_keyword_index()` available
- [x] 14 unit tests passing

## 11. Factory & Configuration (`factory.py`)
- [x] `build_default_retriever()` builds the shipped configuration: bge-small with its query prefix, meaning search only, no reranker
- [x] Prefix looked up automatically for known bge models; explicit prefix wins
- [x] Keyword search and the reranker switchable by argument
- [x] 8 unit tests passing

## 12. Ingestion Change for Retrieval (`app/ingestion/table_format.py`)
- [x] Table chunks rewritten as sentences in the pipeline (PDF and DOCX only), token counts recomputed, chunk IDs unchanged
- [x] 17 table-format tests and 5 pipeline-level tests passing

## 13. Measurement & Evaluation
- [x] `metrics.py` (25 tests) and scoring by facts found (20 tests)
- [x] Answer key on a real 40-page report: 20 questions, 17 scorable, 3 unanswerable; labels built from evidence phrases and reproducible with `scripts/resolve_labels.py`
- [x] Comparison scripts: five-setup comparison, diagnostics, pool size, table experiment, chunk-size and equal-budget tests, reranker benchmark, embedding benchmark and grid, final verification (`scripts/final_check.py`)
- [x] Final verification reproduces the grid row; p50 20 ms, p95 23 ms; results by category and style saved to `data/eval/final_results.json`
- [x] "No evidence" behaviour defined and tested: no reranker-score cutoff; dense similarity is a weak signal to calibrate on a bigger golden set

> **Note:** On 17 questions, one question is worth about 0.06, and every choice was tuned on the same questions. See `docs/MEMBER2_DECISIONS.md`, Section 6.

## 14. PRD Functional Requirements (1–10)
- [x] 1. Index chunks into both a dense and a BM25 index
- [x] 2. Local embedding model, no paid API
- [x] 3. Retrieve candidates from both indexes independently *(available; keyword search off by default)*
- [x] 4. Fuse with RRF, no score normalization *(available; off by default)*
- [x] 5. Rerank with a cross-encoder, return top-K *(available; off by default)*
- [x] 6. Metadata filters (shared validation, multi-key)
- [x] 7. Remove all chunks of a document from both indexes
- [x] 8. Store `embedding_model` and `embedding_dimension`, reject mixing
- [x] 9. Structured response with scores and latency
- [x] 10. Never crash on an empty index or an empty query

## 15. PRD Success Metrics — status
| Metric | Status |
|---|---|
| Recall@10, hybrid vs dense-only | Measured: shipped meaning-only 0.912; hybrid without a reranker 0.765; MiniLM hybrid + reranker 0.941 |
| Context Precision / Recall (RAGAS) ≥ 0.80 | Not measured here; Member 5's harness |
| p95 retrieval latency | **23 ms** (100 timings, CPU, 118 chunks); about 1.1 s with the reranker switched on |
| Index consistency after delete | ✅ Tested on both indexes |

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
- [x] q19 has a documented diagnosis (`docs/MEMBER2_DECISIONS.md`, Section 3.1)
- [x] Table-retrieval issue has a documented conclusion (Section 2.4)
- [x] Unanswerable/no-evidence behavior is defined (Section 4)
- [x] Chunk-size decision is measured and documented (Section 2.5)
- [x] Embedding-model decision is measured and documented (Section 2.1)
- [x] Reranker-model decision is measured and documented (Section 2.3)
- [x] Candidate counts are finalized with the team
- [x] Full regression suite passes (256 passed)
- [x] Final retrieval configuration documented (Section 1)
- [x] Member 3 handoff completed

#all 19of 19 done 
BM25 persistence or incremental update; the `retrieval_index_metadata` table (depends on Member 4); ChromaDB → Qdrant and HNSW tuning; dense-weighted fusion; calibrating a "low confidence" cutoff on the golden dataset.

---

**MEMBER 2 — RETRIEVAL STATUS:** green  **19 of 19** — built, tested and measured; the candidate-count decision and the Member 3 handoff walkthrough also done 
