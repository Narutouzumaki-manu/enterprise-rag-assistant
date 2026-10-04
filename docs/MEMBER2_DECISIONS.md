# Member 2 — Retrieval: Diagnoses, Decisions and Current Configuration

**Last updated:** Session 10, October 2026
**Evidence base:** a 40-page TCS annual report (118 chunks), 20 hand-written questions (17 scorable, 3 unanswerable). All numbers come from `scripts/diagnose.py`, `scripts/run_comparison.py` and `scripts/pool_size_test.py`. On 17 questions, one question moves a score by about 0.06.

---

## 1. q19 diagnosis

**Question:** "What was the company's profit after tax in the October-to-December quarter of the year before FY26?"
**Right chunk:** #58 (page 20), a table with Q1 to Q4 FY25 columns and a "Net income" row.

| Stage | Result |
|---|---|
| Meaning search | position 30 of 118 |
| Keyword search | not found (no word in common with the chunk) |
| Fused list | position 77 of 118 |
| Hybrid + rerank, 30-chunk pool | not in the pool |
| Reranker score for the right chunk, shown to it directly | -8.40 (the lowest right-chunk score of any question) |

The chunks that won were #110 (a snapshot of the quarter ended 30 June 2026, score 2.71), #34 (four quarters of FY26 against FY25, 1.68) and #62 (a "Reported profit after tax" table, 1.39).

**Diagnosis.** A wording mismatch, not an index fault. The question describes the period in words ("October-to-December quarter of the year before FY26") and calls the figure "profit after tax". The table says "Q3 FY25" and "Net income". Nothing in either index connects them.

**Test.** With the query rewritten as "Net income Q3 FY25": meaning search rank 2 of 118, keyword search rank 1, hybrid + rerank rank 2. This is an upper bound, because we chose the words knowing what the table says.

**Conclusion.** The retrieval stack finds this chunk when the query uses the document's own terms. The fix is in query wording, which is Member 3's planner: rewrite relative periods into fiscal quarters ("October-to-December of the year before FY26" → "Q3 FY25") and try term variants (profit after tax / net income). No retrieval change is needed. This rests on one question and a rewrite we wrote ourselves.

---

## 2. Candidate pool size and the keyword half

Both reranked setups hand the reranker N candidates. "Pool recall" is the share of right facts inside the pool before reranking.

| Pool size | Meaning pool recall | Hybrid pool recall | Meaning + rerank (Recall@10 / MRR) | Hybrid + rerank (Recall@10 / MRR) |
|---|---|---|---|---|
| 5 | 0.794 | 0.853 | 0.794 / 0.583 | 0.853 / 0.608 |
| 10 | 0.853 | 0.853 | 0.853 / 0.538 | 0.853 / 0.580 |
| 20 | 0.853 | 0.941 | 0.853 / 0.535 | 0.941 / 0.592 |
| 30 | 0.971 | 0.941 | 0.912 / 0.592 | 0.941 / 0.591 |

**What it shows.**
- The keyword half builds a better pool at sizes 5 and 20 and ties at 10. At 30 the order flips, because the meaning pool then contains q19's chunk (position 30) and the fused pool does not.
- After reranking, hybrid is at least as good on Recall@10 at every size. The gaps come from one or two questions: q06 (found by keyword search), q16 (its second fact) and q12 (the reverse at size 10).
- For hybrid, a pool of 20 matches a pool of 30 on Recall@10 (0.941), MRR (0.592 vs 0.591) and NDCG@10 (0.679 vs 0.678), and reranks a third fewer chunks.

**Conclusion.** Keyword search adds a small edge when the pool is small, and the edge shrinks as the pool grows. On 118 chunks the effect is at most two questions. A pool of 20 is enough here.

**Limits.** This does not carry over to larger collections, where the same pool is a much smaller share of the corpus. `fetch_k` stays a parameter and must be re-tested when the corpus grows.

---

## 3. No-evidence behaviour (defined)

1. **Retrieval never decides that there is no answer.** It returns the top-k chunks even when none contains the answer. For the three unanswerable questions it returned: q17, the CSR chunk (#108), on-topic but with no spend figure; q18 and q20, loosely related chunks.
2. **Retrieval returns an empty result only when** the query is empty or whitespace, the index is empty, or a filter matches nothing.
3. **Rerank scores cannot be used as a "no evidence" cutoff.**
   - Unanswerable top-1 scores: q17 +1.92, q18 -4.41, q20 -1.81.
   - Answerable top-1 scores range from -9.88 to +8.89.
   - q06 is correct at rank 1 with a score of -9.88. q19's wrong top chunk scores +2.71, above q17.
   - Any cutoff that blocks all three unanswerable questions (about 2.0) also rejects 7 of 17 answerable ones.
4. **The decision belongs to Member 3's fact-checker.** It checks each claim against the text of the retrieved chunks. If no claim is supported, the answer is "I don't have sufficient evidence in the provided documents."
5. **The hard case is q17:** a chunk that is on the right topic but does not contain the figure. The fact-checker has to confirm that the specific figure appears in the chunk.
6. **Not tested:** relative signals (the gap between the first and second score) and per-collection calibration. With three unanswerable questions, any threshold would be a guess.

---

## 4. Current retrieval configuration

| Setting | Value |
|---|---|
| Embedding model | `all-MiniLM-L6-v2`, 384 dimensions, normalized vectors |
| Vector store | ChromaDB (in-memory or persisted), `dense_score = 1 - distance / 2` |
| Keyword index | `rank_bm25` BM25Okapi, in memory; tokens are lowercase words and numbers; a chunk must share at least one word with the query |
| Fusion | Reciprocal Rank Fusion, k = 60, on rank positions only |
| Candidates per index (`fetch_k`) | 30 (20 gave the same quality on the test document) |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| Results returned | `RetrievalRequest.top_k`, default 5 (the backend passes 8) |
| Allowed filter keys | `document_id`, `source_type`, `page_number`, `section_title`, `content_hash`; unknown keys raise an error |
| Reranker failure | falls back to the fused order; `reranker_model` says so |
| Restart | the keyword index is rebuilt from ChromaDB when it is empty and ChromaDB is not |
| Latency (CPU, 118 chunks) | about 14 ms without the reranker, about 0.9 to 1.1 s with a 30-chunk pool (averages, not p95) |

This is the **current** configuration, not the final one. The open decisions below can change it.

---

## 5. Decisions still open

| Decision | What will decide it |
|---|---|
| Table-retrieval conclusion | `scripts/table_experiment.py`: original table text against sentence-form text |
| Chunk size | Re-merge neighbouring chunks to several target sizes and re-run the comparison; Member 1 owns the chunker |
| Embedding model | Benchmark `bge-small` and `multi-qa-mpnet-base-dot-v1` against MiniLM (the TRD asks for at least three) |
| Reranker model | Benchmark `bge-reranker-base` against the small model, including latency |
| Candidate counts for the agent trace | Team sync, because the response schema is frozen |
| Final configuration | Filled in once the decisions above are made |
