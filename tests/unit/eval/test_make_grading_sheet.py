"""Unit tests for scripts/make_grading_sheet.py.

Tests:
1. Never fills grade or notes (leaves them empty).
2. Preserves existing manual grades and notes on re-run.
3. Handles missing variant files gracefully without crashing.
"""

import csv
import json
from pathlib import Path

import pytest

from scripts.make_grading_sheet import (
    COLUMNS,
    make_grading_sheet,
    parse_answer_file,
)


@pytest.fixture
def sample_golden_data():
    return [
        {
            "question_id": "tcs-gold-01",
            "question": "What were the priorities?",
            "category": "fact_lookup",
            "style": "paraphrase",
            "reference_answer": "AI delivery and AI clients",
        },
        {
            "question_id": "tcs-gold-02",
            "question": "What was the operating margin?",
            "category": "table",
            "style": "exact",
            "reference_answer": "25% operating margin",
        },
        {
            "question_id": "tcs-gold-24",
            "question": "Share of women in March 2026?",
            "category": "unanswerable",
            "style": "paraphrase",
            "reference_answer": "",
        },
    ]


@pytest.fixture
def sample_answers_dense():
    return [
        {
            "question_id": "tcs-gold-01",
            "answer": "TCS prioritised AI in delivery and selling AI transformation.",
            "verification_status": "verified",
            "refused": False,
        },
        {
            "question_id": "tcs-gold-02",
            "answer": "Operating margin was 25%.",
            "verification_status": "verified",
            "refused": False,
        },
        {
            "question_id": "tcs-gold-24",
            "answer": "I don't have sufficient evidence in the provided documents.",
            "verification_status": "unverified",
            "refused": True,
        },
    ]


def test_never_fills_grade(tmp_path: Path, sample_golden_data, sample_answers_dense):
    """Test that all newly generated rows have empty grade and empty notes."""
    golden_file = tmp_path / "golden.json"
    golden_file.write_text(json.dumps(sample_golden_data), encoding="utf-8")

    results_dir = tmp_path / "results"
    results_dir.mkdir()
    ans_file = results_dir / "answers_retrieval_dense.json"
    ans_file.write_text(json.dumps(sample_answers_dense), encoding="utf-8")

    out_csv = results_dir / "grading_sheet.csv"
    res_path = make_grading_sheet(
        golden_path=golden_file,
        results_dir=results_dir,
        output_csv=out_csv,
    )

    assert res_path.exists()
    with res_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == COLUMNS
        rows = list(reader)

    assert len(rows) == 3
    for r in rows:
        assert r["grade"] == "", f"Grade must be empty, got {r['grade']}"
        assert r["notes"] == "", f"Notes must be empty, got {r['notes']}"
        assert r["variant"] == "retrieval_dense"
        assert r["answerable"] in ("True", "False")

    # Specific checks
    row_01 = next(r for r in rows if r["question_id"] == "tcs-gold-01")
    assert row_01["answerable"] == "True"
    assert row_01["reference_answer"] == "AI delivery and AI clients"
    assert row_01["refused"] == "False"

    row_24 = next(r for r in rows if r["question_id"] == "tcs-gold-24")
    assert row_24["answerable"] == "False"
    assert row_24["refused"] == "True"
    assert row_24["reference_answer"] == ""


def test_preserves_existing_grades_on_rerun(tmp_path: Path, sample_golden_data, sample_answers_dense):
    """Test that re-running preserves hand-entered grade and notes for matching (question_id, variant)."""
    golden_file = tmp_path / "golden.json"
    golden_file.write_text(json.dumps(sample_golden_data), encoding="utf-8")

    results_dir = tmp_path / "results"
    results_dir.mkdir()
    ans_dense = results_dir / "answers_retrieval_dense.json"
    ans_dense.write_text(json.dumps(sample_answers_dense), encoding="utf-8")

    out_csv = results_dir / "grading_sheet.csv"

    # 1. Initial run
    make_grading_sheet(
        golden_path=golden_file,
        results_dir=results_dir,
        output_csv=out_csv,
    )

    # 2. Simulate manual grading
    with out_csv.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    for r in rows:
        if r["question_id"] == "tcs-gold-01" and r["variant"] == "retrieval_dense":
            r["grade"] = "CORRECT"
            r["notes"] = "matches reference answer accurately"
        elif r["question_id"] == "tcs-gold-24" and r["variant"] == "retrieval_dense":
            r["grade"] = "REFUSED_GOOD"
            r["notes"] = "honest refusal on unanswerable metric"

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    # 3. Add a second variant: retrieval_keyword
    ans_keyword = results_dir / "answers_retrieval_keyword.json"
    keyword_data = [
        {
            "question_id": "tcs-gold-01",
            "answer": "Delivery and client priorities.",
            "verification_status": "verified",
            "refused": False,
        },
        {
            "question_id": "tcs-gold-02",
            "answer": "25% operating margin.",
            "verification_status": "verified",
            "refused": False,
        },
    ]
    ans_keyword.write_text(json.dumps(keyword_data), encoding="utf-8")

    # 4. Re-run make_grading_sheet
    make_grading_sheet(
        golden_path=golden_file,
        results_dir=results_dir,
        output_csv=out_csv,
    )

    # 5. Verify preserved grades and empty grades for new rows
    with out_csv.open("r", encoding="utf-8", newline="") as f:
        updated_rows = list(csv.DictReader(f))

    # Dense row 01 preserved
    dense_01 = next(r for r in updated_rows if r["question_id"] == "tcs-gold-01" and r["variant"] == "retrieval_dense")
    assert dense_01["grade"] == "CORRECT"
    assert dense_01["notes"] == "matches reference answer accurately"

    # Dense row 24 preserved
    dense_24 = next(r for r in updated_rows if r["question_id"] == "tcs-gold-24" and r["variant"] == "retrieval_dense")
    assert dense_24["grade"] == "REFUSED_GOOD"
    assert dense_24["notes"] == "honest refusal on unanswerable metric"

    # Dense row 02 was not graded, should still be empty
    dense_02 = next(r for r in updated_rows if r["question_id"] == "tcs-gold-02" and r["variant"] == "retrieval_dense")
    assert dense_02["grade"] == ""
    assert dense_02["notes"] == ""

    # Keyword rows are new: grade and notes must be empty
    keyword_01 = next(r for r in updated_rows if r["question_id"] == "tcs-gold-01" and r["variant"] == "retrieval_keyword")
    assert keyword_01["grade"] == ""
    assert keyword_01["notes"] == ""

    keyword_02 = next(r for r in updated_rows if r["question_id"] == "tcs-gold-02" and r["variant"] == "retrieval_keyword")
    assert keyword_02["grade"] == ""
    assert keyword_02["notes"] == ""


def test_handles_missing_variant_file(tmp_path: Path, sample_golden_data):
    """Test graceful handling when variant files are missing."""
    golden_file = tmp_path / "golden.json"
    golden_file.write_text(json.dumps(sample_golden_data), encoding="utf-8")

    results_dir = tmp_path / "results"
    results_dir.mkdir()
    out_csv = results_dir / "grading_sheet.csv"

    # 1. Explicitly passing a non-existent file path does not crash
    missing_file = results_dir / "answers_nonexistent.json"
    assert not missing_file.exists()

    res = parse_answer_file(missing_file)
    assert res == []

    # 2. Calling make_grading_sheet with missing variant file passes cleanly
    make_grading_sheet(
        golden_path=golden_file,
        results_dir=results_dir,
        output_csv=out_csv,
        variant_files=[missing_file],
    )
    assert out_csv.exists()
    with out_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == COLUMNS
        rows = list(reader)
    assert len(rows) == 0  # No variant answers found, clean empty header

    # 3. Calling make_grading_sheet on empty results directory does not crash
    make_grading_sheet(
        golden_path=golden_file,
        results_dir=results_dir,
        output_csv=out_csv,
    )
    assert out_csv.exists()


def test_error_record_is_skipped(tmp_path: Path, sample_golden_data):
    """An error record is skipped and never enters the grading sheet."""
    golden_file = tmp_path / "golden.json"
    golden_file.write_text(json.dumps(sample_golden_data), encoding="utf-8")

    results_dir = tmp_path / "results"
    results_dir.mkdir()
    ans_file = results_dir / "answers_full_agent.json"
    ans_data = [
        {
            "question_id": "tcs-gold-01",
            "answer": "I couldn't write an answer right now. Please try again.",
            "verification_status": "unverified",
            "refused": False,
            "error": "No cached answer for this Draft request (replay-only mode)",
        }
    ]
    ans_file.write_text(json.dumps(ans_data), encoding="utf-8")

    # parse_answer_file skips error record
    parsed = parse_answer_file(ans_file)
    assert parsed == []

    # make_grading_sheet produces 0 rows
    out_csv = results_dir / "grading_sheet.csv"
    make_grading_sheet(
        golden_path=golden_file,
        results_dir=results_dir,
        output_csv=out_csv,
    )
    with out_csv.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 0


def test_existing_sheet_row_for_error_record_kept_only_if_graded(tmp_path: Path, sample_golden_data):
    """An existing sheet row for a question whose record has an error stays untouched only if it already has a grade."""
    golden_file = tmp_path / "golden.json"
    golden_file.write_text(json.dumps(sample_golden_data), encoding="utf-8")

    results_dir = tmp_path / "results"
    results_dir.mkdir()
    out_csv = results_dir / "grading_sheet.csv"

    # Pre-populate grading_sheet.csv: gold-01 is graded, gold-02 is ungraded
    pre_rows = [
        {
            "question_id": "tcs-gold-01",
            "category": "fact_lookup",
            "style": "paraphrase",
            "answerable": "True",
            "variant": "full_agent",
            "answer": "Previously verified correct answer",
            "verification_status": "verified",
            "refused": "False",
            "reference_answer": "AI delivery and AI clients",
            "grade": "CORRECT",
            "notes": "already graded",
        },
        {
            "question_id": "tcs-gold-02",
            "category": "table",
            "style": "exact",
            "answerable": "True",
            "variant": "full_agent",
            "answer": "Old unverified answer",
            "verification_status": "unverified",
            "refused": "False",
            "reference_answer": "25% operating margin",
            "grade": "",
            "notes": "",
        },
    ]
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(pre_rows)

    # Both questions have errors in the new answers file
    ans_file = results_dir / "answers_full_agent.json"
    ans_data = [
        {
            "question_id": "tcs-gold-01",
            "answer": "Error answer for q1",
            "error": "Cache miss",
        },
        {
            "question_id": "tcs-gold-02",
            "answer": "Error answer for q2",
            "error": "Timeout",
        },
    ]
    ans_file.write_text(json.dumps(ans_data), encoding="utf-8")

    make_grading_sheet(
        golden_path=golden_file,
        results_dir=results_dir,
        output_csv=out_csv,
    )

    with out_csv.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    # gold-01 stayed untouched because it had a grade
    assert len(rows) == 1
    r01 = rows[0]
    assert r01["question_id"] == "tcs-gold-01"
    assert r01["answer"] == "Previously verified correct answer"
    assert r01["grade"] == "CORRECT"
    assert r01["notes"] == "already graded"

    # gold-02 had no grade and its record had an error, so it was dropped
    assert not any(r["question_id"] == "tcs-gold-02" for r in rows)


def test_record_without_error_is_added(tmp_path: Path, sample_golden_data):
    """A record without an error is added to the sheet."""
    golden_file = tmp_path / "golden.json"
    golden_file.write_text(json.dumps(sample_golden_data), encoding="utf-8")

    results_dir = tmp_path / "results"
    results_dir.mkdir()
    ans_file = results_dir / "answers_full_agent.json"
    ans_data = [
        {
            "question_id": "tcs-gold-01",
            "answer": "Valid clean answer",
            "verification_status": "verified",
            "refused": False,
            "error": None,
        },
        {
            "question_id": "tcs-gold-02",
            "answer": "Error answer",
            "error": "LLM failed",
        },
    ]
    ans_file.write_text(json.dumps(ans_data), encoding="utf-8")

    out_csv = results_dir / "grading_sheet.csv"
    make_grading_sheet(
        golden_path=golden_file,
        results_dir=results_dir,
        output_csv=out_csv,
    )

    with out_csv.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    # Only gold-01 was added
    assert len(rows) == 1
    assert rows[0]["question_id"] == "tcs-gold-01"
    assert rows[0]["answer"] == "Valid clean answer"
    assert rows[0]["grade"] == ""
