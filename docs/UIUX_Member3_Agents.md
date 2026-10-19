# UI/UX Notes
## Module: Agentic Orchestration (LangGraph)
### Owner: Member 3 — Agentic Orchestration Engineer
### Project: Enterprise RAG Assistant
### Version: v0.3 (Session 19, October 2026; written to match the implementation; supersedes v0.2)

---

## 0. What changed from v0.2

| # | Change | Section |
|---|---|---|
| 1 | Interface updated: `run(query, session_context, top_k)`, `run_streaming`, run in a thread | 2 |
| 2 | Trace wording tables now list the exact strings the agent emits, including the new "searching again" and "removed because it contains instructions" steps | 3 |
| 3 | The answer states are listed with their exact texts, including the new "passages do not contain the answer" outcome and the error states | 4 |
| 4 | Trust levels: what `verified` does and does not mean | 5 |
| 5 | Citations: snippets are excerpts and may start with "..." | 6 |
| 6 | Streaming: the final, verified answer is streamed after verification | 6, 7 |
| 7 | Mapping from trace steps to Member 4's SSE events | 7 |

---

## 1. Scope Note

This module has **no direct end-user interface**, but its internal reasoning steps are explicitly meant to be *shown* to the user in Member 5's "agent trace" panel. That is one of the project's stated differentiators, so the trace output deserves real design care even though Member 3 renders no pixels.

This document covers:
1. The **developer-facing interface** this module exposes to Member 4
2. The **trace events** Member 5 renders live during a query
3. What makes a trace trustworthy and not overwhelming
4. How the module's honest failure states ("I don't have sufficient evidence...") should reach the user

---

## 2. Developer-Facing Interface

```python
# Built ONCE per process by Member 4 at startup (model loading takes seconds)
agent = build_agent(retriever, llm, config=AgentConfig())

# Called by Member 4's /chat endpoint
response: AgentResponse = agent.run(query, session_context=None, top_k=None)

# Streaming variant, called by /chat/stream: yields AgentStep events as they occur, then a final AgentResponse
for event in agent.run_streaming(query, session_context=None, top_k=None):
    ...
```

- `retriever` is Member 2's `build_default_retriever(...)`; `llm` is `OpenRouterLLM` (never `CachingLLM` on a production server)
- Both calls are **synchronous** and take 12 to 36 seconds per model call on the free model, so an async server must run them in a thread
- `top_k` is clamped to 1 to 20; `session_context` is accepted and unused

Design principles:
- **Observable**: every meaningful decision (classify, retrieve, synthesize, verify, retry) emits a trace event. Nothing happens silently
- **Predictable**: always returns an `AgentResponse`, even in the worst case. It never raises
- **Bounded**: the caller never needs its own loop protection (`max_steps` 12, `max_retries` 2, `max_subqueries` 5)

---

## 3. Trace Events for the Frontend (via Member 4 → Member 5)

The frontend shows something like:

```
✓ Classified as multi-hop; 3 sub-queries
✓ Retrieved 18 passages across 3 sub-queries
✓ Draft answer generated with 2 citations
⚠ 3 of 4 claims verified; searching again for 1 unsupported claim
✓ Found 8 new passages (20 in total)
✓ Draft answer generated with 2 citations
✓ 2 of 2 claims verified
```

Each `AgentStep.content` is already written for the UI. The exact strings:

| Step | Content |
|---|---|
| `plan` | "Classified as simple; 1 sub-query" · "Classified as multi-hop; 3 sub-queries" (with "; N reworded to match the document's terms" only if rewrites are on) · "Could not plan the question; searching with the original wording" |
| `retrieve` | "Retrieved 8 passages across 1 sub-query" · "Found 5 new passages (13 in total)" · "No new passages found" · "No relevant passages found" · "Search failed; no passages retrieved" · any of these with "; 1 passage removed because it contains instructions" |
| `synthesize` | "Draft answer generated with 1 citation" · "The passages do not contain the answer; searching again" · "The passages do not contain the answer" · "No relevant passages; the generator was not called" · "Search failed; the generator was not called" · "Could not generate a draft answer" |
| `fact_check` | "1 of 1 claim verified" · "3 of 4 claims verified; searching again for 1 unsupported claim" · "1 of 2 claims verified; 1 could not be verified" · "No claim could be verified in the documents" · "No new passages found; finalising with the best available answer" · "Could not verify the answer; returning the draft marked unverified" · "Step limit reached before the answer was checked; returning the draft marked unverified" · "Step limit reached before an answer was written" · "The agent stopped unexpectedly; returning what is available marked unverified" |

Notes:
- Counts in the trace are ones this module computes itself (passages per sub-query, passages after merging). Member 2's optional candidate counts ("searched N, reranked to R") are not available, so the UI must not promise "reranked" wording
- A retry is shown honestly. "Searching again" appears for two reasons: the checker found unsupported claims, or the draft said the passages do not contain the answer
- Metadata keys are listed in the Backend Schema, Section 7. They hold counts and labels only; no prompts and no passage text

---

## 4. The Answer States (each must be shown distinctly)

Retrieval never decides "no answer"; this module does. The exact answer texts:

| Situation | Answer text | Status |
|---|---|---|
| Nothing retrieved | "I don't have sufficient evidence in the provided documents." (no draft was generated) | `unverified` |
| Passages found, but they do not contain the answer after the allowed searches | The same text | `unverified` |
| Passages found, but no claim of the draft is supported | The same text (the unsupported draft is not shown) | `unverified` |
| Some claims supported, some not, retries used up | The answer, followed by "Could not be verified in the documents:" and the unsupported claims | `partially_verified` |
| Most claims supported (at or above 80%) with a few unsupported | The answer, followed by the same list | `verified` |
| The search itself failed | "I couldn't search the documents right now. Please try again." | `unverified` |
| The model failed or returned an empty draft | "I couldn't write an answer right now. Please try again." | `unverified` |
| The check failed | The draft, marked unverified; the trace says "Could not verify the answer; returning the draft marked unverified" | `unverified` |
| Blank question | "Please enter a question." (no trace) | `unverified` |
| The agent stopped unexpectedly | The draft, or "I couldn't write an answer right now. Please try again."; the last trace step says "The agent stopped unexpectedly..." | `unverified` |

- The UI should present the insufficient-evidence answer as a clear, honest answer, not as an error or a blank screen
- Never let this state read as "the system didn't try": the trace still shows what was searched
- Error details never reach the UI; only the error's type name appears in the last trace step

---

## 5. Trust Levels (what the status means)

| `verification_status` | Meaning | Suggested treatment |
|---|---|---|
| `verified` | Enough of the answer's claims (at least 80%) were found in the retrieved passages | Normal, confident display |
| `partially_verified` | Some claims supported; retries were used up | Visible caution: "Some parts of this answer could not be fully verified" |
| `unverified` | No claim supported, no evidence, the check failed, or an error | Strong warning treatment; never the same visual confidence as `verified` |

- **"Verified" means the claims appear in the retrieved passages. It does not mean the document itself is correct.** If a document contains a false statement, a verified answer repeats it. The UI copy should say "found in the documents", not "correct"
- `unverified` always has confidence 0. Confidence never exceeds 0.95
- The 80% threshold is an initial value, not yet calibrated on Member 5's golden dataset

---

## 6. Recommended UX Behaviours (for Member 5 to consider)

- Show the trace **progressively** as steps complete, not all at once at the end
- Show a retry honestly ("searching again") rather than hiding it; a visible self-correction is a feature
- **Citations.** Each citation links to the `page_number` of its chunk. `text_snippet` is an excerpt of at most 200 characters: the sentence that best supports the claim, with a leading "..." when it starts in the middle of the chunk. It is not the whole passage, so offer a way to open the source. The filename is not in `Citation`; Member 4 adds it (`source_file`) from the `document_id`
- **Streaming.** The final answer is streamed *after* verification: if tokens streamed before the check and a retry then changed the answer, the user would watch text get retracted. The cost is a longer wait before the first word, because verification (and any retry) finishes first; the trace panel fills the wait, so the screen is never idle. Measured on the free model: 36 to 175 seconds per question live
- **Waiting.** A single model call can take 12 to 36 seconds with no event in between. Show the last step as "in progress", send heartbeats (Member 4), and never show an infinite spinner

---

## 7. How Trace Steps Map to Member 4's SSE Events

| Agent output | SSE event (Member 4) |
|---|---|
| each `AgentStep` (plan, retrieve, synthesize, fact_check) | `status` |
| each citation of the final answer | `source` |
| the final answer text | `token` (split the finished answer into words) |
| the final status and confidence | `verification` |
| end of response | `done` (with `latency_ms`) |

Member 4 owns the exact event shapes. If a step type needs its own event, that is a team sync.

---

## 8. What NOT to Show (avoid overwhelming the user)

- Raw LLM prompts or internal reasoning text: the trace summarises *decisions*
- Every claim-level check individually: aggregate into "4 of 4 claims verified" unless the user expands it
- Internal counters (`retry_count`, `step_count`) as raw numbers: say "searching again" instead
- The model's search hints or rewritten queries by default: keep them behind an expand control
- Raw error text or stack traces: failures always arrive as a human-readable answer plus a status

---

## 9. Out of Scope for This Module

- Rendering the trace UI, chat bubbles and citation links: Member 5
- Streaming transport (SSE) mechanics: Member 4
- Authentication, sessions, document upload control, and the agent's own bounded retries versus client retries: Member 4
