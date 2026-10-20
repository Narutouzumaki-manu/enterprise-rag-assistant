# Agent Hand-off for Members 4 and 5

**From:** Member 3 (Agentic Orchestration) **To:** Member 4 (Backend / API) and Member 5 (Evaluation, Frontend)
**Last updated:** Session 20, October 2026

You call the agent from the API (Member 4) and you show and measure what it does (Member 5). This page covers how to call it, what you can rely on, what you cannot, and what each of you needs to do. The measurements behind it are in `docs/MEMBER3_DECISIONS.md`.

---

## 1. What you get

One object, built once, with two ways to ask a question:

| Call | Use |
|---|---|
| `build_agent(retriever, llm, config) -> Agent` | Build once per process (model loading takes seconds) |
| `agent.run(query, session_context=None, top_k=None) -> AgentResponse` | One question, one finished answer |
| `agent.run_streaming(query, session_context=None, top_k=None)` | Yields each `AgentStep` as it finishes, then the final `AgentResponse` |

`AgentResponse` (frozen contract, `app/schemas/agent.py`): `answer`, `citations`, `trace`, `verification_status`, `confidence`, `latency_ms`. `Citation`: `chunk_id`, `document_id`, `page_number`, `text_snippet`.

## 2. How to call it (Member 4)

```python
# once, at server startup
from app.agents.agent import build_agent
from app.agents.config import AgentConfig
from app.agents.llm import OpenRouterLLM
from app.retrieval.factory import build_default_retriever

config = AgentConfig()
retriever = build_default_retriever(persist_path="data/chroma")
llm = OpenRouterLLM.from_env(retries=config.llm_retries)   # NOT CachingLLM in production
agent = build_agent(retriever, llm, config)

# per request: run() is synchronous, so run it in a thread
from starlette.concurrency import run_in_threadpool
response = await run_in_threadpool(agent.run, question, top_k=request.top_k)
```

- **Build it once.** One agent serves many questions; each question gets a fresh state, so questions cannot leak into each other.
- **`run()` and `run_streaming()` block** while they wait for the model, which takes 12 to 36 seconds per call on the free model. In an async server they must run in a thread or they stall every other request.
- **`top_k`** is clamped to 1 to 20 (your `ChatRequest` range). If you omit it, the config default (8) is used.
- **A blank question** returns "Please enter a question." without any model call.
- **Environment:** `OPENROUTER_API_KEY` (required), `OPENROUTER_MODEL`, `OPENROUTER_FALLBACK_MODELS` in `.env`. The key must never be committed.

## 3. What you can rely on

- **Always a valid `AgentResponse`.** The agent never raises to its caller: failures inside (model errors, a retriever crash, the step limit, even a graph error) become an `unverified` response with confidence 0, and the error's type name (never its details) in the last trace step. Details go to the log.
- **Status vocabulary:** `verified`, `partially_verified`, `unverified`. `unverified` always has confidence 0. Confidence never exceeds 0.95.
- **"I don't have sufficient evidence in the provided documents."** is the exact answer text for: no passages found, the passages do not contain the answer after the allowed searches, or no claim could be verified. It always comes with `unverified`, confidence 0 and no citations.
- **Citations** only point at passages that were really retrieved, and `text_snippet` is the sentence of the chunk that best matches the claim (it starts with "..." when it begins mid-chunk, and falls back to the start of the chunk when nothing matches).
- **Bounded work.** At most 12 steps, 2 retries, 5 sub-queries. A question costs **3 model calls** when clean, **2 to 4** for an unanswerable one (2 measured on gold-09, whose retry found no new passages and stopped early; about 4 on earlier ones), and **at most 7** in the worst case.
- **Trace:** one `AgentStep` per step, in order, with counts and labels only (no prompts, no passage text). See Section 6 for the wording.
- **Reproducible runs.** Wrapped in `CachingLLM`, a run replays from disk in about 0.1 seconds (see Section 7).

## 4. What you cannot rely on

- **"Verified" means faithful to the retrieved passages, not true.** If a document contains a false fact, the agent repeats it as `verified`. Controlling who uploads documents (Member 4) and cleaning at ingestion (Member 1) is outside the agent.
- **"Verified" can include a figure the agent computed.** On golden question gold-05 the model calculated a difference (₹7,261 crore, correct) and the fact-checker still marked it `verified`, although no passage states it. The checker's "specific figures must appear" rule is a prompt instruction, not enforced in code.
- **A rounded figure can come back verified.** When retrieval misses the exact figure, the agent may answer from a rounded one (gold-07: "$30.0 billion" against US$30,017 million) and mark it `verified`, because the rounded figure is in a passage.
- **Confidence carries almost no information.** On the golden set every `verified` answer had confidence 0.95 (the cap) and every `unverified` one 0. Use the status, not the number.
- **The instruction filter is a heuristic.** The agent removes passages that address the AI ("ignore all previous instructions", "note to the assistant"), but a paraphrased attack would get through. Treat it as one layer of defence.
- **Thresholds are guesses.** The 0.8 coverage threshold, the widened `top_k` of 15 and the 0.95 confidence cap were recorded as uncalibrated in Session 20 (`MEMBER3_DECISIONS.md` §2.10); the golden set could not tell 0.8 from 0.9.
- **The model varies.** The same question can produce different drafts and different search hints on different live runs.
- **No cancellation.** If the client disconnects, the run continues to the end (up to about three minutes on the free model).
- **`session_context` is accepted but unused** (reserved for chat history).
- **Free-tier limits:** about 20 requests a minute and about 50 a day on the free model.

## 5. For Member 4

**Recommendation (agreed): build the agent once at startup and call it in a thread.**

- **Concurrency.** Put a semaphore (say 2) around agent calls. One question is 3 to 7 sequential model calls, and the free model is rate-limited. If the model is rate-limited the agent returns an `unverified` answer such as "I couldn't write an answer right now"; treat that as a normal response, not a server error.
- **Timeouts and heartbeats.** A single model call can take 12 to 36 seconds with no event in between. Send an SSE heartbeat about every 15 seconds, and allow a total of at least 5 minutes in Nginx and the client.
- **Streaming.** Run `run_streaming` in a worker thread and push events to an `asyncio.Queue` with `loop.call_soon_threadsafe`; the SSE generator reads the queue.

```python
async def agent_events(question, top_k):
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def worker():
        try:
            for event in agent.run_streaming(question, top_k=top_k):
                loop.call_soon_threadsafe(queue.put_nowait, event)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=worker, daemon=True).start()
    while (event := await queue.get()) is not None:
        yield event          # AgentStep objects, then one AgentResponse
```

- **SSE mapping.**

| Agent output | Your SSE event |
|---|---|
| each `AgentStep` | `status` (send `step_type` and `content`) |
| final `AgentResponse`: each citation | `source` |
| final `AgentResponse`: the answer text | `token` (see below) |
| final `AgentResponse`: status and confidence | `verification` |
| end | `done` (with `latency_ms`) |

  The agent does **not** stream model tokens: the answer is complete only after verification, so a retry never shows text that is later retracted. After the last step arrives, split the final answer into words and send them as `token` events. The trace panel fills the wait.

- **Persistence.** `messages`: answer, `verification_status`, `confidence`, `latency_ms`. `citations`: one row per citation. `agent_traces`: one row per step (`step_order`, `step_type`, `content`, `metadata` as JSON).
- **Do not wrap the production model in `CachingLLM`.** It replays old answers; it is for development, evaluation and demos.
- **Security.** Authenticate uploads, limit file types and sizes, and say in the docs that the agent trusts the documents it is given.
- **Two gaps in your schema:** the synchronous `ChatResponse` has no `verification_status` (the UI needs it), and `Citation` has no filename. Recommendation: you add `source_file` by looking up `document_id` in your documents table when you build the response; the agent does not need to change.

## 6. For Member 5

**Trace wording** (each `AgentStep.content` is already written for the UI):

| Step | Wording (examples) |
|---|---|
| `plan` | "Classified as simple; 1 sub-query", "Classified as multi-hop; 3 sub-queries"; "Could not plan the question; searching with the original wording" |
| `retrieve` | "Retrieved 8 passages across 1 sub-query", "Found 5 new passages (13 in total)", "No new passages found", "No relevant passages found", "Search failed; no passages retrieved"; a suffix "; 1 passage removed because it contains instructions" |
| `synthesize` | "Draft answer generated with 1 citation", "The passages do not contain the answer; searching again", "The passages do not contain the answer", "No relevant passages; the generator was not called", "Could not generate a draft answer" |
| `fact_check` | "1 of 1 claim verified", "3 of 4 claims verified; searching again for 1 unsupported claim", "1 of 2 claims verified; 1 could not be verified", "No claim could be verified in the documents", "No new passages found; finalising with the best available answer", "Could not verify the answer; returning the draft marked unverified", "The agent stopped unexpectedly; returning what is available marked unverified" |

Metadata keys (counts and labels only): plan `query_type`, `subquery_count`, `rewritten` (+ `fallback`); retrieve `search_query_count`, `chunks_per_search`, `chunks_after_merge`, `new_chunks`, `attempt`, `errors`, `quarantined`; synthesize `citation_count`, `dropped_citations`, `generator_called` (+ `not_found`, `retry_search`, `reason`); fact_check `claims_total`, `claims_supported`, `coverage`, `retry` (+ `checker_failed`, `stopped_early`, `step_limit`, `agent_error`).

**What to show**
- `verified`: normal display. `partially_verified`: a visible caution ("Some parts of this answer could not be verified"), and the answer text itself ends with a "Could not be verified in the documents:" list. `unverified`: a strong warning, never the same look as `verified`.
- Show a retry honestly ("Re-checking evidence..."). Never show raw prompts, counters or error details.
- Present the insufficient-evidence answer as a clear, honest answer, not as an error.
- Do not call `verified` "correct": the UI copy should say the answer was found in the documents.
- Do not show confidence as a percentage or probability; on the golden set it only took the values 0.95 and 0. Show the three statuses.

**Evaluation notes**
- **Budget.** The 10-question golden set took 30 live generator calls in one day and about 16 judge calls over two days. Judge calls share the same daily free-tier pool (about 50 requests) as the generator's, so spread runs over several days.
- **Cache everything.** Wrap the model in `CachingLLM` (namespace per prompt version) for evaluation runs so each answer is paid for once. `scripts/live_agent_run.py` is a working template.
- **Judge model.** Use a model different from the generator (Nemotron 3 Super); a model judging its own answers tends to rate them higher. In Session 20, `google/gemma-4-31b-it:free` returned a temporary 429 from a shared upstream pool, `qwen/qwen3.8-27b:free` was no longer free, and `minimax/minimax-m3.1-flash:free` worked with structured output. Free-model availability changes, so check the model page first (JSON or structured-output support matters). Our judge was a single-call claim judge, **not the ragas package**; running real RAGAS is still open (item 21).
- **Judge limits.** It caught 3 of 3 planted errors, but it is lenient on interpretive wording ("supports", "is connected to") and its rule accepts plain arithmetic. On the golden set it scored 1.000 for both the agent and the baseline, a ceiling effect.
- **Unanswerable questions.** 4 exist so far (q17, q18, q20 and gold-09); the golden file has 1. More are needed before an unanswerable rate means anything.
- **Golden file.** I resolved the evidence phrases in a working copy (`data/eval/golden_questions_resolved.json`); the changes are listed in `MEMBER3_DECISIONS.md` §2.10.
- **Free metrics:** Member 2's Recall@K, MRR and NDCG need no model; the safety checks in `scripts/live_safety_checks.py` are already done.

## 7. Measured so far, with limits

- **Live answers** (Nemotron 3 Super, free): the closing-headcount question and q16 matched the report and were `verified`; q19 (profit after tax, Q3 FY25) was answered correctly after retries (₹123,800 million) and `verified`; q17, q18 and q20 (unanswerable) all gave "insufficient evidence".
- **Safety checks:** all 3 planted false drafts were marked unsupported; with the instruction filter all 3 injection cases passed (the model alone followed an instruction hidden in a fake row).
- **Planner:** on Member 2's 17 questions the planner's searches score 0.912 / 0.912 / 0.776 / 0.804 (recall@5, recall@10, MRR, NDCG@10) against 0.882 / 0.912 / 0.753 / 0.792 for the question alone.
- **Latency:** about 12 to 36 s per model call; 36 to 175 s per question live in Session 19 and 22 to 158 s on the golden set (Session 20); about 0.1 s replayed.
- **Golden set (Session 20, 10 questions: 9 answerable and 1 unanswerable, one document, one run).** Manual reading: agent answers matched references 9/9 (gold-07 rounded, gold-05 computed figure); the single-draft baseline matched 7/9 and refused 2. MiniMax judge Faithfulness was 1.000 for both (ceiling effect; lenient on interpretive wording). The judge caught 3/3 planted errors. This compares the whole agent with a single-draft baseline; it does not isolate the fact-checker. Real RAGAS comparison with Member 5 remains open. See `MEMBER3_DECISIONS.md` §2.10.
- **Cost on the golden set.** 3 model calls for a clean question, 5 for gold-08 and gold-10 (each needed a retry), and 2 for unanswerable gold-09 (its retry found no new passages, so it stopped early). Judge calls share the generator's daily free-tier request pool.
- **Retrieval floor.** Retrieval-only on the original question: recall@5 0.500, recall@10 0.667 on the 9 golden questions that nobody tuned against, against 0.882 / 0.912 on Member 2's tuned set. Six of nine golden questions had every fact in the top 8. The tuned-set figures are optimistic and should not be treated as the general retrieval expectation.
- **Limits:** these are a handful of questions on one document with one free model; the Session 19 figures were tuned on the same questions Member 2 used. They are signs, not rates.

## 8. Decisions needed from the team

1. **Citation filename:** Member 4 adds `source_file` when building the response (recommended).
2. **`verification_status` on the synchronous `ChatResponse`:** add it.
3. **Streaming policy:** the final answer is streamed after verification, as in Section 5 (recommended).
4. **`VerificationStatus` as an Enum** on the wire: identical JSON, safer typing (optional).
5. **Which golden file is canonical:** Member 5's original, or the resolved copy with rewritten evidence phrases (gold-02, 03, 04, 05, 06, 07, 08, 10; gold-08's `alt_evidence` emptied)? Recommendation: adopt the resolved copy, because the original phrases matched no chunk.

## 9. Suggested 10-minute walkthrough

1. The picture: question, plan, search, draft, check, answer (with a retry loop).
2. Section 3 and 4: what you can and cannot rely on, especially "verified is not true".
3. Section 5 for Member 4 and Section 6 for Member 5.
4. Settle the decisions in Section 8.
5. Show the Session 20 results table.
