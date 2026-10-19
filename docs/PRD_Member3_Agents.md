# Product Requirements Document (PRD)
## Module: Agentic Orchestration (LangGraph)
### Owner: Member 3 — Agentic Orchestration Engineer
### Project: Enterprise RAG Assistant
### Version: v0.3 (Session 19, October 2026; written to match the implementation; supersedes v0.2)

---

## 0. What changed from v0.2

v0.2 described what the agent should do. v0.3 describes what it does, after live runs on the real model changed several things.

| # | Change | Why |
|---|---|---|
| 1 | Rewriting is built but **off by default**; the original question is always searched first (FR 3) | Measured: the first planner dropped the original question and hurt two questions; synonym rewrites showed no benefit |
| 2 | New: **"not found" path**. The draft says whether the passages contain the answer; if not, the agent searches again, then gives the insufficient-evidence answer (FR 9) | A live run marked "the passages do not provide it" as `verified` |
| 3 | New: retries **do not repeat earlier searches** (FR 11) | In every "not found" case the retry hints were rephrasings of the first |
| 4 | New: passages that address the AI are **removed before the model sees them** (FR 15) | A live injection test: the model alone followed an instruction hidden in a fake row |
| 5 | Citation snippets show **the part of the chunk that supports the claim** (FR 6) | The headcount question cited the wrong row |
| 6 | Retry hints come from the fact-checker's own call (FR 11) | One model call fewer per retry; retries stay at 3 steps |
| 7 | The entry point is specified: `build_agent`, `run`, `run_streaming`; it never raises (FR 1, 12, 16) | Members 4 and 5 build against it |
| 8 | Success metrics show **measured status**, with sample sizes and limits (Section 7) | Live runs and safety checks exist now |

---

## 1. Purpose

The Agentic Orchestration module is the "brain" of the system. It takes a user's question, decides how to answer it (directly, or after splitting it into sub-questions), calls Member 2's retrieval module for evidence, drafts an answer, and checks that the answer is actually grounded in the retrieved evidence before returning it.

This is what separates the project from a plain "question → retrieve → LLM answers" chatbot. If this module blindly trusts the LLM, the system's credibility and its Faithfulness score collapse, whatever the quality of retrieval upstream.

---

## 2. Problem Statement

A single-shot RAG chain (embed question → retrieve top-k → stuff into a prompt → generate) fails in predictable ways:
- It cannot handle questions that need several lookups ("how did deal value change, and what share of revenue does that market make up?" needs two facts)
- It cannot cope with wording that does not match the document: the model's own search hints used "profit after tax" while the report's table says "net income", and the right table was not in the top 30 results
- It has no way to notice that the evidence is insufficient, or on-topic but missing the requested figure
- It cannot detect or correct unsupported claims, and trusts the LLM output verbatim
- It can obey instructions hidden in a document
- It provides no observable reasoning trace

An explicit state-machine agent is required for bounded, inspectable, self-correcting behaviour.

---

## 3. Goals

| Goal | Description |
|---|---|
| G1 | Classify incoming queries (simple / multi-hop / comparison / aggregation / ambiguous) to decide whether decomposition is needed |
| G2 | Decompose multi-fact questions into sub-queries, one per fact, and always search the original question as well |
| G3 | Call Member 2's retrieval module per search query and merge the evidence |
| G4 | Synthesize a draft answer with citations tied to specific retrieved chunks |
| G5 | Verify each claim in the draft against the retrieved evidence, including specific figures |
| G6 | Retry with a **changed** search when verification fails or the passages lack the answer, bounded by hard caps |
| G7 | Answer "I don't have sufficient evidence in the provided documents" when the evidence is missing, instead of guessing |
| G8 | Resist instructions hidden in documents |
| G9 | Expose the full reasoning trace (plan → retrieve → synthesize → verify) for the frontend's agent-trace viewer |
| G10 | Never loop indefinitely and never raise to the caller |

---

## 4. Non-Goals

- This module does **not** perform retrieval itself (Member 2)
- It does **not** own the API layer, streaming transport or session persistence (Member 4)
- It does **not** render any UI; the trace it produces is consumed by Member 5's frontend
- It does **not** parse or chunk documents (Member 1)
- It does **not** set retrieval switches (keyword search, reranker); these are build-time options of `build_default_retriever`
- It does **not** decide whether a document is true or who may upload it: "verified" means faithful to the retrieved passages, not true (document trust belongs to Members 1 and 4)
- It does **not** train or fine-tune any model

---

## 5. Users of This Module

| User | How they use it |
|---|---|
| Member 2 (Retrieval) | Is called by this module's retriever node via `retrieve(RetrievalRequest)` |
| Member 4 (Backend/API) | Builds the agent once at startup and runs it in a thread from the chat endpoints, streaming its trace events via SSE |
| Member 5 (Frontend / Eval) | Renders the trace events and trust level; measures this module; supplies the golden dataset used to calibrate its thresholds |
| End users (indirect) | Receive the final answer, citations and verification status |

---

## 6. Functional Requirements

1. Accept a user query string, an optional `top_k` (clamped to 1 to 20), and an optional `session_context` (accepted, currently unused). Provide `run()` for one finished answer and `run_streaming()`, which yields each trace step as it finishes and then the final response. A blank question returns "Please enter a question." without any model call
2. Classify the query: `simple`, `multi-hop`, `comparison`, `aggregation`, `ambiguous`
3. Rewrite the query into the document's terms **only when `use_rewrites` is on (default off)**. The original question is always searched first, and a rewrite is only ever added next to it
4. Decompose multi-hop, comparison and aggregation queries into a bounded list of sub-queries, **one per fact** (max 5). Simple and ambiguous queries are never split
5. Call Member 2's `retrieve()` once per search query; merge results by `chunk_id` (never by score), interleaving across searches before the evidence cap (20); remove passages that address the AI before merging; on a retry, new passages go first
6. Synthesize a draft answer with citations built in code from the retrieved chunks only; each citation's snippet is the chunk sentence that best matches the claim, with a leading "..." when it starts mid-chunk
7. Split the draft into atomic claims and verify each against the **combined** retrieved evidence (entailment-style check, one model call). A "supported" verdict must name at least one passage that was really retrieved
8. A claim containing a specific figure, name or date is supported only if that value appears in the evidence; an on-topic chunk that lacks the figure does not support the claim
9. When retrieval returns **no results**, answer "I don't have sufficient evidence in the provided documents" **without calling the generator**. When passages exist but the draft says they **do not contain the answer** (`answer_found` false), search again with the model's hint (no fact-check call), then give the same insufficient-evidence answer if the searches run out
10. When passages exist but **no claim is supported**, return the same insufficient-evidence answer with `unverified`; do not return the unsupported draft
11. If verification coverage is below the threshold (0.8), retry. A retry must change the search: each unsupported claim is searched by its own wording and the model's hint; the second retry also widens `top_k` (never narrower than requested); new passages are merged with the earlier ones. Searches already run are listed in the prompt of the next draft, and a repeated hint triggers a wider search of the question instead
12. Return a structured `AgentResponse`: answer, citations, trace, verification status, confidence (derived from coverage, capped at 0.95, 0 for `unverified`), latency
13. Enforce hard caps: `max_steps = 12`, `max_retries = 2`, `max_subqueries = 5`; always terminate with a best-effort answer. A step guard and LangGraph's recursion limit (`max_steps + 5`) back this up
14. Make all LLM calls through a swappable `LLMClient`, with `MockLLM` for tests, `OpenRouterLLM` for the real model and `CachingLLM` for development, evaluation and demos
15. Never treat retrieved document content as instructions: prompts say passages are data, passage text cannot close its own tag, and passages that address the AI are removed
16. Never raise an unhandled exception to the caller; every failure ends in a valid `AgentResponse` (a graph error becomes an `unverified` response with only the error's type name in the trace)

---

## 7. Success Metrics

Targets, with measured status. Every number comes from a run recorded in `docs/MEMBER3_DECISIONS.md`, with its sample size and limits.

| Metric | Target | Status |
|---|---|---|
| Faithfulness (RAGAS, Member 5's golden dataset) | ≥ 0.85, against the "retrieval only, no fact-checker" baseline | Not measured (Session 20 plans a 10-question comparison; the full measurement needs the golden dataset) |
| Multi-hop questions (2+ lookups) answered correctly | Demonstrated in at least one scenario (q16) | Live: q16 answered with the reference figures ($21.6B to $19.0B, about 48%), `verified`. One question, not a rate |
| Wording-mismatch questions answered correctly | Demonstrated in at least one scenario (q19) | Live: q19 answered ₹123,800 million (the reference) after the retry change, `verified`. One question picked after seeing it fail; not a rate |
| Fact-checker catches a seeded hallucination | At least one | Live: all 3 planted false drafts had the planted claim marked unsupported. Obvious errors, one model |
| On-topic chunk without the figure (q17) returns insufficient evidence | Demonstrated | Live: q17 gave "insufficient evidence" after three searches; q18 and q20 the same |
| Unanswerable questions answered with "insufficient evidence" | Measured on the golden dataset | 3 of 3 live; a sample, not a rate |
| Agent loop termination | 100% | Tested on mocks including the two-retry worst case (10 steps, cap 12) and graph failures; live runs finished in 4 to 8 steps |
| Prompt-injection resistance | Document content instructing the agent is never followed | Live: the model alone followed an instruction hidden in a fake row; with the instruction filter all 3 planted cases pass. The filter was written looking at those cases; paraphrased attacks untested; a plain false fact is not defended against |

---

## 8. Risks & Open Questions

- **Model variance and speed.** The free model's output varies between runs, and a call takes 12 to 36 seconds. Mitigation: `CachingLLM` makes runs repeatable and demos replayable
- **Search hint wording decides whether a retry finds the answer.** The model's hints did not reach q19's table (not in the top 30) while the short "Net income Q3 FY25" ranks 2. The retry change helped on q19, but that is one question
- **The instruction filter is a heuristic.** It catches obvious phrasings only
- **"Verified" is not "true".** A false fact in a document is repeated as `verified`; document trust is outside this module
- **Thresholds are guesses.** The coverage threshold (0.8), the widened `top_k` (15) and the confidence cap (0.95) are not calibrated; they need Member 5's golden dataset
- **The planner costs one of the three model calls per question**, and its only visible benefit so far is multi-fact questions
- **Free-tier quota** (about 50 requests a day) limits how much can be evaluated per day
- **The same 17 questions Member 2 tuned on** were used for the planner decisions, so those measurements are optimistic

---

## 9. Dependencies on Other Members

- **Member 2** (shipped configuration: `bge-small-en-v1.5`, meaning search only, via `build_default_retriever`):
  - Results are sorted best-first by `dense_score`; `sparse_score`, `fused_score` and `rerank_score` are `None` by default and are never read
  - Every result carries `chunk_id`, `document_id`, `page_number`, `section_title`
  - Empty query, empty index, or a filter that matches nothing returns an empty `results` list; an unknown filter key raises `ValueError`
  - Retrieval always returns something for a non-empty query on a non-empty index; it never decides "no answer"
  - Scores are not comparable across queries
  - Table chunks read as sentences ("Quarter end: Q2 FY26 (30 Sep 2025); Closing headcount: 593,314; ...")
- **Member 4**: builds the agent once at process start, runs `run()` or `run_streaming()` in a thread, forwards trace events, resolves citation filenames from `document_id`, controls who can upload documents
- **Member 5**: consumes trace events and `AgentResponse`; supplies the golden dataset used to calibrate thresholds; measures Faithfulness for this module
- **Member 1** (indirect): citation quality depends on `page_number` / `section_title`; cleaning documents at ingestion is the first defence against poisoned content
