import pytest

from app.schemas.retrieval import RetrievalRequest
from tests.unit.agents.mocks import MockRetriever, make_chunk


def _request(query, top_k=5, filters=None):
    return RetrievalRequest(query=query, top_k=top_k, filters=filters)


def test_returns_configured_results_for_a_known_query():
    a, b = make_chunk("a"), make_chunk("b")
    retriever = MockRetriever(responses={"q": [a, b]})
    response = retriever.retrieve(_request("q"))
    assert [c.chunk_id for c in response.results] == ["a", "b"]


def test_top_k_limits_the_number_of_results():
    chunks = [make_chunk(f"c{i}") for i in range(10)]
    retriever = MockRetriever(responses={"q": chunks})
    assert len(retriever.retrieve(_request("q", top_k=3)).results) == 3
    assert len(retriever.retrieve(_request("q", top_k=8)).results) == 8


def test_unknown_query_returns_empty_results():
    retriever = MockRetriever(responses={"q": [make_chunk("a")]})
    assert retriever.retrieve(_request("other")).results == []


def test_unknown_query_returns_custom_default():
    retriever = MockRetriever(default=[make_chunk("d")])
    response = retriever.retrieve(_request("anything"))
    assert [c.chunk_id for c in response.results] == ["d"]


@pytest.mark.parametrize("empty_query", ["", "   "])
def test_empty_and_whitespace_query_return_empty_results(empty_query):
    retriever = MockRetriever(default=[make_chunk("d")])
    assert retriever.retrieve(_request(empty_query)).results == []


def test_every_call_is_recorded_in_order():
    retriever = MockRetriever()
    retriever.retrieve(_request("first"))
    retriever.retrieve(_request("second", top_k=15))
    assert [c.query for c in retriever.calls] == ["first", "second"]
    assert retriever.calls[1].top_k == 15


def test_only_dense_score_is_filled():
    chunk = MockRetriever(default=[make_chunk("a")]).retrieve(_request("q")).results[0]
    assert chunk.dense_score is not None
    assert chunk.sparse_score is None
    assert chunk.fused_score is None
    assert chunk.rerank_score is None


def test_error_is_raised_and_call_still_recorded():
    retriever = MockRetriever(error=RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        retriever.retrieve(_request("q"))
    assert len(retriever.calls) == 1


def test_unknown_filter_key_raises_value_error():
    retriever = MockRetriever()
    with pytest.raises(ValueError, match="colour"):
        retriever.retrieve(_request("q", filters={"colour": "red"}))


def test_known_filter_key_is_accepted():
    retriever = MockRetriever(default=[make_chunk("a")])
    response = retriever.retrieve(_request("q", filters={"document_id": "doc1"}))
    assert len(response.results) == 1


def test_returned_chunks_are_copies():
    retriever = MockRetriever(default=[make_chunk("a")])
    first = retriever.retrieve(_request("q"))
    first.results[0].text = "EDITED"
    second = retriever.retrieve(_request("q"))
    assert second.results[0].text == "text of a"


def test_response_carries_query_and_model_names():
    response = MockRetriever().retrieve(_request("q"))
    assert response.query == "q"
    assert response.embedding_model == "mock"
    assert response.reranker_model == "none"