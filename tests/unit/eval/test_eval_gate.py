"""Unit tests for scripts/eval_gate.py.

Tests:
1. the gate passes on identical metrics
2. fails when a metric drops more than the tolerance (use synthetic numbers, no model)
3. passes when a metric drops less than the tolerance
4. fails on a hash mismatch
"""

import json
from pathlib import Path

import pytest

from scripts.eval_gate import (
    DEFAULT_TOLERANCE,
    compare_metrics,
    compute_sha256,
    run_eval_gate,
)
from tests.unit.agents.mocks import MockRetriever, make_chunk


def make_sample_question(qid: str, is_unans: bool = False) -> dict:
    return {
        "question_id": qid,
        "question": f"Sample question text for {qid}?",
        "category": "unanswerable" if is_unans else "fact_lookup",
        "style": "exact",
        "evidence": [] if is_unans else ["Sample evidence phrase"],
        "alt_evidence": [],
        "reference_answer": "" if is_unans else "Sample answer",
    }


def test_gate_passes_on_identical_metrics():
    """Gate passes when measured metrics are identical to baseline."""
    baseline = {"recall_at_5": 0.5635, "recall_at_10": 0.6667, "mrr": 0.4321}
    measured = {"recall_at_5": 0.5635, "recall_at_10": 0.6667, "mrr": 0.4321}

    passed, details = compare_metrics(measured, baseline, tolerance=0.02)
    assert passed is True
    assert all("PASS" in d for d in details)


def test_gate_fails_when_metric_drops_more_than_tolerance():
    """Gate fails when any metric drops more than tolerance below baseline."""
    baseline = {"recall_at_5": 0.5635, "recall_at_10": 0.6667, "mrr": 0.4321}

    # Case 1: recall_at_5 drops by 0.05 (> tolerance 0.02)
    measured_r5_drop = {"recall_at_5": 0.5100, "recall_at_10": 0.6667, "mrr": 0.4321}
    passed_r5, details_r5 = compare_metrics(measured_r5_drop, baseline, tolerance=0.02)
    assert passed_r5 is False
    assert any("FAIL: recall_at_5 dropped" in d for d in details_r5)

    # Case 2: recall_at_10 drops by 0.03 (> tolerance 0.02)
    measured_r10_drop = {"recall_at_5": 0.5635, "recall_at_10": 0.6300, "mrr": 0.4321}
    passed_r10, details_r10 = compare_metrics(measured_r10_drop, baseline, tolerance=0.02)
    assert passed_r10 is False
    assert any("FAIL: recall_at_10 dropped" in d for d in details_r10)

    # Case 3: mrr drops by 0.04 (> tolerance 0.02)
    measured_mrr_drop = {"recall_at_5": 0.5635, "recall_at_10": 0.6667, "mrr": 0.3900}
    passed_mrr, details_mrr = compare_metrics(measured_mrr_drop, baseline, tolerance=0.02)
    assert passed_mrr is False
    assert any("FAIL: mrr dropped" in d for d in details_mrr)


def test_gate_passes_when_metric_drops_less_than_tolerance():
    """Gate passes when a metric drops less than or equal to tolerance."""
    baseline = {"recall_at_5": 0.5635, "recall_at_10": 0.6667, "mrr": 0.4321}
    # Drop of 0.01 on all metrics (<= tolerance 0.02)
    measured = {"recall_at_5": 0.5535, "recall_at_10": 0.6567, "mrr": 0.4221}

    passed, details = compare_metrics(measured, baseline, tolerance=0.02)
    assert passed is True
    assert all("PASS" in d for d in details)


def test_gate_fails_on_hash_mismatch(tmp_path: Path):
    """Gate fails immediately if golden file hash does not match baseline."""
    q_file = tmp_path / "golden_questions.json"
    q_file.write_text(json.dumps([make_sample_question("tcs-gold-01")]), encoding="utf-8")

    baseline_file = tmp_path / "gate_baseline.json"
    baseline_content = {
        "golden_hash": "mismatched_hash_00000000000000000000000000000000",
        "pipeline_variant": "retrieval_dense",
        "model_names": {"embedding_model": "BAAI/bge-small-en-v1.5", "reranker_model": None},
        "subset": "independent",
        "n": 1,
        "recall_at_5": 1.0,
        "recall_at_10": 1.0,
        "mrr": 1.0,
        "metrics": {"recall_at_5": 1.0, "recall_at_10": 1.0, "mrr": 1.0},
        "tolerance": 0.02,
        "note": "synthetic baseline",
    }
    baseline_file.write_text(json.dumps(baseline_content), encoding="utf-8")

    mock_ret = MockRetriever(default=[make_chunk("c1", text="Sample evidence phrase")])

    exit_code = run_eval_gate(
        golden_path=q_file,
        overlap_path=tmp_path / "empty_overlap.json",
        baseline_path=baseline_file,
        retriever=mock_ret,
        verbose=False,
    )
    assert exit_code == 1
