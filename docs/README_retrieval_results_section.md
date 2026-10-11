## Retrieval results

We measured retrieval on a real document instead of judging it by eye, and we let the measurements decide the design.

**Setup.** A 40-page TCS annual report (not included in this repo) goes through the ingestion pipeline (tables are rewritten as sentences) and becomes 118 chunks. We wrote 20 questions in our own words: 17 have answers in the report and 3 do not. Each answerable question is labelled with the chunk(s) that hold the answer, and the labels are found automatically from short evidence phrases, so no chunk ID is typed by hand.

**Metrics.**
- **Recall@K:** is the right chunk in the top K results? (K = 5 or 10)
- **MRR:** how close to the top is the first right chunk? (1 for first place, 0.5 for second, and so on)
- **NDCG@10:** how good is the whole ordering of the top 10?

A fact repeated in several chunks counts once, and a question that needs two facts gets partial credit for one.

### Results (17 scorable questions, top 10 results)

| Setup | Recall@5 | Recall@10 | MRR | NDCG@10 | ms/query |
|---|---|---|---|---|---|
| MiniLM, meaning search only | 0.794 | 0.853 | 0.542 | 0.615 | 13 |
| MiniLM + keyword search + reranker | 0.853 | 0.941 | 0.670 | 0.737 | 1090 |
| bge-small + keyword search (no reranker) | 0.765 | 0.765 | 0.629 | 0.655 | 26 |
| bge-small + reranker | 0.853 | 0.912 | 0.670 | 0.725 | 1145 |
| bge-base, meaning search only | 0.912 | 0.941 | 0.767 | 0.810 | 46 |
| **bge-small, meaning search only (shipped)** | **0.882** | **0.912** | **0.753** | **0.792** | **p95 23** |

Averages come from separate runs on one CPU; the shipped row is a p50/p95 over 100 timings (p50 20 ms).

### What the numbers say
- **The embedding model is the biggest lever.** Moving from MiniLM to bge-small, with meaning search alone, raises MRR from 0.542 to 0.753. bge-small and bge-base differ by at most half a question, so the cheaper one ships.
- **Merging keyword search hurt on this question set.** It helped exact-term ranking by one question (MRR 0.800 → 0.900 on five exact-term questions) and cost the paraphrase questions about two (Recall@5 0.833 → 0.667). The feared weakness of meaning-only search on exact terms did not show.
- **The small reranker capped quality.** Every reranked setup landed at about Recall@5 0.853, MRR 0.67 and about 1.1 s per query, below the shipped setup on Recall@5, MRR and NDCG.
- **Tables needed rewriting.** Pipe-separated table rows hurt the reranker; writing them as sentences lifted the table-question MRR from 0.229 to 0.562 with no loss of recall.
- **Chunk size stays as it is.** Merging chunks to about one per page helped only at tight text budgets and would change every chunk ID.
- **Keyword search and the reranker stay in the code as switches** (`use_keyword=True`, `reranker_model=...`), tested and off by default.
- **The two remaining misses are planner problems.** One question describes a quarter in words ("October-to-December of the year before FY26") while the table says "Q3 FY25", and one needs two lookups. Rewriting and splitting questions belongs to the agent layer.

### Limits
- 17 questions on one 118-chunk document, and every choice was tuned on those same questions, so the numbers are somewhat optimistic. One question moves a score by about 0.06; treat small gaps as noise.
- A larger, noisier corpus is where keyword search and a reranker are most likely to earn their place again.
- Only five questions test exact terms and codes.
- Latency is a CPU measurement on a small corpus.
- A "no answer" cutoff on the similarity score is not reliable: the unanswerable questions scored 0.62–0.64 and the answerable ones 0.63–0.83. The fact-checker decides.

### Reproduce
Download the report and save it as `data/eval/documents/tcs_annual_report.pdf`, then:

```
python -m scripts.resolve_labels
python -m scripts.final_check
python -m scripts.embedding_grid
```

Full decisions and the evidence behind each: `docs/MEMBER2_DECISIONS.md`.
