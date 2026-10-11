# Retrieval Hand-off for Member 3 (Agents)

**From:** Member 2 (Retrieval) **To:** Member 3 (Agentic Orchestration)
**Last updated:** Session 11, October 2026

You call retrieval from the agent's retriever node. This page covers how to call it, what you can rely on, what you cannot, and what retrieval expects of the planner. The measurements behind it are in `docs/MEMBER2_DECISIONS.md`.

---

## 1. What you get

One object, built by one function:

| Method | Use |
|---|---|
| `retrieve(RetrievalRequest) -> RetrievalResponse` | Find the best chunks for a (sub-)query |
| `index_chunks(chunks)` | Add chunks (Member 4 calls this after ingestion) |
| `delete_document(document_id)` | Remove a document |

**What runs behind `retrieve()` by default:** meaning search with the `bge-small-en-v1.5` model. Keyword search and a reranker exist and are tested, but they are **off by default** because they did not help on our measurements.

## 2. How to call it

```python
from app.retrieval.factory import build_default_retriever
from app.schemas.retrieval import RetrievalRequest

# Build ONCE per process: loading the model takes seconds.
retriever = build_default_retriever(persist_path="data/chroma")

retriever.index_chunks(chunks)   # chunks come from Member 1's IngestionResult (Member 4 wires this)

response = retriever.retrieve(
    RetrievalRequest(query="What was Q4 FY26 revenue?", top_k=8, filters={"document_id": "tcs_annual_report"})
)
for r in response.results:
    print(r.chunk_id, r.page_number, r.section_title, round(r.dense_score, 3), r.text[:80])
```

- **Always build it through `build_default_retriever`.** It applies the model's required query prefix automatically. Wiring the pieces by hand and forgetting the prefix silently lowers quality.
- **One shared retriever.** Creating one per request reloads the model every time. Member 4 decides where it lives.
- **Testing without the model:** the contract is `RetrievalRequest` in, `RetrievalResponse` out (`app/schemas/retrieval.py`). Write a `MockRetriever` that returns a fixed `RetrievalResponse` and build the agent against it.
- **The switches**, if you or Member 5 want to compare:
  `build_default_retriever(use_keyword=True)` merges keyword search; `build_default_retriever(reranker_model="cross-encoder/ms-marco-MiniLM-L-6-v2")` adds the reranker (about 1.1 s per call).

## 3. What you can rely on

- **Order:** `results` is sorted best first by `dense_score`, the cosine similarity between the query and the chunk.
- **Citations:** every result carries `chunk_id`, `document_id`, `page_number` and `section_title`, unchanged from Member 1's metadata.
- **Several fields are `None` by default.** `sparse_score`, `fused_score` and `rerank_score` are only filled in when keyword search or the reranker is switched on. **Do not assume they exist.** Use `dense_score`.
- **No exceptions for empty cases:** an empty query, an empty index or a filter that matches nothing returns an empty `results` list.
- **Filters:** `document_id`, `source_type`, `page_number`, `section_title`, `content_hash`, alone or together. An unknown key raises `ValueError`, so a typo can't silently return nothing.
- **Tables are sentences.** Table chunks read like `Quarter end: Q2 FY26 (30 Sep 2025); Closing headcount: 593,314; ...`, so the generator and the source viewer see sentences, not pipe-separated rows.
- **Speed:** p50 20 ms and p95 23 ms per call on a CPU with the 118-chunk test document. A question split into five sub-queries costs about 0.1 s of retrieval. That is a measurement on one small corpus, not a promise for a large one.
- **Restarts:** the vector store persists to disk. If a saved index was built with a different model, `build_default_retriever` raises a clear `ValueError`: delete the old `data/chroma` folder and re-index.

## 4. What you cannot rely on

- **The right chunk is usually, not always, in the results.** On our test set (17 answerable questions), all the needed chunks were in the top 5 for 15 of 17 questions (Recall@5 0.882) and about 91% of the needed facts were in the top 10 (Recall@10 0.912). Check each claim against the retrieved text. Never assume the answer is there.
- **There is no reliable "no answer" score.** Retrieval always returns something. A cutoff on the reranker score does not work. Dense similarity shows a weak signal (the three unanswerable questions scored 0.62–0.64, the answerable ones 0.63–0.83), but one answerable question sits inside that band and the three negatives are too few to set a rule. The fact-checker has to decide whether the evidence supports each claim. If you want a low-confidence hint, calibrate it on Member 5's golden dataset first. See `MEMBER2_DECISIONS.md`, Section 4.
- **Scores are not comparable across queries.**

## 5. What retrieval expects of the planner

Both remaining misses on our test set are planner problems, not index problems:

- **Wording that does not match the document (q19).** "The October-to-December quarter of the year before FY26" found nothing; "Net income Q3 FY25" found the right table at rank 2. A planner that rewrites relative periods into the document's own terms (fiscal quarters, "net income" for "profit after tax") would fix this class of question.
- **Questions that need two lookups (q16).** "How did the value of new deals from the biggest market change, and what portion of revenue does that market make up?" found one of the two facts. Split it: one sub-query per fact, call `retrieve` once per sub-query, merge by `chunk_id`.

## 6. Practical suggestions

- Pass the top 8 chunks (the backend default) to the generator and keep `page_number` for citations.
- When `results` is empty, answer "I don't have sufficient evidence in the provided documents" without calling the generator.
- When the top chunk is on-topic but lacks the specific figure (our q17, community spending), the fact-checker should mark the claim unsupported.

## 7. Open item that needs the team

The agent trace in the UI wants counts such as "searched N candidates, M keyword candidates, K combined, reranked to R". `RetrievalResponse` has no field for them, and the schema is frozen. **Proposal** (backwards compatible: existing code keeps working):

```python
class RetrievalResponse(BaseModel):
    query: str
    results: list[RetrievedChunk]
    embedding_model: str
    reranker_model: str
    latency_ms: float
    # NEW, optional. None when the stage did not run.
    dense_candidate_count: int | None = None
    sparse_candidate_count: int | None = None
    fused_candidate_count: int | None = None
    reranked_count: int | None = None
```

With the default configuration only `dense_candidate_count` would be filled. This needs a yes from Members 3, 4 and 5 before it is built.

## 8. Notes for Members 4 and 5

- **Member 4:** the first run downloads the embedding model (about 130 MB) from Hugging Face. Bake it into the Docker image or cache it, or the first container start will be slow or fail offline. Build the retriever once at startup.
- **Member 5:** measure the golden-dataset baseline with the shipped configuration. Build labels from evidence phrases, not chunk IDs, so a later chunking change doesn't break them. See `scripts/resolve_labels.py`.

## 9. Suggested 10-minute walkthrough

1. The picture: question → meaning search → top chunks.
2. The comparison table (README, "Retrieval results").
3. Sections 3 to 5 above, especially the `None` fields and the two planner cases.
4. Decide the candidate counts (Section 7), and who builds the shared retriever.
