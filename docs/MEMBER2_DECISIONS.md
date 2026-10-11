# Member 2 — Retrieval: Final Configuration and Measured Decisions

**Last updated:** Session 11, October 2026
**Evidence base:** a 40-page TCS annual report (118 chunks, tables rewritten as sentences) and 20 hand-written questions: 17 with answers in the report, 3 without. All numbers come from `scripts/run_comparison.py`, `table_experiment.py`, `chunk_size_experiment.py`, `chunk_budget_experiment.py`, `reranker_benchmark.py`, `embedding_benchmark.py`, `embedding_grid.py`, `diagnose.py`, `pool_size_test.py` and `final_check.py`. On 17 questions, one question moves a score by about 0.06.

> **Read this first.** Every choice below was made by looking at the same 17 questions, so the numbers are somewhat optimistic. The large effects (the embedding model) are far above that noise. The small ones (bge-small against bge-base) are not.

---

## 1. Final configuration (v1, revised)

Built by `app/retrieval/factory.py` → `build_default_retriever()`.

| Setting | Value |
|---|---|
| Embedding model | `BAAI/bge-small-en-v1.5`, 384 dimensions, normalized vectors |
| Query prefix | `Represent this sentence for searching relevant passages: ` (added to queries only; applied automatically for bge models) |
| Retrieval | meaning search only; results ordered by `dense_score` (cosine similarity) |
| Keyword search (BM25) + fusion | **off by default**, switch: `use_keyword=True` |
| Reranker | **off by default**, switch: `reranker_model="cross-encoder/ms-marco-MiniLM-L-6-v2"` |
| Candidates fetched (`fetch_k`) | 30 (only matters when keyword search or the reranker is on) |
| Table chunks | rewritten as sentences by the ingestion pipeline (`app/ingestion/table_format.py`) |
| Chunking | as produced by Member 1's pipeline (average 88 tokens on the test document) |
| Vector store | ChromaDB, in memory or persisted; refuses to open a collection built with a different model |
| Latency (CPU, 118 chunks, 100 timings) | p50 20 ms, p95 23 ms, max 24 ms |
| Result on the 17 scorable questions (top 10) | Recall@5 0.882, Recall@10 0.912, MRR 0.753, NDCG@10 0.792 |

---

## 2. Measured decisions

### 2.1 Embedding model → `bge-small-en-v1.5`

Same chunks, same 17 questions, top 10. Avg ms per query on this CPU.

| Setup | Model | Recall@5 | Recall@10 | MRR | NDCG@10 | ms |
|---|---|---|---|---|---|---|
| Meaning only | MiniLM (384-d) | 0.794 | 0.853 | 0.542 | 0.615 | 13 |
| Meaning only | **bge-small (384-d)** | 0.882 | 0.912 | 0.753 | 0.792 | 23 |
| Meaning only | bge-base (768-d) | 0.912 | 0.941 | 0.767 | 0.810 | 46 |
| Meaning only | multi-qa-mpnet (768-d) | 0.794 | 0.794 | 0.657 | 0.680 | 48 |
| Hybrid + rerank | MiniLM | 0.853 | 0.941 | 0.670 | 0.737 | 1090 |
| Hybrid + rerank | bge-small | 0.853 | 0.882 | 0.664 | 0.720 | 1136 |
| Hybrid + rerank | bge-base | 0.853 | 0.941 | 0.670 | 0.737 | 1082 |

Index build for 118 chunks: MiniLM 2.0 s, bge-small 5.0 s, bge-base 15.1 s, mpnet 17.8 s.

**Decision.** bge-small. The move from MiniLM is a large effect (MRR 0.542 → 0.753). bge-small and bge-base differ by at most half a question (Recall@5 0.882 vs 0.912, MRR 0.753 vs 0.767), so the cheaper model wins: the same 384 dimensions, a third of the index time, half the query time. `multi-qa-mpnet` is rejected: lower Recall@10 and slower.
**Upgrade path.** bge-base, if Member 5's golden dataset shows a gap. Switching models means a full re-index.

### 2.2 Keyword search (BM25 + RRF fusion) → off by default

| bge-small, top 10 | Recall@5 | Recall@10 | MRR | NDCG@10 |
|---|---|---|---|---|
| Meaning only (shipped) | 0.882 | 0.912 | 0.753 | 0.792 |
| Hybrid (no reranker) | 0.765 | 0.765 | 0.629 | 0.655 |

By question style (from `final_check.py`):

| | Recall@5 | Recall@10 | MRR | NDCG@10 |
|---|---|---|---|---|
| exact-term questions (n=5): shipped | 1.000 | 1.000 | 0.800 | 0.852 |
| exact-term questions: + keyword | 1.000 | 1.000 | 0.900 | 0.926 |
| paraphrase questions (n=12): shipped | 0.833 | 0.875 | 0.733 | 0.766 |
| paraphrase questions: + keyword | 0.667 | 0.667 | 0.517 | 0.542 |

**Decision.** Off by default. Equal-weight fusion helped exact-term ranking by one question (q07, rank 2 → 1) and cost the paraphrase questions about two (q04 and q05 dropped out of the top 10). The feared weakness of dense-only search on exact identifiers did not appear: all five exact-term questions were found in the top 2.
**Turn it on when** a corpus is heavy in codes, clause numbers or acronyms. **Not tested:** fusion weights that favour the meaning list.

### 2.3 Reranker → off by default

- **It caps quality.** With any embedding model, every reranked setup lands at about Recall@5 0.853, MRR 0.67 and NDCG 0.73, at about 1.1 s per query. All of these are below bge meaning-only on Recall@5, MRR and NDCG.
- **L-6 against L-12 (tables as sentences, MiniLM candidates):**

| Reranker | Recall@10 | MRR | NDCG@10 | avg ms |
|---|---|---|---|---|
| ms-marco-MiniLM-L-6 | 0.941 | 0.670 | 0.737 | 1052 |
| ms-marco-MiniLM-L-12 | 0.941 | 0.688 | 0.736 | 1967 |

With the original pipe-format tables, L-12 looked better (MRR 0.683 against 0.591); sentence-form tables recovered most of that for free.
- **`bge-reranker-base` (the TRD's model): rejected.** 7.2 s per query and a lower Recall@10 (0.853 vs 0.941), with MiniLM candidates.

**Decision.** Off by default. If switched on, use `ms-marco-MiniLM-L-6-v2`. **Revisit** on a larger, noisier corpus, where rerankers often help more than on a 118-chunk document.

### 2.4 Table format → sentence form

Hybrid + reranker, MiniLM candidates, before and after rewriting 25 table chunks as sentences:

| | Original (pipe rows) | As sentences |
|---|---|---|
| MRR, 4 table questions | 0.229 | 0.562 |
| MRR, all 17 | 0.591 | 0.670 |
| NDCG@10, all 17 | 0.678 | 0.737 |
| Recall@5 / Recall@10 | 0.853 / 0.941 | 0.853 / 0.941 |

Two table questions (q13, q14) moved from rank 3 to rank 1. Meaning search alone did not benefit.

**Decision.** Adopted. Pipe-separated rows hurt the reranker, and sentence form costs nothing. Implemented in the pipeline, so the parsers and their tests are untouched. Chunk IDs and the schema are unchanged. With the shipped retriever the four table questions score MRR 0.750.
**Basis:** four table questions, two of which moved.

### 2.5 Chunk size → keep as ingested

Share of right facts found within a text budget (Hybrid + rerank, MiniLM, original tables):

| Chunking (avg tokens) | 400 tok | 600 tok | 1000 tok | 1500 tok |
|---|---|---|---|---|
| as ingested (88) | 0.735 | 0.794 | 0.882 | 0.941 |
| merged to 150 (108) | 0.706 | 0.824 | 0.853 | 0.912 |
| merged to 250 (168) | 0.676 | 0.824 | 0.853 | 0.853 |
| merged to 400 (254, about one chunk per page) | 0.794 | 0.912 | 0.912 | 0.912 |

**Decision.** Keep the current chunking. Merging to about one chunk per page was ahead by one or two questions at tight budgets (600 tokens or less), half a question at 1000 and behind at 1500. It would also change every chunk ID and keep only the first section title of a merged chunk. The result at 150 and 250 was not smooth, which points to noise.
**Revisit** when the golden dataset has 30–50 questions, or if Member 3's generator has a small context window. This was measured with MiniLM and the reranker, before the final configuration.

### 2.6 Candidate pool

For hybrid + reranker (MiniLM, original tables), a pool of 20 matched a pool of 30 on Recall@10 (0.941), MRR (0.592 vs 0.591) and NDCG@10 (0.679 vs 0.678). In the shipped dense-only mode the pool only caps how many candidates are fetched. `fetch_k` stays a parameter and must be re-tested when the corpus grows.

---

## 3. Diagnoses

### 3.1 q19: wording mismatch, a planner problem

"What was the company's profit after tax in the October-to-December quarter of the year before FY26?" The right chunk (#58, page 20) is a table with "Q3 FY25" and "Net income". With the earlier pipeline it was meaning-search position 30 of 118, never found by keyword search (no shared word), outside the 30-chunk pool, and scored -8.40 by the reranker. The competing chunks matched the question's wording. Rewritten as "Net income Q3 FY25", it reached meaning rank 2, keyword rank 1 and reranked rank 2 (an upper bound: we chose the words). The shipped retriever still misses q19.
**Conclusion.** The index can find the table. The fix is query rewriting in Member 3's planner (relative periods → fiscal quarters, term variants).

### 3.2 q16: a two-fact question

"How did the value of new deals from the biggest market change over the year, and roughly what portion of revenue does that market make up?" The shipped retriever finds one of the two facts, at rank 10. Answering needs two lookups. **Conclusion.** The planner should split it into sub-queries (for example "North America total contract value FY26 and FY25" and "North America share of revenue"), and the retriever is called once per sub-query.

---

## 4. No-evidence behaviour (defined)

1. **Retrieval never decides that there is no answer.** It returns the top chunks even when none contains the answer.
2. **Empty results only when** the query is empty or whitespace, the index is empty, or a filter matches nothing.
3. **Reranker scores cannot serve as a cutoff** (measured earlier: a correct answer scored -9.9, a wrong chunk +2.7).
4. **Dense similarity shows a weak signal, not a rule.** Top-1 dense score for the shipped retriever: answerable questions min 0.633, median 0.707, max 0.830; unanswerable questions q17 0.621, q18 0.637, q20 0.630. A cutoff near 0.656 keeps 15 of 17 answerable questions and lets none of the 3 unanswerable through. But one answerable question (0.633) sits inside the unanswerable band, the cutoff was found on the same data, and only 3 negatives exist.
5. **The decision belongs to Member 3's fact-checker.** It checks each claim against the retrieved text; if none is supported, the answer is "I don't have sufficient evidence in the provided documents." A low top-1 similarity can be passed to the fact-checker as a hint, but calibrate any cutoff on Member 5's golden dataset with many unanswerable questions first.
6. **The hard case is q17:** a chunk on the right topic that does not contain the figure. The fact-checker must confirm that the specific figure appears.

---

## 5. Deviations from the PRD / TRD defaults

| Requirement | Status |
|---|---|
| PRD FR4 / G3: fuse dense and BM25 with RRF | Implemented, tested, **off by default** (Section 2.2) |
| PRD FR5 / G4, TRD: cross-encoder reranking, `bge-reranker-base` | Implemented, tested, **off by default**; `bge-reranker-base` benchmarked and rejected (Section 2.3) |
| TRD: benchmark at least three embedding models | Done: MiniLM, bge-small, bge-base, multi-qa-mpnet |
| PRD: p95 latency reported | Done: 23 ms on this CPU and corpus; about 1.1 s with the reranker |
| PRD: Context Precision / Recall ≥ 0.80 (RAGAS) | Not measured here; Member 5's harness |

The deviations are deliberate and based on measurement.

---

## 6. Limits and revisit triggers

| Limit | Revisit when |
|---|---|
| 17 questions on one document; choices tuned on the same set | Member 5's golden dataset exists: re-measure the shipped configuration on questions we never looked at |
| 118 chunks | The corpus grows: re-test the reranker, keyword search, `fetch_k` and latency |
| Only five exact-term questions | A corpus with many identifiers is added |
| Equal-weight RRF only | Someone wants to try dense-weighted fusion |
| Chunk size measured with MiniLM and the reranker | The golden dataset has 30–50 questions |
| p95 measured on one CPU, 118 chunks | Member 4's deployment target is known |

## 7. Open items

- Candidate counts for the agent trace: proposal and team sync (see `docs/MEMBER3_HANDOFF.md`, Section 6)
- BM25 is in memory and rebuilt from the vector store after a restart
- ChromaDB → Qdrant and HNSW tuning, only if scale demands it
