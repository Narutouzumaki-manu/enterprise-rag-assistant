# Product Requirements Document (PRD)
## Module: Agentic Orchestration (LangGraph)
### Owner: Member 3 — Agentic Orchestration Engineer
### Project: Enterprise RAG Assistant
### Version: v0.2 (revised Session 12, October 2026; supersedes the September v0.1)

---

## 0. What changed from v0.1

v0.1 was written before Member 2 measured anything. Member 2's handoff (`MEMBER3_HANDOFF.md`, `MEMBER2_DECISIONS.md`) changed what the agent can assume about retrieval. Changes in this version:

| # | Change | Why |
|---|---|---|
| 1 | Planner now **rewrites** queries into the document's own terms, in addition to classifying and decomposing (FR 3–4) | Both remaining retrieval misses (q19, q16) are wording / two-fact problems that the index cannot fix |
| 2 | A retry must **change something** about the query or evidence (FR 11) | Shipped retrieval is deterministic: the same query returns the same chunks |
| 3 | **No-evidence behaviour** is a defined requirement (FR 9–10) | Retrieval never says "no answer" and has no reliable score cutoff; the decision belongs to this module |
| 4 | Fact-checker must confirm **specific figures, names and dates**, and judges each claim against **all** retrieved evidence together (FR 7–8) | The hard case is a chunk that is on-topic but lacks the figure (q17); chunks are small (average about 88 tokens) so a claim can span chunks |
| 5 | Dependency on Member 2 rewritten to the shipped configuration (Section 9) | Meaning search only by default; `sparse_score`, `fused_score`, `rerank_score` are `None` |
| 6 | Success metrics reworded as **targets, not results** (Section 7) | Nothing has been measured for the agent yet |
| 7 | `max_steps` raised from 8 to 12 (FR 13) | 8 steps did not allow two retries (see TRD Section 14) |
| 8 | LLM calls go through a swappable interface with a mock (FR 14) | Lets every node be built and tested before a model is chosen |

---

## 1. Purpose

The Agentic Orchestration module is the "brain" of the system. It takes a user's question, decides how to answer it (directly, or after rewriting and splitting it into sub-questions), calls Member 2's retrieval module for evidence, drafts an answer, and checks that the answer is actually grounded in the retrieved evidence before returning it.

This is what separates the project from a plain "question → retrieve → LLM answers" chatbot. If this module blindly trusts the LLM, the system's credibility and its Faithfulness score collapse, whatever the quality of retrieval upstream.

---

## 2. Problem Statement

A single-shot RAG chain (embed question → retrieve top-k → stuff into a prompt → generate) fails in predictable ways:
- It cannot handle multi-hop questions that need several lookups (e.g. "how did deal value change, and what share of revenue does that market make up?" needs two facts)
- It cannot cope with **wording that doesn't match the document**: "the October-to-December quarter of the year before FY26" finds nothing, while "Net income Q3 FY25" finds the right table at rank 2
- It has no way to notice that retrieved evidence is insufficient, or that the evidence is on-topic but doesn't contain the requested figure
- It cannot detect or correct hallucinated claims, and trusts the LLM output verbatim
- It provides no observable reasoning trace, so it is impossible to debug why an answer went wrong

An explicit state-machine agent is required for bounded, inspectable, self-correcting behaviour.

---

## 3. Goals

| Goal | Description |
|---|---|
| G1 | Classify incoming queries (simple / multi-hop / comparison / aggregation / ambiguous) to decide whether decomposition is needed |
| G2 | Rewrite queries into the document's own terms (relative periods → fiscal quarters, synonyms → the term the document uses) |
| G3 | Decompose complex questions into independently answerable sub-queries, one per fact |
| G4 | Call Member 2's retrieval module per (sub-)query and merge the evidence |
| G5 | Synthesize a draft answer with citations tied to specific retrieved chunks |
| G6 | Verify each claim in the draft is supported by the retrieved evidence, including specific figures |
| G7 | Retry with a **changed** query when verification fails, bounded by hard caps |
| G8 | Answer "I don't have sufficient evidence in the provided documents" when evidence is missing, instead of guessing |
| G9 | Expose the full reasoning trace (plan → retrieve → synthesize → verify) for the frontend's agent-trace viewer |
| G10 | Never loop indefinitely: hard caps on steps, retries and sub-queries |

---

## 4. Non-Goals

- This module does **not** perform retrieval itself (Member 2) — it only calls Member 2's interface
- It does **not** own the API layer, streaming transport or session persistence (Member 4)
- It does **not** render any UI; the trace it produces is consumed by Member 5's frontend
- It does **not** parse or chunk documents (Member 1)
- It does **not** set retrieval switches (keyword search, reranker); these are build-time options of Member 2's `build_default_retriever`, not per-request options
- It does **not** train or fine-tune any model

---

## 5. Users of This Module

| User | How they use it |
|---|---|
| Member 2 (Retrieval) | Is called by this module's retriever node via `retrieve(RetrievalRequest)` |
| Member 4 (Backend/API) | Builds the agent once at startup and invokes it from the `/chat` and `/chat/stream` endpoints, streaming its trace events via SSE |
| Member 5 (Frontend / Eval) | Renders the trace events and trust level; uses RAGAS Faithfulness to measure this module; supplies the golden dataset used to tune this module's thresholds |
| End users (indirect) | Receive the final answer, citations and verification status |

---

## 6. Functional Requirements

1. Accept a user query string (and optional session context) as input
2. Classify the query: `simple`, `multi-hop`, `comparison`, `aggregation`, `ambiguous`
3. **Rewrite** the query into the document's own terms where needed (relative time periods → fiscal quarters or years; informal terms → the document's term). Keep the original wording as well, and retrieve with both when they differ
4. Decompose complex queries into a bounded list of sub-queries, **one per fact** (max 5)
5. Call Member 2's `retrieve()` once per search query, then merge results by `chunk_id` (never rely on scores being comparable across queries)
6. Synthesize a draft answer with citations tied to specific retrieved chunks
7. Split the draft into atomic claims and verify each against the **combined** retrieved evidence (entailment-style check)
8. A claim containing a specific figure, name or date is supported only if that specific value appears in the evidence; an on-topic chunk that lacks the figure does not support the claim
9. When retrieval returns **no results**, answer "I don't have sufficient evidence in the provided documents" **without calling the generator**
10. When results exist but **no claim is supported**, return the same insufficient-evidence answer with `verification_status = "unverified"`; do not return the unsupported draft
11. If verification coverage is below the threshold, retry. A retry must change the search: rewrite the query around the unsupported claims, and (on the second retry) widen `top_k`; new chunks are merged with the earlier ones by `chunk_id`
12. Return a structured `AgentResponse`: answer, citations, verification status, confidence, full trace, latency
13. Enforce hard caps: `max_steps = 12`, `max_retries = 2`, `max_subqueries = 5`; always terminate with a best-effort answer and a low-confidence flag
14. Make all LLM calls through a swappable `LLMClient` interface, with a `MockLLM` for tests, so the module has no hard dependency on one provider
15. Never treat retrieved document content as instructions (guard against prompt injection)
16. Never raise an unhandled exception to the caller; every failure ends in a valid `AgentResponse`

---

## 7. Success Metrics

These are **targets**, not results. Nothing has been measured for the agent yet. Report whatever the benchmark actually produces, with sample size and its limits.

| Metric | Target |
|---|---|
| Faithfulness (RAGAS, Member 5's golden dataset) | ≥ 0.85, measured against the "retrieval only, no fact-checker" baseline so the delta is visible |
| Multi-hop questions (2+ lookups) answered correctly | Demonstrated in at least one test scenario (retrieval's q16 is the reference case) |
| Wording-mismatch questions answered correctly via rewriting | Demonstrated in at least one test scenario (retrieval's q19 is the reference case) |
| Fact-checker catches at least one seeded hallucination | Demonstrated in a test case |
| Topical-but-missing-figure case (retrieval's q17) returns insufficient evidence | Demonstrated in a test case |
| Unanswerable questions answered with "insufficient evidence" | Measured on Member 5's golden dataset (needs many more unanswerable questions than the 3 used so far) |
| Agent loop termination | 100%: no query ever causes an infinite loop |
| Prompt-injection resistance | Document content instructing the agent to deviate from its task is never followed |

---

## 8. Risks & Open Questions

- **Query classification is a judgement call.** Misclassifying a complex question as simple gives an incomplete answer. Fallback: if the verified answer looks thin, escalate to decomposition
- **Rewriting can make things worse.** A rewrite may drift from the user's meaning. Mitigation: always retrieve with the original wording as well as the rewrite
- **The LLM judge is only as good as the LLM.** Claim decomposition and entailment need benchmarking against a small labelled set, not blind trust
- **Thresholds are guesses until measured.** The coverage threshold (0.8) and the status mapping must be calibrated on Member 5's golden dataset. Any "low similarity" hint from retrieval is a hypothesis: Member 2 found a possible cutoff near 0.656 on top-1 `dense_score`, but it was fitted on the same 17 questions with only 3 negatives, and one answerable question overlapped the unanswerable band
- **Latency.** Retrieval takes about 20 ms (p95 23 ms on one CPU and one 118-chunk document), so LLM calls dominate. Each retry adds a full retrieve + synthesize + verify pass. Latency per question has not been measured
- **Retry design is unproven.** Whether "rewrite around the unsupported claim" actually recovers missing evidence is an assumption to test, not a known result
- **Candidate counts for the trace** (searched / combined / reranked counts) need a team decision (Members 3, 4, 5) and a schema change on `RetrievalResponse`. Until then the trace reports counts this module can compute itself (chunks retrieved per sub-query)
- **LLM provider not yet chosen** (local model via Ollama vs. a hosted API). The interface in FR 14 keeps this decision from blocking development

---

## 9. Dependencies on Other Members

- **Member 2** (shipped configuration: `bge-small-en-v1.5`, meaning search only, via `build_default_retriever`):
  - Results are sorted best-first by `dense_score`. `sparse_score`, `fused_score` and `rerank_score` are `None` by default and must not be relied on
  - Every result carries `chunk_id`, `document_id`, `page_number`, `section_title` unchanged from ingestion
  - Empty query, empty index, or a filter that matches nothing returns an empty `results` list (never an exception); an unknown filter key raises `ValueError`
  - Retrieval always returns something for a non-empty query on a non-empty index; it never decides "no answer"
  - Scores are not comparable across queries
  - Reference: on 17 answerable test questions, Recall@5 0.882 and Recall@10 0.912 (one document, tuned on the same questions), so the right chunk is usually but not always present
  - Table chunks read as sentences ("Quarter end: Q2 FY26 (30 Sep 2025); Closing headcount: 593,314; ...")
- **Member 4**: builds the agent once at process start (model loading takes seconds), wires its entry point into `/chat` and `/chat/stream`, and forwards trace events as they are emitted
- **Member 5**: consumes trace events and `AgentResponse`; supplies the golden dataset used to calibrate thresholds; measures Faithfulness for this module
- **Member 1** (indirect): citation quality depends on the `page_number` / `section_title` metadata that ingestion produces and Member 2 passes through unchanged
