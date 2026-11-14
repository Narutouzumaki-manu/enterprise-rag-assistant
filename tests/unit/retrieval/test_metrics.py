import math

import pytest

from app.retrieval.metrics import mean, ndcg_at_k, recall_at_k, reciprocal_rank

# ---- recall@k ----

def test_recall_all_found():
    assert recall_at_k(["a", "b", "x"], {"a", "b"}, k=3) == 1.0


def test_recall_half_found():
    assert recall_at_k(["a", "x", "y"], {"a", "b"}, k=3) == 0.5


def test_recall_none_found():
    assert recall_at_k(["x", "y"], {"a"}, k=2) == 0.0


def test_recall_only_looks_at_top_k():
    ranked = ["x", "y", "z", "a"]
    assert recall_at_k(ranked, {"a"}, k=3) == 0.0
    assert recall_at_k(ranked, {"a"}, k=4) == 1.0


def test_recall_no_relevant_chunks_returns_zero():
    assert recall_at_k(["a"], set(), k=3) == 0.0


def test_recall_k_zero_returns_zero():
    assert recall_at_k(["a"], {"a"}, k=0) == 0.0


def test_recall_k_larger_than_list():
    assert recall_at_k(["a"], {"a"}, k=50) == 1.0


def test_recall_duplicates_in_results_do_not_inflate():
    assert recall_at_k(["a", "a", "a"], {"a", "b"}, k=3) == 0.5


# ---- reciprocal rank ----

def test_rr_first_position():
    assert reciprocal_rank(["a", "x"], {"a"}) == 1.0


def test_rr_second_position():
    assert reciprocal_rank(["x", "a"], {"a"}) == 0.5


def test_rr_third_position():
    assert reciprocal_rank(["x", "y", "a"], {"a"}) == pytest.approx(1 / 3)


def test_rr_not_found():
    assert reciprocal_rank(["x", "y"], {"a"}) == 0.0


def test_rr_uses_first_relevant_hit():
    assert reciprocal_rank(["x", "b", "a"], {"a", "b"}) == 0.5


def test_rr_empty_results():
    assert reciprocal_rank([], {"a"}) == 0.0


# ---- NDCG@k ----

def test_ndcg_perfect_ordering_is_one():
    assert ndcg_at_k(["a", "b", "x"], {"a", "b"}, k=3) == pytest.approx(1.0)


def test_ndcg_positions_one_and_three():
    expected = 1.5 / (1 + 1 / math.log2(3))
    assert ndcg_at_k(["a", "x", "b", "y"], {"a", "b"}, k=4) == pytest.approx(expected)


def test_ndcg_positions_two_and_four():
    expected = (1 / math.log2(3) + 1 / math.log2(5)) / (1 + 1 / math.log2(3))
    assert ndcg_at_k(["x", "a", "y", "b", "z"], {"a", "b"}, k=5) == pytest.approx(expected)


def test_ndcg_none_found_is_zero():
    assert ndcg_at_k(["x", "y"], {"a"}, k=2) == 0.0


def test_ndcg_ignores_results_beyond_k():
    assert ndcg_at_k(["x", "y", "z", "a"], {"a"}, k=3) == 0.0


def test_ndcg_higher_position_scores_better():
    early = ndcg_at_k(["a", "x", "y"], {"a"}, k=3)
    late = ndcg_at_k(["x", "y", "a"], {"a"}, k=3)
    assert early > late


def test_ndcg_no_relevant_chunks_returns_zero():
    assert ndcg_at_k(["a"], set(), k=3) == 0.0


def test_ndcg_duplicate_result_counted_once():
    assert ndcg_at_k(["a", "a", "x"], {"a"}, k=3) == pytest.approx(1.0)


def test_ndcg_more_relevant_chunks_than_k_can_still_reach_one():
    relevant = {"a", "b", "c", "d", "e"}
    assert ndcg_at_k(["a", "b", "x"], relevant, k=2) == pytest.approx(1.0)


# ---- mean ----

def test_mean_of_values():
    assert mean([1.0, 0.5, 0.0]) == 0.5


def test_mean_of_nothing_is_zero():
    assert mean([]) == 0.0

