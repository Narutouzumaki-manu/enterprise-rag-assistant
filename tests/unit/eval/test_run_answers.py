"""Unit tests for scripts/run_answers.py.

Tests:
1. hash abort: mismatched --expect-hash returns code 1
2. replay-only reports misses: without --live, cache misses are reported and 0 requests made
3. --limit: stops after N questions
4. resume merges without duplicating: merging into existing results file prevents duplicate question_ids
5. skipped no-checker variant: prints "SKIPPED: switch not available" and exits 0 when switch is absent
6. refused flag: true if refusal text matches exact prompt string, false otherwise
"""

import json
from pathlib import Path
from unittest.mock import patch
import pytest

from app.agents.fact_checker import ClaimVerdict, Verification
from app.agents.planner import Plan
from app.agents.synthesizer import NO_EVIDENCE_ANSWER, Draft
from app.eval.golden_schema import GoldenQuestion
from scripts.run_answers import (
    REFUSAL_STRING,
    compute_sha256,
    get_cache_namespace,
    main as run_answers_main,
    run_answers,
)
from tests.unit.agents.mocks import MockLLM, MockRetriever, make_chunk


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


def make_clean_mock_llm(copies: int = 10, answer: str = "TCS reported revenue of $30 billion."):
    plan = Plan(query_type="simple", subqueries=["Sample query"])
    draft = Draft(answer=answer, cited_chunk_ids=["c1"], answer_found=True)
    verdict = ClaimVerdict(claim=answer, supported=True, supporting_chunk_ids=["c1"])
    verification = Verification(verdicts=[verdict])

    return MockLLM(
        structured={
            Plan: [plan] * copies,
            Draft: [draft] * copies,
            Verification: [verification] * copies,
        }
    )


def test_hash_abort(tmp_path: Path):
    """Hash abort: run_answers exits with code 1 when --expect-hash differs."""
    q_file = tmp_path / "golden_questions.json"
    q_file.write_text(json.dumps([make_sample_question("tcs-gold-01")]), encoding="utf-8")
    actual_hash = compute_sha256(q_file)

    exit_code = run_answers_main([
        "--expect-hash",
        "wrong_hash_00000000000000000000000000000000",
        "--golden-file",
        str(q_file),
    ])
    assert exit_code == 1


def test_replay_only_reports_misses(tmp_path: Path):
    """Replay-only mode: without --live, an empty cache reports a cache miss, makes 0 requests, and records the error."""
    q_file = tmp_path / "golden_questions.json"
    q_data = [make_sample_question("tcs-gold-01")]
    q_file.write_text(json.dumps(q_data), encoding="utf-8")
    h = compute_sha256(q_file)

    out_dir = tmp_path / "results"
    cache_path = tmp_path / "empty_cache.json"
    cache_path.write_text("{}", encoding="utf-8")

    mock_ret = MockRetriever(default=[make_chunk("c1", text="Sample evidence phrase")])

    exit_code = run_answers(
        expect_hash=h,
        variant="full_agent",
        golden_file=q_file,
        output_dir=out_dir,
        cache_path=cache_path,
        live=False,
        retriever=mock_ret,
        verbose=False,
    )
    assert exit_code == 0

    results_file = out_dir / "answers_full_agent.json"
    assert results_file.exists()
    records = json.loads(results_file.read_text(encoding="utf-8"))
    assert len(records) == 1

    rec = records[0]
    assert rec["question_id"] == "tcs-gold-01"
    assert rec["error"] is not None
    assert "replay-only mode" in rec["error"] or "no cached answer" in rec["error"].lower()
    assert rec["llm_calls"] == 2


def test_limit(tmp_path: Path):
    """--limit N stops after N questions."""
    q_file = tmp_path / "golden_questions.json"
    q_data = [
        make_sample_question("tcs-gold-01"),
        make_sample_question("tcs-gold-02"),
        make_sample_question("tcs-gold-03"),
        make_sample_question("tcs-gold-04"),
    ]
    q_file.write_text(json.dumps(q_data), encoding="utf-8")
    h = compute_sha256(q_file)

    out_dir = tmp_path / "results"
    mock_ret = MockRetriever(default=[make_chunk("c1")])
    mock_llm = make_clean_mock_llm(copies=10)

    exit_code = run_answers(
        expect_hash=h,
        variant="full_agent",
        golden_file=q_file,
        output_dir=out_dir,
        limit=2,
        retriever=mock_ret,
        llm=mock_llm,
        verbose=False,
    )
    assert exit_code == 0

    results_file = out_dir / "answers_full_agent.json"
    records = json.loads(results_file.read_text(encoding="utf-8"))
    assert len(records) == 2
    assert [r["question_id"] for r in records] == ["tcs-gold-01", "tcs-gold-02"]


def test_resume_merges_without_duplicating(tmp_path: Path):
    """Resume merges new questions into existing results without duplicate entries."""
    out_dir = tmp_path / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "answers_full_agent.json"

    # Pre-seed existing result for question 1
    initial_record = {
        "question_id": "tcs-gold-01",
        "category": "fact_lookup",
        "style": "exact",
        "answer": "Initial pre-existing answer",
        "verification_status": "verified",
        "confidence": 0.9,
        "citations": [],
        "trace": {"counts": {"plan": 1}, "labels": ["plan"]},
        "llm_calls": 1,
        "latency_ms": 100.0,
        "refused": False,
        "error": None,
        "golden_hash": "samplehash",
    }
    out_file.write_text(json.dumps([initial_record]), encoding="utf-8")

    q_file = tmp_path / "golden_questions.json"
    q_data = [
        make_sample_question("tcs-gold-01"),
        make_sample_question("tcs-gold-02"),
    ]
    q_file.write_text(json.dumps(q_data), encoding="utf-8")
    h = compute_sha256(q_file)

    mock_ret = MockRetriever(default=[make_chunk("c1")])
    mock_llm = make_clean_mock_llm(copies=10)

    # Run only question 2 with resume
    exit_code = run_answers(
        expect_hash=h,
        variant="full_agent",
        golden_file=q_file,
        output_dir=out_dir,
        questions=["tcs-gold-02"],
        resume=True,
        retriever=mock_ret,
        llm=mock_llm,
        verbose=False,
    )
    assert exit_code == 0

    records = json.loads(out_file.read_text(encoding="utf-8"))
    assert len(records) == 2
    ids = [r["question_id"] for r in records]
    assert ids == ["tcs-gold-01", "tcs-gold-02"]

    # Run question 1 again; it should update/merge without duplicating
    mock_llm_q1 = make_clean_mock_llm(copies=5, answer="Updated answer for q1")
    exit_code2 = run_answers(
        expect_hash=h,
        variant="full_agent",
        golden_file=q_file,
        output_dir=out_dir,
        questions=["tcs-gold-01"],
        resume=False,
        retriever=mock_ret,
        llm=mock_llm_q1,
        verbose=False,
    )
    assert exit_code2 == 0

    records2 = json.loads(out_file.read_text(encoding="utf-8"))
    assert len(records2) == 2
    assert [r["question_id"] for r in records2] == ["tcs-gold-01", "tcs-gold-02"]
    q1_rec = next(r for r in records2 if r["question_id"] == "tcs-gold-01")
    assert q1_rec["answer"] == "Updated answer for q1"


def test_skipped_no_checker_variant(tmp_path: Path, capsys):
    """agent_no_checker prints 'SKIPPED: switch not available' and exits 0 when switch is not available."""
    q_file = tmp_path / "golden_questions.json"
    q_file.write_text(json.dumps([make_sample_question("tcs-gold-01")]), encoding="utf-8")
    h = compute_sha256(q_file)

    with patch("dataclasses.fields", return_value=[]):
        exit_code = run_answers_main([
            "--expect-hash",
            h,
            "--golden-file",
            str(q_file),
            "--output-dir",
            str(tmp_path / "results"),
            "--variant",
            "agent_no_checker",
        ])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "SKIPPED: switch not available" in captured.out


def test_refused_flag(tmp_path: Path):
    """Refused flag is True when answer equals exact refusal text, False otherwise."""
    q_file = tmp_path / "golden_questions.json"
    q_data = [
        make_sample_question("tcs-gold-01", is_unans=True),
        make_sample_question("tcs-gold-02", is_unans=False),
    ]
    q_file.write_text(json.dumps(q_data), encoding="utf-8")
    h = compute_sha256(q_file)

    out_dir = tmp_path / "results"
    mock_ret = MockRetriever(
        responses={
            "Sample question text for tcs-gold-02?": [make_chunk("c1", text="TCS revenue was $30 billion.")],
            "q2": [make_chunk("c1", text="TCS revenue was $30 billion.")],
        },
        default=[],
    )

    # For q1: planner runs, retriever returns empty chunks -> direct refusal
    plan_refuse = Plan(query_type="simple", subqueries=["q1"])

    # For q2: normal answer
    plan_ans = Plan(query_type="simple", subqueries=["q2"])
    draft_ans = Draft(answer="TCS revenue was $30 billion.", cited_chunk_ids=["c1"], answer_found=True)
    verdict_ans = ClaimVerdict(claim="TCS revenue was $30 billion.", supported=True, supporting_chunk_ids=["c1"])
    ver_ans = Verification(verdicts=[verdict_ans])

    mock_llm = MockLLM(
        structured={
            Plan: [plan_refuse, plan_ans],
            Draft: [draft_ans],
            Verification: [ver_ans],
        }
    )

    exit_code = run_answers(
        expect_hash=h,
        variant="full_agent",
        golden_file=q_file,
        output_dir=out_dir,
        retriever=mock_ret,
        llm=mock_llm,
        verbose=False,
    )
    assert exit_code == 0

    records = json.loads((out_dir / "answers_full_agent.json").read_text(encoding="utf-8"))
    assert len(records) == 2

    r_unans = next(r for r in records if r["question_id"] == "tcs-gold-01")
    r_ans = next(r for r in records if r["question_id"] == "tcs-gold-02")

    assert r_unans["refused"] is True
    assert r_unans["answer"] == REFUSAL_STRING

    assert r_ans["refused"] is False
    assert r_ans["answer"] == "TCS revenue was $30 billion."


def test_caching_llm_namespaces_shared_for_agent_variants():
    """full_agent and agent_no_checker share 'answers-agent-v1'; single_draft uses 'answers-single_draft-v1'."""
    ns_full = get_cache_namespace("full_agent")
    ns_no_checker = get_cache_namespace("agent_no_checker")
    ns_single = get_cache_namespace("single_draft")

    assert ns_full == "answers-agent-v1"
    assert ns_no_checker == "answers-agent-v1"
    assert ns_full == ns_no_checker
    assert ns_single == "answers-single_draft-v1"
    assert ns_single != ns_full
