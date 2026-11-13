"""Evaluation gate for CI and release checks.

Runs retrieval evaluation on the independent subset of golden questions (n=21)
using the shipped dense retrieval pipeline, compares against committed baseline metrics,
and fails if any key metric drops more than tolerance below baseline or if the golden
file hash mismatches.

Replay / offline execution only: 0 live model calls, fits within free quotas.
If app/eval/results/answers_full_agent.json exists in the repo it is NOT used (git-ignored).
No answer-based check added yet.
"""

import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path
from statistics import mean
from typing import Any

from app.eval.golden_schema import validate_golden_questions
from app.eval.validate_golden import load_chunks
from app.retrieval.factory import EMBEDDING_MODEL, build_default_retriever
from app.schemas.retrieval import RetrievalRequest
from scripts.run_retrieval_eval import compute_sha256, get_fact_phrases, score_retrieval

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Tolerance default 0.02 (a guess: retrieval is deterministic for a fixed model, so it can be small; say so in a comment).
DEFAULT_TOLERANCE = 0.02


def get_git_commit_hash() -> str:
    """Return the current HEAD commit hash, or 'unknown' if git is not available."""
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
        return out.decode("utf-8").strip()
    except Exception:
        return "unknown"


def compare_metrics(
    measured: dict[str, float],
    baseline: dict[str, float],
    tolerance: float = DEFAULT_TOLERANCE,
) -> tuple[bool, list[str]]:
    """Compare measured metrics against baseline.

    FAILS if any of recall_at_5, recall_at_10, or mrr drops by more than tolerance below baseline.
    # Tolerance default 0.02 (a guess: retrieval is deterministic for a fixed model, so it can be small; say so in a comment).
    """
    passed = True
    details: list[str] = []
    # Metrics to evaluate
    metric_keys = ["recall_at_5", "recall_at_10", "mrr"]
    for key in metric_keys:
        b_val = float(baseline.get(key, 0.0))
        m_val = float(measured.get(key, 0.0))
        drop = b_val - m_val
        if drop > tolerance:
            passed = False
            details.append(
                f"FAIL: {key} dropped by {drop:.4f} > tolerance {tolerance:.4f} "
                f"(baseline={b_val:.4f}, measured={m_val:.4f})"
            )
        else:
            diff_str = f"-{abs(drop):.4f}" if drop > 0 else f"+{abs(drop):.4f}"
            details.append(
                f"PASS: {key} baseline={b_val:.4f}, measured={m_val:.4f} "
                f"(diff={diff_str}, tolerance={tolerance:.4f})"
            )
    return passed, details


def run_eval_gate(
    golden_path: Path | str = "app/eval/golden_questions.json",
    overlap_path: Path | str = "app/eval/golden_tuned_overlap.json",
    baseline_path: Path | str = "app/eval/gate_baseline.json",
    expect_hash: str | None = None,
    tolerance: float = DEFAULT_TOLERANCE,
    simulate_drop: float = 0.0,
    write_baseline: bool = False,
    retriever: Any = None,
    verbose: bool = True,
) -> int:
    golden_file = Path(golden_path)
    if not golden_file.exists():
        print(f"ERROR: Golden questions file not found: {golden_file}", file=sys.stderr)
        return 1

    current_hash = compute_sha256(golden_file)
    if verbose:
        print(f"Golden questions file : {golden_file}")
        print(f"Golden file SHA-256    : {current_hash}")

    if expect_hash is not None and expect_hash.strip().lower() != current_hash:
        print(
            f"ERROR: Hash mismatch! Expected {expect_hash.strip().lower()}, got {current_hash}",
            file=sys.stderr,
        )
        return 1

    baseline_file = Path(baseline_path)
    baseline_data: dict[str, Any] = {}
    if not write_baseline:
        if not baseline_file.exists():
            print(f"ERROR: Baseline file not found: {baseline_file}", file=sys.stderr)
            return 1
        try:
            baseline_data = json.loads(baseline_file.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"ERROR: Failed to parse baseline file '{baseline_file}': {exc}", file=sys.stderr)
            return 1

        stored_hash = baseline_data.get("golden_hash", "").strip().lower()
        if stored_hash != current_hash:
            print(
                f"ERROR: Golden file hash mismatch with baseline! Baseline has {stored_hash}, current is {current_hash}",
                file=sys.stderr,
            )
            return 1

    # Load and validate questions
    raw_questions = json.loads(golden_file.read_text(encoding="utf-8"))
    questions = validate_golden_questions(raw_questions)

    overlap_file = Path(overlap_path)
    flagged_same_fact: set[str] = set()
    if overlap_file.exists():
        try:
            ov_data = json.loads(overlap_file.read_text(encoding="utf-8"))
            flagged_same_fact = {
                item["golden"] for item in ov_data.get("flagged_same_fact", []) if "golden" in item
            }
        except Exception as exc:
            if verbose:
                print(f"Warning: Could not parse overlap file: {exc}")

    # Filter independent answerable questions
    indep_questions = [
        q for q in questions if q.category != "unanswerable" and q.question_id not in flagged_same_fact
    ]
    if verbose:
        print(f"Evaluating {len(indep_questions)} independent answerable questions...")

    # Build dense retriever if not provided
    if retriever is None:
        start_load = time.perf_counter()
        if verbose:
            print("Loading document chunks and embedding model...")
        chunks = load_chunks()
        retriever = build_default_retriever(collection_name=f"eval_gate_{uuid.uuid4().hex}")
        retriever.index_chunks(chunks)
        retriever.retrieve(RetrievalRequest(query="warm up", top_k=20))
        load_time = time.perf_counter() - start_load
        if verbose:
            print(f"Retriever initialized in {load_time:.2f}s.")

    # Evaluate questions
    records: list[dict[str, Any]] = []
    start_eval = time.perf_counter()
    for q in indep_questions:
        fact_phrases = get_fact_phrases(q)
        resp = retriever.retrieve(RetrievalRequest(query=q.question, top_k=20))
        scores = score_retrieval(fact_phrases, resp.results)
        records.append({
            "question_id": q.question_id,
            "recall_at_5": scores["recall@5"],
            "recall_at_10": scores["recall@10"],
            "mrr": scores["mrr"],
        })
    eval_time = time.perf_counter() - start_eval
    if verbose:
        print(f"Evaluated {len(records)} questions in {eval_time:.2f}s.")

    measured = {
        "recall_at_5": round(mean([r["recall_at_5"] for r in records]), 4),
        "recall_at_10": round(mean([r["recall_at_10"] for r in records]), 4),
        "mrr": round(mean([r["mrr"] for r in records]), 4),
    }

    if simulate_drop != 0.0:
        if verbose:
            print(f"Simulating metric drop: -{simulate_drop:.4f}")
        for k in measured:
            measured[k] = round(measured[k] - simulate_drop, 4)

    if write_baseline:
        commit_hash = get_git_commit_hash()
        baseline_record = {
            "golden_hash": current_hash,
            "pipeline_variant": "retrieval_dense",
            "model_names": {
                "embedding_model": EMBEDDING_MODEL,
                "reranker_model": None,
            },
            "embedding_model": EMBEDDING_MODEL,
            "reranker_model": None,
            "subset": "independent",
            "n": len(records),
            "recall_at_5": measured["recall_at_5"],
            "recall_at_10": measured["recall_at_10"],
            "mrr": measured["mrr"],
            "metrics": {
                "recall_at_5": measured["recall_at_5"],
                "recall_at_10": measured["recall_at_10"],
                "mrr": measured["mrr"],
            },
            "tolerance": tolerance,
            "note": f"baseline from commit {commit_hash}",
        }
        baseline_file.parent.mkdir(parents=True, exist_ok=True)
        baseline_file.write_text(json.dumps(baseline_record, indent=2), encoding="utf-8")
        print(f"Baseline successfully written to: {baseline_file}")
        print(json.dumps(baseline_record, indent=2))
        return 0

    # Extract baseline metrics
    baseline_metrics = baseline_data.get("metrics") or {
        "recall_at_5": baseline_data.get("recall_at_5", 0.0),
        "recall_at_10": baseline_data.get("recall_at_10", 0.0),
        "mrr": baseline_data.get("mrr", 0.0),
    }

    passed, details = compare_metrics(measured, baseline_metrics, tolerance=tolerance)
    if verbose:
        print("\n=== EVALUATION GATE RESULTS ===")
        print(f"Baseline note: {baseline_data.get('note', 'none')}")
        print(f"Subset       : independent (n={len(records)})")
        print(f"Tolerance    : {tolerance:.4f}")
        for line in details:
            print(f"  {line}")

    if not passed:
        print("\nGATE STATUS: FAILED (one or more metrics dropped below tolerance)", file=sys.stderr)
        return 1

    print("\nGATE STATUS: PASSED")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluation gate checking retrieval metrics against baseline.")
    parser.add_argument("--expect-hash", type=str, default=None, help="Expected golden file SHA-256 hash")
    parser.add_argument("--golden-file", type=str, default="app/eval/golden_questions.json", help="Path to golden questions JSON")
    parser.add_argument("--overlap-file", type=str, default="app/eval/golden_tuned_overlap.json", help="Path to overlap JSON")
    parser.add_argument("--baseline-file", type=str, default="app/eval/gate_baseline.json", help="Path to gate baseline JSON")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE, help="Allowed metric drop tolerance")
    parser.add_argument("--simulate-drop", type=float, default=0.0, help="Simulate a drop in metrics for testing gate failure")
    parser.add_argument("--write-baseline", action="store_true", help="Write measured metrics as new baseline file")

    args = parser.parse_args(argv)
    return run_eval_gate(
        golden_path=args.golden_file,
        overlap_path=args.overlap_file,
        baseline_path=args.baseline_file,
        expect_hash=args.expect_hash,
        tolerance=args.tolerance,
        simulate_drop=args.simulate_drop,
        write_baseline=args.write_baseline,
    )


if __name__ == "__main__":
    sys.exit(main())
