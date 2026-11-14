import uuid
from datetime import UTC, datetime

import pytest

from app.retrieval.bm25_index import BM25Index
from app.retrieval.embeddings import EmbeddingService
from app.retrieval.hybrid_search import HybridRetriever
from app.retrieval.reranker import Reranker
from app.retrieval.vector_store import VectorStore
from app.schemas.document import Chunk, ChunkMetadata, SourceType
from app.schemas.retrieval import RetrievalRequest, RetrievalResponse


@pytest.fixture(scope="module")
def embedding_service():
    return EmbeddingService()


@pytest.fixture(scope="module")
def reranker():
    return Reranker()


def make_chunk(text, position, doc_id, page, section=None):
    return Chunk(
        chunk_id=f"{doc_id}_{position}",
        document_id=doc_id,
        text=text,
        token_count=len(text.split()),
        metadata=ChunkMetadata(
            document_id=doc_id,
            source_type=SourceType.PDF,
            page_number=page,
            section_title=section,
            content_hash="fakehash",
            ingested_at=datetime.now(UTC),
        ),
    )


@pytest.fixture
def chunks():
    return [
        make_chunk("Revenue increased 18% in Q3 due to strong cloud sales.", 0, "finance", 12, "Revenue Overview"),
        make_chunk("Operating margin was 18.4% in the third quarter.", 1, "finance", 17),
        make_chunk("The vendor holds a SOC 2 Type II certification, audited annually.", 0, "security", 4),
        make_chunk("Data is encrypted at rest using AES-256 and in transit using TLS 1.3.", 1, "security", 6),
        make_chunk("The company cafeteria serves lunch from noon to 2 pm.", 0, "hr", 3),
        make_chunk("Employees get 24 days of paid leave per year.", 1, "hr", 5),
    ]


def build(embedding_service, reranker):
    # A unique collection name per test keeps tests from sharing data
    return HybridRetriever(
        VectorStore(embedding_service, collection_name=f"test_{uuid.uuid4().hex}"),
        BM25Index(),
        reranker,
    )


@pytest.fixture
def retriever(embedding_service, reranker, chunks):
    r = build(embedding_service, reranker)
    r.index_chunks(chunks)
    return r


class FailingReranker:
    model_name = "broken-reranker"

    def rerank(self, query, candidates, top_k=5):
        raise RuntimeError("model crashed")


def test_retrieve_returns_response_with_models_and_latency(retriever, embedding_service, reranker):
    response = retriever.retrieve(RetrievalRequest(query="paid leave"))
    assert isinstance(response, RetrievalResponse)
    assert response.query == "paid leave"
    assert response.embedding_model == embedding_service.model_name
    assert response.reranker_model == reranker.model_name
    assert response.latency_ms >= 0


def test_paraphrase_query_finds_right_chunk(retriever):
    response = retriever.retrieve(RetrievalRequest(query="How did sales grow?", top_k=3))
    assert response.results[0].chunk_id == "finance_0"


def test_exact_keyword_query_finds_right_chunk(retriever):
    response = retriever.retrieve(RetrievalRequest(query="SOC 2 Type II", top_k=3))
    assert response.results[0].chunk_id == "security_0"


def test_result_carries_all_scores(retriever):
    response = retriever.retrieve(RetrievalRequest(query="cloud sales revenue", top_k=6))
    finance = next(r for r in response.results if r.chunk_id == "finance_0")
    assert finance.dense_score is not None
    assert finance.sparse_score is not None
    assert finance.fused_score is not None
    assert finance.rerank_score is not None


def test_top_k_limits_results(retriever):
    response = retriever.retrieve(RetrievalRequest(query="company", top_k=2))
    assert len(response.results) == 2


def test_empty_query_returns_empty_response(retriever):
    response = retriever.retrieve(RetrievalRequest(query="   "))
    assert response.results == []


def test_empty_index_returns_empty_response(embedding_service, reranker):
    empty = build(embedding_service, reranker)
    response = empty.retrieve(RetrievalRequest(query="anything"))
    assert response.results == []


def test_filter_restricts_to_one_document(retriever):
    response = retriever.retrieve(
        RetrievalRequest(query="time off", top_k=5, filters={"document_id": "hr"})
    )
    assert len(response.results) > 0
    assert all(r.document_id == "hr" for r in response.results)


def test_filter_matching_nothing_returns_empty(retriever):
    response = retriever.retrieve(
        RetrievalRequest(query="revenue", filters={"document_id": "does_not_exist"})
    )
    assert response.results == []


def test_delete_document_removes_from_both_indexes(retriever):
    assert retriever.delete_document("finance") == 2
    assert retriever.bm25_index.search("revenue cloud sales") == []
    response = retriever.retrieve(RetrievalRequest(query="revenue cloud sales", top_k=10))
    assert all(r.document_id != "finance" for r in response.results)


def test_index_chunks_is_idempotent(retriever, chunks):
    retriever.index_chunks(chunks)
    assert retriever.vector_store.count() == 6
    assert retriever.bm25_index.count() == 6


def test_without_reranker_uses_fused_order(embedding_service, chunks):
    plain = HybridRetriever(
        VectorStore(embedding_service, collection_name=f"test_{uuid.uuid4().hex}"),
        BM25Index(),
        reranker=None,
    )
    plain.index_chunks(chunks)
    response = plain.retrieve(RetrievalRequest(query="How did sales grow?", top_k=3))
    assert response.reranker_model == "none"
    assert len(response.results) == 3
    assert all(r.rerank_score is None for r in response.results)
    assert all(r.fused_score is not None for r in response.results)


def test_reranker_failure_falls_back_to_fused_order(embedding_service, chunks):
    broken = HybridRetriever(
        VectorStore(embedding_service, collection_name=f"test_{uuid.uuid4().hex}"),
        BM25Index(),
        reranker=FailingReranker(),
    )
    broken.index_chunks(chunks)
    response = broken.retrieve(RetrievalRequest(query="How did sales grow?", top_k=3))
    assert len(response.results) == 3
    assert all(r.rerank_score is None for r in response.results)
    assert "failed" in response.reranker_model


def test_page_and_section_metadata_survive_the_whole_pipeline(retriever):
    response = retriever.retrieve(RetrievalRequest(query="How did sales grow?", top_k=1))
    top = response.results[0]
    assert top.page_number == 12
    assert top.section_title == "Revenue Overview"

class ExplodingBM25(BM25Index):
    def search(self, *args, **kwargs):
        raise AssertionError("keyword search must not run in meaning-only mode")


def build_meaning_only(embedding_service, reranker=None, bm25=None):
    return HybridRetriever(
        VectorStore(embedding_service, collection_name=f"test_{uuid.uuid4().hex}"),
        bm25 if bm25 is not None else BM25Index(),
        reranker,
        use_keyword=False,
    )


def test_meaning_only_returns_the_vector_stores_own_order(embedding_service, chunks):
    r = build_meaning_only(embedding_service)
    r.index_chunks(chunks)
    expected = [c.chunk_id for c in r.vector_store.search("How did sales grow?", k=3)]
    response = r.retrieve(RetrievalRequest(query="How did sales grow?", top_k=3))
    assert [c.chunk_id for c in response.results] == expected
    assert response.reranker_model == "none"


def test_meaning_only_results_have_only_a_dense_score(embedding_service, chunks):
    r = build_meaning_only(embedding_service)
    r.index_chunks(chunks)
    response = r.retrieve(RetrievalRequest(query="paid leave", top_k=3))
    assert response.results
    for result in response.results:
        assert result.dense_score is not None
        assert result.sparse_score is None
        assert result.fused_score is None
        assert result.rerank_score is None


def test_meaning_only_never_calls_keyword_search(embedding_service, chunks):
    r = build_meaning_only(embedding_service, bm25=ExplodingBM25())
    r.index_chunks(chunks)
    assert len(r.retrieve(RetrievalRequest(query="paid leave", top_k=2)).results) == 2


def test_meaning_only_still_fills_both_indexes(embedding_service, chunks):
    r = build_meaning_only(embedding_service)
    r.index_chunks(chunks)
    assert r.vector_store.count() == 6
    assert r.bm25_index.count() == 6


def test_meaning_only_can_still_use_a_reranker(embedding_service, reranker, chunks):
    r = build_meaning_only(embedding_service, reranker=reranker)
    r.index_chunks(chunks)
    response = r.retrieve(RetrievalRequest(query="How did sales grow?", top_k=3))
    assert response.reranker_model == reranker.model_name
    assert all(x.rerank_score is not None for x in response.results)


def test_meaning_only_respects_filters_and_empty_queries(embedding_service, chunks):
    r = build_meaning_only(embedding_service)
    r.index_chunks(chunks)
    filtered = r.retrieve(RetrievalRequest(query="time off", top_k=5, filters={"document_id": "hr"}))
    assert filtered.results and all(x.document_id == "hr" for x in filtered.results)
    assert r.retrieve(RetrievalRequest(query="   ")).results == []


def test_default_mode_still_merges_keyword_search(retriever):
    assert retriever.use_keyword is True
    response = retriever.retrieve(RetrievalRequest(query="SOC 2 Type II", top_k=3))
    assert all(x.fused_score is not None for x in response.results)