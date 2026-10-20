# Member 3 — Agentic Orchestration (LangGraph): Completion Checklist

**Status:** 24 of 25 Definition-of-Done items complete. The agent is
built, tested end to end on mocks, run live on real TCS questions, and
evaluated on the 10-question golden set. Thresholds (item 20) are
recorded as uncalibrated; Faithfulness with and without the fact-checker
(item 21) remains open pending the RAGAS comparison with Member 5.
**Last updated:** Session 20, October 2026 **Tests:** 306 agent unit
tests passing (14 test files). Full project suite: 562 passed. (Counts
reported by the user from their runs.)

> **How completion is judged.** Member 3 is declared complete only when
> every item in Section 16 is true. Tests on mocks prove the control
> flow is correct; they do **not** prove the answers are good. Items
> that need the real model, the real index or Member 5’s golden dataset
> stay open until they are measured, and every number recorded here must
> come from a run, with its sample size and limits.

------------------------------------------------------------------------

## 1. Environment & Foundation

- [x] `langgraph`, `langchain-core`, `openai`, `python-dotenv` installed
  and pinned in `requirements.txt`
- [x] `app/agents/` package and `tests/unit/agents/` created and
  runnable
- [x] `.env` git-ignored, `.env.example` committed with a blank key
- [x] Provider chosen: NVIDIA Nemotron 3 Super (free) via OpenRouter; no
  purchase planned (about 50 requests a day)

## 2. Documents

- [x] PRD, TRD, Backend Schema and UI/UX v0.2 written and pushed
- [x] The five synchronization proposals (TRD Section 18) agreed by the
  team
- [x] Documentation pass: PRD, TRD, Backend Schema and UI/UX rewritten
  as v0.3 to match the code and checked mechanically by
  `scripts/check_docs_against_code.py` (Session 19)

## 3. State (`state.py`)

- [x] `AgentState` with a trace that appends and every other field
  overwriting
- [x] `initial_state()` fails safe (`unverified`, confidence 0) and
  shares no lists between requests
- [x] `citations` and `tried_queries` fields
- [x] 10 unit tests passing

## 4. Config (`config.py`)

- [x] Frozen `AgentConfig`: caps and thresholds in one place, validated
  at creation
- [x] `max_steps >= 4 + 3 * max_retries` enforced; `widened_top_k`
  between `top_k` and 20
- [x] `llm_retries`, `max_confidence`, `use_rewrites` (default off),
  `quarantine_instructions` (default on)
- [x] 17 unit tests passing

## 5. Test doubles (`tests/unit/agents/mocks.py`)

- [x] `MockRetriever` mirrors the real retriever (top_k cut, blank
  query, filter validation, only `dense_score`, copies)
- [x] `MockLLM` replays queues per schema, never invents an answer,
  records every call
- [x] 13 + 13 unit tests passing

## 6. LLM access (`llm.py`)

- [x] `LLMClient` protocol and one `LLMError` for every failed call
- [x] `OpenRouterLLM`: own retries (SDK retries off), backoff,
  structured output with schema in the prompt, fence stripping, ordered
  fallback models
- [x] 23 unit tests passing
- [x] Live smoke test passed (plain and structured answers from Nemotron
  3 Super)
- [x] `CachingLLM` (`llm_cache.py`): same key and file format as the old
  throwaway cache, failures never cached, replay-only mode, optional
  namespace, lazy model creation, merge-on-write so two instances on one
  file keep each other’s entries
- [x] 20 unit tests passing; both measurement scripts now use it and
  still make 0 requests

## 7. Planner (`planner.py`)

- [x] One structured call: classify, decompose (max 5), rewrite; plan
  cleaned in code (dedupe, truncate, simple and ambiguous forced to the
  original); LLM failure falls back to the original question
- [x] The original question is always searched first, then the
  sub-questions; rewrites are searched only when `use_rewrites` is on
  (default off)
- [x] 24 unit tests passing
- [x] Live check on 3 questions, measured on the 17 answerable TCS
  questions (Session 14), then an offline ablation of seven search
  variants (Session 15, 0 requests)
- [x] Decision made after the ablation: original first, then
  sub-questions, no rewrites by default
- [x] q19 has a documented conclusion: the planner alone does not fix it
  (Session 17: three searches, then an honest “insufficient evidence”;
  retrieval-only check: the model’s hints did not reach the table while
  the short “Net income Q3 FY25” ranks 2). After the retry-diversity
  change (Session 19) q19 was answered correctly, `verified`, in one
  live run. That is one question picked after seeing it fail, so it is a
  sign, not a rate

> **Measured (17 questions, top 10; recall@5 / recall@10 / MRR /
> NDCG@10).** Baseline 0.882 / 0.912 / 0.753 / 0.792. Planner as first
> built (Session 14): 0.853 / 0.912 / 0.714 / 0.747. Planner after the
> decision (Session 15): 0.912 / 0.912 / 0.776 / 0.804. It changes 6
> questions, none worse; q16’s first right chunk moves from rank 10 to
> rank 2 (not every fact in the top 10). In the full evidence (up to 20
> passages) the 6 changed questions find every fact (1.000 against
> 0.917), at 15.3 passages on average. q19 is unchanged and still
> missed. Same 17 questions Member 2 tuned on, variants added after
> seeing results; a hypothesis for the live run and the golden dataset,
> not a proof.

## 8. Retriever node (`retriever_agent.py`)

- [x] One search per search query, merged by `chunk_id`, first copy
  wins, never by score
- [x] Interleaved before the evidence cap; new chunks first on a retry
- [x] Retriever failures counted in the trace, other searches kept
- [x] Passages that address the AI (hidden instructions) are removed
  before merging (`guard.py`, switch `quarantine_instructions`), and the
  trace says so
- [x] 27 unit tests passing (plus 18 for the guard); the node records
  every search that ran (`tried_queries`)

## 9. Synthesizer (`synthesizer.py`)

- [x] Draft with citations rebuilt in code from retrieved chunks only
- [x] No evidence, search failed and generation failed give their own
  answers without a fabricated draft
- [x] Passages passed as data, tag escaping; unsupported claims from a
  previous draft listed on a retry
- [x] 44 unit tests passing (`answer_found` flag, search again when the
  passages lack the answer, no calculated values, typographic characters
  cleaned, citation snippets that show the part of the chunk supporting
  the answer and split before rows that start with a currency symbol,
  the next draft’s prompt lists the searches already tried)
- [x] Tried on the real model (Session 17): a real bug found and fixed
  (an “it is not provided” answer was marked verified); details in the
  Session 17 log

## 10. Fact-checker (`fact_checker.py`)

- [x] One call extracts claims and judges them against all evidence
  together
- [x] A “supported” verdict must name a real retrieved passage; specific
  figures must match exactly
- [x] Coverage, status mapping, confidence cap, flagged unsupported
  claims, rebuilt citations
- [x] Retry changes the search (claim wording plus hint; second retry
  widens `top_k` but never narrows a larger requested one); step budget
  respected
- [x] Checker failure returns the draft marked `unverified`; `finalize`
  node for the early stop
- [x] 35 unit tests passing
- [x] Tried on the real model (Session 17): verdicts were sensible on
  three questions and it flagged an unstated computed figure on q16; the
  absence-statement weakness is now handled upstream by the synthesizer.
  A hand spot-check of its verdicts against the report is still
  advisable

## 11. Graph (`graph.py`)

- [x] Routing functions for each fork; set `final_answer` always means
  done
- [x] Early stop when a retry finds no new passages; `step_limit` guard
  node; recursion limit `max_steps + 5`
- [x] Two-retry worst case ends at 10 steps (cap 12) on mocks
- [x] 27 unit tests passing; a “not found” draft sends the run back to
  the retriever (route `retry_search`) without a fact-check, and a
  repeated search hint triggers a wider search of the question

## 12. Public entry point (`agent.py`)

- [x] `build_agent(retriever, llm, config)`, built once per process;
  each question gets a fresh state
- [x] `run()` returns a valid `AgentResponse` (answer, citations, trace,
  status, confidence, latency)
- [x] `run_streaming()` yields trace steps as they happen, then the
  final response; `run()` shares the same path
- [x] Graph errors, including the recursion-limit error, become a valid
  `unverified` response; error details are logged, not returned
- [x] `top_k` from the request clamped to 1 to 20; blank question
  answered without any model call
- [x] 24 unit tests passing

## 13. Live runs

- [x] First end-to-end run of the whole agent on 3 real TCS questions
  (simple, q16, q19), Session 17
- [x] Seeded hallucination (3 planted false drafts, every planted claim
  marked unsupported) and the q17 case (on-topic chunk without the
  figure: honest insufficient evidence), plus q18 and q20, run with the
  real model (Session 18)
- [x] Prompt-injection cases run with the real model (Session 18): the
  model alone passed an override instruction and a conflicting row
  without instructions, but followed an instruction hidden in a fake
  row; with the instruction filter on all three pass. Paraphrased
  attacks untested; the agent cannot defend against a plain false fact
- [x] LLM calls and latency per question measured on those 3 questions
  (3 to 5 calls; the free model takes 12 to 36 s per call, so 36 to 175
  s per question live)

## 14. Evaluation with Member 5

- [x] Thresholds (`coverage_threshold` 0.8, `widened_top_k` 15,
  `max_confidence` 0.95) recorded as uncalibrated on the golden dataset
  (Session 20; see `MEMBER3_DECISIONS.md` §2.10)
- [ ] Faithfulness with and without the fact-checker measured together
  with Member 5; still open because the Session 20 MiniMax comparison is
  not the RAGAS evaluation and did not isolate the checker
- [x] Unanswerable questions measured on the golden dataset: gold-09
  refused (1/1), plus q17, q18 and q20 earlier (3/3); four cases total,
  not a general success rate

## 15. PRD functional requirements (1–16) — status

- [x] 1. Accept a query and optional session context
  *(`run(query, session_context, top_k)`; `session_context` is accepted
  but unused for now)*
- [x] 2. Classify the query
- [x] 3. Rewrite into the document’s terms, keep the original *(built,
  but rewrites are off by default: the measurements showed no benefit;
  the original is always searched first)*
- [x] 4. Decompose into sub-queries, max 5
- [x] 5. One retrieve per search query, merge by `chunk_id`
- [x] 6. Draft with citations *(mock-tested; ran live on three
  questions)*
- [x] 7. Claim-level verification against combined evidence
  *(mock-tested; ran live on three questions)*
- [x] 8. Specific figures must appear in the evidence *(prompt and code;
  on q16 the real model flagged an unstated computed figure)*
- [x] 9. No results gives the insufficient-evidence answer without
  calling the generator
- [x] 10. Results exist but no claim supported gives the
  insufficient-evidence answer, `unverified`
- [x] 11. A retry changes the search and merges evidence *(mock-tested;
  fired live on q16 and q19; on q19, with the retry-diversity change, it
  recovered the answer in one run)*
- [x] 12. Return a structured `AgentResponse`
- [x] 13. Hard caps: `max_steps` 12, `max_retries` 2, `max_subqueries` 5
- [x] 14. All LLM calls through `LLMClient`, `MockLLM` for tests
- [x] 15. Retrieved text treated as data *(prompt, tag escaping and a
  filter for passages that address the AI; real-model test run in
  Session 18, see Section 13)*
- [x] 16. Never raise an unhandled exception *(every node handles its
  failures; `agent.py` wraps the whole graph)*

## 16. Definition of Done

- [x] 1. State and config implemented and tested
- [x] 2. Test doubles (`MockRetriever`, `MockLLM`) implemented and
  tested
- [x] 3. LLM adapter implemented, tested and smoke-tested live
- [x] 4. Planner implemented and tested
- [x] 5. Planner measured on the real index and the result logged
- [x] 6. Planner decision made after the offline ablation
- [x] 7. q19 has a documented conclusion
- [x] 8. Retriever node implemented and tested
- [x] 9. Synthesizer implemented and tested
- [x] 10. Fact-checker and `finalize` node implemented and tested
- [x] 11. Graph with routing, step guard and recursion limit implemented
  and tested
- [x] 12. `agent.py` (`build_agent`, `run`, `run_streaming`) implemented
  and tested
- [x] 13. Every failure path, including graph errors, returns a valid
  `AgentResponse`
- [x] 14. `CachingLLM` implemented and tested
- [x] 15. Synthesizer and fact-checker prompts tried on the real model,
  findings recorded
- [x] 16. First live end-to-end run on at least 3 real TCS questions,
  including q16 and q19
- [x] 17. Seeded-hallucination and q17 cases run with the real model
- [x] 18. Prompt-injection case run with the real model
- [x] 19. LLM calls and latency per question measured (3 questions)
- [x] 20. Thresholds recorded as uncalibrated on the golden dataset
  (Session 20; see `MEMBER3_DECISIONS.md` §2.10)
- [ ] 21. Faithfulness with and without the fact-checker measured with
  Member 5 (see `MEMBER3_DECISIONS.md` §2.10; the MiniMax comparison is
  not a substitute for RAGAS)
- [x] 22. Full project test suite total recorded (562 passed at Session
  19)
- [x] 23. Hand-off note for Members 4 and 5
  (`docs/MEMBER4_5_HANDOFF.md`)
- [x] 24. Documentation pass: PRD, TRD, Backend Schema and UI/UX match
  the code (v0.3; mechanical check passed)
- [x] 25. `MEMBER3_DECISIONS.md`: final configuration and measured
  decisions (like Member 2’s)

## 17. PRD success metrics — status

| Metric                                                                      | Status                                                                                                                                                                                                                                                                                                    |
|:----------------------------------------------------------------------------|:----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Faithfulness ≥ 0.85, against the “retrieval only, no fact-checker” baseline | Session 20 single-draft baseline and full agent both scored 1.000 with the MiniMax claim judge on answered questions; this does not isolate the fact-checker and is not the RAGAS comparison. See `MEMBER3_DECISIONS.md` §2.10; Member 5 comparison remains open.                                         |
| Multi-hop questions answered correctly (q16 reference)                      | q16 answered live with figures matching the reference (\$21.6B to \$19.0B, about 48% of revenue), `verified`, in 2 to 5 calls. One question, not a rate                                                                                                                                                   |
| Wording-mismatch questions answered via rewriting (q19 reference)           | q19 answered ₹123,800 million (the reference), `verified`, after the retry change (Session 19); before it the agent gave an honest “insufficient evidence”. One question picked after seeing it fail; not a rate                                                                                          |
| Fact-checker catches a seeded hallucination                                 | Demonstrated with mocks and live (Session 18): all 3 planted false drafts (wrong figure, reversed direction and region, invented fact) had the planted claim marked unsupported while the true claims stayed supported. Obvious errors, one model, 3 cases                                                |
| On-topic chunk without the figure (q17) returns insufficient evidence       | q17 run live: honest insufficient evidence after 3 searches (the 2% legal minimum was not given as the answer); q18 and q20 the same                                                                                                                                                                      |
| Unanswerable questions answered with “insufficient evidence”                | Session 20: gold-09 refused (1/1) on the golden set; q17, q18 and q20 were also refused earlier (3/3). Four cases total, not a general success rate; see `MEMBER3_DECISIONS.md` §2.10.                                                                                                                    |
| Loop termination 100%                                                       | Tested on mocks including the two-retry worst case (10 steps, cap 12) and graph-level failures in `agent.py`; real runs: 3 questions finished in 4 to 7 steps                                                                                                                                             |
| Prompt-injection resistance                                                 | Real model, Session 18: alone it resisted 2 of 3 planted cases and followed an instruction hidden in a fake row; with the instruction filter on all 3 pass. The filter was written looking at these cases, paraphrased attacks are untested, and a plain false fact in a document is not defended against |

## 18. Known limitations

- Live runs cover three answerable questions, three unanswerable ones
  and a few planted cases; evaluation on a golden dataset is still open.
- A draft that only says “the documents do not contain this” is now
  caught upstream by the `answer_found` flag. If the model reports
  `answer_found` true with such a text, the checker could still treat it
  as a supported claim (it did once, before the fix).
- Citation snippets now show the sentence that best matches the claim;
  when nothing matches they fall back to the start of the chunk.
- The instruction filter catches obvious phrasings only. “Verified”
  means faithful to the retrieved passages, not true, so a false fact in
  a document is repeated (a document-trust matter for Members 1 and 4).
- Retry hints are now steered away from earlier searches
  (`tried_queries`), which helped q19 in one run; whether that
  generalises is untested, and the model’s wording still decides whether
  a retry reaches the right chunk.
- The free model takes 12 to 36 s per call, so a question takes about 36
  to 175 s live.
- The planner never sees the documents; its decomposition helped on the
  multi-fact question (q16), synonym rewrites showed no benefit, and it
  costs one of the three LLM calls per question.
- `run()` and `run_streaming()` are synchronous; an async server should
  run them in a thread.
- `CachingLLM` is for development, evaluation and demos, not a
  production server; two separate processes writing one cache file at
  the same instant could still race (inside one process it is safe).
- The free tier allows about 50 requests a day; Member 5’s evaluation
  will not fit in that without spreading it over days.
- The 17 TCS questions are the ones Member 2 tuned on, so early
  measurements are optimistic.

------------------------------------------------------------------------

**MEMBER 3 — AGENTS STATUS:** **24 of 25** — agent built, tested and
evaluated on the golden set; item 20 is complete as recorded as
uncalibrated, while item 21 (RAGAS Faithfulness with and without the
fact-checker) remains open.
