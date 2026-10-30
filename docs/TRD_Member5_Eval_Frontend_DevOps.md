# Technical Requirements Document (TRD)
## Module: Evaluation, Frontend & DevOps/QA
### Owner: Member 5 — Evaluation, Frontend & DevOps/QA Lead
### Project: Enterprise RAG Assistant
### Version: v0.2 (written after Members 1 to 4 were built, October 2026; supersedes the September v0.1)

> **Status.** Design only: the frontend, CI pipeline, compose file and RAGAS harness are not built or checked against code. Items marked **(unverified)** are beliefs about libraries or tools that must be confirmed on the installed versions. Numbers are starting values unless marked "measured".

---

## 0. What changed from v0.1

| # | Change | Section |
|---|---|---|
| 1 | Streaming uses `fetch` with a streamed POST body, not `EventSource`; event set now includes `error` and `status` carries `step_type` and `content` | 5 |
| 2 | Token handling: 1-hour token, no refresh, 401 returns to login; stored in memory and `sessionStorage` | 5 |
| 3 | Dev proxy instead of CORS (the backend has no CORS configuration) | 5 |
| 4 | RAGAS harness details: column names depend on the installed version, judge must differ from the generator, free-tier budget | 6 |
| 5 | Baselines rewritten to the shipped configuration and the single-draft baseline | 7 |
| 6 | Golden dataset: real file shape, label resolution, one canonical file | 8 |
| 7 | CI: Postgres service, `alembic upgrade head`, frontend jobs, and an evaluation gate designed for the free quota | 9 |
| 8 | Compose: five services, no worker, no vector-database server; health endpoint as healthcheck | 10 |
| 9 | Nginx rules for streaming, uploads, forwarded addresses and `/metrics` | 11 |
| 10 | Testing plan updated; E2E uses a replay cache | 12 |
| 11 | Open decisions table | 14 |

---

## 1. Scope

Technical design of the evaluation harness, the React frontend, the CI pipeline, and the Docker Compose and Nginx deployment.

---

## 2. Architecture Overview

```
Browser (React UI)
   |  same origin
   v
Nginx  (SSE route: no buffering, long read timeout; /metrics not exposed)
   |
   +--> frontend (static files)
   +--> api  (ONE replica: FastAPI, agent, retriever with embedded index, ingestion)
           |
           +--> postgres   (durable data)
           +--> redis      (rate limits; optional for chat)

Evaluation (run by hand or by the gate, outside the request path)
   golden file -> resolve labels -> retrieval metrics (no model)
                                 -> agent / single draft -> answers (cached) -> RAGAS
```

---

## 3. Tech Stack

| Component | Tool | Notes |
|---|---|---|
| Frontend | React 18, TypeScript (strict), Vite, React Router | |
| Data fetching | TanStack Query | Streaming is handled by our own `fetch` reader |
| Styling | Tailwind | |
| Frontend tests | Vitest, React Testing Library | |
| Evaluation | RAGAS (version to be pinned) plus Member 2's metrics tooling | |
| Backend tests | pytest, pytest-asyncio, httpx | Already in use |
| CI | GitHub Actions | |
| Containers | Docker, Docker Compose | Dev compose (Postgres and Redis only) already exists: `docker/docker-compose.dev.yml` |
| Proxy | Nginx | |

---

## 4. Module Breakdown

```
app/eval/
├── golden_questions.json        — the canonical golden file (one version, see Section 8)
├── resolve_labels.py            — evidence phrases to chunk ids (Member 2's script is the starting point)
├── run_retrieval_metrics.py     — Recall@K, MRR, NDCG per question, no model
├── run_answers.py               — agent or single draft over the golden set, through CachingLLM
├── run_ragas.py                 — RAGAS over cached answers
└── baselines.py                 — retrieval and answer ladders, writes eval_results.csv

frontend/
├── src/api/        client.ts (typed fetch, error mapping, 401 handling), sse.ts (stream parser), types.ts
├── src/pages/      Login, Chat, Documents
├── src/components/ AgentSteps, AnswerCard, TrustBadge, CitationCard, UploadArea, DocumentRow, RatingButtons, ErrorState
├── src/hooks/      useChatStream, useDocuments, useSessions
└── vite.config.ts  (dev proxy)

.github/workflows/ci.yml
docker/             Dockerfile.api, Dockerfile.frontend, docker-compose.yml, nginx/
tests/              unit, integration, e2e
```

---

## 5. Frontend Technical Design

### 5.1 Contract and proxy
Types mirror Member 4's contract in one file (`types.ts`; see the Backend Schema, Section 4). In development, Vite's dev proxy forwards `/auth`, `/sessions`, `/documents`, `/chat`, `/feedback` and `/health` to `http://127.0.0.1:8000`. The backend has no CORS configuration, so the browser must see one origin. Behind Nginx it is one origin by construction. Whether Vite's proxy passes a streamed response without buffering is **(unverified)** and is part of the first test.

### 5.2 Streaming a POST
```
fetch("/chat/stream", {method: "POST", headers: {Authorization, "Content-Type": "application/json"}, body, signal})
  -> response.body.getReader()
  -> decode with TextDecoder (stream: true)
  -> split on blank lines into blocks; each block has "event: <name>" and "data: <json>"
  -> lines starting with ":" are comments (": keep-alive" about every 15 s): ignore
```
- Handle chunks that end in the middle of a line or a block (keep a buffer)
- Problems found before the stream starts arrive as ordinary JSON errors, not events: `422` blank or too long query, `404` unknown session, `503 AGENT_BUSY`, `429`
- **Exactly one of `done` or `error` ends a stream.** A stream that closes without either is a lost connection: show it and offer a retry, never a silent spinner
- Allow the user to stop waiting (`AbortController`). The server still finishes and saves the answer
- Event data: `status` `{step_type, content}`, `source` `{chunk_id, document_id, source_file, page_number, text_snippet}`, `token` `{text}` (a word plus its trailing space), `verification` `{status, confidence}`, `done` `{request_id, confidence, latency_ms}`, `error` `{error, code}`

### 5.3 Waiting and trust
- The answer is streamed after verification. Measured on one free model: the first word came 26 s, 34 s and 147 s after the request (worst cases are longer). The `status` events fill the wait; the last one is shown as in progress
- Show `verification_status` as a badge on every assistant answer and never `confidence` (it only took the values 0.95 and 0). "Found in your documents", never "correct"
- A retry line ("searching again") is shown with a caution icon: a visible self-correction is a feature
- `done` has no `message_id`: after `done`, refetch `GET /sessions/{id}` and use the last assistant message's id for feedback (a `message_id` in `done` is a proposed backend change)

### 5.4 Session, uploads, errors
- Token in memory and `sessionStorage` (never `localStorage`, never in a URL or log). Any `401` clears it and returns to login, remembering the page
- Upload with `XMLHttpRequest` to get real progress (`fetch` has none); validate type (PDF, DOCX, CSV) and 25 MB before sending; one failing file must not block the others
- Poll `GET /documents` every 2 s while any document is `queued`, `parsing` or `indexing`
- `429` and `503` are temporary: show a retry with the `Retry-After` countdown. Show the `X-Request-ID` in a details line on error screens
- Render all API text as plain text (no `dangerouslySetInnerHTML`)

### 5.5 Alternative
`docs/FRONTEND_BUILD_PROMPT.md` is a self-contained prompt to have the frontend built by an AI coding tool, with a nine-point acceptance checklist. Whoever uses it reviews the result against Section 5 and can explain it.

---

## 6. RAGAS Evaluation Harness

- **Version matters.** RAGAS changed its input column names between releases (older: `question`, `answer`, `contexts`, `ground_truth`; newer: `user_input`, `response`, `retrieved_contexts`, `reference`) and its metric imports **(unverified for the installed version)**. Pin the version and write the converter against it
- **Inputs per question:** the question, the generated answer, the retrieved passages the answer used (the agent's final evidence), and the reference answer. Unanswerable questions have an empty reference: handle them separately (the expected behaviour is the refusal text, not a RAGAS score)
- **Judge:** an LLM and embeddings are needed by RAGAS itself. The judge model must differ from the generator (Nemotron); a model judging its own answers rates them higher. Free models change availability: check the model page first and note JSON or structured-output support
- **Budget:** judge calls share the same daily free pool as the generator. Answers are produced once and cached (`CachingLLM`, namespace per prompt version); RAGAS runs over the cache. Spread runs over days
- **Output:** `eval_results.csv`, one row per run and variant, recording generator model, judge model, dataset version, number of questions, number of unanswerable questions
- **Reporting rules:** report n; split by category and style; report a ceiling effect as a ceiling effect; never present tuned-set numbers (Member 2's 17 questions) next to untouched ones as one figure
- The agent can be called through the `agent` object with `CachingLLM` (see `scripts/live_agent_run.py` as a template), or through the real API for an end-to-end run

---

## 7. Baseline Ladders

**Retrieval ladder** (free, no model; Member 2's tooling):

| Variant | How | Measured on Member 2's 17 tuned questions (Recall@5 / Recall@10 / MRR / NDCG@10) |
|---|---|---|
| Meaning search only (shipped) | `build_default_retriever()` | 0.882 / 0.912 / 0.753 / 0.792 |
| + keyword search and fusion | `use_keyword=True` | 0.765 / 0.765 / 0.629 / 0.655 |
| + reranker | `reranker_model="cross-encoder/ms-marco-MiniLM-L-6-v2"` | about 0.853 / 0.88 to 0.94 / about 0.67 / about 0.72 to 0.74 (varies with the embedding model) |

On the 9 untouched golden questions the shipped configuration scored 0.500 / 0.667 / 0.481 / 0.527. Run the ladder on the golden set and report both sets separately.

**Answer ladder** (needs model calls, cached):

| Variant | What it isolates |
|---|---|
| Single draft: search once, one draft, no planner, no fact-check, no retries | The floor |
| Full agent | Planner, not-found search, fact-checker and retries together |
| Agent without the fact-checker (if a switch is added) | The fact-checker alone. **Not available today:** Member 3's comparison could not separate it |

Session 20 result (10 golden questions, one run, hand reading): the agent matched the references 9 of 9, the single draft 7 of 9 (it refused two answerable questions); the unanswerable question was refused by both; both scored Faithfulness 1.000 with the claim judge. This is a sign, not a rate.

---

## 8. Golden Dataset

Current file (`tcs_golden_questions_deduplicated.json`, 10 questions: 9 answerable, 1 unanswerable) has entries of this shape: `question_id`, `question`, `category` (`fact_lookup`, `table`, `numerical_comparison`, `cross_section`, `unanswerable`), `style` (`exact` or `paraphrase`), `evidence` (phrases), `alt_evidence`, `reference_answer`, and optional `notes`. See the Backend Schema, Section 2.

- **Labels from phrases.** Evidence phrases are matched to chunks by a script, so a chunking change does not break the labels. In Session 20 Member 3 found that the original phrases (for gold-02, 03, 04, 05, 06, 07, 08 and 10) matched no chunk and rewrote them in a working copy (`data/eval/golden_questions_resolved.json`; gold-08's `alt_evidence` emptied). **Decision needed:** adopt the resolved copy as the canonical file (recommended), and keep a note of what changed
- **Grow it.** At least 30 questions; at least 8 unanswerable (the topical-but-missing-figure kind, as in q17, is the hard case); more multi-fact and table questions. Labels are fixed before looking at any agent output
- **Limits to state:** one document; written by hand after reading it; bias towards what the writer finds askable

---

## 9. CI Pipeline (`.github/workflows/ci.yml`)

```
push / pull request
   |
   +-- backend:  ruff -> mypy -> pytest unit
   |             pytest integration (Postgres service; database rag_test)
   |             alembic upgrade head on an EMPTY database (migrations are otherwise only tested by hand)
   |             (optionally: alembic check, to compare the migrations with the models; unverified for the installed version)
   +-- frontend: npm ci -> lint -> vitest -> build
   +-- docker:   build images
   +-- eval gate (see below)
```

- Unit tests do not need Redis (the limiter uses in-memory storage in tests) and do not need the model. Integration tests need the Postgres service; they skip if it is unreachable, so CI must fail if they were skipped
- The suite is green only if it is green **twice**: leaks between tests (global limiter settings, shared counters) appeared only on a second or full run
- **Evaluation gate.** A live gate on every pull request does not fit the free quota (about 50 requests a day). Options: (1) **replay gate**: replay cached answers and run only the free metrics (retrieval metrics and refusal checks) on each pull request, and refresh the cache and RAGAS by hand when prompts change; (2) a scheduled run (daily or weekly) that posts the numbers; (3) a manual trigger. Recommendation: (1) plus (3). A gate must prove it works: one deliberately worsened change must fail it
- Tolerance band, not equality: LLM-judged scores are noisy. Starting values `faithfulness_regression_tolerance` 0.03 and `eval_run_count` 3 are guesses

---

## 10. Docker Compose (MVP)

Services: `frontend`, `api`, `postgres`, `redis`, `nginx`. **No separate worker and no vector-database server**: the vector index is a local Chroma directory opened by the API process, and ingestion runs inside it. Two processes writing the same directory is unsafe.

- Healthchecks and `depends_on: condition: service_healthy` for Postgres and Redis; the API's own healthcheck calls `GET /health` (HTTP 503 when Postgres is down; 200 with `degraded` when only Redis is down)
- Volumes: Postgres data, the Chroma directory (`data/chroma`), uploaded files (`data/uploads`)
- The embedding model (about 130 MB) is downloaded on first start: bake it into the API image or mount a cache volume
- API command: one worker; `--timeout-graceful-shutdown 10` (an open stream otherwise keeps the process from exiting); `--proxy-headers` and trusted forwarded addresses for the login limit (uvicorn only trusts forwarded headers from allowed addresses, by default localhost: set the allowed addresses to the proxy's network **(unverified)**)
- Secrets (`OPENROUTER_API_KEY`, `JWT_SECRET`) only through the environment; `ENVIRONMENT=production` makes the API refuse the development JWT secret; `LOG_JSON=true` in production
- Metrics are per process (one replica): state it in the README
- Multi-stage Dockerfiles; `python:3.12-slim` where compatible

---

## 11. Nginx

- **Streaming route** (`/chat/stream`): `proxy_buffering off`, `proxy_http_version 1.1`, and a long `proxy_read_timeout` (starting value 600 s). The API sends a heartbeat comment about every 15 s; Nginx's read timeout is believed to measure silence between reads, not the total time, so the heartbeat keeps the stream alive **(unverified: confirm in the compose test)**. A single question can still last many minutes in the worst case (one model call can take 122 s with its retry; a question makes 3 to 7 calls)
- **Uploads:** `client_max_body_size` a little above 25 MB (for example 30 MB); the API refuses larger files itself with `413 FILE_TOO_LARGE`
- **Forwarded addresses:** pass `X-Forwarded-For` and `X-Request-ID`; without them every client shares one login limit
- **`/metrics`** is internal: do not proxy it publicly
- Serve the built frontend, with a fallback to `index.html` for client-side routes

---

## 12. Testing Plan

- **Frontend unit:** the SSE parser (split chunks, comment lines, both ending events, a stream closing without one), 401 handling, the trust badge for all three statuses, upload validation, the refetch-for-`message_id` flow
- **Evaluation:** the label resolver, the metric functions on a hand-computed example, the RAGAS converter against a stub
- **Backend (already in place):** about 168 unit tests in `tests/unit/api` and the integration set; this module adds the migration check
- **Compose test:** through Nginx, tokens and steps arrive progressively; a 25 MB upload passes; the login limit counts per client, not per proxy; `/metrics` is not reachable from outside
- **E2E:** upload a real PDF, wait for `success`, ask one question, assert a citation with `source_file` and a status. Uses the real model: run rarely or against a replay cache
- **Gate test:** a deliberately worsened prompt must fail the gate once

---

## 13. Error Handling (frontend)

| Case | Behaviour |
|---|---|
| 401 | Clear token, go to login, return afterwards |
| 429, `AGENT_BUSY`, `DEPENDENCY_UNAVAILABLE` | Friendly message, retry with countdown from `Retry-After` |
| `error` event or a stream that closes early | Show it, keep the question, offer a retry |
| "I couldn't ... right now. Please try again." answers | A normal answer (status `unverified`) with a "Try again" button |
| Backend unreachable | Full-page unavailable state with the request id if there is one |

---

## 14. Open Decisions

| Decision | Owner | Needed by |
|---|---|---|
| Canonical golden file: the resolved copy (recommended) or the original | Member 5 with Member 3 | Before RAGAS runs |
| Evaluation gate mode: replay plus manual (recommended), scheduled, or live | Member 5 | Before CI is final |
| RAGAS version and the judge model to use | Member 5 | Before the first run |
| A switch to run the agent without the fact-checker, so its effect can be isolated | Members 3 and 5 | Before claiming a fact-checker gain |
| `message_id` in the `done` event | Members 4 and 5 | Before the feedback UI is final |
| Build the frontend with an AI tool or by hand | Member 5 | Now |
| Trusted forwarded addresses and the exact Nginx read timeout | Members 4 and 5 | Compose test |
| Commit a recorded demo cache (currently git-ignored) | Member 3 | When prompts settle |
