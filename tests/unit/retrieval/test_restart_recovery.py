import uuid
from datetime import UTC, datetime

import pytest

from app.retrieval.bm25_index import BM25Index
from app.retrieval.embeddings import EmbeddingService
from app.retrieval.hybrid_search import HybridRetriever
from app.retrieval.vector_store import VectorStore
from app.schemas.document import Chunk, ChunkMetadata, SourceType
from app.schemas.retrieval import RetrievalRequest


@pytest.fixture(scope="module")
def embedding_service():
    return EmbeddingService()


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
            content_hash=f"hash_{doc_id}",
            ingested_at=datetime.now(UTC),
        ),
    )


@pytest.fixture
def chunks():
    return [
        make_chunk("Revenue increased 18% in Q3 due to strong cloud sales.", 0, "finance", 12, "Revenue Overview"),
        make_chunk("Operating margin was 18.4% in the third quarter.", 1, "finance", 17),
        make_chunk("The vendor holds a SOC 2 Type II certification, audited annually.", 0, "security", 4),
        make_chunk("The company cafeteria serves lunch from noon to 2 pm.", 0, "hr", 3),
    ]


@pytest.fixture
def filled_store(embedding_service, chunks):
    store = VectorStore(embedding_service, collection_name=f"test_{uuid.uuid4().hex}")
    store.upsert(chunks)
    return store


# ---- VectorStore.export_records ----

def test_export_records_returns_every_chunk(filled_store, chunks):
    records = filled_store.export_records()
    assert {r["chunk_id"] for r in records} == {c.chunk_id for c in chunks}


def test_export_records_includes_text_and_metadata(filled_store):
    by_id = {r["chunk_id"]: r for r in filled_store.export_records()}
    record = by_id["finance_0"]
    assert record["text"].startswith("Revenue")
    assert record["metadata"]["document_id"] == "finance"
    assert record["metadata"]["page_number"] == 12
    assert record["metadata"]["section_title"] == "Revenue Overview"


def test_export_records_on_empty_store_returns_empty(embedding_service):
    store = VectorStore(embedding_service, collection_name=f"test_{uuid.uuid4().hex}")
    assert store.export_records() == []


def test_export_records_works_across_several_batches(filled_store):
    assert len(filled_store.export_records(batch_size=1)) == 4


# ---- BM25Index.restore and clear ----

def test_restore_makes_chunks_searchable(filled_store):
    bm25 = BM25Index()
    bm25.restore(filled_store.export_records())
    assert bm25.count() == 4
    assert bm25.search("SOC 2 Type II", k=1)[0].chunk_id == "security_0"


def test_restore_keeps_page_and_section(filled_store):
    bm25 = BM25Index()
    bm25.restore(filled_store.export_records())
    top = bm25.search("cloud sales", k=1)[0]
    assert top.page_number == 12
    assert top.section_title == "Revenue Overview"


def test_restore_with_no_records_does_nothing():
    bm25 = BM25Index()
    bm25.restore([])
    assert bm25.count() == 0


def test_clear_empties_the_index(chunks):
    bm25 = BM25Index()
    bm25.upsert(chunks)
    bm25.clear()
    assert bm25.count() == 0
    assert bm25.search("revenue") == []


def test_restored_index_finds_the_same_chunks_as_the_original(filled_store, chunks):
    original = BM25Index()
    original.upsert(chunks)
    restored = BM25Index()
    restored.restore(filled_store.export_records())
    query = "the company year quarter"
    assert {r.chunk_id for r in original.search(query, k=10)} == {
        r.chunk_id for r in restored.search(query, k=10)
    }


# ---- HybridRetriever after a restart ----

def _first_run(embedding_service, chunks, path):
    retriever = HybridRetriever(
        VectorStore(embedding_service, persist_path=path), BM25Index(), reranker=None
    )
    retriever.index_chunks(chunks)
    return retriever


def test_retriever_rebuilds_keyword_index_after_restart(embedding_service, chunks, tmp_path):
    _first_run(embedding_service, chunks, str(tmp_path))
    restarted = HybridRetriever(
        VectorStore(embedding_service, persist_path=str(tmp_path)), BM25Index(), reranker=None
    )
    assert restarted.vector_store.count() == 4
    assert restarted.bm25_index.count() == 4


def test_keyword_search_works_after_restart(embedding_service, chunks, tmp_path):
    _first_run(embedding_service, chunks, str(tmp_path))
    restarted = HybridRetriever(
        VectorStore(embedding_service, persist_path=str(tmp_path)), BM25Index(), reranker=None
    )
    response = restarted.retrieve(RetrievalRequest(query="SOC 2 Type II", top_k=4))
    assert any(r.chunk_id == "security_0" and r.sparse_score is not None for r in response.results)


def test_rebuild_keyword_index_is_repeatable(embedding_service, chunks, tmp_path):
    retriever = _first_run(embedding_service, chunks, str(tmp_path))
    assert retriever.rebuild_keyword_index() == 4
    assert retriever.rebuild_keyword_index() == 4


def test_restart_with_empty_store_leaves_keyword_index_empty(embedding_service, tmp_path):
    retriever = HybridRetriever(
        VectorStore(embedding_service, persist_path=str(tmp_path)), BM25Index(), reranker=None
    )
    assert retriever.bm25_index.count() == 0


def test_delete_after_restart_removes_from_both_indexes(embedding_service, chunks, tmp_path):
    _first_run(embedding_service, chunks, str(tmp_path))
    restarted = HybridRetriever(
        VectorStore(embedding_service, persist_path=str(tmp_path)), BM25Index(), reranker=None
    )
    assert restarted.delete_document("security") == 1
    assert restarted.vector_store.count() == 3
    assert restarted.bm25_index.count() == 3
    assert "security_0" not in {r.chunk_id for r in restarted.bm25_index.search("SOC 2 Type II")}