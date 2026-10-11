# UI/UX Notes
## Module: Agentic Orchestration (LangGraph)
### Owner: Member 3 — Agentic Orchestration Engineer
### Project: Enterprise RAG Assistant
### Version: v0.2 (revised Session 12, October 2026; supersedes the September v0.1)

---

## 0. What changed from v0.1

| # | Change | Section |
|---|---|---|
| 1 | Developer-facing interface now builds the agent once (`build_agent`) instead of `run_agent(...)` | 2 |
| 2 | Trace events updated for query rewriting, per-sub-query retrieval, and honest retries | 3 |
| 3 | New: the "insufficient evidence" experience and how it must look | 4 |
| 4 | Trust-level treatment clarified (what `verified`, `partially_verified`, `unverified` mean) | 5 |
| 5 | Streaming: a proposal to stream the final, post-verification answer | 6 |
| 6 | Mapping from trace steps to Member 4's SSE events added | 7 |

---

## 1. Scope Note

This module has **no direct end-user interface**, but its internal reasoning steps are explicitly meant to be *shown* to the user in Member 5's "agent trace" panel. That is one of the project's stated differentiators, so the trace output deserves real design care even though Member 3 renders no pixels.

This document covers:
1. The **developer-facing interface** this module exposes to Member 4
2. The **trace events** Member 5 renders live during a query
3. What makes a trace trustworthy and not overwhelming
4. How the module's honest failure states ("I don't have enough evidence") should reach the user

---

## 2. Developer-Facing Interface

```python
# Built ONCE per process by Member 4 at startup (model loading takes seconds)
agent = build_agent(retriever, llm, config=AgentConfig())

# Called by Member 4's /chat endpoint
response: AgentResponse = agent.run(query: str, session_context: dict | None = None)

# Streaming variant, called by /chat/stream: yields AgentStep events as they occur, then a final AgentResponse
for event in agent.run_streaming(query: str, session_context: dict | None = None):
    ...
```

`retriever` is Member 2's `build_default_retriever(...)`; `llm` is the project's `LLMClient`. This replaces the v0.1 `run_agent(...)` sketch and needs a short sync with Member 4.

Design principles:
- **Observable**: every meaningful decision (classify, rewrite, decompose, retrieve, synthesize, verify, retry) emits a trace event. Nothing happens silently
- **Predictable**: always returns an `AgentResponse`, even in the worst case (empty evidence, LLM failure, step cap hit). It never raises unhandled
- **Bounded**: the caller never needs its own loop protection; the graph guarantees termination (`max_steps = 12`, `max_retries = 2`, `max_subqueries = 5`)

---

## 3. Trace Events for the Frontend (via Member 4 → Member 5)

The frontend shows something like:

```
✓ Question analysed
✓ 2 searches planned
✓ 14 passages found
✓ Answer drafted
⚠ Re-checking evidence... (1 retry)
✓ Answer verified
```

One trace event per step, in this shape:

| step_type | Example `content` | Suggested frontend treatment |
|---|---|---|
| `plan` | "Classified as multi-hop; 2 sub-queries; 1 reworded to match the document's terms" | "✓ Question analysed", expandable to show the sub-queries |
| `retrieve` | "Retrieved 14 passages across 2 sub-queries" | "✓ 14 passages found" |
| `retrieve` (nothing found) | "No relevant passages found" | "No relevant information found in the uploaded documents" (see Section 4) |
| `synthesize` | "Draft answer generated with 5 citations" | "✓ Answer drafted" |
| `fact_check` (retry) | "3 of 4 claims verified; searching again for 1 unsupported claim" | "⚠ Re-checking evidence... (1 retry)" |
| `fact_check` (final) | "4 of 4 claims verified" | "✓ Answer verified" |

Notes:
- Counts in the trace are ones this module computes itself (passages per sub-query, passages after merging). Member 2's optional candidate counts ("searched N, reranked to R") are **not** available by default, so the UI must not promise "reranked" wording unless that feature is later adopted
- A rewrite is shown as a decision ("1 reworded to match the document's terms"), with the actual rewritten text available only on expand

---

## 4. When There Is No Evidence (a first-class state)

Retrieval never decides "no answer"; this module does. Three outcomes the UI must be able to show distinctly:

| Situation | Answer the user sees | Status |
|---|---|---|
| Nothing retrieved at all | "I don't have sufficient evidence in the provided documents." No draft was generated | `unverified` |
| Passages found, but none of the answer's claims are supported (including the case of an on-topic passage that lacks the specific figure) | The same insufficient-evidence message, not the unsupported draft | `unverified` |
| Some claims supported, some not, retries used up | The answer with the unsupported parts removed or flagged | `partially_verified` |

- The UI should present the first two as a clear, honest answer, not as an error or a blank screen
- Never let this state read as "the system didn't try": the trace still shows what was searched

---

## 5. Trust Levels (what the status means)

| `verification_status` | Meaning | Suggested treatment |
|---|---|---|
| `verified` | Enough of the answer's claims (initially 80% or more) were found in the retrieved text | Normal, confident display |
| `partially_verified` | Some claims supported; retries were used up | Visible caution icon or banner: "Some parts of this answer could not be fully verified" |
| `unverified` | No claim supported, no evidence, or the checker itself failed | Strong warning treatment; never the same visual confidence as `verified` |

- "Verified" means the claims appear in the retrieved text. It does **not** mean the document itself is correct
- The 80% threshold is an initial value, still to be calibrated on Member 5's golden dataset

---

## 6. Recommended UX Behaviours (for Member 5 to consider)

- Show the trace **progressively** as steps complete, not all at once at the end
- Show a retry honestly ("⚠ Re-checking evidence...") rather than hiding it; a visible self-correction is a feature
- Citations link to the exact `page_number` / `section_title` of the originating chunk. The filename is not in `Citation`; resolve it from the documents list by `document_id`
- **Streaming proposal (needs agreement with Members 4 and 5):** stream the *final, post-verification* answer. If tokens streamed before fact-checking and a retry then changed the answer, the user would watch text get retracted. The cost is a longer wait before the first token, because verification (and any retry) finishes first. The trace panel fills the wait, so the screen is never idle. Latency per question has not been measured yet; revisit if the wait proves too long

---

## 7. How Trace Steps Map to Member 4's SSE Events

| Agent output | SSE event (Member 4) |
|---|---|
| `AgentStep` of type `plan` / `retrieve` / `synthesize` / `fact_check` (in progress) | `status` |
| Citations of the final answer | `source` |
| Final answer text | `token` (streamed from the verified answer, per Section 6) |
| `verification_status` of the final response | `verification` |
| End of response | `done` |

Member 4 owns the exact event shapes. If a step type needs its own event, that is a team sync.

---

## 8. What NOT to Show (avoid overwhelming the user)

- Raw LLM prompts or internal reasoning text: the trace summarises *decisions*, not prompt and completion text
- Every claim-level check individually: aggregate into "4 of 4 claims verified" unless the user expands it
- Internal counters (`retry_count`, `step_count`) as raw numbers: say "re-checking evidence..." instead
- Rewritten query text by default: keep it behind an expand control
- Raw error text or stack traces: failures always arrive as a human-readable answer plus a status

---

## 9. Out of Scope for This Module

- Rendering the trace UI, chat bubbles and citation links: Member 5
- Streaming transport (SSE) mechanics: Member 4
- Authentication, sessions and retry logic outside the agent's own bounded retries: Member 4
