import json
from dataclasses import dataclass, field

import pytest
from pydantic import ValidationError

from app.eval.golden_schema import (
    GoldenQuestion,
    validate_golden_questions,
)
from app.eval.search_chunks import search_term_in_chunks
from app.eval.validate_golden import (
    check_duplicates,
    normalize_text,
    validate_golden_file,
    validate_question_phrases,
)
from scripts.merge_golden_v1 import merge_golden
from scripts.merge_golden_v1_1 import (
    generate_overlap_file,
    merge_golden_v1_1,
)


@dataclass
class MockMetadata:
    page_number: int = 1


@dataclass
class MockChunk:
    chunk_id: str
    text: str
    metadata: MockMetadata = field(default_factory=MockMetadata)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Schema Rules Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_valid_answerable_question():
    q = GoldenQuestion(
        question_id="test-01",
        question="What is the revenue?",
        category="fact_lookup",
        style="exact",
        evidence=["revenue was $100M"],
        reference_answer="The revenue was $100M.",
    )
    assert q.question_id == "test-01"
    assert q.category == "fact_lookup"
    assert q.evidence == ["revenue was $100M"]


def test_valid_unanswerable_question():
    q = GoldenQuestion(
        question_id="test-02",
        question="What was the secret budget?",
        category="unanswerable",
        style="paraphrase",
        evidence=[],
        reference_answer="",
        notes="Not mentioned in the document.",
    )
    assert q.question_id == "test-02"
    assert q.category == "unanswerable"
    assert q.evidence == []
    assert q.reference_answer == ""


def test_invalid_category_raises():
    with pytest.raises(ValidationError):
        GoldenQuestion(
            question_id="test-bad-cat",
            question="Question?",
            category="unsupported_category",  # type: ignore
            style="exact",
            evidence=["some evidence"],
            reference_answer="Answer.",
        )


def test_invalid_style_raises():
    with pytest.raises(ValidationError):
        GoldenQuestion(
            question_id="test-bad-style",
            question="Question?",
            category="table",
            style="creative",  # type: ignore
            evidence=["some evidence"],
            reference_answer="Answer.",
        )


def test_answerable_missing_evidence_raises():
    with pytest.raises(ValidationError, match="evidence must be non-empty"):
        GoldenQuestion(
            question_id="test-no-ev",
            question="What is revenue?",
            category="fact_lookup",
            style="exact",
            evidence=[],
            reference_answer="Revenue was $10M.",
        )


def test_answerable_missing_reference_answer_raises():
    with pytest.raises(ValidationError, match="reference_answer must be non-empty"):
        GoldenQuestion(
            question_id="test-no-ans",
            question="What is revenue?",
            category="fact_lookup",
            style="exact",
            evidence=["revenue was $10M"],
            reference_answer="",
        )


def test_unanswerable_with_evidence_raises():
    with pytest.raises(ValidationError, match="evidence must be empty"):
        GoldenQuestion(
            question_id="test-unans-ev",
            question="What is secret budget?",
            category="unanswerable",
            style="paraphrase",
            evidence=["secret budget is 0"],
            reference_answer="",
        )


def test_unanswerable_with_reference_answer_raises():
    with pytest.raises(ValidationError, match="reference_answer must be empty"):
        GoldenQuestion(
            question_id="test-unans-ans",
            question="What is secret budget?",
            category="unanswerable",
            style="paraphrase",
            evidence=[],
            reference_answer="It cannot be answered.",
        )


def test_duplicate_question_ids_raises():
    questions = [
        {
            "question_id": "duplicate-id",
            "question": "Question 1",
            "category": "fact_lookup",
            "style": "exact",
            "evidence": ["ev 1"],
            "reference_answer": "ans 1",
        },
        {
            "question_id": "duplicate-id",
            "question": "Question 2",
            "category": "table",
            "style": "paraphrase",
            "evidence": ["ev 2"],
            "reference_answer": "ans 2",
        },
    ]
    with pytest.raises(ValueError, match="Duplicate question_ids found"):
        validate_golden_questions(questions)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Text Normalization & Matching Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_whitespace_and_case_normalization():
    raw = "  TCS’s   ‘operating   margin’\nwas   25%  “quote”  \u00a0\u00ad"
    expected = "tcs's 'operating margin' was 25% \"quote\""
    assert normalize_text(raw) == expected


def test_phrase_counting_and_chunk_matching():
    chunks = [
        MockChunk(chunk_id="chunk-1", text="Operating margin was 25% for FY26.", metadata=MockMetadata(page_number=1)),
        MockChunk(chunk_id="chunk-2", text="Net margin was 19.8% in Q4.", metadata=MockMetadata(page_number=2)),
        MockChunk(chunk_id="chunk-3", text="Operating margin was 25% in historical trends.", metadata=MockMetadata(page_number=3)),
    ]

    q = GoldenQuestion(
        question_id="test-match-01",
        question="What was operating margin?",
        category="fact_lookup",
        style="exact",
        evidence=["Operating margin was 25%"],
        reference_answer="Operating margin was 25%.",
    )

    result = validate_question_phrases(q, chunks)
    assert result.status == "PASS"
    assert len(result.phrase_matches) == 1
    pm = result.phrase_matches[0]
    assert pm.count == 2
    assert sorted(pm.matching_chunk_ids) == ["chunk-1", "chunk-3"]
    assert result.unique_matched_chunk_ids == ["chunk-1", "chunk-3"]
    assert result.distinct_pages == [1, 3]


def test_zero_match_evidence_flags_error():
    chunks = [
        MockChunk(chunk_id="chunk-1", text="Some unrelated text about technology."),
    ]

    q = GoldenQuestion(
        question_id="test-zero-match",
        question="What was revenue?",
        category="fact_lookup",
        style="exact",
        evidence=["Completely missing phrase that does not exist in any chunk"],
        reference_answer="Revenue was $10M.",
    )

    result = validate_question_phrases(q, chunks)
    assert result.status == "ERROR"
    assert any("has 0 matches" in err for err in result.errors)


def test_too_generic_warning_for_more_than_three_matches():
    chunks = [
        MockChunk(chunk_id=f"chunk-{i}", text="The company reported strong results.")
        for i in range(5)
    ]

    q = GoldenQuestion(
        question_id="test-generic",
        question="Did company report results?",
        category="fact_lookup",
        style="exact",
        evidence=["company reported"],
        reference_answer="Yes, strong results.",
    )

    result = validate_question_phrases(q, chunks)
    assert result.status == "WARN"
    assert any("too generic" in warn for warn in result.warnings)


def test_unanswerable_question_validation():
    chunks = [
        MockChunk(chunk_id="chunk-1", text="Some financial metrics."),
    ]

    q = GoldenQuestion(
        question_id="test-unans",
        question="What was Q3 cash balance?",
        category="unanswerable",
        style="paraphrase",
        evidence=[],
        reference_answer="",
        notes="Not available.",
    )

    result = validate_question_phrases(q, chunks)
    assert result.status == "PASS"
    assert len(result.errors) == 0
    assert len(result.warnings) == 0
    assert result.distinct_pages == []


def test_numerical_fact_warning_when_number_missing():
    chunks = [
        MockChunk(chunk_id="chunk-1", text="Operating margin improved significantly."),
    ]

    q = GoldenQuestion(
        question_id="test-num-warn",
        question="What was margin?",
        category="numerical_comparison",
        style="exact",
        evidence=["Operating margin improved"],
        reference_answer="Margin was 25.4%.",
    )

    result = validate_question_phrases(q, chunks)
    assert any("Number '25.4' from reference_answer not found" in warn for warn in result.warnings)


def test_numerical_warning_suppressed_when_no_evidence_matched():
    chunks = [
        MockChunk(chunk_id="chunk-1", text="Different text entirely."),
    ]

    q = GoldenQuestion(
        question_id="test-no-match-num",
        question="What was margin?",
        category="numerical_comparison",
        style="exact",
        evidence=["Missing evidence phrase"],
        reference_answer="Margin was 25.4%.",
    )

    result = validate_question_phrases(q, chunks)
    # Evidence has 0 matches (ERROR), but number warning should NOT be emitted
    assert any("has 0 matches" in err for err in result.errors)
    assert not any("Number '25.4' from reference_answer not found" in warn for warn in result.warnings)


def test_validate_golden_file_with_in_memory_fixture(tmp_path):
    chunks = [
        MockChunk(chunk_id="c-1", text="AI revenue reached $2.3 billion.", metadata=MockMetadata(page_number=5)),
        MockChunk(chunk_id="c-2", text="No cash information.", metadata=MockMetadata(page_number=6)),
    ]

    valid_data = [
        {
            "question_id": "q-1",
            "question": "What did AI revenue reach?",
            "category": "fact_lookup",
            "style": "exact",
            "evidence": ["AI revenue reached $2.3 billion"],
            "alt_evidence": [],
            "reference_answer": "AI revenue reached $2.3 billion.",
        },
        {
            "question_id": "q-2",
            "question": "What was confidential cash?",
            "category": "unanswerable",
            "style": "paraphrase",
            "evidence": [],
            "alt_evidence": [],
            "reference_answer": "",
            "notes": "Unanswerable topic.",
        },
    ]

    json_path = tmp_path / "test_golden.json"
    json_path.write_text(json.dumps(valid_data), encoding="utf-8")

    results, totals, duplicate_warnings, error_count = validate_golden_file(json_path, chunks=chunks)
    assert error_count == 0
    assert totals["total_questions"] == 2
    assert totals["answerable"] == 1
    assert totals["unanswerable"] == 1
    assert results[0].status == "PASS"
    assert results[0].distinct_pages == [5]
    assert results[1].status == "PASS"
    assert results[1].distinct_pages == []
    assert len(duplicate_warnings) == 0


def test_validate_golden_file_reports_errors_for_missing_phrases(tmp_path):
    chunks = [MockChunk(chunk_id="c-1", text="Completely unrelated content.")]
    invalid_data = [
        {
            "question_id": "q-err-1",
            "question": "What is missing?",
            "category": "fact_lookup",
            "style": "exact",
            "evidence": ["This phrase does not exist anywhere"],
            "reference_answer": "Missing answer.",
        }
    ]
    json_path = tmp_path / "err_golden.json"
    json_path.write_text(json.dumps(invalid_data), encoding="utf-8")

    results, totals, duplicate_warnings, error_count = validate_golden_file(json_path, chunks=chunks)
    assert error_count == 1
    assert results[0].status == "ERROR"
    assert len(results[0].errors) == 1
    assert "has 0 matches" in results[0].errors[0]


def test_search_chunks_in_memory():
    chunks = [
        MockChunk(chunk_id="cid-1", text="TCS framed its AI-first vision around client transformation."),
        MockChunk(chunk_id="cid-2", text="Net income excluded exceptional items."),
    ]

    # Term present
    count, previews = search_term_in_chunks("AI-first", chunks)
    assert count == 1
    assert previews[0]["chunk_id"] == "cid-1"
    assert "AI-first" in previews[0]["snippet"]

    # Term absent
    absent_count, absent_previews = search_term_in_chunks("nonexistent_topic_xyz", chunks)
    assert absent_count == 0
    assert len(absent_previews) == 0


# ─────────────────────────────────────────────────────────────────────────────
# 3. New Options, Duplicate Checks & Merge Refusal Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_min_total_and_min_unanswerable_thresholds(tmp_path):
    chunks = [MockChunk(chunk_id="c-1", text="Sample text for testing.")]
    data = [
        {
            "question_id": "q-thresh-1",
            "question": "Question 1?",
            "category": "unanswerable",
            "style": "exact",
            "evidence": [],
            "reference_answer": "",
        }
    ]
    json_path = tmp_path / "threshold.json"
    json_path.write_text(json.dumps(data), encoding="utf-8")

    # Min total not met (requires 5, have 1)
    _, _, _, err1 = validate_golden_file(json_path, chunks=chunks, min_total=5)
    assert err1 == 1

    # Min unanswerable not met (requires 2, have 1)
    _, _, _, err2 = validate_golden_file(json_path, chunks=chunks, min_unanswerable=2)
    assert err2 == 1

    # Both met (requires min_total=1, min_unanswerable=1)
    _, _, _, err3 = validate_golden_file(json_path, chunks=chunks, min_total=1, min_unanswerable=1)
    assert err3 == 0


def test_near_duplicate_checks():
    # 1. Identical normalized question
    q1 = GoldenQuestion(
        question_id="q-dup-1",
        question="  What was TCS's   revenue?  ",
        category="fact_lookup",
        style="exact",
        evidence=["revenue"],
        reference_answer="Revenue was $30B.",
    )
    q2 = GoldenQuestion(
        question_id="q-dup-2",
        question="what was tcs's revenue?",
        category="fact_lookup",
        style="paraphrase",
        evidence=["revenue"],
        reference_answer="Revenue was $30B.",
    )
    dup_warns = check_duplicates([q1, q2])
    assert any("Identical normalised question" in w for w in dup_warns)

    # 2. Identical evidence phrase used across >3 questions
    shared_phrase = "common evidence phrase"
    many_qs = [
        GoldenQuestion(
            question_id=f"q-shared-{i}",
            question=f"Question {i}?",
            category="fact_lookup",
            style="exact",
            evidence=[shared_phrase],
            reference_answer=f"Answer {i}.",
        )
        for i in range(4)
    ]
    many_warns = check_duplicates(many_qs)
    assert any("Identical normalised evidence phrase used by 4 questions (>3)" in w for w in many_warns)


def test_merge_golden_refusal_missing_id(tmp_path):
    canonical = tmp_path / "canonical.json"
    canonical.write_text(json.dumps([
        {"question_id": "q-1", "question": "Q1?", "category": "fact_lookup", "style": "exact", "evidence": ["ev"], "reference_answer": "ans"}
    ]), encoding="utf-8")

    patch = tmp_path / "patch.json"
    patch.write_text(json.dumps([
        {"question_id": "non-existent-id", "evidence": ["new ev"]}
    ]), encoding="utf-8")

    new_ans = tmp_path / "new_ans.json"
    new_ans.write_text("[]", encoding="utf-8")
    new_unans = tmp_path / "new_unans.json"
    new_unans.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="Patch question_id 'non-existent-id' not found"):
        merge_golden(canonical, patch, new_ans, new_unans)


def test_merge_golden_refusal_duplicate_id(tmp_path):
    canonical = tmp_path / "canonical.json"
    canonical.write_text(json.dumps([
        {"question_id": "q-1", "question": "Q1?", "category": "fact_lookup", "style": "exact", "evidence": ["ev"], "reference_answer": "ans"}
    ]), encoding="utf-8")

    patch = tmp_path / "patch.json"
    patch.write_text("[]", encoding="utf-8")

    # Duplicate between new answerable and unanswerable
    new_ans = tmp_path / "new_ans.json"
    new_ans.write_text(json.dumps([
        {"question_id": "q-dup", "question": "New Q?", "category": "fact_lookup", "style": "exact", "evidence": ["ev"], "reference_answer": "ans"}
    ]), encoding="utf-8")
    new_unans = tmp_path / "new_unans.json"
    new_unans.write_text(json.dumps([
        {"question_id": "q-dup", "question": "Unans?", "category": "unanswerable", "style": "paraphrase", "evidence": [], "reference_answer": ""}
    ]), encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate question_id across new questions"):
        merge_golden(canonical, patch, new_ans, new_unans)


def test_merge_golden_refusal_changed_non_evidence_field(tmp_path):
    canonical = tmp_path / "canonical.json"
    canonical.write_text(json.dumps([
        {"question_id": "q-1", "question": "Original Q?", "category": "fact_lookup", "style": "exact", "evidence": ["ev"], "reference_answer": "ans"}
    ]), encoding="utf-8")

    # Patch tries to change question text
    patch = tmp_path / "patch.json"
    patch.write_text(json.dumps([
        {"question_id": "q-1", "evidence": ["new ev"], "question": "Changed Question!"}
    ]), encoding="utf-8")

    new_ans = tmp_path / "new_ans.json"
    new_ans.write_text("[]", encoding="utf-8")
    new_unans = tmp_path / "new_unans.json"
    new_unans.write_text("[]", encoding="utf-8")

    with pytest.raises(AssertionError, match="Patch tried to change non-evidence field"):
        merge_golden(canonical, patch, new_ans, new_unans)


def test_merge_golden_safe_rerun_refusal(tmp_path):
    canonical = tmp_path / "canonical.json"
    canonical.write_text(json.dumps([
        {"question_id": "q-1", "question": "Q1?", "category": "fact_lookup", "style": "exact", "evidence": ["ev"], "reference_answer": "ans"},
        {"question_id": "q-new-1", "question": "Q New?", "category": "unanswerable", "style": "exact", "evidence": [], "reference_answer": ""}
    ]), encoding="utf-8")

    patch = tmp_path / "patch.json"
    patch.write_text("[]", encoding="utf-8")

    new_ans = tmp_path / "new_ans.json"
    new_ans.write_text("[]", encoding="utf-8")
    new_unans = tmp_path / "new_unans.json"
    new_unans.write_text(json.dumps([
        {"question_id": "q-new-1", "question": "Q New?", "category": "unanswerable", "style": "exact", "evidence": [], "reference_answer": ""}
    ]), encoding="utf-8")

    # Should refuse merge because q-new-1 is already in canonical
    success = merge_golden(canonical, patch, new_ans, new_unans)
    assert success is False


# ─────────────────────────────────────────────────────────────────────────────
# 4. Patch v1.1 Merge Script & Overlap Option Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_merge_golden_v1_1_success_and_swap(tmp_path):
    canonical = tmp_path / "canonical.json"
    canonical.write_text(json.dumps([
        {"question_id": "tcs-gold-01", "question": "Old Q1?", "category": "fact_lookup", "style": "exact", "evidence": ["old ev"], "reference_answer": "ans 1"},
        {"question_id": "tcs-gold-02", "question": "Unans 2?", "category": "unanswerable", "style": "paraphrase", "evidence": [], "reference_answer": ""},
    ]), encoding="utf-8")

    patch = tmp_path / "patch_v1_1.json"
    patch.write_text(json.dumps({
        "replace": [
            {"question_id": "tcs-gold-01", "question": "Replaced Q1?", "category": "fact_lookup", "style": "exact", "evidence": ["new ev"], "reference_answer": "new ans 1"}
        ],
        "append": [
            {"question_id": "tcs-gold-32", "question": "Appended Q32?", "category": "fact_lookup", "style": "exact", "evidence": ["ev 32"], "reference_answer": "ans 32"}
        ]
    }), encoding="utf-8")

    output = tmp_path / "output.json"
    success = merge_golden_v1_1(
        canonical_file=canonical,
        patch_file=patch,
        output_file=output,
        generate_overlap=False,
    )
    assert success is True

    result_data = json.loads(output.read_text(encoding="utf-8"))
    assert len(result_data) == 3
    # Check swapped in place
    assert result_data[0]["question_id"] == "tcs-gold-01"
    assert result_data[0]["question"] == "Replaced Q1?"
    assert result_data[0]["evidence"] == ["new ev"]
    # Check untouched
    assert result_data[1]["question_id"] == "tcs-gold-02"
    # Check appended
    assert result_data[2]["question_id"] == "tcs-gold-32"
    assert result_data[2]["question"] == "Appended Q32?"


def test_merge_golden_v1_1_double_apply_refusal(tmp_path):
    canonical = tmp_path / "canonical.json"
    canonical.write_text(json.dumps([
        {"question_id": "tcs-gold-32", "question": "Q32?", "category": "fact_lookup", "style": "exact", "evidence": ["ev"], "reference_answer": "ans"}
    ]), encoding="utf-8")

    patch = tmp_path / "patch_v1_1.json"
    patch.write_text(json.dumps({
        "replace": [],
        "append": [
            {"question_id": "tcs-gold-32", "question": "Q32 again?", "category": "fact_lookup", "style": "exact", "evidence": ["ev"], "reference_answer": "ans"}
        ]
    }), encoding="utf-8")

    success = merge_golden_v1_1(
        canonical_file=canonical,
        patch_file=patch,
        generate_overlap=False,
    )
    assert success is False


def test_merge_golden_v1_1_missing_id_on_replace(tmp_path):
    canonical = tmp_path / "canonical.json"
    canonical.write_text(json.dumps([
        {"question_id": "tcs-gold-01", "question": "Q1?", "category": "fact_lookup", "style": "exact", "evidence": ["ev"], "reference_answer": "ans"}
    ]), encoding="utf-8")

    patch = tmp_path / "patch_v1_1.json"
    patch.write_text(json.dumps({
        "replace": [
            {"question_id": "tcs-gold-nonexistent", "question": "Bad?", "category": "fact_lookup", "style": "exact", "evidence": ["ev"], "reference_answer": "ans"}
        ],
        "append": []
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="Replace question_id 'tcs-gold-nonexistent' not found"):
        merge_golden_v1_1(
            canonical_file=canonical,
            patch_file=patch,
            generate_overlap=False,
        )


def test_merge_golden_v1_1_existing_id_on_append(tmp_path):
    # Here canonical does not have tcs-gold-32, but has another ID (e.g. tcs-gold-01) that append tries to insert
    canonical = tmp_path / "canonical.json"
    canonical.write_text(json.dumps([
        {"question_id": "tcs-gold-01", "question": "Q1?", "category": "fact_lookup", "style": "exact", "evidence": ["ev"], "reference_answer": "ans"}
    ]), encoding="utf-8")

    patch = tmp_path / "patch_v1_1.json"
    patch.write_text(json.dumps({
        "replace": [],
        "append": [
            {"question_id": "tcs-gold-01", "question": "Q1 again?", "category": "fact_lookup", "style": "exact", "evidence": ["ev"], "reference_answer": "ans"}
        ]
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="already exists in canonical questions"):
        merge_golden_v1_1(
            canonical_file=canonical,
            patch_file=patch,
            generate_overlap=False,
        )


def test_overlap_file_independent_calculation(tmp_path):
    chunks = [
        MockChunk(chunk_id="c-1", text="Sample text content for testing."),
    ]
    golden_data = [
        {"question_id": "gold-1", "question": "Q1?", "category": "fact_lookup", "style": "exact", "evidence": ["Sample text"], "reference_answer": "Sample text"},
        {"question_id": "gold-2", "question": "Q2?", "category": "fact_lookup", "style": "exact", "evidence": ["Sample text"], "reference_answer": "Sample text"},
        {"question_id": "gold-3", "question": "Q3?", "category": "unanswerable", "style": "paraphrase", "evidence": [], "reference_answer": ""},
    ]
    golden_path = tmp_path / "test_golden.json"
    golden_path.write_text(json.dumps(golden_data), encoding="utf-8")

    overlap_data = {
        "tuned_pool": "tuned.json",
        "flagged_same_fact": [
            {"golden": "gold-1", "tuned": "q01"}
        ],
        "shared_chunk": []
    }
    overlap_path = tmp_path / "test_overlap.json"
    overlap_path.write_text(json.dumps(overlap_data), encoding="utf-8")

    results, totals, duplicate_warnings, err_count = validate_golden_file(
        golden_path,
        chunks=chunks,
        overlap_file=overlap_path,
    )
    assert err_count == 0
    assert "independent" in totals
    ind = totals["independent"]
    assert ind["total"] == 2
    assert ind["answerable"] == 1  # gold-2 is independent; gold-1 is flagged
    assert ind["unanswerable"] == 1  # gold-3 is independent
    assert ind["flagged_count"] == 1
    assert ind["flagged_ids"] == ["gold-1"]


def test_compute_shared_chunks_in_memory(tmp_path):
    chunks = [
        MockChunk(chunk_id="shared-cid-123", text="Common phrase in chunk."),
        MockChunk(chunk_id="other-cid-456", text="Unrelated phrase in chunk."),
    ]

    labels_data = {
        "questions": [
            {
                "question_id": "q01",
                "needs": [
                    {"phrase": "common", "chunk_ids": ["shared-cid-123"]}
                ]
            }
        ]
    }
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(json.dumps(labels_data), encoding="utf-8")

    golden_questions = [
        {
            "question_id": "tcs-gold-01",
            "question": "What is common?",
            "category": "fact_lookup",
            "style": "exact",
            "evidence": ["Common phrase"],
            "reference_answer": "Common phrase",
        }
    ]

    overlap_out = tmp_path / "overlap_out.json"
    overlap = generate_overlap_file(
        golden_questions=golden_questions,
        output_path=overlap_out,
        retrieval_labels_path=labels_path,
        chunks=chunks,
    )

    assert "tuned_pool" in overlap
    assert "flagged_same_fact" in overlap
    assert "shared_chunk" in overlap
    assert len(overlap["shared_chunk"]) == 1
    entry = overlap["shared_chunk"][0]
    assert entry["golden"] == "tcs-gold-01"
    assert entry["tuned"] == "q01"
    assert entry["shared_chunk_ids"] == ["shared-cid-123"]

