# Retrieval Evaluation Summary

## Metadata
- **Evaluation Timestamp**: `2026-11-11T06:34:30.955602+00:00`
- **Golden File SHA-256**: `9f78d9b82e4a7ccb2f2449cc28f45ea0a324e0c0507cb38938745ea8914bf5fc`
- **Dataset**: `app/eval/golden_questions.json` (v1.1, 34 questions: 25 answerable, 9 unanswerable)
- **Corpus**: `data/eval/documents/tcs_annual_report.pdf` (118 chunks)
- **Embedding Model**: `BAAI/bge-small-en-v1.5` (dimension: 384)
- **Reranker Model**: `cross-encoder/ms-marco-MiniLM-L-6-v2`

---

## 1. Overall Performance (All 25 Answerable Questions)

| Pipeline Variant | Recall@5 | Recall@10 | Recall@15 | Recall@20 | MRR | NDCG@10 | Avg Latency (ms) | P95 Latency (ms) |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `retrieval_dense` | 0.6133 | 0.7200 | 0.8600 | 0.9200 | 0.5230 | 0.5552 | 23.8 | 27.8 |
| `retrieval_keyword` | 0.6667 | 0.8200 | 0.8800 | 0.8800 | 0.6088 | 0.6437 | 24.8 | 27.9 |
| `retrieval_rerank` | 0.6533 | 0.7733 | 0.9200 | 0.9200 | 0.5564 | 0.6107 | 1124.5 | 1269.6 |

## 2. Independent Subset Performance (21 Questions Not Flagged SAME_FACT)

| Pipeline Variant | Recall@5 | Recall@10 | Recall@15 | Recall@20 | MRR | NDCG@10 | Avg Latency (ms) | P95 Latency (ms) |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `retrieval_dense` | 0.5635 | 0.6667 | 0.8333 | 0.9048 | 0.4321 | 0.4871 | 23.7 | 25.7 |
| `retrieval_keyword` | 0.6349 | 0.7857 | 0.8571 | 0.8571 | 0.5343 | 0.5856 | 24.8 | 27.9 |
| `retrieval_rerank` | 0.6190 | 0.7302 | 0.9048 | 0.9048 | 0.4958 | 0.5556 | 1107.5 | 1269.6 |

## 3. Breakdown by Category (All Answerable)

| Variant | Category | n | Recall@5 | Recall@10 | Recall@15 | Recall@20 | MRR | NDCG@10 | Avg Latency (ms) |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `retrieval_dense` | comparison | 1 | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 0.0000 | 0.0000 | 21.2 |
| `retrieval_dense` | cross_section | 2 | 0.6667 | 1.0000 | 1.0000 | 1.0000 | 0.6000 | 0.6444 | 23.2 |
| `retrieval_dense` | fact_lookup | 8 | 0.5625 | 0.6875 | 0.6875 | 0.7500 | 0.4844 | 0.5341 | 24.1 |
| `retrieval_dense` | multi_fact | 3 | 0.6667 | 1.0000 | 1.0000 | 1.0000 | 0.6111 | 0.6608 | 23.2 |
| `retrieval_dense` | numerical_comparison | 3 | 0.5000 | 0.5000 | 1.0000 | 1.0000 | 0.4444 | 0.3946 | 24.3 |
| `retrieval_dense` | table | 8 | 0.7500 | 0.7500 | 1.0000 | 1.0000 | 0.6042 | 0.6439 | 24.0 |
| `retrieval_keyword` | comparison | 1 | 0.0000 | 1.0000 | 1.0000 | 1.0000 | 0.1250 | 0.3155 | 24.8 |
| `retrieval_keyword` | cross_section | 2 | 0.3333 | 1.0000 | 1.0000 | 1.0000 | 0.6000 | 0.5550 | 24.8 |
| `retrieval_keyword` | fact_lookup | 8 | 0.5625 | 0.6875 | 0.7500 | 0.7500 | 0.5764 | 0.5757 | 22.7 |
| `retrieval_keyword` | multi_fact | 3 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.7500 | 0.8070 | 24.0 |
| `retrieval_keyword` | numerical_comparison | 3 | 0.5000 | 0.6667 | 0.6667 | 0.6667 | 0.5000 | 0.5083 | 25.5 |
| `retrieval_keyword` | table | 8 | 0.8750 | 0.8750 | 1.0000 | 1.0000 | 0.6917 | 0.7642 | 27.0 |
| `retrieval_rerank` | comparison | 1 | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 866.1 |
| `retrieval_rerank` | cross_section | 2 | 0.1667 | 0.6667 | 1.0000 | 1.0000 | 0.3000 | 0.3681 | 1228.2 |
| `retrieval_rerank` | fact_lookup | 8 | 0.5000 | 0.6250 | 0.7500 | 0.7500 | 0.4583 | 0.5033 | 1084.4 |
| `retrieval_rerank` | multi_fact | 3 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.7778 | 0.8569 | 1115.5 |
| `retrieval_rerank` | numerical_comparison | 3 | 0.6667 | 0.6667 | 1.0000 | 1.0000 | 0.5000 | 0.5645 | 1162.7 |
| `retrieval_rerank` | table | 8 | 0.8750 | 1.0000 | 1.0000 | 1.0000 | 0.7264 | 0.7802 | 1159.8 |

## 4. Breakdown by Style (All Answerable)

| Variant | Style | n | Recall@5 | Recall@10 | Recall@15 | Recall@20 | MRR | NDCG@10 | Avg Latency (ms) |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `retrieval_dense` | exact | 7 | 0.7143 | 0.7143 | 0.8571 | 0.8571 | 0.6429 | 0.6644 | 23.3 |
| `retrieval_dense` | paraphrase | 18 | 0.5741 | 0.7222 | 0.8611 | 0.9444 | 0.4764 | 0.5127 | 24.0 |
| `retrieval_keyword` | exact | 7 | 0.7143 | 0.7143 | 0.8571 | 0.8571 | 0.6190 | 0.6529 | 26.1 |
| `retrieval_keyword` | paraphrase | 18 | 0.6481 | 0.8611 | 0.8889 | 0.8889 | 0.6048 | 0.6400 | 24.4 |
| `retrieval_rerank` | exact | 7 | 0.8571 | 0.8571 | 0.8571 | 0.8571 | 0.6714 | 0.7158 | 1090.0 |
| `retrieval_rerank` | paraphrase | 18 | 0.5741 | 0.7407 | 0.9444 | 0.9444 | 0.5117 | 0.5698 | 1137.9 |

---

## 5. Unanswerable Questions & Dense Score Separation Analysis

Because no similarity cutoff is shipped, retrievers return `top_k=10` candidates even for questions whose answers do not exist in the document.

- **Answerable Top-1 Dense Similarity**: Min = `0.646`, Median = `0.782`, Max = `0.881`

| Unanswerable ID | Question | Top-1 Dense Score | Top-1 Chunk ID |
|---|---|:---:|:---:|
| `tcs-gold-09` | What was TCS's exact cash-and-investments balance at the end of Q3 FY26? | 0.875 | `9aa3eb0a` |
| `tcs-gold-24` | What share of the TCS workforce were women at the end of March 2026? | 0.723 | `bb091f2a` |
| `tcs-gold-25` | What were TCS's total carbon emissions in FY26? | 0.731 | `53b780ef` |
| `tcs-gold-26` | What were TCS's revenue and net profit for Q1 FY27? | 0.741 | `7c6edd4d` |
| `tcs-gold-27` | Who is the Chief Financial Officer of TCS? | 0.787 | `832c5924` |
| `tcs-gold-28` | What revenue growth guidance did TCS give for FY27? | 0.739 | `8d031b20` |
| `tcs-gold-29` | How many directors sit on the TCS board, and how many of them are independent? | 0.698 | `f62f0ef2` |
| `tcs-gold-30` | What was TCS's operating margin in Q4 FY26? | 0.836 | `7c6edd4d` |
| `tcs-gold-31` | What was TCS's revenue from India in FY26? | 0.804 | `4275a701` |

> [!IMPORTANT]
> **Can a simple dense similarity threshold separate unanswerable questions?**
> **No.** The unanswerable top-1 similarity scores range from `0.698` to `0.875`, completely overlapping the answerable range (`0.646` to `0.881`). Four unanswerables (`tcs-gold-09` at 0.875, `tcs-gold-30` at 0.836, `tcs-gold-31` at 0.804, and `tcs-gold-27` at 0.787) score higher than the median answerable question (`0.782`). Any score threshold high enough to filter out unanswerables would reject more than half of valid answerable queries.

---

## 6. Limits of this Evaluation

1. **PDF Format Only**: Chunks are ingested solely from the formatted PDF (`tcs_annual_report.pdf`) using PyMuPDF; DOCX/HTML parsers were not exercised.
2. **Single Document**: Evaluated exclusively against the TCS Annual Report 2025-26 (118 chunks). Cross-document scaling and interference remain untested.
3. **Small Query Sample**: 34 questions total (25 answerable, 9 unanswerable), of which 21 answerable questions remain after excluding the four that repeat a tuning fact (some still share source chunks with tuning questions, so this subset is not fully independent).
4. **Retrieval-Only Scope**: Evaluates search ranking and evidence discovery only. Downstream LLM generation, grounding faithfulness, and refusal behavior were not evaluated in this run.
5. **Simple Keyword Tokenizer**: The BM25 keyword index uses simple punctuation/whitespace regex tokenization without stemming, lemmatization, or financial acronym expansion.
