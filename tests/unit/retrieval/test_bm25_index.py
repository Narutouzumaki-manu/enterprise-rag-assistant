from datetime import datetime, timezone

import pytest

from app.retrieval.bm25_index import BM25Index
from app.schemas.document import Chunk, ChunkMetadata, SourceType


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
        make_chunk("The vendor holds a SOC 2 Type II certification, audited annually.", 0, "security", 4),
        make_chunk("The company cafeteria serves lunch from noon to 2 pm.", 0, "hr", 3),
        make_chunk("Employees get 24 days of paid leave per year.", 1, "hr", 5),
    ]


@pytest.fixture
def index(sample_chunks):
    idx = BM25Index()
    idx.upsert(sample_chunks)
    return idx


def test_upsert_adds_chunks(index):
    assert index.count() == 5


def test_upsert_same_chunks_twice_creates_no_duplicates(index, sample_chunks):
    index.upsert(sample_chunks)
    assert index.count() == 5


def test_upsert_empty_list_does_nothing():
    idx = BM25Index()
    idx.upsert([])
    assert idx.count() == 0


def test_exact_keyword_match_ranks_first(index):
    results = index.search("SOC 2 Type II", k=3)
    assert results[0].chunk_id == "security_0"


def test_query_with_no_matching_words_returns_empty(index):
    assert index.search("xylophone") == []


def test_search_is_case_insensitive(index):
    upper = index.search("SOC 2 TYPE II", k=1)
    lower = index.search("soc 2 type ii", k=1)
    assert upper[0].chunk_id == lower[0].chunk_id == "security_0"


def test_more_matching_words_ranks_higher(index):
    index.upsert([make_chunk("Cloud storage costs rose last year.", 0, "ops", 1)])
    results = index.search("cloud sales revenue", k=5)
    assert len(results) >= 2
    assert results[0].chunk_id == "finance_0"


def test_scores_are_sorted_descending(index):
    results = index.search("the company year", k=5)
    scores = [r.sparse_score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_search_carries_page_and_section_metadata(index):
    top = index.search("cloud sales", k=1)[0]
    assert top.page_number == 12
    assert top.section_title == "Revenue Overview"


def test_sparse_score_is_set_and_dense_score_is_none(index):
    top = index.search("cloud sales", k=1)[0]
    assert top.sparse_score is not None
    assert top.dense_score is None


def test_empty_query_returns_empty(index):
    assert index.search("") == []
    assert index.search("   ") == []


def test_punctuation_only_query_returns_empty(index):
    assert index.search("?!...") == []


def test_search_on_empty_index_returns_empty():
    assert BM25Index().search("anything") == []


def test_k_limits_number_of_results(index):
    assert len(index.search("the company year", k=1)) == 1


def test_filter_restricts_to_one_document(index):
    results = index.search("the company year", k=5, filters={"document_id": "hr"})
    assert len(results) == 2
    assert all(r.document_id == "hr" for r in results)


def test_filter_matching_nothing_returns_empty(index):
    assert index.search("revenue", filters={"document_id": "does_not_exist"}) == []


def test_delete_removes_only_target_document(index):
    removed = index.delete("finance")
    assert removed == 2
    assert index.count() == 3


def test_deleted_chunks_no_longer_surface(index):
    index.delete("finance")
    assert index.search("revenue cloud sales") == []


def test_delete_unknown_document_returns_zero(index):
    assert index.delete("does_not_exist") == 0
    assert index.count() == 5


def test_reupserting_changed_text_updates_the_index(index):
    index.upsert([make_chunk("Headcount grew by 40 engineers.", 0, "finance", 12)])
    assert index.search("cloud") == []
    assert index.search("headcount")[0].chunk_id == "finance_0"


def test_chunks_added_after_a_search_are_found(index):
    first = index.search("cloud")
    assert [r.chunk_id for r in first] == ["finance_0"]
    index.upsert([make_chunk("Cloud costs fell sharply.", 0, "ops", 2)])
    second = {r.chunk_id for r in index.search("cloud")}
    assert second == {"finance_0", "ops_0"}


def test_index_with_only_empty_text_chunks_does_not_crash():
    idx = BM25Index()
    idx.upsert([make_chunk("...", 0)])
    assert idx.search("anything") == []