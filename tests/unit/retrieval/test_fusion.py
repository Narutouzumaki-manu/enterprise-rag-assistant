import pytest

from app.retrieval.fusion import reciprocal_rank_fusion
from app.schemas.retrieval import RetrievedChunk


def rc(chunk_id, dense=None, sparse=None):
    return RetrievedChunk(
        chunk_id=chunk_id, document_id="d", text=chunk_id, dense_score=dense, sparse_score=sparse
    )


def test_rrf_matches_hand_computed_example():
    dense = [rc("A"), rc("B"), rc("C")]
    sparse = [rc("C"), rc("A"), rc("D")]
    fused = reciprocal_rank_fusion(dense, sparse)
    assert [c.chunk_id for c in fused] == ["A", "C", "B", "D"]
    assert fused[0].fused_score == pytest.approx(1 / 61 + 1 / 62)
    assert fused[1].fused_score == pytest.approx(1 / 63 + 1 / 61)


def test_chunk_in_both_lists_keeps_both_scores():
    fused = reciprocal_rank_fusion([rc("A", dense=0.9)], [rc("A", sparse=7.5)])
    assert fused[0].dense_score == 0.9
    assert fused[0].sparse_score == 7.5


def test_chunk_in_one_list_has_other_score_none():
    fused = reciprocal_rank_fusion([rc("A", dense=0.9)], [rc("B", sparse=7.5)])
    by_id = {c.chunk_id: c for c in fused}
    assert by_id["A"].sparse_score is None
    assert by_id["B"].dense_score is None


def test_both_empty_returns_empty():
    assert reciprocal_rank_fusion([], []) == []


def test_one_empty_list_preserves_other_order():
    fused = reciprocal_rank_fusion([rc("A"), rc("B"), rc("C")], [])
    assert [c.chunk_id for c in fused] == ["A", "B", "C"]


def test_inputs_are_not_mutated():
    dense = [rc("A", dense=0.9)]
    sparse = [rc("A", sparse=7.5)]
    reciprocal_rank_fusion(dense, sparse)
    assert dense[0].sparse_score is None
    assert dense[0].fused_score is None
    assert sparse[0].dense_score is None


def test_limit_truncates_results():
    fused = reciprocal_rank_fusion([rc("A"), rc("B"), rc("C")], [rc("D")], limit=2)
    assert len(fused) == 2


def test_duplicate_in_same_list_counted_once():
    fused = reciprocal_rank_fusion([rc("A"), rc("A"), rc("B")], [])
    by_id = {c.chunk_id: c for c in fused}
    assert len(fused) == 2
    assert by_id["A"].fused_score == pytest.approx(1 / 61)


def test_fused_score_set_on_every_result():
    fused = reciprocal_rank_fusion([rc("A"), rc("B")], [rc("C")])
    assert all(c.fused_score is not None for c in fused)