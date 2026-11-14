import uuid
from datetime import UTC, datetime

import pytest

from app.retrieval import factory
from app.retrieval.factory import BGE_QUERY_PREFIX, build_default_retriever
from app.schemas.document import Chunk, ChunkMetadata, SourceType
from app.schemas.retrieval import RetrievalRequest


def unique():
    return f"test_{uuid.uuid4().hex}"


def make_chunk(text, position, doc_id, page):
    return Chunk(
        chunk_id=f"{doc_id}_{position}",
        document_id=doc_id,
        text=text,
        token_count=len(text.split()),
        metadata=ChunkMetadata(
            document_id=doc_id,
            source_type=SourceType.PDF,
            page_number=page,
            content_hash="fakehash",
            ingested_at=datetime.now(UTC),
        ),
    )


CHUNKS = [
    make_chunk("Revenue increased 18% in Q3 due to strong cloud sales.", 0, "finance", 12),
    make_chunk("The company cafeteria serves lunch from noon to 2 pm.", 0, "hr", 3),
    make_chunk("Employees get 24 days of paid leave per year.", 1, "hr", 5),
]


def test_shipped_configuration_values():
    assert factory.EMBEDDING_MODEL == "BAAI/bge-small-en-v1.5"
    assert factory.USE_KEYWORD_SEARCH is False
    assert factory.RERANKER_MODEL is None


def test_default_retriever_is_meaning_only_without_a_reranker():
    r = build_default_retriever(collection_name=unique())
    assert r.use_keyword is False
    assert r.reranker is None
    assert r.vector_store.embedding_service.model_name == factory.EMBEDDING_MODEL


def test_bge_models_get_their_query_prefix_automatically():
    r = build_default_retriever(collection_name=unique())
    assert r.vector_store.embedding_service.query_prefix == BGE_QUERY_PREFIX


def test_other_models_get_no_prefix():
    r = build_default_retriever(collection_name=unique(), embedding_model="all-MiniLM-L6-v2")
    assert r.vector_store.embedding_service.query_prefix == ""


def test_an_explicit_prefix_wins():
    r = build_default_retriever(collection_name=unique(), query_prefix="query: ")
    assert r.vector_store.embedding_service.query_prefix == "query: "


def test_keyword_search_and_reranker_can_be_switched_on():
    name = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    r = build_default_retriever(collection_name=unique(), use_keyword=True, reranker_model=name)
    assert r.use_keyword is True
    assert r.reranker.model_name == name


def test_end_to_end_with_the_default_retriever():
    r = build_default_retriever(collection_name=unique())
    r.index_chunks(CHUNKS)
    response = r.retrieve(RetrievalRequest(query="How did sales grow?", top_k=2))
    assert response.results[0].chunk_id == "finance_0"
    assert response.reranker_model == "none"

import uuid
from datetime import UTC, datetime

import pytest

from app.retrieval import factory
from app.retrieval.factory import BGE_QUERY_PREFIX, build_default_retriever
from app.schemas.document import Chunk, ChunkMetadata, SourceType
from app.schemas.retrieval import RetrievalRequest


def unique():
    return f"test_{uuid.uuid4().hex}"


def make_chunk(text, position, doc_id, page):
    return Chunk(
        chunk_id=f"{doc_id}_{position}",
        document_id=doc_id,
        text=text,
        token_count=len(text.split()),
        metadata=ChunkMetadata(
            document_id=doc_id,
            source_type=SourceType.PDF,
            page_number=page,
            content_hash="fakehash",
            ingested_at=datetime.now(UTC),
        ),
    )


CHUNKS = [
    make_chunk("Revenue increased 18% in Q3 due to strong cloud sales.", 0, "finance", 12),
    make_chunk("The company cafeteria serves lunch from noon to 2 pm.", 0, "hr", 3),
    make_chunk("Employees get 24 days of paid leave per year.", 1, "hr", 5),
]


def test_shipped_configuration_values():
    assert factory.EMBEDDING_MODEL == "BAAI/bge-small-en-v1.5"
    assert factory.USE_KEYWORD_SEARCH is False
    assert factory.RERANKER_MODEL is None


def test_default_retriever_is_meaning_only_without_a_reranker():
    r = build_default_retriever(collection_name=unique())
    assert r.use_keyword is False
    assert r.reranker is None
    assert r.vector_store.embedding_service.model_name == factory.EMBEDDING_MODEL


def test_bge_models_get_their_query_prefix_automatically():
    r = build_default_retriever(collection_name=unique())
    assert r.vector_store.embedding_service.query_prefix == BGE_QUERY_PREFIX


def test_other_models_get_no_prefix():
    r = build_default_retriever(collection_name=unique(), embedding_model="all-MiniLM-L6-v2")
    assert r.vector_store.embedding_service.query_prefix == ""


def test_an_explicit_prefix_wins():
    r = build_default_retriever(collection_name=unique(), query_prefix="query: ")
    assert r.vector_store.embedding_service.query_prefix == "query: "


def test_keyword_search_and_reranker_can_be_switched_on():
    name = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    r = build_default_retriever(collection_name=unique(), use_keyword=True, reranker_model=name)
    assert r.use_keyword is True
    assert r.reranker.model_name == name


def test_end_to_end_with_the_default_retriever():
    r = build_default_retriever(collection_name=unique())
    r.index_chunks(CHUNKS)
    response = r.retrieve(RetrievalRequest(query="How did sales grow?", top_k=2))
    assert response.results[0].chunk_id == "finance_0"
    assert response.reranker_model == "none"


def test_a_saved_index_reopens_and_a_different_model_is_rejected(tmp_path):
    first = build_default_retriever(str(tmp_path))
    first.index_chunks(CHUNKS)
    reopened = build_default_retriever(str(tmp_path))
    assert reopened.vector_store.count() == len(CHUNKS)
    with pytest.raises(ValueError):
        build_default_retriever(str(tmp_path), embedding_model="all-MiniLM-L6-v2")
def test_a_saved_index_reopens_and_a_different_model_is_rejected(tmp_path):
    first = build_default_retriever(str(tmp_path))
    first.index_chunks(CHUNKS)
    reopened = build_default_retriever(str(tmp_path))
    assert reopened.vector_store.count() == len(CHUNKS)
    with pytest.raises(ValueError):
        build_default_retriever(str(tmp_path), embedding_model="all-MiniLM-L6-v2")