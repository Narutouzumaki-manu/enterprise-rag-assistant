# Product Requirements Document (PRD)
## Module: Evaluation, Frontend & DevOps/QA
### Owner: Member 5 — Evaluation, Frontend & DevOps/QA Lead
### Project: Enterprise RAG Assistant
### Version: v0.2 (written after Members 1 to 4 were built, October 2026; supersedes the September v0.1)

> **Status of this document.** Written from the finished backend (Members 1 to 4), Member 3's evaluation notes, and the golden question file. **Nothing in Member 5's own module has been checked against code**: the frontend, the CI pipeline, the compose file and the RAGAS harness are designs, not results. Every number below is a target or a starting value unless marked "measured". Measured numbers come from Members 2 and 3 (one 118-chunk document, 10 to 17 questions, one free model) and are signs, not rates. Member 5 should correct anything that does not match their code.

---

## 0. What changed from v0.1

| # | Change | Why |
|---|---|---|
| 1 | The chat stream is a **POST**, so the browser needs `fetch` with a streamed body, not `EventSource` (FR 6) | Member 4 built `POST /chat/stream`; `EventSource` can only send GET |
| 2 | The frontend shows `verification_status`, **never `confidence`** (FR 8) | On the golden set every `verified` answer had confidence 0.95 and every `unverified` one 0 |
| 3 | The UI must handle a **1-hour token with no refresh**, rate limits (429), busy service (503) and very long waits (FR 6, 8) | Built in Member 4's API; measured waits of 26 s to 147 s to the first word |
| 4 | The golden dataset already exists as a 10-question file with a different shape from v0.1's schema; **one canonical version must be chosen** (FR 1) | Member 3 resolved evidence phrases in a working copy; the original phrases matched no chunk |
| 5 | Baseline ladder rewritten to the **shipped configuration**: meaning search only, keyword search and reranker off by default (FR 4) | Member 2 measured hybrid and the reranker as worse on their test set |
| 6 | RAGAS is **not yet run**; Member 3's comparison used a single-call claim judge, not RAGAS, and could not separate the agent from a single-draft baseline (FR 3, Risks) | Both scored Faithfulness 1.000 (a ceiling effect) |
| 7 | Free-tier model limits (about 50 requests a day, shared by generator and judge) shape the whole evaluation and CI design (FR 3, 7) | A live eval-gate on every pull request does not fit the quota |
| 8 | Deployment is **one API replica** with an embedded vector index: no separate worker or vector-database server (FR 9) | Member 2's index is a local directory; Member 4's ingestion runs inside the API |
| 9 | New CI requirement: `alembic upgrade head` on an empty database (FR 7) | Tests build tables from the models, so the migration files are only tested by hand |
| 10 | New: the AI-built frontend option and its acceptance checklist (FR 6, Risks) | `docs/FRONTEND_BUILD_PROMPT.md` exists; a person must still be able to defend the result |
| 11 | Success metrics reworded as targets (Section 7) | Nothing in this module has been measured |

---

## 1. Purpose

This module has three responsibilities that make the project provable and usable: (1) measure whether the system works (retrieval metrics, answer evaluation, baseline comparisons), (2) build the user interface, and (3) make the system reproducible and continuously tested (Docker Compose, Nginx, CI).

Without it the team has four finished backend modules and no honest evidence of quality, no way to use them, and no way to catch regressions.

---

## 2. Problem Statement

- A RAG system without measurement "seems to work". Member 3's first comparison shows the risk: with a lenient judge and ten questions, both a single draft and the full agent scored 1.000, so the evaluation could not tell them apart
- The free model is slow (12 to 36 s per call), rate-limited (about 50 requests a day) and changes without notice (the first model stopped working in Session 28). Any plan that assumes unlimited live model calls fails
- Without a usable frontend, the work of Members 1 to 4 is invisible
- The UI can mislead: "verified" means faithful to the retrieved passages, not true; a refusal is a good answer; a long wait is normal. A naive chat UI would present all of these wrongly
- Without CI and a reproducible environment, regressions and "works on my machine" problems reach `main`

---

## 3. Goals

| Goal | Description |
|---|---|
| G1 | One canonical golden dataset of at least 30 questions with a real share of unanswerable ones, labelled from evidence phrases |
| G2 | Measure retrieval quality for free (Recall@K, MRR, NDCG), with no model calls |
| G3 | Measure answer quality with RAGAS (Faithfulness, Answer Relevancy, Context Precision, Context Recall) using a judge that differs from the generator, recording both models |
| G4 | Report the baseline ladder with deltas, sample sizes and limits, never a bare final number |
| G5 | Build the chat, documents and login screens against the real contract, with honest trust display |
| G6 | CI: lint, types, tests, a migration check and an evaluation gate that fits the free quota |
| G7 | One-command deployment through Docker Compose and Nginx, with streaming that works behind the proxy |
| G8 | End-to-end tests of upload, question, cited answer |

---

## 4. Non-Goals

- Ingestion, retrieval, agent logic and the API itself (Members 1 to 4): this module measures, shows and deploys them
- Fine-tuning any model
- Horizontal scaling (one API replica)
- OCR (not built in Member 1's module)
- Per-user document visibility (all signed-in users search the same documents in this version)

---

## 5. Users of This Module

| User | How they use it |
|---|---|
| Members 1 to 4 | Measured by the evaluation, made visible by the UI, protected by CI |
| End users | Use the system only through the frontend |
| The team (interviews) | The metrics table, the CI pipeline and the demo are the evidence that this is not a tutorial project |

---

## 6. Functional Requirements

1. **Golden dataset:** one canonical file, at least 30 questions across fact lookup, tables, numerical comparison, multi-fact, cross-section and **unanswerable** questions (the current file has 1 unanswerable out of 10; a proposal is at least 8 in 30). Labels come from evidence phrases, not chunk ids, so a later chunking change does not break them (`scripts/resolve_labels.py`, Member 2). Each entry records `style` (exact or paraphrase) so results can be split
2. **Retrieval metrics:** Recall@5, Recall@10, MRR and NDCG@10 on the golden set with Member 2's tooling; needs no model
3. **Answer evaluation:** run RAGAS on the golden set. The judge model must differ from the generator. Record generator model, judge model, dataset version and number of questions with every run. Splitting results by category and style is required
4. **Baselines:** (a) retrieval ladder as built: dense only (shipped), `use_keyword=True`, `reranker_model=...`, each reported even where it is worse; (b) answer ladder: single draft (search once, one draft, no planner, no fact-check, no retries) against the full agent. The fact-checker's own effect is measured only if a run isolates it (the agent without the checker, or the checker on and off)
5. **Unanswerable and unsupported-answer rates** measured on the golden set (target: report the rate with its sample size)
6. **Frontend** (React, TypeScript): login, chat with a live steps panel and citations, documents with upload progress and status, session list, feedback buttons. Streams the answer with `fetch` against `POST /chat/stream`. Handles the 1-hour token (401 returns to login), 429 and 503 with retry, long waits, and a closed stream without an ending event
7. **CI** (GitHub Actions): `ruff`, `mypy`, backend tests with Postgres (and Redis if needed) as services, `alembic upgrade head` on an empty database, frontend lint, tests and build, Docker image builds, and an evaluation gate designed for the free quota (see TRD)
8. **Trust display:** `verified`, `partially_verified` and `unverified` must look clearly different; an "insufficient evidence" answer is shown calmly as an answer, not as an error; confidence is never shown; the copy says "found in your documents", never "correct"
9. **Deployment:** Docker Compose with `frontend`, `api`, `postgres`, `redis`, `nginx`, healthchecks and persistent volumes; Nginx configured for streaming (no buffering, long read timeout) and uploads (body size above 25 MB), forwarding the client address, and not exposing `/metrics`
10. **End-to-end tests:** upload a real PDF, wait for `success`, ask a question, assert citations and a trust status. These use the real model and the daily quota: run rarely, or against a replay cache
11. **Reporting:** the README metrics table lists each run's models, number of questions and limits

---

## 7. Success Metrics (targets, not results)

| Metric | Target |
|---|---|
| Golden dataset | 30 or more questions, 8 or more unanswerable, one canonical file |
| Faithfulness (RAGAS, full system) | At least 0.85, reported next to the single-draft baseline, with n |
| Context Precision and Context Recall | At least 0.80 each, with the caveat that thresholds are tuned on a small set |
| Unanswerable questions refused | Report the rate with its sample size (so far 4 of 4 by hand, not a rate) |
| CI blocks a deliberately worsened change | Demonstrated once, not assumed |
| Migration check in CI | Passes on an empty database |
| `docker compose up` from a clean clone | No manual steps |
| Streaming works through Nginx | Tokens and steps arrive progressively (tested, not assumed) |
| Frontend acceptance checklist (`docs/FRONTEND_BUILD_PROMPT.md`, Section 11) | All 9 checks pass by hand |

---

## 8. Risks & Open Questions

- **Free-tier quota.** About 50 requests a day, shared by generator and judge; one question is 3 to 7 generator calls. A 30-question run needs about 100 to 200 calls before judging, so a full evaluation takes several days. Mitigation: cache every answer (`CachingLLM`, namespace per prompt version) and spread runs. Credits were declined, so this is a standing constraint
- **Judge quality.** Member 3's judge (MiniMax, a single-call claim judge) caught 3 of 3 planted errors but was lenient on interpretive wording; both systems scored 1.000. RAGAS with the same free judge may be equally lenient and noisy. Add harder questions, report the ceiling effect, and never claim the fact-checker improved Faithfulness unless a run isolates it
- **Golden-set bias.** Questions and labels were written by hand after reading the one report; the 17 questions Member 2 tuned on are optimistic, and the 9 untouched golden questions scored Recall@5 0.500 / Recall@10 0.667. State both, do not blend them
- **Model availability.** A model that worked can start failing (Session 28). Record the model with every number; keep a short fallback list (each extra model can add up to about two minutes per call in the worst case)
- **Evaluation gate versus quota.** A live gate on every pull request is not affordable. Options in the TRD
- **Streaming behind a proxy** can silently buffer. It needs a real test through Nginx
- **Login limit behind Nginx:** every request would share the proxy's address unless forwarded addresses are passed and trusted
- **AI-built frontend.** It may be fast, but whoever presents it must be able to explain it line by line; review it against the contract, not by appearance
- **One replica, in-memory metrics and in-memory limits** (counted per process): state it in the README

---

## 9. Dependencies on Other Members

- **Member 1:** chunk quality and the table-as-sentence rewrite affect what the golden set can test; no OCR means scanned documents fail
- **Member 2:** retrieval metrics tooling (`scripts/resolve_labels.py`, metrics module), the switches for keyword search and the reranker, and the measured configuration
- **Member 3:** the agent, its cache and the evaluation scripts; the single-draft baseline and judge scripts; open items 20 and 21 of Member 3's checklist (thresholds recorded as uncalibrated; real RAGAS comparison still open)
- **Member 4:** the API contract (`docs/MEMBER4_CONTRACT_NOTES_FOR_MEMBER5.md`), the mock server (`python -m scripts.dev_mock_server`), `/health` and `/metrics`, and the settings needed for deployment (`--timeout-graceful-shutdown`, `--proxy-headers`, one worker)
