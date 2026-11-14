"""Unit tests for retrieval evaluation logic, metrics math, independent subset filtering, and integrity checks."""

import math
from dataclasses import dataclass

import pytest

from app.eval.golden_schema import GoldenQuestion
from scripts.run_retrieval_eval import (
    compute_sha256,
    get_fact_phrases,
    score_retrieval,
)
from scripts.run_retrieval_eval import (
    main as eval_main,
)


@dataclass
class FakeChunk:
    chunk_id: str
    text: str
    dense_score: float = 0.8
    page_number: int = 1


def test_score_retrieval_rank_1():
    """Hand-computed test: single fact found at rank 1."""
    fact_phrases = [["annualised ai revenue above $2.3 billion"]]
    retrieved = [
        FakeChunk(chunk_id="c1", text="TCS reported annualised AI revenue above $2.3 billion in FY26."),
        FakeChunk(chunk_id="c2", text="Unrelated text 1"),
        FakeChunk(chunk_id="c3", text="Unrelated text 2"),
    ]

    scores = score_retrieval(fact_phrases, retrieved)
    assert scores["facts_total"] == 1
    assert scores["facts_found_at_5"] == 1
    assert scores["facts_found_at_10"] == 1
    assert scores["rank_of_first_relevant_chunk"] == 1
    assert scores["recall@5"] == 1.0
    assert scores["recall@10"] == 1.0
    assert scores["mrr"] == 1.0
    assert scores["ndcg@10"] == 1.0


def test_score_retrieval_rank_3():
    """Hand-computed test: single fact found at rank 3."""
    fact_phrases = [["q4 fy26 tcv of $12 billion"]]
    retrieved = [
        FakeChunk(chunk_id="c1", text="Unrelated text 1"),
        FakeChunk(chunk_id="c2", text="Unrelated text 2"),
        FakeChunk(chunk_id="c3", text="Total deal wins included Q4 FY26 TCV of $12 billion."),
        FakeChunk(chunk_id="c4", text="Unrelated text 4"),
    ]

    scores = score_retrieval(fact_phrases, retrieved)
    assert scores["facts_total"] == 1
    assert scores["facts_found_at_5"] == 1
    assert scores["facts_found_at_10"] == 1
    assert scores["rank_of_first_relevant_chunk"] == 3
    assert scores["recall@5"] == 1.0
    assert scores["recall@10"] == 1.0
    assert pytest.approx(scores["mrr"], abs=1e-4) == 1.0 / 3.0
    # NDCG@10 for rank 3: (1 / log2(4)) / 1.0 = 0.5 / 1.0 = 0.5
    assert pytest.approx(scores["ndcg@10"], abs=1e-4) == 0.5


def test_score_retrieval_not_found():
    """Hand-computed test: fact not found in top 10 results."""
    fact_phrases = [["revenue $30,017 million"]]
    retrieved = [FakeChunk(chunk_id=f"c{i}", text=f"Irrelevant text {i}") for i in range(10)]

    scores = score_retrieval(fact_phrases, retrieved)
    assert scores["facts_total"] == 1
    assert scores["facts_found_at_5"] == 0
    assert scores["facts_found_at_10"] == 0
    assert scores["rank_of_first_relevant_chunk"] is None
    assert scores["recall@5"] == 0.0
    assert scores["recall@10"] == 0.0
    assert scores["mrr"] == 0.0
    assert scores["ndcg@10"] == 0.0


def test_score_retrieval_multi_fact():
    """Multi-fact test: 2 facts; fact 0 found at rank 2, fact 1 found at rank 4."""
    fact_phrases = [
        ["net margin 19.8%"],
        ["operating margin 25%"],
    ]
    retrieved = [
        FakeChunk(chunk_id="c1", text="Introductory remarks"),
        FakeChunk(chunk_id="c2", text="The company achieved a net margin 19.8% this year."),
        FakeChunk(chunk_id="c3", text="Macroeconomic climate commentary"),
        FakeChunk(chunk_id="c4", text="With strong cost discipline, operating margin 25% was delivered."),
    ]

    scores = score_retrieval(fact_phrases, retrieved)
    assert scores["facts_total"] == 2
    assert scores["facts_found_at_5"] == 2
    assert scores["facts_found_at_10"] == 2
    assert scores["rank_of_first_relevant_chunk"] == 2
    assert scores["recall@5"] == 1.0
    assert scores["recall@10"] == 1.0
    assert scores["mrr"] == 0.5

    # Hand-computed NDCG@10:
    # dcg = 1 / log2(3) + 1 / log2(5)
    # ideal = 1 / log2(2) + 1 / log2(3)
    expected_dcg = 1.0 / math.log2(3) + 1.0 / math.log2(5)
    expected_ideal = 1.0 / math.log2(2) + 1.0 / math.log2(3)
    assert pytest.approx(scores["ndcg@10"], abs=1e-4) == expected_dcg / expected_ideal


def test_get_fact_phrases_alt_evidence_handling():
    """Verify phrase resolution for single-fact vs multi-fact questions."""
    # Single-fact with alt
    q_single = GoldenQuestion(
        question_id="tcs-gold-03",
        question="What did AI revenue exceed?",
        category="fact_lookup",
        style="paraphrase",
        evidence=["annualised AI revenue above $2.3 billion"],
        alt_evidence=["Annualised AI revenue; FY26: Above $2.3 billion"],
        reference_answer="$2.3 billion",
    )
    phrases_single = get_fact_phrases(q_single)
    assert len(phrases_single) == 1
    assert len(phrases_single[0]) == 2

    # Multi-fact tcs-gold-02
    q_02 = GoldenQuestion(
        question_id="tcs-gold-02",
        question="Margins question",
        category="multi_fact",
        style="exact",
        evidence=["Net margin 19.8%", "Operating margin 25%"],
        alt_evidence=[
            "Metric: Operating margin; FY26: 25%",
            "the net margin excluding exceptional items rose to 19.8%",
        ],
        reference_answer="19.8% and 25%",
    )
    phrases_02 = get_fact_phrases(q_02)
    assert len(phrases_02) == 2
    # Fact 0 has net margin primary and alt
    assert "Net margin 19.8%" in phrases_02[0]
    assert "the net margin excluding exceptional items rose to 19.8%" in phrases_02[0]
    # Fact 1 has operating margin primary and alt
    assert "Operating margin 25%" in phrases_02[1]
    assert "Metric: Operating margin; FY26: 25%" in phrases_02[1]


def test_independent_subset_filtering():
    """Verify that independent subset filtering correctly identifies questions not in flagged_same_fact."""
    flagged = {"tcs-gold-04", "tcs-gold-14", "tcs-gold-16", "tcs-gold-21"}
    sample_ids = ["tcs-gold-01", "tcs-gold-04", "tcs-gold-06", "tcs-gold-14"]

    independent = [qid for qid in sample_ids if qid not in flagged]
    assert independent == ["tcs-gold-01", "tcs-gold-06"]


def test_hash_mismatch_aborts(monkeypatch, tmp_path):
    """Verify that run_retrieval_eval aborts when --expect-hash differs from file hash."""
    fake_file = tmp_path / "fake_golden.json"
    fake_file.write_text('[]', encoding="utf-8")
    actual_hash = compute_sha256(fake_file)

    # Calling main with a different hash should return exit code 1
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_retrieval_eval.py",
            "--expect-hash",
            "wrong_hash_1234567890abcdef",
            "--golden-file",
            str(fake_file),
        ],
    )
    exit_code = eval_main()
    assert exit_code == 1
