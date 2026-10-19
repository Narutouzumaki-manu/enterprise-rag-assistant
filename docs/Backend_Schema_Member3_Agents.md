# Backend Schema Document
## Module: Agentic Orchestration (LangGraph)
### Owner: Member 3 — Agentic Orchestration Engineer
### Project: Enterprise RAG Assistant
### Version: v0.3 (Session 19, October 2026; written to match the implementation; supersedes v0.2)

---

## 0. What changed from v0.2

| # | Change | Section |
|---|---|---|
| 1 | `AgentState` gains `tried_queries` and `citations`; `trace` is documented as append-only | 3 |
| 2 | New internal model `Draft` (`answer_found`, `search_query`); `ClaimVerdict` gains `search_query` | 4 |
| 3 | `AgentConfig` documented in full: `max_confidence`, `use_rewrites`, `quarantine_instructions`, `llm_retries` | 5 |
| 4 | New: `LLMError` and the `CachingLLM` file format | 6 |
| 5 | Persistent tables: **unchanged**; the full list of `agent_traces.metadata` keys is now documented | 7 |
| 6 | Data flow redrawn: the "not found" search, the early stop and the step guard | 8 |
| 7 | Open items updated | 9 |

The frozen output contract (`AgentResponse`, `AgentStep`, `Citation`) is **unchanged**. The code blocks in Sections 3 to 5 are checked against the real code by `scripts/check_docs_against_code.py`.

---

## 1. Purpose

This document defines the data schemas owned by the Agentic Orchestration module: the Pydantic contracts for the agent's final response, the internal models used between LangGraph nodes, the configuration, and the shared in-memory state structure.

---

## 2. Pydantic Schemas (Application Layer, frozen)

Location: `app/schemas/agent.py`
Status: **Frozen, v0.1-contracts, unchanged**. Changes require a team sync (Members 4 and 5 depend on this).

```python
from pydantic import BaseModel
from enum import Enum


class AgentStepType(str, Enum):
    PLAN = "plan"
    RETRIEVE = "retrieve"
    FACT_CHECK = "fact_check"
    SYNTHESIZE = "synthesize"


class AgentStep(BaseModel):
    step_type: AgentStepType
    content: str
    metadata: dict = {}


class Citation(BaseModel):
    chunk_id: str
    document_id: str
    page_number: int | None = None
    text_snippet: str


class AgentResponse(BaseModel):
    answer: str
    citations: list[Citation]
    trace: list[AgentStep]
    verification_status: str   # "verified" | "partially_verified" | "unverified"
    confidence: float
    latency_ms: float
```

### Field Notes

| Field | Type | Notes |
|---|---|---|
| `trace` | `list[AgentStep]` | Full ordered sequence of reasoning steps; Member 5 renders it progressively |
| `citations` | `list[Citation]` | Each traces back to a `chunk_id` / `document_id` from Member 2's `RetrievedChunk`, always tied to actual retrieved evidence and **limited to chunks that support a surviving claim** |
| `text_snippet` | `str` | At most 200 characters: the chunk sentence that best matches the claim (a leading "..." means it starts mid-chunk); the start of the chunk when nothing matches |
| `verification_status` | `str` | `"verified"` (coverage at or above the threshold), `"partially_verified"` (some claims supported, retries exhausted), `"unverified"` (no claim supported, no evidence, the check failed, the step cap was hit, or an error). Optional improvement: a `str` Enum, identical JSON |
| `confidence` | `float` | 0 to 1, derived from coverage, **capped at `max_confidence` (0.95)**, always 0 for `unverified` |
| `latency_ms` | `float` | End to end, including retries |

**Not in the contract (so nobody assumes otherwise):** there is no filename on `Citation`, only `document_id`. Member 4 resolves the name from the documents table when building the response. "Verified" means faithful to the retrieved passages, not true.

---

## 3. Shared Agent State (in-memory, per request, not persisted directly)

Location: `app/agents/state.py`

```python
class AgentState(TypedDict):
    query: str
    query_type: str                  # simple | multi-hop | comparison | aggregation | ambiguous
    subqueries: list[str]            # max 5
    search_queries: list[str]        # what the retriever node searches this pass
    tried_queries: list[str]         # searches that actually ran, in order, no duplicates
    top_k: int                       # starts at the request or config value; widened on retry 2
    retrieved_chunks: list[RetrievedChunk]   # merged, deduped by chunk_id
    draft_answer: str
    citations: list[Citation]        # the draft's citations; rebuilt after verification
    claims: list[str]
    verification_results: list[dict] # per claim: claim, supported, supporting_chunk_ids, search_query, reason
    unsupported_claims: list[str]
    coverage: float                  # supported claims / total claims
    confidence: float
    retry_count: int
    step_count: int
    trace: Annotated[list[AgentStep], operator.add]   # each node APPENDS; every other field is overwritten
    final_answer: str | None
    verification_status: str
```

This `TypedDict` is the object LangGraph passes between nodes. It is **not** written to a database directly: only the final `AgentResponse` and its trace are persisted by Member 4 (Section 7). `initial_state()` starts it fail-safe (`unverified`, confidence 0) with fresh lists, so questions never share state.

### Field Notes

| Field | Notes |
|---|---|
| `search_queries` | The original question first, then the sub-queries (and rewrites only when `use_rewrites` is on). On a retry it is replaced by the retry searches |
| `tried_queries` | Filled by the retriever node with every search that actually ran (a failed search is not recorded); listed in the next draft's prompt so retries do not repeat themselves |
| `retrieved_chunks` | Merged by `chunk_id`, interleaved across searches before the cap of 20; **never read `sparse_score`, `fused_score` or `rerank_score`** (they are `None` with Member 2's shipped configuration) |
| `top_k` | The request value or 8; becomes `max(widened_top_k, current)` on the second retry or a wider search |
| `verification_results` | One dict per claim: `claim`, `supported`, `supporting_chunk_ids`, `search_query`, `reason` |
| `unsupported_claims` | Input to the retry step and to the next draft's prompt |
| `step_count` | One step = one node execution; cap `max_steps` (12) |
| `final_answer` | Set by any node that ends the run; a set value always means "done" |

---

## 4. Internal Models (not part of the cross-module contract)

Location: `app/agents/` (used between nodes and as structured LLM output; not consumed by Members 4 or 5)

```python
class Plan(BaseModel):
    """Structured output of the planner's single LLM call (planner.py)."""
    query_type: Literal["simple", "multi-hop", "comparison", "aggregation", "ambiguous"]
    subqueries: list[str]          # one per fact; ignored for simple and ambiguous queries
    rewrites: dict[str, str] = {}  # subquery -> rewritten form; searched only when use_rewrites is on


class Draft(BaseModel):
    """Structured output of the generator's LLM call (synthesizer.py)."""
    answer: str
    cited_chunk_ids: list[str] = []
    answer_found: bool = True      # false when the passages do not contain the answer
    search_query: str = ""         # then: a short search likely to find the missing information


class ClaimVerdict(BaseModel):
    """One claim of the draft and its verdict (fact_checker.py)."""
    claim: str
    supported: bool
    supporting_chunk_ids: list[str] = []
    search_query: str = ""         # for an unsupported claim: how to look for the missing fact
    reason: str = ""


class Verification(BaseModel):
    """Structured output of the fact-checker's single LLM call."""
    verdicts: list[ClaimVerdict]
```

- `coverage = supported / total` over the cleaned verdicts; an empty list means the check failed and the draft is returned `unverified`
- A verdict counts as supported only if it names at least one passage that was really retrieved; a claim with a figure, name or date is supported only if that value appears in the evidence
- `Draft.cited_chunk_ids` is advisory: citations are built in code from the retrieved chunks, and unknown ids are dropped and counted
- `Draft.answer_found` false never reaches the fact-checker: the agent searches again with `search_query`, or ends with the insufficient-evidence answer

---

## 5. Agent Configuration

Location: `app/agents/config.py`. All caps and thresholds live here, with no magic numbers inside nodes. The config is frozen and validates itself when created.

```python
FIRST_PASS_STEPS = 4      # planner, retrieve, synthesize, fact-check
STEPS_PER_RETRY = 3       # retrieve, synthesize, fact-check
TOP_K_LIMIT = 20          # the backend's ChatRequest limit


@dataclass(frozen=True)
class AgentConfig:
    top_k: int = 8                     # per search query; matches the backend default
    widened_top_k: int = 15            # used on retry 2; never above TOP_K_LIMIT
    max_subqueries: int = 5
    max_retries: int = 2
    max_steps: int = 12                # two retries on a complex query need 10 steps
    max_evidence_chunks: int = 20      # cap on merged evidence
    coverage_threshold: float = 0.8    # INITIAL value; not calibrated
    max_confidence: float = 0.95       # never claim certainty
    use_rewrites: bool = False         # also search the planner's rewrites (no measured benefit)
    quarantine_instructions: bool = True   # remove passages that address the AI
    use_similarity_hint: bool = False  # reserved; unused
    llm_retries: int = 1               # retry a failed LLM call once, with backoff
```

Validation (raises `ValueError`): `top_k` between 1 and 20; `widened_top_k` between `top_k` and 20; `max_subqueries` at least 1; `max_retries` at least 0; `max_evidence_chunks` at least 1; `coverage_threshold` between 0 and 1; `max_confidence` above 0 and at most 1; `llm_retries` at least 0; and **`max_steps >= FIRST_PASS_STEPS + STEPS_PER_RETRY * max_retries`**.

`coverage_threshold`, `widened_top_k` and `max_confidence` are starting guesses, not measured values.

---

## 6. LLM Errors and the Cache File

**`LLMError`** (`app/agents/llm.py`) is the one error type for any failed model call: timeout, rate limit, output that does not fit the requested schema, a replay-only cache miss. Nodes catch only this.

**`CachingLLM` file** (`app/agents/llm_cache.py`, default location `data/llm_cache/`, git-ignored): a JSON object whose keys are SHA-256 hashes of `[namespace\n]kind\nsystem\nprompt` (`kind` is `complete` or the schema's class name) and whose values are the saved answer (text, or the schema object as JSON). An entry that no longer fits the current schema is a miss. Failures are never saved. The planner cache written by the early measurement scripts (`data/eval/planner_cache.json`) uses the same format.

---

## 7. Persistent Database Schema (co-owned with Member 4, unchanged)

Member 4 owns the FastAPI/Postgres implementation. This module defines the **data it needs persisted** so chat history and traces survive across requests.

### Table: `messages` (extended for agent output)

| Column | Type | Notes |
|---|---|---|
| `message_id` | `str` (PK) | |
| `session_id` | `str` (FK) | |
| `role` | `str` | "user" or "assistant" |
| `content` | `text` | The final answer text |
| `verification_status` | `str` | "verified" / "partially_verified" / "unverified" |
| `confidence` | `float` | |
| `latency_ms` | `int` | |
| `created_at` | `timestamp` | |

### Table: `citations`

| Column | Type | Notes |
|---|---|---|
| `citation_id` | `str` (PK) | |
| `message_id` | `str` (FK → messages) | |
| `chunk_id` | `str` | References the chunk from Members 1/2's pipeline |
| `document_id` | `str` | |
| `page_number` | `int \| null` | |
| `text_snippet` | `str` | |

### Table: `agent_traces`

| Column | Type | Notes |
|---|---|---|
| `trace_id` | `str` (PK) | |
| `message_id` | `str` (FK → messages) | |
| `step_order` | `int` | Preserves the sequence for replay and debugging |
| `step_type` | `str` | plan / retrieve / fact_check / synthesize |
| `content` | `text` | |
| `metadata` | `dict` (JSON column) | See below |

**`AgentStep.metadata` keys** (kept in the existing JSON column, so no table change is needed; counts and labels only, never prompts, completions or chunk text):

| step_type | Keys |
|---|---|
| `plan` | `query_type`, `subquery_count`, `rewritten` (bool); `fallback` (true when planning failed) |
| `retrieve` | `search_query_count`, `chunks_per_search` (list), `chunks_after_merge`, `new_chunks`, `attempt` (0 = first pass), `errors`, `quarantined` |
| `synthesize` | `citation_count`, `dropped_citations`, `generator_called`; `not_found` and `retry_search` (the passages lack the answer and another search follows); `reason` (`no_evidence`, `search_failed`, `llm_failed` or `not_found` on a terminal answer) |
| `fact_check` | `claims_total`, `claims_supported`, `coverage`, `retry` (bool); `checker_failed`, `stopped_early`, `step_limit`, `agent_error` (the error's type name only) |

**Indexing recommendations:**
- Index `citations.message_id` and `agent_traces.message_id`: both are looked up every time a past message is re-rendered
- Index `agent_traces.message_id, step_order` together: needed to replay a trace in order

---

## 8. Data Flow: One Query, End to End

```
User query arrives (from Member 4's API)
      |
      v
AgentState initialised (query set, top_k from the request or config, everything else empty / zero)
      |
      v
planner node -> ONE structured LLM call -> Plan; search_queries = original question first, then the sub-queries
      |          trace: "plan"        (LLM failure -> one simple search, fallback)
      v
retriever node -> retrieve() per search query -> instruction filter -> merge by chunk_id (interleaved, cap 20)
      |          tried_queries updated;   trace: "retrieve"
      |
      +-- a retry found no new passages --------------> finalize node -> final answer (best checked so far)
      +-- no room for synthesize + check --------------> step_limit node
      v
synthesizer node -> ONE structured call -> Draft;  trace: "synthesize"
      |
      +-- no passages / search failed / model failed ---> final answer set (insufficient evidence or error text), END
      +-- answer_found = false:
      |       searches left -> search_queries = [hint], retry_count + 1  -> back to the retriever node
      |       none left ------> insufficient-evidence answer, END
      v
fact-checker node -> ONE structured call -> verdicts -> coverage;  trace: "fact_check"
      |
 coverage >= threshold ---------------------------> final_answer set, status "verified", END
      |
 below, retries and steps left -> unsupported claims drive new search_queries (retry 2 widens top_k) -> retriever node
      |
 below, none left ---------------> "partially_verified" (some supported) or insufficient evidence (none supported), END
      |
      v
Agent builds AgentResponse (answer, citations, trace, verification_status, confidence, latency_ms)
      |
      v
Returned to Member 4 -> persisted (messages / citations / agent_traces) -> streamed to Member 5's UI
```

Every path, including failures and cap hits, ends in a valid `AgentResponse`.

---

## 9. Open Items for Future Iteration

- Replace `verification_status: str` with a `str` Enum. JSON on the wire is identical; needs a team sync
- **Cross-module gap:** Member 4's synchronous `ChatResponse` has no `verification_status` (the streaming path has the `verification` event). The UI must show the trust level, so the synchronous response should carry it too
- **Cross-module gap:** `Citation` has `document_id` but no filename; Member 4 adds `source_file` when building the response (recommended)
- `session_context` is accepted by the agent and unused; reserved for chat history
- Consider persisting the full `AgentState` for debugging and replay, once storage cost is evaluated
- Add a `model_version` field to `AgentResponse` once multiple LLM configurations are supported
- Calibrate `coverage_threshold`, `widened_top_k` and `max_confidence` on Member 5's golden dataset, or keep them recorded as uncalibrated
