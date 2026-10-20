# Technical Requirements Document (TRD)

## Module: Agentic Orchestration (LangGraph)

### Owner: Member 3 — Agentic Orchestration Engineer

### Project: Enterprise RAG Assistant

### Version: v0.3 (implementation aligned in Session 19; Session 20 evaluation status recorded in `MEMBER3_DECISIONS.md` §2.10; supersedes v0.2)

------------------------------------------------------------------------

## 0. What changed from v0.2

| \#  | Change                                                                                                                                           | Section   |
|:----|:-------------------------------------------------------------------------------------------------------------------------------------------------|:----------|
| 1   | New “not found” path: the draft carries `answer_found` and `search_query`; the agent searches again, then gives the insufficient-evidence answer | 2, 10, 13 |
| 2   | Retry hints come from the fact-checker’s single call (no separate rewrite step)                                                                  | 11, 13    |
| 3   | Retries do not repeat searches: `tried_queries`, a prompt note, and a wider search when a hint repeats                                           | 9, 13     |
| 4   | Planner always searches the original question first; rewrites are off by default (`use_rewrites`)                                                | 8         |
| 5   | Instruction filter (`guard.py`) in the retriever node                                                                                            | 9, 14     |
| 6   | Interleaved merge before the evidence cap; new passages first on a retry                                                                         | 9         |
| 7   | Citation snippets show the sentence that best matches the claim                                                                                  | 10        |
| 8   | `finalize` and `step_limit` nodes; routing functions; recursion limit                                                                            | 2, 14     |
| 9   | `Agent` entry point (`run`, `run_streaming`) that never raises                                                                                   | 5, 12     |
| 10  | `OpenRouterLLM` adapter and `CachingLLM`                                                                                                         | 5         |
| 11  | Confidence capped (`max_confidence`); unsupported claims flagged in the answer text                                                              | 11        |
| 12  | Measured latency and call counts; proposals from v0.2 Section 18 resolved                                                                        | 18, 20    |

The frozen output contract (`AgentResponse`, `AgentStep`, `Citation`) is
**unchanged**.

------------------------------------------------------------------------

## 1. Scope

Technical design for the agent graph: query classification and
decomposition, retrieval-tool calling, evidence merging, answer
synthesis, claim-level fact-checking, bounded retry logic, and the
public entry point, all implemented as an explicit LangGraph state
machine.

------------------------------------------------------------------------

## 2. Architecture Overview

    START
      |
      v
    Planner  (ONE structured LLM call: classify + decompose; rewrites are produced but off by default)
      |
      v
    Retriever  (one search per search query, original question first; instruction filter; merge by chunk_id)
      |
      +-- a retry found no new passages ----------------> FINALIZE --> END
      +-- not enough steps left for synthesize + check --> STEP_LIMIT --> END
      |
      v
    Synthesizer  (ONE structured call: answer, cited ids, answer_found, search_query)
      |
      +-- no passages / search failed / generation failed --> END (final_answer set)
      +-- answer_found is false:
      |        searches left ---> back to Retriever (hint search; the second one widens top_k)
      |        none left -------> END (insufficient evidence)
      +-- not enough steps left for the check -------------> STEP_LIMIT --> END
      |
      v
    Fact-checker  (ONE structured call: claims -> verdicts)
      |
      +-- coverage >= 0.8 ---------------------> END (verified)
      +-- below, retries and steps left --------> back to Retriever (claim wording + hint; second retry widens top_k)
      +-- below, none left ---------------------> END (partially_verified, or insufficient evidence if nothing supported)

A set `final_answer` always means “done”. Simple and ambiguous queries
skip decomposition; the planner call still runs because it is the
classifier.

------------------------------------------------------------------------

## 3. Tech Stack

| Component         | Tool                                                                          | Reason                                                  |
|:------------------|:------------------------------------------------------------------------------|:--------------------------------------------------------|
| Language          | Python 3.11+                                                                  | Matches the rest of the team                            |
| Orchestration     | LangGraph (`StateGraph`, conditional edges)                                   | Explicit state machine \> implicit chains               |
| LLM access        | Own `LLMClient` protocol; `OpenRouterLLM` (OpenAI-compatible client)          | No hard dependency on one provider; trivial to mock     |
| Model             | `nvidia/nemotron-3-super-120b-a12b:free` through OpenRouter                   | Free; valid structured output on every live call so far |
| Structured output | Pydantic models, JSON schema in the request and repeated in the system prompt | Enforces plan, draft and verdict shapes                 |
| Tokenization      | `tiktoken`                                                                    | Consistent with Members 1 and 2                         |
| Testing           | `pytest`, `MockRetriever`, `MockLLM`                                          | No model or network needed for unit tests               |
| Evaluation        | RAGAS (run by Member 5)                                                       | Quantitative, CI-gatable                                |

------------------------------------------------------------------------

## 4. Module Breakdown

    app/agents/
    ├── state.py             — AgentState TypedDict and initial_state()
    ├── config.py            — AgentConfig (frozen, validated); step constants
    ├── llm.py               — LLMClient protocol, LLMError, OpenRouterLLM
    ├── llm_cache.py         — CachingLLM (replayable LLM answers)
    ├── guard.py             — instruction filter for retrieved passages
    ├── planner.py           — Plan model and the planner node
    ├── retriever_agent.py   — retriever node, interleave
    ├── synthesizer.py       — Draft model, synthesizer node, citations, snippets
    ├── fact_checker.py      — Verification models, fact-checker node, finalize node
    ├── graph.py             — routing functions, step_limit node, build_graph, run_config
    └── agent.py             — Agent class and build_agent

    scripts/                 — live_agent_run, live_safety_checks, safety_judges, measure_planner,
                               planner_ablation, check_hints, check_docs_against_code, try_* hand-checks
    tests/unit/agents/       — mocks.py (MockRetriever, MockLLM) and test_*.py

------------------------------------------------------------------------

## 5. Interfaces

### 5.1 The agent

``` python
agent = build_agent(retriever, llm, config=AgentConfig())     # build ONCE per process
response: AgentResponse = agent.run(query, session_context=None, top_k=None)
for event in agent.run_streaming(query, session_context=None, top_k=None):   # AgentStep ..., then AgentResponse
    ...
```

- `retriever` is anything with
  `retrieve(RetrievalRequest) -> RetrievalResponse`: in production
  Member 2’s `build_default_retriever(...)`, in tests `MockRetriever`
- `top_k` is clamped to 1 to 20; if omitted, `AgentConfig.top_k` (8) is
  used. `session_context` is accepted and unused
- `run()` reads `run_streaming()` to the end, so the two share one code
  path. Both are **synchronous**: in an async server they run in a
  thread
- A blank question returns “Please enter a question.” without any model
  or retriever call
- Whatever happens inside, the caller gets a valid `AgentResponse`: a
  graph error (including LangGraph’s recursion-limit error) becomes an
  `unverified` response with the draft if one exists, confidence 0, and
  a trace step whose metadata holds only the error’s type name
  (`agent_error`). The details go to the log, never to the response
- The response is sanity-checked: an unknown status becomes
  `unverified`, `unverified` means confidence 0, confidence is clamped
  to 0 to 1

### 5.2 LLM interface

``` python
class LLMClient(Protocol):
    def complete(self, system: str, prompt: str) -> str: ...
    def complete_structured(self, system: str, prompt: str, schema: type[T]) -> T: ...
```

- **`LLMError`** is the one error for any failed call: timeout, rate
  limit, or output that does not fit the schema. Nodes catch only this
- **`OpenRouterLLM`**: the SDK’s own retries are off, so every request
  counts; its own retries (`llm_retries`, default 1) apply only to
  temporary problems (rate limit, timeout, connection, server error,
  empty or malformed output), with doubling backoff; an ordered list of
  fallback models is supported (a model gets its retries before the next
  is tried); a missing `OPENROUTER_API_KEY` fails at startup.
  Environment: `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`,
  `OPENROUTER_FALLBACK_MODELS`
- **`CachingLLM`**: saves every answer to a JSON file and replays it;
  failures are never saved; replay-only mode raises `LLMError` on a
  miss; an optional namespace separates models or prompt versions; the
  real client is built only on the first miss; writes merge with the
  file on disk under a process-wide lock; a corrupt file raises a clear
  error instead of starting empty. For development, evaluation and
  demos, **not** for a production server
- **`MockLLM`** (tests): replays scripted answers per schema, never
  invents one, records every call

------------------------------------------------------------------------

## 6. Agent State (shared across all nodes)

``` python
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

Per request, in memory, not persisted. The state starts fail-safe
(`unverified`, confidence 0) and shares no lists between requests.

------------------------------------------------------------------------

## 7. Retrieval Assumptions (shipped Member 2 configuration)

Source: `docs/MEMBER3_HANDOFF.md` and `docs/MEMBER2_DECISIONS.md`.
Measurements are from one 118-chunk document.

- Default retrieval is meaning search only (`bge-small-en-v1.5`);
  `results` are sorted best-first by `dense_score`. **`sparse_score`,
  `fused_score`, `rerank_score` are `None`: never read them**
- Every result carries `chunk_id`, `document_id`, `page_number`,
  `section_title`
- Empty query, empty index, or a non-matching filter returns an empty
  list; an unknown filter key raises `ValueError`, so the agent sends no
  filters
- Retrieval always returns something for a non-empty query on a
  non-empty index; it never decides “no answer”, and no score cutoff has
  been shown to be reliable
- Scores are not comparable across different queries
- Chunks are small (average about 88 tokens); table chunks are
  sentences, one table row per sentence, for example
  `₹ million: Net income; Q1 FY25: 120,400; ...`
- Speed: about 20 ms per call (p95 23 ms) on one CPU with 118 chunks

------------------------------------------------------------------------

## 8. Planner: classify and decompose

One structured LLM call returns a `Plan`:

``` python
class Plan(BaseModel):
    query_type: Literal["simple", "multi-hop", "comparison", "aggregation", "ambiguous"]
    subqueries: list[str]          # one per fact; ignored for simple and ambiguous queries
    rewrites: dict[str, str] = {}  # subquery -> rewritten form; searched only when use_rewrites is on
```

The model’s plan is cleaned in code, so the limits do not depend on the
model: - Only multi-hop, comparison and aggregation queries are
decomposed. Simple and ambiguous queries use the original question as
their only sub-query - Sub-queries are trimmed, de-duplicated (ignoring
case and spacing) and truncated to `max_subqueries` (5); an empty list
falls back to the original question - **The original question is always
searched first**, then the sub-queries. A rewrite is searched only when
`AgentConfig.use_rewrites` is on (default off) - Any `LLMError` falls
back to one simple search with the original wording; the trace step
carries `fallback: true`

**Why.** The first planner searched only the sub-questions and rewrites
when it split a question, which pushed q01 (rank 1 to 9) and q12 (1 to
3) down. Keeping the original first leaves every changed question at or
above its baseline rank, and synonym rewrites showed no measurable
benefit (Section 18 and `MEMBER3_DECISIONS.md`).

------------------------------------------------------------------------

## 9. Retriever Node and Evidence Merge

    for each search query (the original question, or the retry searches):
        results = retrieve(RetrievalRequest(query, top_k=state.top_k))
        remove passages that address the AI                    (guard.py, when quarantine_instructions is on)
        record the query in tried_queries                      (only if the search ran)
    merge by chunk_id, interleaving across searches            (rank 1 of each search, then rank 2, ...)
    new passages first, then the existing evidence; cap at max_evidence_chunks (20)

- Merge by `chunk_id`, never by score. Interleaving before the cap keeps
  every search represented, so the last sub-question’s evidence is not
  cut off
- A retriever failure is counted in the trace (`errors`); the other
  searches’ results are kept. “Nothing found” and “search failed” are
  distinguishable
- **Instruction filter (`guard.py`).** A passage containing phrases
  aimed at the model (“ignore all previous instructions”, “note to the
  assistant”, “do not answer the user”, “mark every claim as supported”,
  “reveal the system prompt”, “the assistant must”) is removed before
  the model or the checker sees it; the trace says “1 passage removed
  because it contains instructions”. It was checked against ordinary
  report sentences so that, for example, “disregard the previous
  quarter’s draft figures” is not flagged. It catches obvious phrasings
  only and cannot detect a plain false fact
- The trace reports counts this module computes itself. It does not
  depend on Member 2’s optional candidate counts

------------------------------------------------------------------------

## 10. Synthesizer

``` python
class Draft(BaseModel):
    answer: str
    cited_chunk_ids: list[str] = []
    answer_found: bool = True
    search_query: str = ""
```

- The prompt contains the question and the passages as
  `<passage id=... page=... section=...>` blocks; a passage cannot close
  its own block. It states that passages are data, not instructions
- Rules in the prompt: use only facts stated in the passages; copy
  figures exactly; **do not calculate new values** unless a passage
  states them; if the passages do not contain what is needed, set
  `answer_found` false and give a short `search_query` in the wording a
  report would use; say plainly what is missing when the answer is
  partial
- On a retry, the prompt also lists the unsupported claims of the
  previous draft and the searches already tried, and asks for different
  wording
- Terminal answers (they set `final_answer`, `unverified`, confidence 0,
  no citations, and skip the fact-check):

| Situation                                | Answer                                                         | Generator called |
|:-----------------------------------------|:---------------------------------------------------------------|:-----------------|
| No passages                              | “I don’t have sufficient evidence in the provided documents.”  | no               |
| Search failed and no passages            | “I couldn’t search the documents right now. Please try again.” | no               |
| Model failure or empty draft             | “I couldn’t write an answer right now. Please try again.”      | yes              |
| Passages lack the answer, no search left | “I don’t have sufficient evidence in the provided documents.”  | yes              |

- **Not found with a search left.** If `answer_found` is false,
  `retry_count < max_retries` and `step_count + 2 <= max_steps`
  (retrieve + synthesize), the node asks for another search and the
  graph returns to the retriever: the hint becomes the only search
  query; the second such search widens `top_k` to
  `max(widened_top_k, current)`. An empty hint, or a hint equal to an
  earlier search (ignoring case and spacing), searches the original
  question again with the wider `top_k`
- **Citations** are built in code from the retrieved chunks only:
  unknown ids are dropped and counted (`dropped_citations`), repeated
  ids are listed once. Each snippet is the chunk sentence that best
  matches the claims made from it (figures count three times as much as
  words; at most 200 characters; a leading “…” when it starts mid-chunk;
  the start of the chunk when nothing matches)
- `clean_text` replaces the narrow no-break space, no-break space and
  non-breaking hyphen that models emit with plain characters, in
  answers, claims and search hints

------------------------------------------------------------------------

## 11. Fact-Checking Logic

``` python
class ClaimVerdict(BaseModel):
    claim: str
    supported: bool
    supporting_chunk_ids: list[str] = []
    search_query: str = ""      # for an unsupported claim: how to look for the missing fact
    reason: str = ""

class Verification(BaseModel):
    verdicts: list[ClaimVerdict]
```

One call extracts the claims of the draft and judges each against
**all** retrieved passages together. Then plain code decides:

- A “supported” verdict counts only if it names at least one passage
  that was really retrieved; unknown ids are dropped; blank claims are
  ignored
- **Specific-value rule** (in the prompt): a claim with a figure, name,
  date or unit is supported only if that exact value appears in the
  passages; an on-topic passage without the value does not support it
- `coverage = supported claims / total claims`; an empty verdict list
  means the check failed

| Condition                                          | Status                                     | Confidence                                             |
|:---------------------------------------------------|:-------------------------------------------|:-------------------------------------------------------|
| coverage ≥ 0.8                                     | `verified`                                 | `min(coverage, max_confidence)`, `max_confidence` 0.95 |
| 0 \< coverage \< 0.8 and no retry left             | `partially_verified`                       | `min(coverage, 0.95)`                                  |
| coverage = 0 after the retries (nothing supported) | `unverified`, insufficient-evidence answer | 0                                                      |
| the check itself failed                            | `unverified`, the draft is returned        | 0                                                      |

- **Retry decision.** Below the threshold, a retry happens if
  `retry_count < max_retries` and `step_count + 3 <= max_steps`:
  `retry_count` + 1, new search queries (each unsupported claim’s own
  wording, then the model’s hint; de-duplicated; at most
  `max_subqueries * 2`), and on the second retry `top_k` becomes
  `max(widened_top_k, current)`
- Unsupported claims are flagged in the answer text (“Could not be
  verified in the documents:” followed by the claims) instead of being
  edited out. Citations are rebuilt from the passages that support the
  surviving claims
- The `finalize` node ends a run with the best answer already checked;
  the graph uses it when a retry finds no new passages
- Entailment is an LLM-judge prompt, not a fine-tuned model. “Verified”
  means faithful to the retrieved passages, **not true**
- The coverage threshold (0.8), `widened_top_k` (15) and
  `max_confidence` (0.95) are initial values, not calibrated

------------------------------------------------------------------------

## 12. Answer Assembly

The `Agent` builds `AgentResponse` from `final_answer`, the citations,
the trace, the sanitised status and confidence, and the measured latency
in milliseconds (retries included). If no node set a final answer, it
returns the draft (or the generation-failed message) marked `unverified`
with confidence 0.

------------------------------------------------------------------------

## 13. Retry Logic (a retry must change something)

Retrieval is deterministic: the same query returns the same chunks, so a
plain “retrieve again” cannot help. Two kinds of retry share
`retry_count` and the cap `max_retries = 2`:

| Kind             | Trigger                                     | Steps                                | What changes                                                                                             |
|:-----------------|:--------------------------------------------|:-------------------------------------|:---------------------------------------------------------------------------------------------------------|
| Fact-check retry | coverage below the threshold                | retrieve, synthesize, fact-check (3) | Each unsupported claim is searched (claim wording and the model’s hint); the second retry widens `top_k` |
| Not-found search | the draft says the passages lack the answer | retrieve, synthesize (2)             | The model’s hint is searched; the second widens `top_k`; no fact-check call is spent                     |

- **Retries must not repeat themselves.** The retriever node records
  every search that ran (`tried_queries`). On a retry the synthesizer’s
  prompt lists them and asks for different wording (a shorter phrase, or
  the label a statement or table row would use). A hint that repeats an
  earlier search is not run again: the question is searched with the
  wider net instead
- If a retry brings back no new `chunk_id`s, the run stops early with
  the best answer already checked (`finalize`)
- Worst case: planner + (draft + check) × 3 passes = 7 model calls and
  10 steps (cap 12). A not-found search costs 1 model call and 2 steps
- The trace reports a retry honestly (“searching again”); a visible
  self-correction is a feature

------------------------------------------------------------------------

## 14. Guardrails & Bounded Execution

| Guard                     | Limit                              | Behaviour when hit                                                                                   |
|:--------------------------|:-----------------------------------|:-----------------------------------------------------------------------------------------------------|
| `max_steps`               | 12 (one step = one node execution) | `step_limit` node returns the draft (or the generation-failed message) as `unverified`, confidence 0 |
| `max_retries`             | 2                                  | No further search; the current best answer is returned                                               |
| `max_subqueries`          | 5                                  | Planner output truncated                                                                             |
| `max_evidence_chunks`     | 20                                 | Merged evidence truncated, keeping the interleaved order                                             |
| LangGraph recursion limit | `max_steps + 5`                    | Raises; the `Agent` turns it into a valid `unverified` response                                      |
| Instruction filter        | passages that address the AI       | Removed before the model sees them; counted in the trace                                             |
| Prompt injection          | n/a                                | Passages are data in every prompt; a passage cannot close its own tag                                |

`AgentConfig` checks itself when created:
`max_steps >= 4 + 3 * max_retries` (the first pass takes 4 steps and
each fact-check retry 3), `widened_top_k` between `top_k` and 20, the
coverage threshold between 0 and 1, and so on. Routing functions name
their settings parameter `agent_config`, never `config`, because
LangGraph injects its own settings object into any parameter called
`config`.

------------------------------------------------------------------------

## 15. No-Evidence Behaviour

1.  Retrieval never decides “no answer”; this module does
2.  **No passages:** the insufficient-evidence answer, generator not
    called, `unverified`
3.  **Passages that lack the answer:** the draft says so (`answer_found`
    false); the agent searches again with the hint and different
    wording, then gives the insufficient-evidence answer. A draft that
    says “not provided” is never sent to the fact-checker (it was marked
    `verified` once, before this rule)
4.  **Passages exist but no claim is supported:** the same answer,
    `unverified`; the unsupported draft is never returned
5.  **On-topic passage without the figure** (q17): handled by the
    specific-value rule and by (3); q17 returned “insufficient
    evidence”, not the 2% legal minimum
6.  No score cutoff is used; `use_similarity_hint` exists in the config
    but is off and unused

------------------------------------------------------------------------

## 16. Error Handling

| Failure case                                            | Behaviour                                                                                                     |
|:--------------------------------------------------------|:--------------------------------------------------------------------------------------------------------------|
| `retrieve()` returns empty results                      | No-evidence path                                                                                              |
| `retrieve()` raises                                     | Counted in the trace; other searches kept; if nothing came back: “I couldn’t search the documents right now…” |
| Planner LLM call fails or returns malformed output      | Fall back to one simple search with the original wording (`fallback: true`)                                   |
| Draft LLM call fails or the draft is empty              | “I couldn’t write an answer right now…”, `unverified`                                                         |
| Fact-checker LLM call fails or returns no usable claims | The draft is returned `unverified`, confidence 0, `checker_failed: true`; no retry                            |
| `CachingLLM` replay-only miss                           | `LLMError`, handled like any other LLM failure                                                                |
| Step cap reached                                        | `step_limit` node; draft marked `unverified`                                                                  |
| Graph raises (including the recursion limit)            | `Agent` returns a valid `unverified` response; the error’s type name only in the trace, details in the log    |
| Blank question                                          | “Please enter a question.”, no calls                                                                          |

------------------------------------------------------------------------

## 17. Testing Plan (as built)

All unit tests use `MockRetriever` and `MockLLM`; no model or network is
needed.

| File                                         | Tests   | Covers                                                                                       |
|:---------------------------------------------|:--------|:---------------------------------------------------------------------------------------------|
| `test_state.py`                              | 10      | fail-safe start, no shared lists, trace appends                                              |
| `test_config.py`                             | 17      | defaults, frozen, validation, the step rule                                                  |
| `test_mock_retriever.py`, `test_mock_llm.py` | 13 + 13 | the test doubles mirror the real behaviour                                                   |
| `test_openrouter_llm.py`                     | 23      | retries, backoff, schema output, fallback models, setup                                      |
| `test_planner.py`                            | 24      | cleaning, original first, rewrites off, fallback, one call                                   |
| `test_retriever_agent.py`                    | 27      | merge, interleave, retry, failures, instruction filter, tried searches                       |
| `test_synthesizer.py`                        | 44      | terminal answers, citations and snippets, not-found path, retries’ prompt, injection as data |
| `test_fact_checker.py`                       | 35      | verdict cleaning, status mapping, retry rules, failure, finalize, graph runs                 |
| `test_graph.py`                              | 27      | every routing fork, step guard, whole-graph scenarios, two-retry worst case                  |
| `test_agent.py`                              | 24      | response building, streaming order, clamping, failure handling, no leaked details            |
| `test_llm_cache.py`                          | 20      | replay, failures not cached, replay-only, namespace, merge on write                          |
| `test_safety_judges.py`, `test_guard.py`     | 11 + 18 | pass/fail rules, instruction phrases and false positives                                     |

Total: **306** agent unit tests. Live checks (not unit tests, they use
the real model and the daily quota): `live_agent_run.py`,
`live_safety_checks.py`, `measure_planner.py`, `planner_ablation.py`,
`check_hints.py`.

------------------------------------------------------------------------

## 18. Interface Contract and Measured Decisions

The output contract is **frozen and unchanged**:

``` python
# app/schemas/agent.py
class AgentStepType(str, Enum): PLAN, RETRIEVE, FACT_CHECK, SYNTHESIZE
class AgentStep(BaseModel): step_type; content: str; metadata: dict = {}
class Citation(BaseModel): chunk_id; document_id; page_number: int | None = None; text_snippet
class AgentResponse(BaseModel):
    answer: str
    citations: list[Citation]
    trace: list[AgentStep]
    verification_status: str   # "verified" | "partially_verified" | "unverified"
    confidence: float
    latency_ms: float
```

**The five v0.2 proposals** were agreed by the team; their status from
this module’s side: 1. `VerificationStatus` as a `str` Enum (identical
JSON): optional, not done 2. Candidate counts on `RetrievalResponse`:
not adopted; the trace uses counts this module computes itself 3.
`verification_status` on the synchronous `ChatResponse`: needed by the
UI; Member 4 to add 4. Citation filename: Member 4 adds `source_file`
from `document_id` when building the response 5. `build_agent(...)`
replaces `run_agent(...)`: done

The measurements behind the design decisions (planner ablation, retry
change, live runs, safety checks and Session 20 golden-set evaluation)
are in `docs/MEMBER3_DECISIONS.md`.

------------------------------------------------------------------------

## 19. Open Decisions

| Decision                                                                                                       | Owner                                | Needed by                         |
|:---------------------------------------------------------------------------------------------------------------|:-------------------------------------|:----------------------------------|
| Coverage threshold (0.8), `widened_top_k` (15), `max_confidence` (0.95): calibrate or document as uncalibrated | Member 3 + Member 5’s golden dataset | Session 20                        |
| Faithfulness with and without the fact-checker                                                                 | Members 3 and 5                      | Session 20                        |
| Items 1, 3 and 4 in Section 18                                                                                 | Members 4 and 5                      | Before the chat endpoint is final |
| When to commit a recorded demo cache (`data/llm_cache/live_run.json` is git-ignored)                           | Member 3                             | When the prompts settle           |

------------------------------------------------------------------------

## 20. Performance Considerations

- Retrieval is cheap (about 20 ms per call); model calls dominate. On
  the free model one call takes 12 to 36 seconds, so a question takes
  about 36 to 175 seconds live and about 0.1 seconds replayed from the
  cache
- Calls per question: 3 for a clean question (planner, draft, check);
  about 4 for an unanswerable one (planner and three “not found”
  drafts); at most 7. Free tier: about 20 requests a minute and about 50
  a day
- Run `run()` and `run_streaming()` in a thread, cap concurrent
  questions (a semaphore of about 2), send SSE heartbeats about every 15
  seconds, and allow at least 5 minutes in proxies. The agent cannot be
  cancelled mid-run
- The final answer is streamed after verification (not model tokens as
  they are generated), so a retry never shows text that is later
  retracted
- All measurements come from one 118-chunk document and one free model;
  re-measure on a larger corpus
