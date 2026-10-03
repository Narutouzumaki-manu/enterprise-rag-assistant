import uuid
from datetime import datetime, timezone

import pytest

from app.retrieval.bm25_index import BM25Index
from app.retrieval.embeddings import EmbeddingService
from app.retrieval.filters import to_chroma_where, validate_filters
from app.retrieval.vector_store import VectorStore
from app.schemas.document import Chunk, ChunkMetadata, SourceType


# ---- the helper functions on their own ----

def test_no_filters_returns_none():
    assert validate_filters(None) is None


def test_empty_filters_returns_none():
    assert validate_filters({}) is None


def test_unknown_key_raises():
    with pytest.raises(ValueError):
        validate_filters({"docment_id": "hr"})


def test_valid_filters_returned_unchanged():
    assert validate_filters({"document_id": "hr"}) == {"document_id": "hr"}


def test_chroma_where_for_nothing_is_none():
    assert to_chroma_where(None) is None


def test_chroma_where_one_key_stays_simple():
    assert to_chroma_where({"document_id": "hr"}) == {"document_id": "hr"}


def test_chroma_where_two_keys_uses_and():
    where = to_chroma_where({"document_id": "finance", "page_number": 12})
    assert where == {"$and": [{"document_id": "finance"}, {"page_number": 12}]}


# ---- both indexes must treat the same filter the same way ----

@pytest.fixture(scope="module")
def embedding_service():
    return EmbeddingService()


def make_chunk(text, position, doc_id, page, content_hash):
    return Chunk(
        chunk_id=f"{doc_id}_{position}",
        document_id=doc_id,
        text=text,
        token_count=len(text.split()),
        metadata=ChunkMetadata(
            document_id=doc_id,
            source_type=SourceType.PDF,
            page_number=page,
            content_hash=content_hash,
            ingested_at=datetime.now(timezone.utc),
        ),
    )


@pytest.fixture
def both_indexes(embedding_service):
    chunks = [
        make_chunk("Revenue increased 18% in Q3 due to strong cloud sales.", 0, "finance", 12, "hashF"),
        make_chunk("Operating margin was 18.4% in the third quarter.", 1, "finance", 17, "hashF"),
        make_chunk("The company cafeteria serves lunch from noon to 2 pm.", 0, "hr", 3, "hashH"),
        make_chunk("Employees get 24 days of paid leave per year.", 1, "hr", 5, "hashH"),
    ]
    store = VectorStore(embedding_service, collection_name=f"test_{uuid.uuid4().hex}")
    store.upsert(chunks)
    bm25 = BM25Index()
    bm25.upsert(chunks)
    return store, bm25


def test_two_key_filter_works_in_both_indexes(both_indexes):
    store, bm25 = both_indexes
    filters = {"document_id": "finance", "page_number": 12}
    assert [r.chunk_id for r in store.search("revenue cloud sales", k=5, filters=filters)] == ["finance_0"]
    assert [r.chunk_id for r in bm25.search("revenue cloud sales", k=5, filters=filters)] == ["finance_0"]


def test_content_hash_filter_works_in_both_indexes(both_indexes):
    store, bm25 = both_indexes
    filters = {"content_hash": "hashH"}
    dense = {r.chunk_id for r in store.search("company paid leave", k=10, filters=filters)}
    sparse = {r.chunk_id for r in bm25.search("company paid leave", k=10, filters=filters)}
    assert dense == sparse == {"hr_0", "hr_1"}


def test_unknown_key_raises_in_vector_store(both_indexes):
    store, _ = both_indexes
    with pytest.raises(ValueError):
        store.search("revenue", filters={"docment_id": "hr"})


def test_unknown_key_raises_in_bm25(both_indexes):
    _, bm25 = both_indexes
    with pytest.raises(ValueError):
        bm25.search("revenue", filters={"docment_id": "hr"})