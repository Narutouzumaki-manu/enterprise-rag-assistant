import pytest

from app.schemas.retrieval import RetrievalRequest

from .mocks import MockRetriever, make_chunk


def _loaded() -> MockRetriever:
    retriever = MockRetriever()
    retriever.index_chunks([make_chunk("doc_a", i) for i in range(3)] + [make_chunk("doc_b", 0)])
    return retriever


def test_retrieve_returns_ranked_results_with_citation_fields():
    results = _loaded().retrieve(RetrievalRequest(query="q", top_k=8)).results
    assert len(results) == 4
    assert results[0].dense_score > results[1].dense_score
    assert results[0].page_number == 1


def test_indexing_is_idempotent():
    retriever = MockRetriever()
    chunk = make_chunk()
    retriever.index_chunks([chunk])
    retriever.index_chunks([chunk])
    assert retriever.chunk_count == 1


def test_delete_removes_only_that_document():
    retriever = _loaded()
    retriever.delete_document("doc_a")
    results = retriever.retrieve(RetrievalRequest(query="q")).results
    assert [r.document_id for r in results] == ["doc_b"]


def test_blank_query_and_empty_index_return_empty_results():
    assert _loaded().retrieve(RetrievalRequest(query="   ")).results == []
    assert MockRetriever().retrieve(RetrievalRequest(query="q")).results == []


def test_unknown_filter_key_raises():
    with pytest.raises(ValueError):
        _loaded().retrieve(RetrievalRequest(query="q", filters={"colour": "red"}))


def test_document_filter_restricts_results():
    request = RetrievalRequest(query="q", filters={"document_id": "doc_b"})
    results = _loaded().retrieve(request).results
    assert [r.document_id for r in results] == ["doc_b"]


def test_top_k_limits_results():
    assert len(_loaded().retrieve(RetrievalRequest(query="q", top_k=2)).results) == 2


def test_index_error_is_raised_and_nothing_is_stored():
    retriever = MockRetriever(index_error=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        retriever.index_chunks([make_chunk()])
    assert retriever.chunk_count == 0