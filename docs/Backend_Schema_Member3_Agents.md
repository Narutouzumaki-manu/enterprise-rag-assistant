# Backend Schema Document
## Module: Agentic Orchestration (LangGraph)
### Owner: Member 3 — Agentic Orchestration Engineer
### Project: Enterprise RAG Assistant
### Version: v0.2 (revised Session 12, October 2026; supersedes the September v0.1)

---

## 0. What changed from v0.1

| # | Change | Section |
|---|---|---|
| 1 | `AgentState` extended: `query_type`, `search_queries`, `top_k`, `unsupported_claims`, `coverage`, `trace`, `verification_status` | 3 |
| 2 | New internal models for the planner and fact-checker (`Plan`, `ClaimVerdict`, `Verification`) | 4 |
| 3 | New `AgentConfig` (all caps and thresholds in one place) | 5 |
| 4 | Persistent tables: **unchanged**; notes added on what goes into `agent_traces.metadata` | 6 |
| 5 | Data flow redrawn: rewrite step, evidence merge, no-evidence shortcut, retry loop | 7 |
| 6 | Open items updated; two cross-module gaps added | 8 |

The frozen output contract (`AgentResponse`, `AgentStep`, `Citation`) is **unchanged**.

---

## 1. Purpose

This document defines the data schemas owned by the Agentic Orchestration module: the Pydantic contracts for the agent's final response, the internal models used between LangGraph nodes, and the shared in-memory state structure.

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
| `trace` | `list[AgentStep]` | Full ordered sequence of reasoning steps; Member 5 renders it progressively in the agent-status UI |
| `citations` | `list[Citation]` | Each citation traces back to a `chunk_id` / `document_id` from Member 2's `RetrievedChunk`, always tied to actual retrieved evidence and **limited to chunks that support a surviving claim**. Never fabricated |
| `verification_status` | `str` | `"verified"` (coverage at or above threshold), `"partially_verified"` (some claims supported, retries exhausted), `"unverified"` (no claim supported, no evidence, or the checker failed). Should become an Enum (open item, Section 8) |
| `confidence` | `float` | 0–1, derived from fact-checker claim coverage. Never hard-coded to 1.0 |
| `text_snippet` | `str` | Short excerpt of the cited chunk's text, so users can verify the claim without opening the source |
| `latency_ms` | `float` | End to end, including retries |

**Not in the contract (so nobody assumes otherwise):** there is no filename on `Citation`, only `document_id`. The UI must resolve the name (open item, Section 8).

---

## 3. Shared Agent State (in-memory, per request, not persisted directly)

Location: `app/agents/state.py`

```python
from typing import TypedDict

class AgentState(TypedDict):
    query: str
    query_type: str                  # simple | multi-hop | comparison | aggregation | ambiguous
    subqueries: list[str]            # max 5
    search_queries: list[str]        # originals + rewrites actually sent to retrieve()
    top_k: int                       # starts at config.top_k (8); widened on retry 2
    retrieved_chunks: list           # RetrievedChunk objects (Member 2), merged, deduped by chunk_id
    draft_answer: str
    claims: list[str]
    verification_results: list[dict] # per claim: supported, supporting chunk_ids, reason
    unsupported_claims: list[str]
    coverage: float                  # supported claims / total claims
    confidence: float
    retry_count: int
    step_count: int
    trace: list                      # AgentStep objects, in order
    final_answer: str | None
    verification_status: str
```

This `TypedDict` is the object LangGraph passes between nodes. It is **not** written to a database directly: only the final `AgentResponse` and its trace are persisted by Member 4 (Section 6).

### Field Notes

| Field | Notes |
|---|---|
| `search_queries` | Includes the **original** wording of each sub-query plus, when different, its rewrite. A bad rewrite therefore cannot hide a good original match |
| `retrieved_chunks` | Merged by `chunk_id` (first occurrence wins). **Never read `sparse_score`, `fused_score` or `rerank_score`:** with Member 2's shipped configuration they are `None`. Scores from different queries are not comparable |
| `top_k` | 8 by default; widened (default 15, never above 20) on the second retry |
| `unsupported_claims` | Input to the retry step: each one drives a new search query |
| `step_count` | One step = one node execution. Cap is `max_steps = 12` (Section 5) |
| `verification_status` | Set once, at the end; mapping rules are in TRD Section 11 |

---

## 4. Internal Models (not part of the cross-module contract)

Location: `app/agents/` (used between nodes and for structured LLM output; not consumed by Members 4 or 5)

```python
from typing import Literal
from pydantic import BaseModel


class Plan(BaseModel):
    """Structured output of the planner's single LLM call."""
    query_type: Literal["simple", "multi-hop", "comparison", "aggregation", "ambiguous"]
    subqueries: list[str]          # one per fact; [original query] for simple queries
    rewrites: dict[str, str] = {}  # subquery -> rewritten form; omit when no rewrite is needed


class ClaimVerdict(BaseModel):
    claim: str
    supported: bool
    supporting_chunk_ids: list[str] = []
    reason: str = ""               # short, human-readable; not shown to end users by default


class Verification(BaseModel):
    """Structured output of the fact-checker's LLM call."""
    verdicts: list[ClaimVerdict]
```

- `coverage = sum(v.supported for v in verdicts) / len(verdicts)`; an empty `verdicts` list means the draft is treated as unverified
- A claim with a specific figure, name or date is `supported` only if that value appears in the evidence (TRD Section 11)
- `supporting_chunk_ids` is used to correct the final citation list after verification

---

## 5. Agent Configuration

Location: `app/agents/config.py`. All caps and thresholds live here, with no magic numbers inside nodes.

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class AgentConfig:
    top_k: int = 8                    # per search query; matches the backend default
    widened_top_k: int = 15           # used on retry 2; never above 20
    max_subqueries: int = 5
    max_retries: int = 2
    max_steps: int = 12               # two retries on a complex query need 10 steps
    max_evidence_chunks: int = 20     # cap on merged evidence
    coverage_threshold: float = 0.8   # INITIAL value; calibrate on Member 5's golden dataset
    use_similarity_hint: bool = False # pass top-1 dense_score to the fact-checker; off until calibrated
```

`coverage_threshold`, `widened_top_k` and `use_similarity_hint` are starting guesses, not measured values.

---

## 6. Persistent Database Schema (co-owned with Member 4, unchanged)

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

**What goes into `AgentStep.metadata`** (kept in the existing JSON column, so no table change is needed):

| step_type | Suggested metadata keys |
|---|---|
| `plan` | `query_type`, `subquery_count`, `rewritten` (bool) |
| `retrieve` | `search_query_count`, `chunks_per_subquery`, `chunks_after_merge`, `attempt` (0 = first pass) |
| `synthesize` | `citation_count`, `dropped_citations` |
| `fact_check` | `claims_total`, `claims_supported`, `coverage`, `retry` (bool) |

Keep metadata to counts and labels. **Do not store raw prompts, completions or chunk text** in it.

**Indexing recommendations:**
- Index `citations.message_id` and `agent_traces.message_id`: both are looked up every time a past message is re-rendered
- Index `agent_traces.message_id, step_order` together: needed to replay a trace in order

---

## 7. Data Flow: One Query, End to End

```
User query arrives (from Member 4's API)
      |
      v
AgentState initialised (query set, top_k = config.top_k, everything else empty/zero)
      |
      v
planner.py -> ONE structured LLM call -> Plan: query_type, subqueries, rewrites
      |          search_queries = originals + rewrites;   trace: "plan"
      v
retriever_agent.py -> retrieve() per search query -> merge by chunk_id (cap max_evidence_chunks)
      |          trace: "retrieve"
      |
      +-- evidence empty ----------------------------> no-evidence answer (generator NOT called)
      |                                                  status "unverified", trace noted
      v
synthesizer.py -> draft_answer + citations,  trace: "synthesize"
      |
      v
fact_checker.py -> claims -> verify against ALL evidence -> coverage,  trace: "fact_check"
      |
 coverage >= threshold ---------------------> final_answer set, status "verified"
      |
 coverage <  threshold, retry_count < max_retries
      |        -> new search_queries from unsupported_claims (retry 2 also widens top_k)
      |        -> back to retriever_agent.py, merge into existing evidence
      |        -> stop early if no new chunk_id arrived
      |
 retries exhausted ---------------> status "partially_verified" (some supported)
                                      or "unverified" (none supported -> insufficient-evidence answer)
      |
      v
AgentResponse built (answer, citations, trace, verification_status, confidence, latency_ms)
      |
      v
Returned to Member 4 -> persisted (messages / citations / agent_traces) -> streamed to Member 5's UI
```

Every path, including failures and cap hits, ends in a valid `AgentResponse`.

---

## 8. Open Items for Future Iteration

- Replace `verification_status: str` with `class VerificationStatus(str, Enum)`. JSON on the wire is identical, so consumers keep working; matches the same flagged improvement in Member 1's `IngestionResult.status`. Needs a team sync
- **Cross-module gap:** Member 4's synchronous `ChatResponse` has no `verification_status` (the streaming path has the `verification` event). The UI must show the trust level, so the synchronous response should carry it too
- **Cross-module gap:** `Citation` has `document_id` but no filename; the UI wants "[Finance Report, p.12]". Decide who resolves it (for example Member 5 via `/documents`)
- Candidate counts on `RetrievalResponse` (Member 2's proposal) are undecided; `agent_traces.metadata` above deliberately uses counts this module can compute itself
- Consider persisting the full `AgentState` for debugging and replay, once storage cost is evaluated
- Add a `model_version` field to `AgentResponse` once multiple LLM configurations are supported, so past answers can be traced to the model that produced them
- Calibrate `coverage_threshold`, `widened_top_k` and the optional similarity hint on Member 5's golden dataset, and record the measured values here
