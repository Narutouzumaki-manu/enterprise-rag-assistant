import math

import pytest

from app.retrieval.metrics import (
    merge_identical_needs,
    needs_ranking,
    score_against_needs,
)

# ---- merge_identical_needs ----

def test_identical_needs_collapse_into_one():
    assert merge_identical_needs([{"c"}, {"c"}]) == [{"c"}]


def test_different_needs_are_kept():
    assert merge_identical_needs([{"a"}, {"b"}]) == [{"a"}, {"b"}]


def test_merge_of_nothing_is_empty():
    assert merge_identical_needs([]) == []


# ---- needs_ranking ----

def test_first_hit_is_replaced_by_a_label():
    assert needs_ranking(["x", "a", "y"], [{"a"}]) == ["x", "need:0", "y"]


def test_second_chunk_for_same_need_gets_no_credit():
    assert needs_ranking(["a1", "a2"], [{"a1", "a2"}]) == ["need:0", "a2"]


def test_two_needs_are_labelled_in_order_of_appearance():
    assert needs_ranking(["b", "x", "a"], [{"a"}, {"b"}]) == ["need:1", "x", "need:0"]


def test_chunks_that_match_nothing_are_untouched():
    assert needs_ranking(["x", "y"], [{"a"}]) == ["x", "y"]


def test_empty_ranking_gives_empty_result():
    assert needs_ranking([], [{"a"}]) == []


def test_needs_that_share_a_chunk_are_rejected():
    with pytest.raises(ValueError):
        needs_ranking(["a"], [{"a", "b"}, {"b", "c"}])


# ---- score_against_needs ----

def test_one_of_three_acceptable_chunks_found_second():
    scores = score_against_needs(["x", "a2", "x2"], [{"a1", "a2", "a3"}])
    assert scores["recall@5"] == 1.0
    assert scores["mrr"] == 0.5
    assert scores["ndcg@10"] == pytest.approx(1 / math.log2(3))


def test_finding_several_acceptable_chunks_does_not_double_count():
    scores = score_against_needs(["a1", "a2", "a3"], [{"a1", "a2", "a3"}])
    assert scores["recall@5"] == 1.0
    assert scores["mrr"] == 1.0
    assert scores["ndcg@10"] == pytest.approx(1.0)


def test_two_needs_found_at_positions_one_and_three():
    scores = score_against_needs(["a", "x", "b"], [{"a"}, {"b"}])
    assert scores["recall@5"] == 1.0
    assert scores["ndcg@10"] == pytest.approx(1.5 / (1 + 1 / math.log2(3)))


def test_only_one_of_two_needs_found():
    scores = score_against_needs(["x", "b", "y"], [{"a"}, {"b"}])
    assert scores["recall@5"] == 0.5
    assert scores["mrr"] == 0.5


def test_nothing_found_scores_zero_everywhere():
    scores = score_against_needs(["x", "y", "z"], [{"a"}])
    assert all(value == 0.0 for value in scores.values())


def test_hit_beyond_five_counts_for_recall_at_10_only():
    ranked = ["x1", "x2", "x3", "x4", "x5", "x6", "a"]
    scores = score_against_needs(ranked, [{"a"}])
    assert scores["recall@5"] == 0.0
    assert scores["recall@10"] == 1.0


def test_two_facts_in_the_same_chunk_count_as_one_need():
    scores = score_against_needs(["c", "x"], [{"c"}, {"c"}])
    assert scores["recall@5"] == 1.0
    assert scores["ndcg@10"] == pytest.approx(1.0)


def test_empty_needs_raise():
    with pytest.raises(ValueError):
        score_against_needs(["a"], [])


def test_a_need_with_no_chunks_raises():
    with pytest.raises(ValueError):
        score_against_needs(["a"], [set()])


def test_custom_cutoffs_change_the_score_names():
    scores = score_against_needs(["a"], [{"a"}], recall_ks=(1,), ndcg_k=3)
    assert set(scores) == {"recall@1", "mrr", "ndcg@3"}


def test_default_score_names():
    scores = score_against_needs(["a"], [{"a"}])
    assert set(scores) == {"recall@5", "recall@10", "mrr", "ndcg@10"}