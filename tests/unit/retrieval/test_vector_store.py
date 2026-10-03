import uuid
from datetime import datetime, timezone

import pytest

from app.retrieval.embeddings import EmbeddingService
from app.retrieval.vector_store import VectorStore
from app.schemas.document import Chunk, ChunkMetadata, SourceType


@pytest.fixture(scope="module")
def embedding_service():
    # Load the model once for the whole file (much faster)
    return EmbeddingService()


@pytest.fixture
def store(embedding_service):
    # A unique collection name per test, so tests never share data.
    # (ChromaDB's in-memory mode can share state between instances in one process.)
    return VectorStore(embedding_service, collection_name=f"test_{uuid.uuid4().hex}")


def make_chunk(text, position, doc_id="doc1", page=1, section=None):
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
            ingested_at=datetime.now(timezone.utc),
        ),
    )


@pytest.fixture
def sample_chunks():
    return [
        make_chunk("Revenue increased 18% in Q3 due to strong cloud sales.", 0, "finance", 12, "Revenue Overview"),
        make_chunk("Operating margin was 18.4% in the third quarter.", 1, "finance", 17),
        make_chunk("The company cafeteria serves lunch from noon to 2 pm.", 0, "hr", 3),
        make_chunk("Employees get 24 days of paid leave per year.", 1, "hr", 5),
    ]


class FakeEmbeddingService:
    """Pretends to be a different model, to test the safety check."""
    model_name = "some-other-model"
    dimension = 768


def test_upsert_adds_chunks(store, sample_chunks):
    store.upsert(sample_chunks)
    assert store.count() == 4


def test_upsert_same_chunks_twice_creates_no_duplicates(store, sample_chunks):
    store.upsert(sample_chunks)
    store.upsert(sample_chunks)
    assert store.count() == 4


def test_upsert_empty_list_does_nothing(store):
    store.upsert([])
    assert store.count() == 0


def test_search_returns_most_relevant_first(store, sample_chunks):
    store.upsert(sample_chunks)
    results = store.search("How did sales grow?", k=2)
    assert results[0].document_id == "finance"
    assert "Revenue" in results[0].text


def test_search_scores_are_sorted_descending(store, sample_chunks):
    store.upsert(sample_chunks)
    results = store.search("paid time off", k=4)
    scores = [r.dense_score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_search_carries_page_and_section_metadata(store, sample_chunks):
    store.upsert(sample_chunks)
    top = store.search("How did sales grow?", k=1)[0]
    assert top.page_number == 12
    assert top.section_title == "Revenue Overview"


def test_search_chunk_without_section_title_returns_none(store, sample_chunks):
    store.upsert(sample_chunks)
    results = store.search("operating margin third quarter", k=1)
    assert results[0].chunk_id == "finance_1"
    assert results[0].section_title is None


def test_search_empty_query_returns_empty(store, sample_chunks):
    store.upsert(sample_chunks)
    assert store.search("") == []
    assert store.search("   ") == []


def test_search_on_empty_store_returns_empty(store):
    assert store.search("anything") == []


def test_search_k_larger_than_count_returns_everything(store, sample_chunks):
    store.upsert(sample_chunks)
    assert len(store.search("company", k=50)) == 4


def test_search_filter_restricts_to_one_document(store, sample_chunks):
    store.upsert(sample_chunks)
    results = store.search("time off", k=4, filters={"document_id": "hr"})
    assert len(results) == 2
    assert all(r.document_id == "hr" for r in results)


def test_search_filter_matching_nothing_returns_empty(store, sample_chunks):
    store.upsert(sample_chunks)
    assert store.search("revenue", filters={"document_id": "does_not_exist"}) == []


def test_delete_removes_only_the_target_document(store, sample_chunks):
    store.upsert(sample_chunks)
    removed = store.delete("finance")
    assert removed == 2
    assert store.count() == 2
    remaining = store.search("company", k=10)
    assert all(r.document_id == "hr" for r in remaining)


def test_delete_unknown_document_returns_zero(store, sample_chunks):
    store.upsert(sample_chunks)
    assert store.delete("does_not_exist") == 0
    assert store.count() == 4


def test_data_survives_reopening_from_disk(embedding_service, sample_chunks, tmp_path):
    first = VectorStore(embedding_service, persist_path=str(tmp_path))
    first.upsert(sample_chunks)
    reopened = VectorStore(embedding_service, persist_path=str(tmp_path))
    assert reopened.count() == 4


def test_different_embedding_model_is_rejected(embedding_service, sample_chunks, tmp_path):
    first = VectorStore(embedding_service, persist_path=str(tmp_path))
    first.upsert(sample_chunks)
    with pytest.raises(ValueError):
        VectorStore(FakeEmbeddingService(), persist_path=str(tmp_path))