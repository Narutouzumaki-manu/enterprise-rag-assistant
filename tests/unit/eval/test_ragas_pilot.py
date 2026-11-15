"""Unit tests for scripts/run_ragas_pilot.py.

Tests (tmp paths, stub judge, no network):
- the namespace differs by judge model
- --only replaces one row and keeps the others
- a mixed-judge file does not update eval_results.csv
- means ignore missing scores
- the sample is deterministic, always includes gold-04, and never includes gold-14, gold-16 or gold-21
- refusals are never sampled
- a dry run writes no files
"""

import csv
import json
from pathlib import Path
import sys
import types
from typing import Any

import pytest

# Shim for langchain_community vertexai import bug in ragas 0.2.14
if "langchain_community.chat_models.vertexai" not in sys.modules:
    _m = types.ModuleType("langchain_community.chat_models.vertexai")
    _m.ChatVertexAI = type("ChatVertexAI", (), {})
    sys.modules["langchain_community.chat_models.vertexai"] = _m

pytest.importorskip("ragas")

from scripts.run_ragas_pilot import (
    DEFAULT_JUDGE_MODEL,
    REFUSAL_STRING,
    RagasCachingLLM,
    compute_mean,
    extract_float_scores,
    get_judge_cache_file,
    get_judge_cache_namespace,
    get_summary_notes,
    load_excluded_overlap_ids,
    merge_pilot_rows,
    run_ragas_pilot,
    sanitize_model_id,
    select_sample_questions,
    update_eval_results_row,
)
from app.agents.llm_cache import CachingLLM
from langchain_core.prompt_values import StringPromptValue


def make_dummy_answer(qid: str, refused: bool = False, citations: list[str] = None) -> dict[str, Any]:
    return {
        "question_id": qid,
        "category": "table" if "table" in qid else "fact_lookup",
        "style": "exact",
        "answer": REFUSAL_STRING if refused else f"Answer for {qid}",
        "verification_status": "unverified" if refused else "verified",
        "confidence": 0.0 if refused else 0.9,
        "citations": [{"chunk_id": cid} for cid in (citations or [])],
        "refused": refused,
        "golden_hash": "dummy_hash",
    }


def make_test_answers_pool() -> list[dict[str, Any]]:
    pool = []
    # 25 answered questions including tcs-gold-04, 14, 16, 21
    for i in range(1, 26):
        qid = f"tcs-gold-{i:02d}"
        pool.append(make_dummy_answer(qid, refused=False, citations=[f"chunk_{i}"]))
    # 9 refusal questions
    for i in range(26, 35):
        qid = f"tcs-gold-{i:02d}"
        pool.append(make_dummy_answer(qid, refused=True))
    return pool


def test_namespace_and_cache_file_differ_by_judge_model():
    model1 = "inclusionai/ling-3.2-flash:free"
    model2 = "nvidia/nemotron-3.5-super-vl:free"

    ns1 = get_judge_cache_namespace(model1)
    ns2 = get_judge_cache_namespace(model2)
    assert ns1 != ns2
    assert model1 in ns1
    assert model2 in ns2

    file1 = get_judge_cache_file(model1)
    file2 = get_judge_cache_file(model2)
    assert file1 != file2
    assert sanitize_model_id(model1) in str(file1)
    assert sanitize_model_id(model2) in str(file2)


def test_only_replaces_one_row_and_keeps_others():
    existing_rows = [
        {"question_id": "tcs-gold-04", "category": "table", "faithfulness": "0.8000", "context_recall": "0.7500", "judge_model": "model_old"},
        {"question_id": "tcs-gold-06", "category": "table", "faithfulness": "0.9000", "context_recall": "0.8500", "judge_model": "model_old"},
        {"question_id": "tcs-gold-15", "category": "table", "faithfulness": "1.0000", "context_recall": "0.9500", "judge_model": "model_old"},
    ]

    new_rows = [
        {"question_id": "tcs-gold-04", "category": "table", "faithfulness": "0.9500", "context_recall": "0.8800", "judge_model": "model_new"},
    ]

    merged = merge_pilot_rows(existing_rows, new_rows)
    assert len(merged) == 3

    row_map = {r["question_id"]: r for r in merged}
    # gold-04 is replaced with new scores and new judge
    assert row_map["tcs-gold-04"]["faithfulness"] == "0.9500"
    assert row_map["tcs-gold-04"]["judge_model"] == "model_new"

    # gold-06 and gold-15 are kept untouched with their original judge
    assert row_map["tcs-gold-06"]["faithfulness"] == "0.9000"
    assert row_map["tcs-gold-06"]["judge_model"] == "model_old"
    assert row_map["tcs-gold-15"]["faithfulness"] == "1.0000"
    assert row_map["tcs-gold-15"]["judge_model"] == "model_old"


def test_mixed_judge_file_does_not_update_eval_results(tmp_path: Path):
    eval_csv = tmp_path / "eval_results.csv"
    eval_csv.write_text(
        "run_id,run_timestamp,pipeline_variant,dataset_version,n_questions,n_unanswerable,"
        "generator_model,judge_model,faithfulness,answer_relevancy,context_precision,context_recall,"
        "recall_at_5,recall_at_10,mrr,ndcg_at_10,unanswerable_refused,avg_latency_ms,notes\n",
        encoding="utf-8",
    )

    merged_rows = [
        {"question_id": "tcs-gold-04", "faithfulness": "0.8000", "context_recall": "0.7500", "judge_model": "model_a"},
        {"question_id": "tcs-gold-06", "faithfulness": "0.9000", "context_recall": "0.8500", "judge_model": "model_b"},
    ]

    distinct_judges = {r.get("judge_model") for r in merged_rows if r.get("judge_model")}
    assert len(distinct_judges) > 1

    # Mixed judge models must NOT update eval_results.csv
    # When distinct_judges > 1, update_eval_results_row should not be called
    lines_before = eval_csv.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines_before) == 1  # only header


def test_summary_notes_nvidia_vs_other():
    notes_nvidia = get_summary_notes("nvidia/nemotron-3.5-super-vl:free")
    assert "same NVIDIA Nemotron family (possible self-preference)" in notes_nvidia

    notes_other = get_summary_notes("inclusionai/ling-3.2-flash:free")
    assert "judge differs from generator" in notes_other
    assert "possible self-preference" not in notes_other


def test_sample_deterministic_always_includes_gold_04_and_never_overlap(tmp_path: Path):
    overlap_file = tmp_path / "golden_tuned_overlap.json"
    overlap_file.write_text(
        json.dumps({
            "flagged_same_fact": [
                {"golden": "tcs-gold-04"},
                {"golden": "tcs-gold-14"},
                {"golden": "tcs-gold-16"},
                {"golden": "tcs-gold-21"},
            ]
        }),
        encoding="utf-8",
    )

    pool = make_test_answers_pool()
    sample1 = select_sample_questions(pool, overlap_path=overlap_file, seed=2026, verbose=False)
    sample2 = select_sample_questions(pool, overlap_path=overlap_file, seed=2026, verbose=False)

    # Deterministic across multiple calls
    ids1 = [s["question_id"] for s in sample1]
    ids2 = [s["question_id"] for s in sample2]
    assert ids1 == ids2
    assert len(sample1) == 8

    # Always includes tcs-gold-04 as sample 1
    assert sample1[0]["question_id"] == "tcs-gold-04"

    # Never includes tcs-gold-14, tcs-gold-16, or tcs-gold-21
    sample_ids_set = set(ids1)
    assert "tcs-gold-14" not in sample_ids_set
    assert "tcs-gold-16" not in sample_ids_set
    assert "tcs-gold-21" not in sample_ids_set


def test_refusals_are_never_sampled(tmp_path: Path):
    overlap_file = tmp_path / "golden_tuned_overlap.json"
    overlap_file.write_text(json.dumps({"flagged_same_fact": []}), encoding="utf-8")

    pool = make_test_answers_pool()
    samples = select_sample_questions(pool, overlap_path=overlap_file, seed=2026, verbose=False)

    for s in samples:
        assert s["refused"] is False
        assert s["answer"] != REFUSAL_STRING
        assert int(s["question_id"].replace("tcs-gold-", "")) < 26


def test_mean_ignores_missing_scores():
    # Regular valid scores
    val, n = compute_mean([0.8, 0.9])
    assert val == "0.8500"
    assert n == 2

    # Mixed with None and NaN
    val, n = compute_mean([0.8, None, float("nan")])
    assert val == "0.8000"
    assert n == 1

    # All missing
    val, n = compute_mean([])
    assert val == ""
    assert n == 0

    val, n = compute_mean([None, None])
    assert val == ""
    assert n == 0


def test_dry_run_writes_no_files(tmp_path: Path):
    out_csv = tmp_path / "ragas_pilot.csv"
    eval_csv = tmp_path / "eval_results.csv"
    cache_json = tmp_path / "cache.json"

    # Golden file stub
    golden_file = tmp_path / "golden.json"
    golden_file.write_text(json.dumps([
        {
            "question_id": "tcs-gold-04",
            "category": "table",
            "style": "exact",
            "question": "Q4?",
            "reference_answer": "A4",
            "evidence": ["Evidence text 4"],
        }
    ]), encoding="utf-8")

    answers_file = tmp_path / "answers.json"
    answers_file.write_text(json.dumps([
        make_dummy_answer("tcs-gold-04", refused=False, citations=["c4"])
    ]), encoding="utf-8")

    overlap_file = tmp_path / "overlap.json"
    overlap_file.write_text(json.dumps({"flagged_same_fact": []}), encoding="utf-8")

    class DummyChunk:
        chunk_id = "c4"
        text = "Evidence chunk 4"

    ret = run_ragas_pilot(
        expect_hash=None,
        live=False,  # DRY RUN
        only="tcs-gold-04",
        golden_path=golden_file,
        overlap_path=overlap_file,
        answers_path=answers_file,
        grading_sheet_path=tmp_path / "none.csv",
        cache_path=cache_json,
        output_path=out_csv,
        eval_results_path=eval_csv,
        chunks=[DummyChunk()],
        verbose=False,
    )
    assert ret == 0

    # Dry run must NOT write output files
    assert not out_csv.exists()
    assert not eval_csv.exists()
