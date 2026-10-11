# Technical Requirements Document (TRD)
## Module: Agentic Orchestration (LangGraph)
### Owner: Member 3 — Agentic Orchestration Engineer
### Project: Enterprise RAG Assistant
### Version: v0.2 (revised Session 12, October 2026; supersedes the September v0.1)

---

## 0. What changed from v0.1

| # | Change | Section |
|---|---|---|
| 1 | A retry must change the search; same query = same chunks | 13 |
| 2 | `max_steps` 8 → 12 (8 allowed only one retry on a complex query) | 14 |
| 3 | Planner also rewrites queries and issues original + rewritten searches | 8 |
| 4 | Evidence merge by `chunk_id`, scores never compared across queries | 9 |
| 5 | Fact-checker judges claims against all evidence together and must confirm specific figures | 11 |
| 6 | No-evidence rules (empty results, topical-but-missing-figure) | 15 |
| 7 | Retrieval assumptions rewritten to the shipped configuration | 7 |
| 8 | `LLMClient` interface, `MockLLM`, `MockRetriever`, and an injected `Agent` object | 5, 16 |
| 9 | `AgentState` extended (rewrites, evidence, unsupported claims, attempt counter) | 6 |
| 10 | Status mapping and thresholds defined, marked tunable | 11, 12 |

The frozen output contract (`AgentResponse`, `AgentStep`, `Citation`) is **unchanged**. Two optional, backwards-compatible proposals are in Section 18 and need a team sync.

---

## 1. Scope

Technical design for the agent graph: query classification, rewriting, decomposition, retrieval-tool calling, evidence merging, answer synthesis, claim-level fact-checking, and bounded retry logic, all implemented as an explicit LangGraph state machine.

---

## 2. Architecture Overview

```
START
  |
  v
Planner  (ONE structured LLM call: classify + rewrite + decompose)
  |
  v
Retriever  (per sub-query: original + rewritten search; calls Member 2's retrieve())
  |
  v
Evidence merge  (dedupe by chunk_id; no cross-query score comparison)
  |
  +-- no chunks at all --------------------------> NO-EVIDENCE ANSWER (generator NOT called)
  |
  v
Synthesizer  (draft answer + citations)
  |
  v
Fact Checker  (claims -> verify against ALL evidence -> coverage)
  |
  +-- coverage >= threshold -------------------> FINAL (verified)
  |
  +-- coverage < threshold, retries left ------> Rewrite for retry --> Retriever
  |                                              (new query / wider top_k, merge evidence)
  |
  +-- coverage < threshold, no retries left ---> FINAL (partially_verified / unverified)
  +-- no claim supported at all ---------------> NO-EVIDENCE ANSWER (unverified)
```

Simple queries skip decomposition; the planner call still runs (it is the classifier), but returns a single sub-query.

---

## 3. Tech Stack

| Component | Tool | Reason |
|---|---|---|
| Language | Python 3.11+ | Matches the rest of the team |
| Orchestration | LangGraph (`StateGraph`, conditional edges) | Explicit state machine > implicit chains |
| LLM access | Own `LLMClient` protocol (Section 5); `langchain-core` only where it helps | No hard dependency on one provider; trivial to mock |
| Structured output | Pydantic-constrained generation | Enforces plan / claim / verdict schemas instead of free-text parsing |
| Evaluation | RAGAS (run by Member 5) | Quantitative, CI-gatable |
| Tokenization | `tiktoken` | Consistent with Members 1 and 2 |
| Testing | `pytest`, `MockRetriever`, `MockLLM` | No model or network needed for unit tests |
| Guardrails (optional) | `guardrails-ai` or `presidio` | Only if time allows |

---

## 4. Module Breakdown

```
app/agents/
├── state.py             — AgentState TypedDict shared across all nodes
├── config.py            — AgentConfig (caps, thresholds, top_k values); no magic numbers in nodes
├── llm.py               — LLMClient protocol + provider adapter(s)
├── planner.py           — classify + rewrite + decompose (one structured call)
├── retriever_agent.py   — calls retrieve() per search query, merges evidence
├── synthesizer.py       — draft answer + citations (or the no-evidence answer)
├── fact_checker.py      — claim extraction, verification, coverage, retry decision
├── graph.py             — wires nodes into the StateGraph with conditional edges
└── agent.py             — Agent class: build_agent(retriever, llm, config); run / run_streaming

tests/unit/agents/
├── mocks.py             — MockRetriever, MockLLM
└── test_*.py
```

---

## 5. Interfaces

### 5.1 Building the agent (injected dependencies)

```python
# app/agents/agent.py
agent = build_agent(retriever, llm, config=AgentConfig())   # build ONCE per process
response: AgentResponse = agent.run(query, session_context=None)
for event in agent.run_streaming(query, session_context=None):  # yields AgentStep, then AgentResponse
    ...
```

- `retriever` is anything with `retrieve(RetrievalRequest) -> RetrievalResponse`. In production it is Member 2's `build_default_retriever(...)`, built once (model loading takes seconds) by Member 4 at startup. In tests it is `MockRetriever`
- This replaces the v0.1 sketch `run_agent(query, session_context)`. It is not a schema change but **does change the call Member 4 makes**, so it needs a short sync with Member 4

### 5.2 LLM interface

```python
class LLMClient(Protocol):
    def complete(self, system: str, prompt: str) -> str: ...
    def complete_structured(self, system: str, prompt: str, schema: type[BaseModel]) -> BaseModel: ...
```

- `MockLLM` returns scripted responses keyed by node, so every node and the whole graph can be tested without a model
- Provider choice (local model via Ollama vs. hosted API) is an open decision (Section 19); it only changes the adapter in `llm.py`

---

## 6. Agent State (shared across all nodes)

```python
from typing import TypedDict

class AgentState(TypedDict):
    query: str
    query_type: str                  # simple | multi-hop | comparison | aggregation | ambiguous
    subqueries: list[str]            # max 5
    search_queries: list[str]        # originals + rewrites actually sent to retrieve()
    top_k: int                       # starts at config.top_k (8); widened on retry 2
    retrieved_chunks: list           # merged RetrievedChunk objects, deduped by chunk_id
    draft_answer: str
    claims: list[str]
    verification_results: list[dict] # per claim: supported, evidence chunk_ids, reason
    unsupported_claims: list[str]
    coverage: float                  # supported claims / total claims
    confidence: float
    retry_count: int
    step_count: int
    trace: list                      # AgentStep objects, in order
    final_answer: str | None
    verification_status: str
```

Per-request, in-memory, not persisted. Only the final `AgentResponse` and its trace are persisted by Member 4.

---

## 7. Retrieval Assumptions (shipped Member 2 configuration)

Source: `MEMBER3_HANDOFF.md` and `MEMBER2_DECISIONS.md`. Measurements are from one 118-chunk document and 17 answerable questions, tuned on the same set.

- Default retrieval is meaning search only (`bge-small-en-v1.5`). `results` are sorted best-first by `dense_score`. **`sparse_score`, `fused_score`, `rerank_score` are `None`: never read them.** Keyword search and the reranker are build-time switches, not per-request options
- Every result carries `chunk_id`, `document_id`, `page_number`, `section_title`
- Empty query, empty index, or non-matching filter returns an empty `results` list, never an exception. An unknown filter key raises `ValueError`, so filters must come only from the known set (`document_id`, `source_type`, `page_number`, `section_title`, `content_hash`)
- Retrieval always returns something for a non-empty query on a non-empty index. It never decides "no answer", and no score cutoff has been shown to be reliable
- Scores are not comparable across different queries
- Chunks are small (average about 88 tokens on the test document); table chunks are sentences
- Reference numbers: Recall@5 0.882, Recall@10 0.912; the two remaining misses are planner problems (wording mismatch, two-fact question)
- Speed: about 20 ms per call (p95 23 ms) on one CPU with 118 chunks. Not a promise for a large corpus

---

## 8. Planner: classify, rewrite, decompose

One structured LLM call returns a `Plan` (Pydantic model):

```python
class Plan(BaseModel):
    query_type: Literal["simple", "multi-hop", "comparison", "aggregation", "ambiguous"]
    subqueries: list[str]          # one per fact; just [original] for simple queries
    rewrites: dict[str, str]       # subquery -> rewritten form (omit when no rewrite is needed)
```

- **Rewriting** converts wording the document is unlikely to use into its own terms:
  - relative periods → fiscal quarters/years ("the October-to-December quarter of the year before FY26" → "Q3 FY25")
  - informal terms → the document's term ("profit after tax" → "net income")
- **Always keep the original wording.** The retriever sends the original and, when different, the rewrite, then merges. A bad rewrite therefore cannot hide a good original match
- **One sub-query per fact.** Example: "How did the value of new deals from the biggest market change, and what portion of revenue does that market make up?" → two sub-queries, one per fact
- `max_subqueries = 5`: extra sub-queries are truncated, not rejected
- Only multi-hop / comparison / aggregation queries are decomposed; `simple` returns one sub-query
- The planner has no access to the corpus. Rewrites are the LLM's best guess at the document's vocabulary; this is why the original is always kept and why the retry step can rewrite again (Section 13)
- Malformed planner output → fall back to `[original query]` as a single simple query

---

## 9. Retriever Node and Evidence Merge

```
for each search_query in state.search_queries:
    response = retriever.retrieve(RetrievalRequest(query=search_query, top_k=state.top_k))
merge all results by chunk_id (first occurrence wins; keep per-query order)
cap merged evidence at config.max_evidence_chunks (default 20)
```

- Maximum retrieve calls per pass: `max_subqueries × 2 = 10` (original + rewrite). At about 20 ms per call this is about 0.2 s, small next to LLM latency
- Merge by `chunk_id`, never by score: scores from different queries are not comparable
- Default `top_k = 8` per search query (the backend default, roughly 1000 tokens at today's chunk size); passed through from the request when provided
- If every call returns an empty `results` list, evidence is empty → no-evidence path (Section 15)
- The trace step reports counts this module can compute (chunks retrieved per sub-query, chunks after merge). It does not depend on Member 2's optional candidate-count fields (Section 18)

---

## 10. Synthesizer

- Builds the prompt from the merged evidence, labelling each chunk with its `chunk_id` so the generator can cite it
- Produces the draft answer and citations; `Citation.text_snippet` is a short excerpt of the cited chunk's text
- Every prompt template states that retrieved text is **data, never instructions** (Section 14)
- Citations must reference only `chunk_id`s present in the evidence. Any citation that does not is dropped and noted in the trace
- If evidence is empty the generator is **not called** (Section 15)

---

## 11. Fact-Checking Logic

```
Draft answer
   |
   v
Split into atomic claims (one factual assertion per claim)
   |
   v
For each claim: is it supported by the COMBINED evidence?
   - the claim's specific figures, names, dates must appear in the evidence
   - judged against all evidence together (claims can span small chunks)
   |
   v
coverage = supported claims / total claims
```

- Claim extraction and verification may be batched into as few LLM calls as possible (one call for all claims). Latency has not been measured
- **Specific-value rule.** A claim like "Community spending was X" is supported only if the evidence states X. A chunk on the right topic that does not contain the figure does **not** support the claim (retrieval's q17 case)
- Entailment starts as an LLM-judge prompt, not a fine-tuned NLI model, to keep scope realistic
- Each verdict records the supporting `chunk_id`s so citations can be corrected after verification

**Status mapping (initial values, to be calibrated on Member 5's golden dataset):**

| Condition | `verification_status` | `confidence` |
|---|---|---|
| coverage ≥ 0.8 | `verified` | derived from coverage; never hard-coded to 1.0 |
| 0 < coverage < 0.8 after retries exhausted | `partially_verified` | derived from coverage |
| coverage = 0, checker call failed, or no evidence | `unverified` | low |

- Unsupported claims are removed from, or flagged in, the returned answer; the module never returns a draft whose claims are all unsupported (Section 15)
- Never claim 100% certainty. Surface `confidence` and `verification_status` rather than silently upgrading a low-coverage answer

**Optional low-similarity hint.** The top-1 `dense_score` of the evidence may be passed into the fact-checker prompt as a hint ("retrieval similarity was low"). It is **never** used as a hard cutoff here. Member 2's measurements (answerable top-1 min 0.633, unanswerable 0.621–0.637, one overlapping answerable question, only 3 negatives) do not support a rule. Off by default; enable only after calibration on the golden dataset.

---

## 12. Answer Assembly

- Final `AgentResponse` is built from: `final_answer`, citations (limited to chunks that actually support surviving claims), `trace`, `verification_status`, `confidence`, `latency_ms`
- `AgentResponse` always has a valid value for every field, including on failure paths

---

## 13. Retry Logic (a retry must change something)

Shipped retrieval is deterministic. Calling `retrieve()` again with the same query returns the same chunks, so a plain "retrieve again" can never fix a failed verification. Each retry therefore does the following:

| Retry | What changes |
|---|---|
| 1 | The planner (or a lightweight rewrite call) produces a **new search query for each unsupported claim** (the claim's own wording plus the likely document term). New chunks are retrieved and **merged** with the existing evidence by `chunk_id` |
| 2 | Same as retry 1, and `top_k` is **widened** (default 8 → 15, never above 20, the `ChatRequest` limit) |

- Then re-run synthesis and verification on the enlarged evidence
- After `max_retries = 2`, stop and return the current best answer with `partially_verified` or `unverified`
- If a retry brings back no new `chunk_id`s, stop early: another pass cannot help
- The trace reports a retry honestly ("re-checking evidence for 1 unsupported claim"); a visible self-correction is a feature
- Whether a rewritten retry actually recovers missing evidence is an assumption to test on the golden dataset, not a known result

---

## 14. Guardrails & Bounded Execution

| Guard | Limit | Behaviour when hit |
|---|---|---|
| `max_steps` | **12** (one step = one node execution) | Graph terminates, returns best-effort answer with a low-confidence flag |
| `max_retries` | 2 | Stops re-retrieving; returns the current draft as `partially_verified` or `unverified` |
| `max_subqueries` | 5 | Planner output truncated to the first 5 |
| `max_evidence_chunks` | 20 | Merged evidence truncated (keeping per-query order) |
| Prompt injection in retrieved text | n/a | Retrieved chunk text is always treated as data, never as instructions; stated in every prompt template |

**Why 12, not 8.** Steps per pass: complex query = planner, retrieve, synthesize, fact-check = 4 (the planner is one node and the draft is part of synthesis), plus each retry adds retrieve + synthesize + fact-check = 3. Two retries = 4 + 6 = **10**. With `max_steps = 8`, the second retry could never run. 12 leaves headroom. If nodes are later split (separate "merge" or "draft" nodes), recompute this number rather than guessing; add a unit test that asserts a two-retry run finishes under the cap.

---

## 15. No-Evidence Behaviour

1. **Retrieval never decides "no answer".** This module does
2. **Empty evidence** (every `retrieve()` returned an empty list): return "I don't have sufficient evidence in the provided documents." **Do not call the generator.** `verification_status = "unverified"`; trace shows a `retrieve` step noting that nothing was found
3. **Evidence exists but no claim is supported:** return the same insufficient-evidence answer with `unverified`; never return the unsupported draft
4. **Topical-but-missing-figure** (q17): handled by the specific-value rule in Section 11
5. No score cutoff is used (Section 11, optional hint)

---

## 16. Error Handling

| Failure case | Behaviour |
|---|---|
| `retrieve()` returns empty results | No-evidence path (Section 15) |
| `retrieve()` raises (e.g. `ValueError` for a bad filter key) | Caught; trace notes the error; return a graceful `unverified` response, never crash the graph |
| LLM call fails or times out | Retry once with backoff; if still failing, return a graceful error response |
| Fact-checker LLM call fails | `verification_status = "unverified"`; do not block the whole response |
| Malformed planner output | Treat the original query as one simple query |
| Malformed claim list from the checker | Treat the draft as unverified |
| Step cap hit | Terminate with the best-effort answer and a low-confidence flag |

---

## 17. Testing Plan

All tests use `MockRetriever` and `MockLLM`; no model or network is needed.

Unit tests:
- Planner classifies a labelled set of simple vs. multi-hop queries (scripted `MockLLM`)
- Planner output with more than 5 sub-queries is truncated to 5
- Malformed planner output falls back to the original query
- Rewrite: for a q19-style query the retriever is called with **both** the original and the rewritten text
- Decomposition: a q16-style two-fact query produces one retrieve call per sub-query, and results are merged by `chunk_id`
- Merge: duplicate `chunk_id`s across queries appear once; merge never reads `rerank_score` / `fused_score`
- Retriever node attaches results to state and never assumes optional score fields exist
- Empty `RetrievalResponse` → no-evidence answer, and `MockLLM` records **zero generator calls**
- Synthesizer drops any citation whose `chunk_id` is not in the evidence
- Fact-checker flags a **seeded unsupported claim** as unverified
- Topical-but-missing-figure case (q17-style): claim with a figure absent from the evidence is unsupported
- A claim whose support is split across two chunks is judged supported (combined-evidence rule)
- Retry 1 issues a changed query; retry 2 also widens `top_k`; no more than `max_retries` retries happen
- A retry that returns no new `chunk_id`s stops early
- A two-retry run on a complex query finishes within `max_steps = 12`
- Graph terminates within `max_steps` on a pathological input
- Prompt-injection test: a retrieved chunk containing "ignore previous instructions..." does not alter behaviour
- Retriever / LLM exceptions produce a valid `AgentResponse`, not a crash

Integration (after Member 2's real retriever is wired in):
- Run against the real `build_default_retriever` on the 118-chunk test document; the q16 and q19 patterns are the reference scenarios

Evaluation (with Member 5's harness):
- Compare Faithfulness with and without the fact-checker loop; report the delta, the sample size and its limits

---

## 18. Interface Contract

The output contract is **frozen and unchanged**:

```python
# app/schemas/agent.py  (unchanged from v0.1)
class AgentStepType(str, Enum): PLAN, RETRIEVE, FACT_CHECK, SYNTHESIZE
class AgentStep(BaseModel): step_type; content: str; metadata: dict = {}
class Citation(BaseModel): chunk_id; document_id; page_number: int | None = None; text_snippet: str
class AgentResponse(BaseModel):
    answer: str
    citations: list[Citation]
    trace: list[AgentStep]
    verification_status: str   # "verified" | "partially_verified" | "unverified"
    confidence: float
    latency_ms: float
```

**Proposals that need a team sync (nothing is built until they agree):**

1. `verification_status` as `class VerificationStatus(str, Enum)`: JSON on the wire is identical, so existing consumers keep working. The same improvement was flagged in Member 1's `IngestionResult.status`
2. Optional candidate-count fields on `RetrievalResponse` (Member 2's proposal, needs Members 3, 4, 5). This module's trace does not depend on them
3. Member 4's synchronous `ChatResponse` currently has no `verification_status` (the streaming path has the `verification` event). Member 5's UI must show the trust level, so the synchronous response should carry it too
4. `Citation` carries `document_id` but no filename; the UI wants "[Finance Report, p.12]". Agree who resolves the name (for example Member 5 via `/documents`)
5. The `build_agent(...)` call in Section 5.1 replaces v0.1's `run_agent(...)`; confirm with Member 4

---

## 19. Open Decisions

| Decision | Owner | Needed by |
|---|---|---|
| LLM provider for development and for the demo (local vs. hosted) | Member 3 | Before the first real (non-mock) run |
| Coverage threshold (0.8), status mapping, retry `top_k` widening (8 → 15) | Member 3 + Member 5's golden dataset | Calibration run |
| Candidate counts on `RetrievalResponse` | Members 2, 3, 4, 5 | Before Member 5 builds the retrieval trace panel |
| Items 1, 3, 4, 5 in Section 18 | Team sync | Before Member 4 wires `/chat` |

---

## 20. Performance Considerations (future scaling)

- Retrieval is cheap (about 20 ms per call on the test corpus), LLM calls dominate latency. Planner is one call, synthesis one call, fact-check batched into one call; each retry repeats synthesis and fact-check
- Cache sub-query results within a single request to avoid repeating a search that a retry would send again
- Consider streaming the draft token by token to Member 4's SSE layer while fact-checking runs, only if latency becomes a problem. Note that a streamed draft may later be corrected by the fact-checker; the UI must be able to show that
- Re-measure all of the above on a larger corpus; the retrieval numbers come from one 118-chunk document
