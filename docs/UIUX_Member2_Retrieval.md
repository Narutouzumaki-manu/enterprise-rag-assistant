# UI/UX Notes
## Module: Retrieval & Vector Search
### Owner: Member 2 — Retrieval & Vector Search Engineer
### Project: Enterprise RAG Assistant
### Date: September 2026

---

## 1. Scope Note

Like Member 1's ingestion module, Retrieval has **no direct end-user interface** — it's called internally by Member 3's agent layer during query answering. This document covers:
1. The **developer-facing interface** this module exposes to Member 3 (and indirectly, Member 5's trace viewer)
2. The **signals** this module should expose so the frontend's "agent trace" panel can show something meaningful about retrieval
3. Recommendations for what's worth surfacing to end users, even though this module doesn't render anything itself

---

## 2. Developer-Facing Interface

Other team members interact with this module through two main calls:

```python
# Called by Member 4's API when a document finishes ingestion
index_chunks(chunks: list[Chunk]) -> None

# Called by Member 3's retriever agent node
result: RetrievalResponse = retrieve(request: RetrievalRequest)
```

Design principles for this interface:
- **Predictable**: `retrieve()` always returns a `RetrievalResponse`, even when there are zero results — never raises for "no matches found"
- **Fast to fail on real errors**: a misconfigured embedding model should fail loudly at startup, not silently return empty/garbage results per query
- **Idempotent indexing**: re-indexing the same `Chunk` objects (e.g., after a retry) should not create duplicate vector entries — upsert by `chunk_id`, not blind insert

---

## 3. Signals Exposed for the Agent Trace Viewer (via Member 3 → Member 5)

Member 5's frontend shows a live "agent status" trace (per the project roadmap: "✓ Query analyzed → ✓ N candidates retrieved → ✓ N passages reranked"). This module should make the following easy for Member 3 to relay upward:

| Signal | Meaning | Suggested frontend treatment |
|---|---|---|
| `dense_candidate_count` | How many results came from vector search | "Searched semantic index..." |
| `sparse_candidate_count` | How many results came from BM25 | "Searched keyword index..." |
| `fused_candidate_count` | Size of the RRF-fused candidate set | "Combined N candidates..." |
| `reranked_count` | Final count after cross-encoder rerank | "Reranked to top N passages" |
| `latency_ms` | Total retrieval time | Could support a "took Xms" debug detail, not necessarily shown by default |
| Empty result set | No chunks matched at all | "No relevant information found in the uploaded documents" (important — this is what prevents the agent from hallucinating an answer with no grounding) |

---

## 4. Recommended UX Behaviors (for Member 5 to consider)

- When `results` is empty, the frontend/agent should clearly communicate "nothing relevant found" rather than silently producing a generic or hallucinated answer
- Citations shown to the end user should use `page_number` / `section_title` from `RetrievedChunk` metadata (e.g., "Finance Report, p.12, Revenue section") — this metadata flows all the way from Member 1's ingestion module through this one, unchanged
- If reranking meaningfully reorders results vs. the fused order, that's a good "trust-building" detail for a trace viewer (shows the system did real work, not just "top-5 from one search")

---

## 5. Metadata That Enhances the End-User Experience

These fields exist on `RetrievedChunk` (inherited from Member 1's `ChunkMetadata`) and should be surfaced in citations:
- `page_number` — "found on page 12"
- `section_title` — "found in 'Revenue Overview' section" or "found in Table 1"
- `document_id` — links a citation back to the source document in the UI

---

## 6. Out of Scope for This Module

- Rendering citations, chat UI, source viewer — Member 5
- Deciding whether an answer is "grounded enough" to show the user — Member 3 (fact-checker)
- Authentication/session handling around queries — Member 4
