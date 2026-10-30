# Backend Schema Document
## Module: Evaluation, Frontend & DevOps/QA
### Owner: Member 5 — Evaluation, Frontend & DevOps/QA Lead
### Project: Enterprise RAG Assistant
### Version: v0.2 (written after Members 1 to 4 were built, October 2026; supersedes the September v0.1)

> **Status.** Design only: nothing here has been checked against Member 5's code. The golden file shape in Section 2 is taken from the real file; the TypeScript types in Section 4 mirror Member 4's real contract (`docs/MEMBER4_CONTRACT_NOTES_FOR_MEMBER5.md`). Member 4 owns the source of truth for the API shapes.

---

## 0. What changed from v0.1

| # | Change | Section |
|---|---|---|
| 1 | Golden entry rewritten to the real file's fields (`evidence` phrases, `alt_evidence`, `style`, `notes`); labels resolved to chunk ids by a script, not stored by hand | 2 |
| 2 | Categories updated to the ones in use, including `unanswerable` handling | 2 |
| 3 | Evaluation result records now carry the generator and judge models, dataset version and sample sizes; a per-question record added | 3 |
| 4 | `pipeline_variant` values match the built system (dense only is the shipped configuration) | 3 |
| 5 | Frontend types replaced with the full built contract, including `error`, `source_file`, document statuses and the trace | 4 |
| 6 | CI parameters: eval mode (replay), tolerance and run count marked as uncalibrated, new migration check | 6 |
| 7 | Open items updated | 7 |

---

## 1. Purpose

This document defines the data structures this module owns: the golden question file, the evaluation result records, the frontend's typed mirror of the API, and the CI parameters. This module owns no application database tables.

---

## 2. Golden Question File

Location: `app/eval/golden_questions.json` (one canonical version; today the original is `tcs_golden_questions_deduplicated.json` and a working copy with resolved phrases is `data/eval/golden_questions_resolved.json`)

```python
from typing import Literal
from pydantic import BaseModel


class GoldenQuestion(BaseModel):
    question_id: str                   # stable id, for example "tcs-gold-04"
    question: str
    category: Literal[
        "fact_lookup", "table", "numerical_comparison", "cross_section", "unanswerable"
    ]                                  # extend deliberately (multi_fact, comparison) as the set grows
    style: Literal["exact", "paraphrase"]   # exact = wording close to the report; paraphrase = reworded
    evidence: list[str]                # phrases that must appear in the retrieved text; EMPTY for unanswerable
    alt_evidence: list[str] = []       # acceptable alternatives
    reference_answer: str              # EMPTY for unanswerable
    notes: str | None = None           # for example why a question is unanswerable
```

### Field notes

| Field | Notes |
|---|---|
| `evidence` | Phrases, not chunk ids. A script finds the chunks containing them (Member 2's `scripts/resolve_labels.py` is the starting point), so a later change to chunking does not break the labels. Each phrase must match the chunk wording: a phrase that matches no chunk makes recall impossible (Session 20 found this for gold-02, 03, 04, 05, 06, 07, 08 and 10) |
| `unanswerable` | `evidence` and `reference_answer` are empty. The expected behaviour is the refusal "I don't have sufficient evidence in the provided documents." with status `unverified`, no citations. The topical-but-missing-figure kind is the hard case |
| `style` | Lets results be split: Member 2's finding was that paraphrase questions are where keyword fusion hurt |
| Labels | Fixed before looking at any agent output; not changed after seeing results |

**Known limits:** one document; written by hand after reading it; the 17 questions Member 2 tuned on are a different, optimistic set and must be reported separately.

---

## 3. Evaluation Result Records

Location: `app/eval/eval_results.csv` (one row per run and variant) and `app/eval/eval_questions.csv` (one row per question per run)

```python
from pydantic import BaseModel


class EvalRunResult(BaseModel):
    run_id: str
    run_timestamp: str
    pipeline_variant: str              # see below
    dataset_version: str               # a hash or tag of the golden file used
    n_questions: int
    n_unanswerable: int
    generator_model: str               # for example "nvidia/nemotron-3-ultra-550b-a55b:free"
    judge_model: str                   # must differ from the generator
    faithfulness: float | None = None  # None when not measured, never 0.0 as a placeholder
    answer_relevancy: float | None = None
    context_precision: float | None = None
    context_recall: float | None = None
    recall_at_5: float | None = None
    recall_at_10: float | None = None
    mrr: float | None = None
    ndcg_at_10: float | None = None
    unanswerable_refused: int | None = None   # how many of n_unanswerable were refused
    avg_latency_ms: float | None = None
    notes: str = ""                    # ceiling effects, caveats, model changes


class EvalQuestionResult(BaseModel):
    run_id: str
    question_id: str
    category: str
    style: str
    answer: str
    verification_status: str           # "verified" | "partially_verified" | "unverified"
    retrieved_chunk_ids: list[str]
    facts_found: int                   # evidence phrases found in the retrieved text
    facts_total: int
    refused: bool                      # the answer was the insufficient-evidence refusal
    latency_ms: float
```

`pipeline_variant` values: `retrieval_dense` (the shipped configuration), `retrieval_keyword`, `retrieval_rerank`, `single_draft`, `full_agent`, and `agent_no_checker` once a switch exists (not available today).

This is the structure behind the README table: one row per variant and run, so trends and the effect of each change are traceable. **Every number in the README must come from a row here, with `n_questions` and `notes` next to it.**

---

## 4. Frontend Types (mirror of Member 4's contract)

Location: `frontend/src/api/types.ts`. Member 4 owns these shapes; if the API changes, this file changes in the same pull request.

```typescript
export type VerificationStatus = "verified" | "partially_verified" | "unverified";

export type ErrorCode =
  | "VALIDATION_ERROR" | "UNAUTHENTICATED" | "FORBIDDEN" | "NOT_FOUND" | "CONFLICT"
  | "FILE_TOO_LARGE" | "UNSUPPORTED_FILE_TYPE" | "RATE_LIMITED" | "AGENT_BUSY"
  | "DEPENDENCY_UNAVAILABLE" | "INTERNAL_ERROR" | "BAD_REQUEST";

export interface ApiError { error: string; code: ErrorCode }

export interface TokenResponse { access_token: string; token_type: string; expires_in: number } // 3600

export interface SessionSummary {
  session_id: string; title: string | null; created_at: string; updated_at: string;
}

export interface Citation {
  chunk_id: string; document_id: string; page_number: number | null;
  text_snippet: string;            // at most 200 characters; may start with "..."
  source_file: string | null;      // null if the document was deleted
}

export interface TraceStep {
  step_type: "plan" | "retrieve" | "synthesize" | "fact_check";
  content: string; metadata: Record<string, unknown>;
}

export interface Message {
  message_id: string; role: "user" | "assistant"; content: string; created_at: string;
  verification_status: VerificationStatus | null;   // null for user messages
  confidence: number | null;                        // do not display
  latency_ms: number | null;
  citations: Citation[]; trace: TraceStep[];
}

export interface SessionDetail extends SessionSummary { messages: Message[] }

export type DocumentStatus =
  | "queued" | "parsing" | "indexing" | "success" | "partial" | "failed" | "duplicate";
  // "ocr_fallback" is reserved by the backend schema but does not occur (no OCR)

export interface DocumentDetail {
  document_id: string; filename: string; status: DocumentStatus; error_message: string | null;
  source_type: string; created_at: string; uploaded_by_me: boolean;
}
export interface UploadResponse {
  document_id: string; filename: string; status: DocumentStatus; error_message?: string | null;
}

export interface ChatRequest { session_id: string; query: string; top_k?: number }  // top_k 1..20

export interface FeedbackRequest { message_id: string; rating: 1 | -1; comment?: string } // comment <= 1000
export interface FeedbackResponse { message_id: string; rating: number; comment: string | null }

export interface HealthResponse {
  status: "ok" | "degraded";
  checks: { postgres: Health; redis: Health; retriever: Health; agent: Health };
}
export type Health = "ok" | "unavailable" | "disabled";

// The chat stream (POST /chat/stream), after parsing "event:" and "data:" lines
export type StreamEvent =
  | { event: "status"; data: { step_type: TraceStep["step_type"]; content: string } }
  | { event: "source"; data: Citation }
  | { event: "token"; data: { text: string } }                       // a word plus its trailing space
  | { event: "verification"; data: { status: VerificationStatus; confidence: number } }
  | { event: "done"; data: { request_id: string; confidence: number; latency_ms: number } }
  | { event: "error"; data: ApiError };                               // exactly one of done or error ends a stream
```

Notes: `done` carries no `message_id`; after it, reload the session to get the assistant message's id for feedback. Comment lines starting with `:` in the stream are heartbeats; ignore them.

---

## 5. Optional: Persisting Evaluation Runs (co-owned with Member 4, later)

If CSV plus git history is not enough, an `eval_runs` table (the columns of `EvalRunResult`, plus `golden_dataset_version`) could be added to Member 4's schema through a migration. Not needed for the MVP: the CSV files are enough for the README table and the gate.

---

## 6. CI Parameters (conceptual)

Location: `.github/workflows/ci.yml`

| Parameter | Purpose | Status |
|---|---|---|
| `postgres` service, database `rag_test` | Integration tests (they skip if the database is unreachable; CI must fail on skips) | Needed |
| `alembic upgrade head` on an empty database | Tests build tables from the models, so migration files are otherwise only tested by hand | Needed |
| `eval_mode` | `replay` (cached answers, free metrics only), `scheduled` or `manual`; a live gate does not fit the free quota (about 50 requests a day) | Decision open |
| `faithfulness_regression_tolerance` | Allowed drop before the gate fails | 0.03, a guess, uncalibrated |
| `eval_run_count` | Runs averaged to reduce judge noise | 3, a guess, uncalibrated |
| tests run twice | Leaks between tests (global limiter settings, shared counters) appeared only on a second or full run | Recommended |
| lint and type rules (`ruff`, `mypy`) | Shared by all Python code | |
| frontend: `npm ci`, lint, Vitest, build | | Needed |

---

## 7. Open Items for Future Iteration

- Choose the canonical golden file (the resolved copy is recommended) and grow it to at least 30 questions with at least 8 unanswerable
- Pin the RAGAS version and check its input column names on that version; choose a judge model different from the generator
- A way to run the agent without the fact-checker, so its effect can be measured alone (needs Member 3)
- Generate `types.ts` from Member 4's OpenAPI schema instead of keeping it by hand, to remove drift risk
- Add `message_id` to the stream's `done` event (a Member 4 change) so a new answer can be rated without reloading the session
- Decide whether `eval_runs` needs a real table or whether CSV plus git history is enough
