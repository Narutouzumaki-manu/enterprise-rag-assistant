# Retrieval Hand-off for Member 3 (Agents)

**From:** Member 2 (Retrieval) **To:** Member 3 (Agentic Orchestration)
**Last updated:** Session 10, October 2026

You call retrieval from the agent's retriever node. This page covers how to call it, what you can rely on, and what you cannot.

---

## 1. What you get

One object, `HybridRetriever`, with three methods:

| Method | Use |
|---|---|
| `retrieve(RetrievalRequest) -> RetrievalResponse` | Find the best chunks for a (sub-)query |
| `index_chunks(chunks)` | Add chunks (Member 4 calls this after ingestion) |
| `delete_document(document_id)` | Remove a document from both indexes |

Behind `retrieve()`: meaning search + keyword search, merged by rank, then re-read by a reranker.

## 2. How to call it

```python
from app.retrieval.bm25_index import BM25Index
from app.retrieval.embeddings import EmbeddingService
from app.retrieval.hybrid_search import HybridRetriever
from app.retrieval.reranker import Reranker
from app.retrieval.vector_store import VectorStore
from app.schemas.retrieval import RetrievalRequest

# Build ONCE per process: loading the two models takes seconds.
retriever = HybridRetriever(
    VectorStore(EmbeddingService(), persist_path="data/chroma"),
    BM25Index(),
    Reranker(),
)

response = retriever.retrieve(
    RetrievalRequest(query="What was Q4 FY26 revenue?", top_k=8, filters={"document_id": "tcs_annual_report"})
)
for r in response.results:
    print(r.chunk_id, r.page_number, r.section_title, r.rerank_score, r.text[:80])
```

**Build a single shared retriever.** Creating one per request would reload the models every time. Member 4 decides where it lives.

**Testing without the models:** the contract is `RetrievalRequest` in, `RetrievalResponse` out (`app/schemas/retrieval.py`). Write a `MockRetriever` that returns a fixed `RetrievalResponse` and build the agent against it.

## 3. What you can rely on

- **Order:** `results` is sorted best first by `rerank_score`.
- **Citations:** every result carries `chunk_id`, `document_id`, `page_number` and `section_title`, unchanged from Member 1's metadata.
- **No exceptions for empty cases:** an empty query, an empty index, or a filter that matches nothing returns an empty `results` list.
- **Reranker failure is survivable:** if the reranker breaks, you still get results in the fused order, and `reranker_model` says so (it contains the word "failed").
- **Filters:** `document_id`, `source_type`, `page_number`, `section_title`, `content_hash`, alone or together. An unknown key raises `ValueError` (a typo does not silently return nothing).
- **Restarts:** after a restart the keyword index rebuilds itself from the saved vector store.

## 4. What you cannot rely on

- **A score cutoff does not detect "no answer."** `rerank_score` only ranks chunks within one query. A correct chunk scored -9.9 and a wrong one scored +2.7 in our tests. The fact-checker has to decide whether the evidence supports each claim. See `docs/MEMBER2_DECISIONS.md`, Section 3.
- **The right chunk is usually, not always, in the results.** On our test set (17 questions) it was in the top 5 for about 85% of questions and in the top 10 for about 94%. Plan for the gap: check claims against the retrieved text, and do not assume the answer is always there.
- **Dates and synonyms need rewriting first.** "The October-to-December quarter of the year before FY26" found nothing; "Net income Q3 FY25" found the right table at rank 2. A planner that rewrites relative periods into the document's own terms will help.
- **Tables rank lower.** Table chunks (pipe-separated rows) were found less reliably than prose. We are investigating.
- **Speed:** about 1 second per call with the reranker, on a CPU. Calling retrieval for each of up to 5 sub-queries adds up.
- **Scores are not comparable across queries** and not across the four score fields (dense, sparse, fused, rerank).

## 5. Practical suggestions

- Pass the top 8 chunks (the backend default) to the generator; keep `page_number` for citations.
- For multi-part questions, call `retrieve` once per sub-query and merge by `chunk_id` before synthesizing.
- When `results` is empty, answer "I don't have sufficient evidence in the provided documents" without calling the generator.
- When the top chunk is on-topic but lacks the specific figure (our q17), the fact-checker should mark the claim unsupported.

## 6. Open item that needs the team

The agent trace in the UI wants the counts "searched N meaning candidates, M keyword candidates, K combined, reranked to R". `RetrievalResponse` has no field for them, and the schema is frozen. Adding optional fields (for example `dense_candidate_count`) would need agreement from Members 3, 4 and 5.

## 7. Suggested 10-minute walkthrough

1. The picture: question → meaning search + keyword search → merge → reranker → top chunks.
2. The comparison table (README, "Retrieval results").
3. Section 4 above, especially the score cutoff and the date example.
4. Agree on who builds the shared retriever and on the trace counts.
