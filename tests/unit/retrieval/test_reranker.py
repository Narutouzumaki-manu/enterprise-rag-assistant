import pytest

from app.retrieval.reranker import Reranker
from app.schemas.retrieval import RetrievedChunk


@pytest.fixture(scope="module")
def reranker():
    return Reranker()


@pytest.fixture
def candidates():
    return [
        RetrievedChunk(chunk_id="hr_0", document_id="hr", text="The company cafeteria serves lunch from noon to 2 pm.", dense_score=0.4),
        RetrievedChunk(chunk_id="finance_1", document_id="finance", text="Operating margin was 18.4% in the third quarter.", dense_score=0.3),
        RetrievedChunk(chunk_id="hr_1", document_id="hr", text="Employees get 24 days of paid leave per year.", dense_score=0.2),
    ]


QUERY = "What was the operating margin in the third quarter?"


def test_relevant_passage_ranked_first(reranker, candidates):
    results = reranker.rerank(QUERY, candidates)
    assert results[0].chunk_id == "finance_1"


def test_rerank_score_set_on_every_result(reranker, candidates):
    results = reranker.rerank(QUERY, candidates)
    assert all(r.rerank_score is not None for r in results)


def test_scores_sorted_descending(reranker, candidates):
    results = reranker.rerank(QUERY, candidates)
    scores = [r.rerank_score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_top_k_limits_results(reranker, candidates):
    assert len(reranker.rerank(QUERY, candidates, top_k=2)) == 2


def test_empty_candidates_returns_empty(reranker):
    assert reranker.rerank(QUERY, []) == []


def test_empty_query_returns_empty(reranker, candidates):
    assert reranker.rerank("", candidates) == []
    assert reranker.rerank("   ", candidates) == []


def test_inputs_are_not_mutated(reranker, candidates):
    reranker.rerank(QUERY, candidates)
    assert all(c.rerank_score is None for c in candidates)


def test_other_fields_are_preserved(reranker, candidates):
    results = reranker.rerank(QUERY, candidates, top_k=3)
    by_id = {r.chunk_id: r for r in results}
    assert by_id["finance_1"].dense_score == 0.3
    assert by_id["finance_1"].document_id == "finance"