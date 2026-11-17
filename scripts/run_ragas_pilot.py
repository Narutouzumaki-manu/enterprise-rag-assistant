"""Ragas Pilot Evaluation on full_agent answers.

Runs Faithfulness and ContextRecall on sampled full_agent answers using an
external judge model distinct from the generator. Supports offline replay
through CachingLLM with judge-model-specific cache files and namespaces.
"""

import argparse
import asyncio
import csv
import hashlib
import json
import math
import os
import random
import re
import socket
import sys
import types
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)

# Shim for langchain_community vertexai import bug in ragas 0.2.14
if "langchain_community.chat_models.vertexai" not in sys.modules:
    _m = types.ModuleType("langchain_community.chat_models.vertexai")
    _m.ChatVertexAI = type("ChatVertexAI", (), {})
    sys.modules["langchain_community.chat_models.vertexai"] = _m

# On Windows, loopback socket connections may be restricted in sandbox environments.
# If loopback connect fails, switch to WindowsSelectorEventLoopPolicy.
_loopback_ok = False
try:
    _s = socket.socket()
    _s.bind(("127.0.0.1", 0))
    _s.listen(1)
    _c = socket.socket()
    _c.settimeout(0.1)
    _c.connect(("127.0.0.1", _s.getsockname()[1]))
    _s.close()
    _c.close()
    _loopback_ok = True
except OSError:
    pass
if not _loopback_ok and sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Disable telemetry and offline hub checks
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["RAGAS_DO_NOT_TRACK"] = "true"

import ragas
from langchain_core.outputs import Generation, LLMResult
from langchain_core.prompt_values import PromptValue
from ragas.dataset_schema import SingleTurnSample
from ragas.llms.base import BaseRagasLLM
from ragas.metrics._context_recall import ContextRecall
from ragas.metrics._faithfulness import Faithfulness
from ragas.run_config import RunConfig

from app.agents.llm import LLMError, OpenRouterLLM
from app.agents.llm_cache import CachingLLM
from app.eval.golden_schema import validate_golden_questions
from app.eval.validate_golden import load_chunks

RAGAS_VERSION = getattr(ragas, "__version__", "0.2.14")
DEFAULT_JUDGE_MODEL = "inclusionai/ling-3.2-flash:free"
REFUSAL_STRING = "I don't have sufficient evidence in the provided documents."
DEFAULT_OUTPUT_CSV = Path("app/eval/results/ragas_pilot.csv")
DEFAULT_EVAL_RESULTS_CSV = Path("app/eval/eval_results.csv")
DEFAULT_OVERLAP_JSON = Path("app/eval/golden_tuned_overlap.json")
MAX_REQUEST_BUDGET = 40


def compute_sha256(path: Path | str) -> str:
    """Calculate SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest().lower()


def sanitize_model_id(model_id: str) -> str:
    """Sanitize a model identifier for safe use in file paths."""
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", model_id)


def get_judge_cache_namespace(judge_model: str) -> str:
    """Return the CachingLLM namespace for a given judge model.

    The namespace MUST include the judge model ID so that answers cached by an
    earlier judge cannot be replayed under a different judge label.
    """
    return f"ragas-pilot-v1:{judge_model}"


def get_judge_cache_file(judge_model: str, base_dir: Path | str = "data/llm_cache") -> Path:
    """Return the cache file Path for a given judge model.

    The cache file MUST include the sanitised judge model ID so that distinct
    judge models store their cached judgments in separate files.
    """
    sanitized = sanitize_model_id(judge_model)
    return Path(base_dir) / f"ragas_pilot_{sanitized}.json"


def get_summary_notes(judge_model: str) -> str:
    """Return evaluation summary notes depending on judge model family."""
    if judge_model.startswith("nvidia/"):
        return (
            "pilot, cited chunks as contexts, judge is a different model from the generator "
            "but the same NVIDIA Nemotron family (possible self-preference)"
        )
    return "pilot, cited chunks as contexts, judge differs from generator"


def load_excluded_overlap_ids(path: Path | str = DEFAULT_OVERLAP_JSON) -> list[str]:
    """Read excluded overlap golden IDs from golden_tuned_overlap.json."""
    p = Path(path)
    if not p.exists():
        return ["tcs-gold-04", "tcs-gold-14", "tcs-gold-16", "tcs-gold-21"]
    data = json.loads(p.read_text(encoding="utf-8"))
    flagged = data.get("flagged_same_fact", [])
    ids = [item["golden"] for item in flagged if isinstance(item, dict) and "golden" in item]
    return sorted(set(ids))


def select_sample_questions(
    answers: list[dict[str, Any]],
    overlap_path: Path | str = DEFAULT_OVERLAP_JSON,
    seed: int = 2026,
    verbose: bool = True,
) -> list[dict[str, Any]]:
    """Select tcs-gold-04 forced as sample 1 plus 7 drawn with random.seed(2026).

    Excludes refusals and the overlap IDs read from app/eval/golden_tuned_overlap.json
    (tcs-gold-04, 14, 16, 21). The result is fully deterministic.
    """
    excluded_ids = load_excluded_overlap_ids(overlap_path)
    if verbose:
        print(f"Excluded overlap IDs (from {overlap_path}): {excluded_ids}")

    answered = [
        a for a in answers
        if not a.get("refused") and a.get("answer") != REFUSAL_STRING
    ]
    answered.sort(key=lambda a: a["question_id"])

    gold_04 = next((a for a in answered if a["question_id"] == "tcs-gold-04"), None)
    if gold_04 is None:
        raise ValueError("tcs-gold-04 not found in answered full_agent questions")

    remaining = [
        a for a in answered
        if a["question_id"] not in excluded_ids
    ]
    k = min(7, len(remaining))
    rng = random.Random(seed)
    sampled_7 = rng.sample(remaining, k)
    return [gold_04] + sampled_7


def compute_mean(scores: list[float | None]) -> tuple[str, int]:
    """Compute mean over non-missing scores only. Returns (formatted_mean, n)."""
    valid = [
        s for s in scores
        if s is not None and not (isinstance(s, float) and (math.isnan(s) ))
    ]
    if not valid:
        return "", 0
    return f"{sum(valid) / len(valid):.4f}", len(valid)


def load_grades_from_sheet(grading_sheet_path: Path | str) -> dict[str, str]:
    """Load grades from grading_sheet.csv for full_agent variant."""
    path = Path(grading_sheet_path)
    if not path.exists():
        return {}
    grades: dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            qid = row.get("question_id", "")
            variant = row.get("variant", "")
            grade = row.get("grade", "")
            if qid and (variant == "full_agent" or qid not in grades):
                grades[qid] = grade
    return grades


def load_existing_pilot_rows(path: Path | str) -> list[dict[str, str]]:
    """Load existing rows from ragas_pilot.csv if present."""
    p = Path(path)
    if not p.exists():
        return []
    with open(p, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def merge_pilot_rows(
    existing_rows: list[dict[str, str]],
    new_rows: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Merge new_rows into existing_rows keyed by question_id.

    Replaces matched question_id rows with the new ones; retains unmatched existing rows.
    """
    row_map = {r["question_id"]: dict(r) for r in existing_rows}
    for r in new_rows:
        row_map[r["question_id"]] = {k: str(v if v is not None else "") for k, v in r.items()}

    seen = set()
    merged: list[dict[str, str]] = []
    # Retain existing ordering where available
    for r in existing_rows:
        qid = r["question_id"]
        if qid not in seen and qid in row_map:
            merged.append(row_map[qid])
            seen.add(qid)
    for r in new_rows:
        qid = r["question_id"]
        if qid not in seen and qid in row_map:
            merged.append(row_map[qid])
            seen.add(qid)
    return merged


def extract_float_scores(rows: list[dict[str, str]], field_name: str) -> list[float]:
    """Extract float scores from row dicts, ignoring empty or non-numeric."""
    scores: list[float] = []
    for r in rows:
        val = r.get(field_name, "")
        if val != "":
            try:
                scores.append(float(val))
            except ValueError:
                pass
    return scores


@dataclass
class RagasCachingLLM(BaseRagasLLM):
    """Bridges Ragas metric evaluation to project CachingLLM."""
    caching_llm: CachingLLM | None = None
    judge_model: str = DEFAULT_JUDGE_MODEL
    planned_requests: int = 0
    cache_misses: int = 0
    raw_history: list[tuple[str, str]] = field(default_factory=list)

    def is_finished(self, response: LLMResult) -> bool:
        return True

    def generate_text(
        self,
        prompt: PromptValue,
        n: int = 1,
        temperature: float | None = None,
        stop: list[str] | None = None,
        callbacks: Any = None,
    ) -> LLMResult:
        prompt_text = prompt.to_string()
        system = "You are an expert evaluation judge. Follow the prompt instructions and output valid JSON."
        self.planned_requests += 1

        if self.caching_llm and self.caching_llm.calls >= MAX_REQUEST_BUDGET:
            raise LLMError(f"Hard budget of {MAX_REQUEST_BUDGET} requests reached")

        try:
            text = self.caching_llm.complete(system=system, prompt=prompt_text)
        except Exception as exc:
            err_msg = str(exc).lower()
            if "no cached answer" in err_msg or isinstance(exc, LLMError):
                self.cache_misses += 1
            raise

        self.raw_history.append((prompt_text, text))
        gen = Generation(text=text, generation_info={"finish_reason": "stop"})
        return LLMResult(generations=[[gen]])

    async def agenerate_text(
        self,
        prompt: PromptValue,
        n: int = 1,
        temperature: float | None = None,
        stop: list[str] | None = None,
        callbacks: Any = None,
    ) -> LLMResult:
        return self.generate_text(prompt, n=n, temperature=temperature, stop=stop, callbacks=callbacks)

    @property
    def total_misses(self) -> int:
        inner_misses = self.caching_llm.misses if self.caching_llm is not None else 0
        return self.cache_misses + inner_misses


def update_eval_results_row(
    eval_results_path: Path | str,
    dataset_version: str,
    n_questions: int,
    judge_model: str,
    generator_model: str,
    faithfulness_scores: list[float | None],
    context_recall_scores: list[float | None],
) -> bool:
    """Update eval_results.csv with ONE row for (ragas_pilot_full_agent, judge_model).

    Replaces an existing row for that pair instead of appending a duplicate.
    Writes ONLY if at least one score exists. Unmeasured fields stay empty (never 0.0).
    Returns True if written/updated, False if skipped.
    """
    avg_f, n_f = compute_mean(faithfulness_scores)
    avg_cr, n_cr = compute_mean(context_recall_scores)

    # Write only if at least one score exists
    if n_f == 0 and n_cr == 0:
        return False

    path = Path(eval_results_path)
    if not path.exists():
        return False

    with open(path, "r", encoding="utf-8") as f:
        existing_lines = [line for line in f if line.strip()]
    if not existing_lines:
        return False

    header = existing_lines[0].strip().split(",")
    rows: list[dict[str, str]] = []
    for line in existing_lines[1:]:
        r = next(csv.DictReader([existing_lines[0], line]))
        rows.append(r)

    run_id = f"run_{hashlib.md5(f'ragas_pilot_{datetime.now(UTC).isoformat()}'.encode()).hexdigest()[:12]}"
    timestamp = datetime.now(UTC).isoformat()
    notes = get_summary_notes(judge_model)

    new_row = {
        "run_id": run_id,
        "run_timestamp": timestamp,
        "pipeline_variant": "ragas_pilot_full_agent",
        "dataset_version": dataset_version,
        "n_questions": str(n_questions),
        "n_unanswerable": "",
        "generator_model": generator_model,
        "judge_model": judge_model,
        "faithfulness": avg_f,
        "answer_relevancy": "",
        "context_precision": "",
        "context_recall": avg_cr,
        "recall_at_5": "",
        "recall_at_10": "",
        "mrr": "",
        "ndcg_at_10": "",
        "unanswerable_refused": "",
        "avg_latency_ms": "",
        "notes": notes,
    }

    # Replace existing row for (ragas_pilot_full_agent, judge_model) or append
    replaced = False
    for i, r in enumerate(rows):
        if r.get("pipeline_variant") == "ragas_pilot_full_agent" and r.get("judge_model") == judge_model:
            rows[i] = new_row
            replaced = True
            break
    if not replaced:
        rows.append(new_row)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
    return True


def run_ragas_pilot(
    expect_hash: str | None = None,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    only: str | None = None,
    limit: int | None = None,
    live: bool = False,
    golden_path: Path | str = "app/eval/golden_questions.json",
    overlap_path: Path | str = DEFAULT_OVERLAP_JSON,
    answers_path: Path | str = "app/eval/results/answers_full_agent.json",
    grading_sheet_path: Path | str = "app/eval/results/grading_sheet.csv",
    cache_path: Path | str | None = None,
    output_path: Path | str = DEFAULT_OUTPUT_CSV,
    eval_results_path: Path | str = DEFAULT_EVAL_RESULTS_CSV,
    chunks: list[Any] | None = None,
    caching_llm: CachingLLM | None = None,
    verbose: bool = True,
) -> int:
    load_dotenv(".env")
    golden_file = Path(golden_path)
    if not golden_file.exists():
        print(f"ERROR: Golden questions file not found: {golden_file}", file=sys.stderr)
        return 1

    current_hash = compute_sha256(golden_file)
    if expect_hash is not None and expect_hash.strip().lower() != current_hash:
        print(
            f"ERROR: Golden file SHA-256 mismatch! Expected {expect_hash.strip().lower()}, got {current_hash}",
            file=sys.stderr,
        )
        return 1

    raw_golden = json.loads(golden_file.read_text(encoding="utf-8"))
    golden_questions = validate_golden_questions(raw_golden)
    golden_map = {q.question_id: q for q in golden_questions}

    answers_file = Path(answers_path)
    if not answers_file.exists():
        print(f"ERROR: Answers file not found: {answers_file}", file=sys.stderr)
        return 1
    answers_data = json.loads(answers_file.read_text(encoding="utf-8"))

    sample_answers = select_sample_questions(
        answers=answers_data,
        overlap_path=overlap_path,
        seed=2026,
        verbose=verbose,
    )

    # Handle --only merge mode
    only_ids: list[str] = []
    if only:
        only_ids = [qid.strip() for qid in only.split(",") if qid.strip()]
        filtered = [a for a in sample_answers if a["question_id"] in only_ids]
        present = {a["question_id"] for a in filtered}
        for qid in only_ids:
            if qid not in present:
                found = next((a for a in answers_data if a["question_id"] == qid), None)
                if found:
                    filtered.append(found)
        sample_answers = filtered

    if limit is not None and limit > 0:
        sample_answers = sample_answers[:limit]

    # Print the sampled IDs and categories BEFORE any request
    mode_label = f"merge mode --only {only}" if only else "random.seed=2026"
    print(f"\nSelected {len(sample_answers)} sample questions for Ragas pilot ({mode_label}):")
    for idx, s in enumerate(sample_answers, 1):
        qid = s["question_id"]
        cat = golden_map[qid].category if qid in golden_map else s.get("category", "unknown")
        print(f"  {idx}. {qid}: {cat}")

    # Set up judge-model-specific cache file and namespace
    namespace = get_judge_cache_namespace(judge_model)
    if cache_path is None:
        cache_file = get_judge_cache_file(judge_model)
    else:
        cache_file = Path(cache_path)
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    if caching_llm is None:
        if live:
            api_key = os.getenv("OPENROUTER_API_KEY")
            if not api_key:
                print("ERROR: OPENROUTER_API_KEY is not set in .env", file=sys.stderr)
                return 1
            from openai import OpenAI
            client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key, max_retries=0)
            inner = OpenRouterLLM(client, [judge_model], retries=1)
        else:
            inner = None

        caching_llm = CachingLLM(
            path=cache_file,
            inner=inner,
            namespace=namespace,
            replay_only=not live,
        )

    ragas_llm = RagasCachingLLM(caching_llm=caching_llm, judge_model=judge_model)
    _run_cfg = RunConfig(max_retries=0, max_wait=0, timeout=30)
    ragas_llm.set_run_config(_run_cfg)
    faithfulness_metric = Faithfulness(llm=ragas_llm)
    context_recall_metric = ContextRecall(llm=ragas_llm)

    # Ingest chunks
    if chunks is None:
        if verbose:
            print("\nLoading document chunks from TCS Annual Report PDF...")
        chunks = load_chunks()
    chunk_map = {c.chunk_id: c.text for c in chunks}

    grades_map = load_grades_from_sheet(grading_sheet_path)

    # Plan: 3 requests per question (2 faithfulness, 1 context_recall)
    planned_requests = len(sample_answers) * 3
    print(f"\nExecution Mode : {'LIVE' if live else 'REPLAY-ONLY (DRY RUN)'}")
    print(f"Judge Model    : {judge_model}")
    print(f"Cache File     : {cache_file}")
    print(f"Namespace      : {namespace}")
    print(f"Ragas Version  : {RAGAS_VERSION}")
    print(f"Planned Calls  : {planned_requests} requests maximum (hard budget: {MAX_REQUEST_BUDGET})")

    results: list[dict[str, Any]] = []
    faithfulness_valid: list[float] = []
    context_recall_valid: list[float] = []
    aborted_reason: str | None = None
    question_raw_responses: dict[str, list[str]] = {}

    for idx, ans in enumerate(sample_answers, 1):
        qid = ans["question_id"]
        category = golden_map[qid].category if qid in golden_map else ans.get("category", "")
        grade = grades_map.get(qid, "")
        citations = ans.get("citations", [])
        contexts_chunk_ids = [c["chunk_id"] for c in citations if isinstance(c, dict) and "chunk_id" in c]
        contexts = [chunk_map[cid] for cid in contexts_chunk_ids if cid in chunk_map]
        user_input = golden_map[qid].question if qid in golden_map else ""
        response = ans.get("answer", "")
        reference = golden_map[qid].reference_answer if qid in golden_map else ""

        start_hist_len = len(ragas_llm.raw_history)

        if verbose:
            print(f"\n[{idx}/{len(sample_answers)}] Evaluating {qid} (contexts: {len(contexts)} chunks)...")

        f_val = ""
        cr_val = ""

        # Faithfulness
        try:
            sample_f = SingleTurnSample(
                user_input=user_input,
                response=response,
                retrieved_contexts=contexts,
            )
            score_f = faithfulness_metric.single_turn_score(sample_f)
            if score_f is not None and not (isinstance(score_f, float) and (math.isnan(score_f) )):
                f_val = f"{score_f:.4f}"
                faithfulness_valid.append(score_f)
            if verbose:
                print(f"  Faithfulness: {f_val if f_val != '' else 'EMPTY'}")
        except Exception as exc:
            err_str = str(exc)
            if verbose:
                print(f"  Faithfulness evaluation failed/skipped: {err_str}")
            # Faithfulness requires two sequential LLM calls (statement generation and verdict scoring).
            # In replay-only dry run, when the first call misses, the second call cannot be evaluated
            # from cache either; count that unreached second stage as a cache miss as well.
            if "no cached answer" in err_str.lower() and not live:
                ragas_llm.cache_misses += 1
            if "rate limit" in err_str.lower() or "all models failed" in err_str.lower():
                aborted_reason = f"Rate limit / model failure: {err_str}"
                break

        # ContextRecall
        try:
            sample_cr = SingleTurnSample(
                user_input=user_input,
                retrieved_contexts=contexts,
                reference=reference,
            )
            score_cr = context_recall_metric.single_turn_score(sample_cr)
            if score_cr is not None and not (isinstance(score_cr, float) and (math.isnan(score_cr) )):
                cr_val = f"{score_cr:.4f}"
                context_recall_valid.append(score_cr)
            if verbose:
                print(f"  ContextRecall: {cr_val if cr_val != '' else 'EMPTY'}")
        except Exception as exc:
            err_str = str(exc)
            if verbose:
                print(f"  ContextRecall evaluation failed/skipped: {err_str}")
            if "rate limit" in err_str.lower() or "all models failed" in err_str.lower():
                aborted_reason = f"Rate limit / model failure: {err_str}"
                break

        results.append({
            "question_id": qid,
            "category": category,
            "grade_from_sheet": grade,
            "faithfulness": f_val,
            "context_recall": cr_val,
            "judge_model": judge_model,
            "ragas_version": RAGAS_VERSION,
            "contexts_chunk_ids": ";".join(contexts_chunk_ids),
        })

        new_entries = ragas_llm.raw_history[start_hist_len:]
        question_raw_responses[qid] = [text for _, text in new_entries]

        if verbose and live:
            print(f"  Live requests made so far: {caching_llm.calls} / {MAX_REQUEST_BUDGET}")
        if live and caching_llm.calls >= MAX_REQUEST_BUDGET:
            aborted_reason = f"Hard budget of {MAX_REQUEST_BUDGET} live requests reached"
            break

    # Print raw cached judge responses for --only questions in live mode
    if live and only_ids:
        print("\n=== RAW JUDGE RESPONSES (--only mode) ===")
        for qid in only_ids:
            responses = question_raw_responses.get(qid, [])
            print(f"\n--- Raw Judge Responses for {qid} ({len(responses)} response(s)) ---")
            if not responses:
                print("  (No judge responses captured for this question)")
            for i, resp in enumerate(responses, 1):
                preview = resp[:1500]
                print(f"[Judge Response {i}] ({len(resp)} chars, showing first {len(preview)}):\n{preview}\n")

    # Load existing rows and merge for --only mode or append
    existing_rows = load_existing_pilot_rows(output_path)
    merged_rows = merge_pilot_rows(existing_rows, results)

    # Recompute means over ALL rows in the merged file
    all_f_scores = extract_float_scores(merged_rows, "faithfulness")
    all_cr_scores = extract_float_scores(merged_rows, "context_recall")
    all_avg_f, all_n_f = compute_mean(all_f_scores)
    all_avg_cr, all_n_cr = compute_mean(all_cr_scores)

    # Check for multiple judge models
    distinct_judges = sorted({r.get("judge_model") for r in merged_rows if r.get("judge_model")})
    has_mixed_judges = len(distinct_judges) > 1

    generator_model = "nvidia/nemotron-3-ultra-550b-a55b:free"

    if live:
        # Write merged ragas_pilot.csv
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "question_id",
            "category",
            "grade_from_sheet",
            "faithfulness",
            "context_recall",
            "judge_model",
            "ragas_version",
            "contexts_chunk_ids",
        ]
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(merged_rows)
        print(f"\nSaved {len(merged_rows)} rows to {output_file}")

        if has_mixed_judges:
            print(
                f"\nWARNING: ragas_pilot.csv contains rows from multiple judge models ({distinct_judges}).\n"
                f"Cannot update eval_results.csv with a single aggregate row for '{judge_model}'. "
                f"Skipping eval_results.csv update."
            )
        else:
            updated = update_eval_results_row(
                eval_results_path=eval_results_path,
                dataset_version=current_hash,
                n_questions=len(merged_rows),
                judge_model=judge_model,
                generator_model=generator_model,
                faithfulness_scores=all_f_scores,
                context_recall_scores=all_cr_scores,
            )
            if updated:
                print(f"Updated pilot summary row in {eval_results_path}")
            else:
                print(f"No scores to write to {eval_results_path}")
    else:
        # Dry Run: print what it would write
        print("\n[DRY RUN] No files written (--live not specified).")
        print(f"[DRY RUN] Would update/write {len(merged_rows)} rows in {output_path}:")
        for r in merged_rows:
            print(
                f"  {r['question_id']} ({r.get('category', '')}): faithfulness={r.get('faithfulness') or 'EMPTY'}, "
                f"context_recall={r.get('context_recall') or 'EMPTY'}, judge={r.get('judge_model')}"
            )
        if has_mixed_judges:
            print(
                f"\n[DRY RUN] WARNING: Mixed judge models detected ({distinct_judges}). "
                f"eval_results.csv would NOT be updated."
            )
        else:
            print(f"[DRY RUN] Would update {eval_results_path}:")
            print(
                f"  pipeline_variant=ragas_pilot_full_agent, judge_model={judge_model}, "
                f"faithfulness={all_avg_f or 'EMPTY'} (n={all_n_f}), context_recall={all_avg_cr or 'EMPTY'} (n={all_n_cr})"
            )

    # Summary
    samples_evaluated = [s for s in results if s["faithfulness"] != "" or s["context_recall"] != ""]
    samples_with_missing = [s for s in results if s["faithfulness"] == "" or s["context_recall"] == ""]
    total_misses = ragas_llm.cache_misses + (caching_llm.misses if caching_llm else 0)

    print("\n=== RAGAS PILOT SUMMARY ===")
    print(f"Run mode                   : {'--only ' + only if only else 'all sampled'}")
    print(f"Run samples evaluated      : {len(samples_evaluated)} / {len(sample_answers)}")
    print(f"Run samples missing score  : {len(samples_with_missing)} / {len(sample_answers)}")
    print(f"Total file faithfulness    : {all_avg_f if all_avg_f else 'EMPTY'} (n={all_n_f})")
    print(f"Total file context_recall  : {all_avg_cr if all_avg_cr else 'EMPTY'} (n={all_n_cr})")
    print(f"Cache hits                 : {caching_llm.hits}")
    print(f"Cache misses               : {total_misses}")
    print(f"Live requests made         : {caching_llm.calls if live else 0}")
    print(f"Planned requests           : {planned_requests}")

    if aborted_reason:
        print(f"\nABORTED CLEANLY: {aborted_reason}", file=sys.stderr)
        return 1

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Ragas pilot evaluation on full_agent answers.")
    parser.add_argument("--expect-hash", type=str, default=None, help="Expected golden file SHA-256 hash")
    parser.add_argument("--judge-model", type=str, default=DEFAULT_JUDGE_MODEL, help="Judge model identifier")
    parser.add_argument("--only", type=str, default=None, help="Comma-separated question IDs to evaluate in merge mode")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of sample questions")
    parser.add_argument("--live", action="store_true", help="Enable live model calls (default is replay-only)")
    parser.add_argument("--golden-file", type=str, default="app/eval/golden_questions.json")
    parser.add_argument("--overlap-file", type=str, default=str(DEFAULT_OVERLAP_JSON))
    parser.add_argument("--answers-file", type=str, default="app/eval/results/answers_full_agent.json")
    parser.add_argument("--grading-sheet", type=str, default="app/eval/results/grading_sheet.csv")
    parser.add_argument("--cache-file", type=str, default=None, help="Explicit cache file path (defaults to model-specific path)")
    parser.add_argument("--output", type=str, default=str(DEFAULT_OUTPUT_CSV))
    parser.add_argument("--eval-results", type=str, default=str(DEFAULT_EVAL_RESULTS_CSV))

    args = parser.parse_args(argv)
    return run_ragas_pilot(
        expect_hash=args.expect_hash,
        judge_model=args.judge_model,
        only=args.only,
        limit=args.limit,
        live=args.live,
        golden_path=args.golden_file,
        overlap_path=args.overlap_file,
        answers_path=args.answers_file,
        grading_sheet_path=args.grading_sheet,
        cache_path=args.cache_file,
        output_path=args.output,
        eval_results_path=args.eval_results,
    )


if __name__ == "__main__":
    sys.exit(main())
