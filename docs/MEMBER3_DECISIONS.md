# Member 3 — Agentic Orchestration: Final Configuration and Measured Decisions

**Last updated:** Session 20, October 2026 **Evidence base:** the 17
answerable and 3 unanswerable questions on the 40-page TCS annual report
that Member 2 built (118 chunks), a few planted cases, and live runs of
Nemotron 3 Super (free) through OpenRouter. Scripts:
`measure_planner.py`, `planner_ablation.py`, `check_hints.py`,
`live_agent_run.py`, `live_safety_checks.py`. On 17 questions, one
question moves a score by about 0.06.

> **Read this first.** Most choices below were made by looking at the
> same few questions, and the live runs are single runs of a model whose
> output varies. Treat the numbers as signs, not rates. The checks that
> matter most (Faithfulness with and without the fact-checker,
> calibrated thresholds) still need Member 5’s golden dataset.

------------------------------------------------------------------------

## 1. Final configuration

Built by `build_agent(retriever, llm, config)`; every value lives in
`AgentConfig` (frozen, validated at creation).

| Setting                                        | Value                                                                                                                                  |
|:-----------------------------------------------|:---------------------------------------------------------------------------------------------------------------------------------------|
| Model                                          | `nvidia/nemotron-3-super-120b-a12b:free` via OpenRouter; own retries (`llm_retries` 1) with backoff; ordered fallback models supported |
| `top_k` per search                             | 8 (15 on the second retry, never below the requested value, at most 20)                                                                |
| `max_subqueries` / `max_retries` / `max_steps` | 5 / 2 / 12 (rule: `max_steps >= 4 + 3 * max_retries`)                                                                                  |
| `max_evidence_chunks`                          | 20                                                                                                                                     |
| `coverage_threshold`                           | 0.8 (initial, uncalibrated)                                                                                                            |
| `max_confidence`                               | 0.95 (never claim certainty)                                                                                                           |
| `use_rewrites`                                 | False (planner rewrites are not searched)                                                                                              |
| `quarantine_instructions`                      | True (passages that address the AI are removed)                                                                                        |
| `use_similarity_hint`                          | False                                                                                                                                  |
| LLM calls per question                         | planner + draft(s) + check(s): 3 clean, about 4 unanswerable, at most 7                                                                |

## 2. Measured decisions

### 2.1 Planner: search the original question first, then the sub-questions

The planner’s first version searched only the sub-questions and the
rewrites whenever it split a question. Offline ablation on the cached
plans (0 requests), 17 questions, top 10 (recall@5 / recall@10 / MRR /
NDCG@10):

| Variant                                    | Searches | r@5   | r@10  | MRR   | NDCG  | found(20) |
|:-------------------------------------------|:---------|:------|:------|:------|:------|:----------|
| baseline (original only)                   | 1.0      | 0.882 | 0.912 | 0.753 | 0.792 | 0.912     |
| first planner (sub-questions and rewrites) | 2.3      | 0.853 | 0.912 | 0.714 | 0.747 | 0.941     |
| decomposition only                         | 1.5      | 0.912 | 0.941 | 0.723 | 0.765 | 0.941     |
| **original + sub-questions (shipped)**     | 1.9      | 0.912 | 0.912 | 0.776 | 0.804 | 0.941     |

Dropping the original question hurt q01 (rank 1 to 9) and q12 (1 to 3).
Splitting helps only the multi-fact question q16 (first right chunk 10
to 2). Synonym rewrites showed no benefit (q07 ranks 2 in every
variant). **Decision.** Original first, then sub-questions; rewrites
off. After the change the planner changes 6 questions and none gets
worse. **Basis and caveat.** I added variants and a tie-breaker after
seeing the first ablation, on the same 17 questions Member 2 tuned on.
The planner also costs one of the three model calls per question; its
only visible benefit is multi-fact questions.

### 2.2 When the passages lack the answer: search again, then refuse

The first live run answered q19 with “the passages do not provide it”
and marked it `verified` 0.95 with 8 irrelevant citations: the
fact-checker had “supported” an absence statement. **Decision.** The
draft carries `answer_found` and `search_query`. Not found: search again
with the hint (second one widens `top_k` to 15), skip the fact-check;
out of searches or steps: “I don’t have sufficient evidence in the
provided documents.”, `unverified`, confidence 0, no citations. The
drafting prompt also forbids calculated values (a derived “\$2.6 billion
drop” had triggered an unnecessary retry). **Result.** q17, q18 and q20
(unanswerable) end in an honest refusal after three searches; q17 never
presented the 2% legal minimum as the actual spend.

### 2.3 Retries must not repeat themselves

In all four “not found” cases (q17, q18, q19, q20) the model’s hints
were rephrasings of the first, and for q20 the third was identical to
the second. **Decision.** The state records every search that ran
(`tried_queries`); on a retry the prompt lists them and asks for
different wording (a shorter phrase, or the label a statement or table
row would use, with an example unrelated to any test question); a hint
that repeats an earlier search triggers a wider search of the original
question instead. **Result.** q19 is now answered: the second hint
dropped the company name and the months and said “net profit after tax”,
the table was found, and the answer ₹123,800 million (reference:
₹123,800 million, Q3 FY25) was `verified`, in 3 live calls and 58
seconds. q17, q18 and q20 still refuse, with hints that differ more from
each other. **Caveat.** q19 is the question I picked after seeing it
fail, one run, and the model’s output varies. A retrieval-only check
showed the mechanism: the model’s early hints do not reach the table
(not in the top 30), while the short statement-style “Net income Q3
FY25” ranks 2. Whether the change generalises is for the golden dataset.

### 2.4 Retry hints come from the fact-checker’s single call

TRD v0.2 had a separate rewrite step. **Decision.** Each unsupported
claim gets a `search_query` hint in the same fact-checking call, so a
retry costs two model calls (draft and check), not three, and stays at
three steps. If the model gives no hint, the claim’s own wording is
searched.

### 2.5 Fact-checker strictness

A “supported” verdict must name at least one passage that was really
retrieved; a claim with a figure, name or date is supported only if that
value appears. Coverage at or above the threshold is `verified`; below
it, retry; after the retries, `partially_verified` with the unsupported
claims listed in the answer, or the insufficient-evidence answer if
nothing was supported. **Live evidence.** On q16 the checker flagged a
correct but computed figure that no passage states. In the planted-draft
test, all 3 false drafts (wrong figure, reversed direction and region,
invented fact) had the planted claim marked unsupported while the true
claims stayed supported. Obvious errors, one model, 3 cases.

### 2.6 Instruction filter (`guard.py`)

A live check showed the model alone passed a blunt override instruction
and a conflicting fake row with no instruction, but **followed an
instruction hidden in a fake headcount row** (answered 1,000,000,
`verified`). **Decision.** Passages containing phrases aimed at the
model are removed before the model or the checker sees them; the trace
says so. **Result.** With the filter on, all three injection cases pass.
**Limits.** The phrases were written while looking at those test
passages; a paraphrased attack would get through; and a plain false fact
in a document is repeated as `verified`, because “verified” means
faithful to the passages. That is a document-trust matter for Members 1
and 4.

### 2.7 Citation snippets

Snippets were the first 200 characters of a chunk, so the headcount
question (593,314) cited the Q1 row (613,069). **Decision.** The snippet
is the chunk sentence that best matches the claim (figures count three
times as much as words; a leading “…” marks an excerpt; the start of the
chunk is the fallback). The first q19 run showed a remaining case: rows
that start with the rupee sign were not split into sentences, so the
Revenue row was shown for a profit answer; the sentence split was
widened to fix it (checked with a free replay).

### 2.8 Confidence and thresholds

Confidence is the verified share of claims, capped at 0.95, and 0 for
`unverified`. The coverage threshold (0.8), `widened_top_k` (15) and the
cap are starting guesses. **Revisit** on Member 5’s golden dataset.

### 2.9 Provider, quota and the cache

Nemotron 3 Super (free) works: every structured call in the live runs
returned valid output. It takes 12 to 36 seconds per call, and the free
tier allows about 50 requests a day, so the agent is built to be paid
for once: `CachingLLM` saves every answer to a git-ignored file, never
saves failures, has a replay-only mode, and merges on every write. A
purchase of credits was declined; the evaluation will use free
OpenRouter models and must be spread over days.

## 3. Live results

| Question                          | Answer                                                           | Status                                    | Calls                                | Time                            |
|:----------------------------------|:-----------------------------------------------------------------|:------------------------------------------|:-------------------------------------|:--------------------------------|
| Closing headcount, Q2 FY26        | 593,314                                                          | `verified`                                | 3                                    | 36 s first run, 7 s with replay |
| q16 (new deals and revenue share) | \$21.6B to \$19.0B, about 48% of revenue (matches the reference) | `verified`                                | 3 to 5                               | 78 to 175 s                     |
| q19 (profit after tax, Q3 FY25)   | ₹123,800 million (matches the reference)                         | `verified` after two “not found” searches | 5 in total (3 live in the final run) | 58 s                            |
| q17, q18, q20 (unanswerable)      | “I don’t have sufficient evidence in the provided documents.”    | `unverified`, confidence 0                | about 4 each                         | 1 to 2 min                      |

## 4. Deviations from the PRD and TRD (v0.2)

| Requirement                             | Status                                                                                                                                                                           |
|:----------------------------------------|:---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| FR 3: rewrite into the document’s terms | Built, **off by default**; the original question is always searched first (Section 2.1)                                                                                          |
| TRD 13: retry rewrite step              | Replaced by hints from the fact-checker’s call (Section 2.4)                                                                                                                     |
| TRD 9: merge                            | Interleaved across searches before the evidence cap                                                                                                                              |
| TRD 10 and 15: no-evidence path         | Extended with the “not found” search loop (Section 2.2)                                                                                                                          |
| New, not in the TRD                     | Instruction filter (2.6), `tried_queries` and repeated-hint handling (2.3), citation snippets (2.7), `finalize` and `step_limit` nodes, the `agent.py` wrapper that never raises |
| Streaming                               | The final, verified answer is streamed after verification, not model tokens as they are generated                                                                                |
| PRD success metrics                     | Targets only; Faithfulness and the unanswerable rate wait for the golden dataset                                                                                                 |

## 5. Limits and revisit triggers

| Limit                                                            | Revisit when                                                                                                                  |
|:-----------------------------------------------------------------|:------------------------------------------------------------------------------------------------------------------------------|
| A handful of questions on one document, tuned on Member 2’s 17   | Member 5’s golden dataset exists: re-measure the planner, the retry change and the thresholds on questions we never looked at |
| One free model with varying output                               | The model changes, or a judged evaluation shows high variance                                                                 |
| The instruction filter is a heuristic                            | A paraphrased-attack test (optional, about 4 to 6 requests) or a real corpus with untrusted uploads                           |
| A false fact in a document is repeated as `verified`             | Member 1 sanitises at ingestion and Member 4 controls uploads                                                                 |
| The model’s search hints decide whether a retry finds the answer | More “not found” cases appear in evaluation                                                                                   |
| Free-tier quota (about 50 requests a day)                        | Credits become available, or the evaluation is split over days                                                                |
| `run()` is synchronous and cannot be cancelled                   | Member 4 measures real concurrency                                                                                            |

## 6. Open items

- Calibrate `coverage_threshold`, `widened_top_k` and `max_confidence`,
  and measure Faithfulness with and without the fact-checker (checklist
  items 20 and 21), with Member 5.
- `Citation` has no filename (Member 4 resolves it; see the hand-off).
- Commit the live-run cache deliberately (`git add -f`) once the prompts
  have settled, so teammates can replay a demo with no live calls.
- A paraphrased injection test and the “48 %” spacing polish are
  optional.

### 2.10 Session 20: evaluation on the golden questions

**Evidence base.** `tcs_golden_questions_deduplicated.json`: 10
questions (9 answerable, 1 unanswerable) on the same 118-chunk TCS
report. Member 5’s file was left untouched. Evidence phrases were
resolved in a working copy (`golden_questions_resolved.json`): gold-02,
03, 04, 05, 06, 07, 08 and 10 had phrases rewritten to match chunk
wording, and gold-08’s `alt_evidence` was emptied. Labels were fixed
before looking at any agent output and not changed after seeing
retrieval results. Agent and baseline: Nemotron 3 Super, one run each.
Judge: `minimax/minimax-m3.1-flash:free`, a different model family from
the generator. Gemma 4 returned a temporary 429 and Qwen was no longer
free. The judge is a single-call claim judge (splits the answer into
statements and checks each against the passages), **not the RAGAS
package**.

**Retrieval-only floor** (original question, top 10, shipped retriever,
0 requests):

|                               | recall@5 | recall@10 |   MRR | NDCG@10 |
|-------------------------------|---------:|----------:|------:|--------:|
| Member 2’s 17 tuned questions |    0.882 |     0.912 | 0.753 |   0.792 |
| These 9 golden questions      |    0.500 |     0.667 | 0.481 |   0.527 |

All facts were in the top 8 for 6 of 9 questions. The misses were
gold-05, gold-07 and gold-10, all genuine misses (wording far from the
report, or a two-fact question). Labels are strict (for example,
gold-02’s margins also appear in other chunks that are not credited), so
recall is understated rather than flattered. The unanswerable gold-09
had a top-1 dense similarity of 0.875, higher than any answerable
question in Member 2’s range, further evidence against a similarity
cutoff.

**Agent against a single-draft baseline** (baseline: search once with
the original question, one draft, no planner, no fact-check, no retries;
same prompt and cache as the agent):

|                                                       |             Baseline |                                 Full agent |
|-------------------------------------------------------|---------------------:|-------------------------------------------:|
| Answers matching the reference (hand reading)         |               7 of 9 |                                     9 of 9 |
| Refused an answerable question                        | 2 (gold-05, gold-10) |                                          0 |
| Wrong figures                                         |                    0 |                                          0 |
| gold-09 (unanswerable) refused                        |                  yes |                                        yes |
| Faithfulness (MiniMax judge, answered questions only) |    1.000 (7 answers) |                          1.000 (9 answers) |
| Live model calls                                      |                    4 | 30 (3 to 5 per question; 22 to 158 s each) |

Agreement with the references is a hand reading, not an independent
grade. gold-07 was answered as “\$30.0 billion” (reference US\$30,017
million: correct fact, rounded). gold-05 was answered ₹7,261 crore, a
computed figure that is arithmetically correct.

**What did the work.** The not-found search recovered gold-10 (two “not
found” drafts, then the BFSI table on the third pass, with a wider
`top_k` and new wording at the same time). On gold-08 the fact-checker
flagged one claim and the retry produced a clean answer. This compares
the whole agentic layer against a single draft, **not the fact-checker
alone**.

**Faithfulness cannot separate the two.** Both score 1.000: a ceiling
effect, and the baseline score leaves out its two refusals. The judge
caught 3 of 3 planted errors (a wrong figure, figures from the wrong
year, an invented claim), but that is only three cases. On gold-08 it
accepted two interpretive baseline claims on a loose reading, so it
appears lenient on “supports / is connected to” wording. We do not claim
the fact-checker improved Faithfulness.

**The fact-checker’s one catch is unconfirmed.** The judge scored the
agent’s first gold-08 draft using the same 15 passages. It restated the
claim the checker had removed (“AI proficiency and learning hours are
outcomes of its AI-led transformation”) as a looser statement and marked
it supported. My reading of chunk \#25 is that the claim overreaches:
the report lists reskilling as a priority and gives the two figures, but
does not call them outcomes. That is a reading plus Nemotron’s verdict,
not independent confirmation. On gold-05 the checker passed a computed
figure that no passage states; the judge also accepts it because its
rule allows plain arithmetic.

**Thresholds: recorded as uncalibrated.**

| Setting              | Value | Observed                                                                                                                          |
|:---------------------|------:|:----------------------------------------------------------------------------------------------------------------------------------|
| `coverage_threshold` |   0.8 | Fired once (gold-08 at 2 of 3 claims). Every other check was 1.0, so any value between 0.667 and 1.0 would have behaved the same. |
| `widened_top_k`      |    15 | Used once (gold-10, third pass), mixed with new wording; its effect alone is not separable.                                       |
| `max_confidence`     |  0.95 | Every verified answer is at the cap; confidence took only the values 0.95 and 0.0.                                                |

(The 0.0 coverage shown for gold-09 is a placeholder: its last step
ended without checking any claim.)

**Unanswerable questions.** gold-09 was refused (1 of 1), in addition to
q17, q18 and q20 earlier (3 of 3). Four cases total, not a general
success rate.

**Limits.** 10 questions, one document, one run, one generator, one free
judge. The golden questions were not tuned against, but the labels and
phrases were written by hand after reading the report. The judge shares
the daily request pool, so runs had to be spread out. About 16 live
judge calls were used (pilot 2, agent 8, baseline 2, planted-error check
3, first-draft check 1), plus one failed Gemma call. Faithfulness with
and without the fact-checker, measured together with Member 5 using real
RAGAS, is **still open** (checklist item 21).
