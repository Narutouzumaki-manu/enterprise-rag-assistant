import math
from datetime import datetime, timezone

import pytest

from app.retrieval.embeddings import EmbeddingService
from app.schemas.document import Chunk, ChunkMetadata, SourceType


@pytest.fixture(scope="module")
def service():
    # scope="module" -> the model loads ONCE for all tests in this file (much faster)
    return EmbeddingService()


def make_chunk(text: str, position: int = 0) -> Chunk:
    """Build a mock Chunk matching Member 1's frozen schema."""
    return Chunk(
        chunk_id=f"test_doc_{position}",
        document_id="test_doc",
        text=text,
        token_count=len(text.split()),
        metadata=ChunkMetadata(
            document_id="test_doc",
            source_type=SourceType.PDF,
            page_number=1,
            content_hash="fakehash",
            ingested_at=datetime.now(timezone.utc),
        ),
    )


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def test_dimension_is_384(service):
    assert service.dimension == 384


def test_embed_query_returns_vector_of_correct_length(service):
    vector = service.embed_query("revenue growth")
    assert isinstance(vector, list)
    assert len(vector) == service.dimension


def test_embed_documents_returns_one_vector_per_chunk(service):
    chunks = [make_chunk("first chunk", 0), make_chunk("second chunk", 1), make_chunk("third chunk", 2)]
    vectors = service.embed_documents(chunks)
    assert len(vectors) == 3
    assert all(len(v) == service.dimension for v in vectors)


def test_embed_documents_empty_list_returns_empty(service):
    assert service.embed_documents([]) == []


def test_embed_query_empty_string_returns_empty(service):
    assert service.embed_query("") == []


def test_embed_query_whitespace_only_returns_empty(service):
    assert service.embed_query("   ") == []


def test_vectors_are_normalized(service):
    vector = service.embed_query("quarterly revenue report")
    length = math.sqrt(sum(x * x for x in vector))
    assert length == pytest.approx(1.0, abs=1e-4)


def test_same_text_gives_same_vector(service):
    v1 = service.embed_query("operating margin")
    v2 = service.embed_query("operating margin")
    assert v1 == pytest.approx(v2, abs=1e-6)


def test_similar_meaning_scores_higher_than_unrelated(service):
    query = service.embed_query("revenue growth")
    related = service.embed_query("sales increase")
    unrelated = service.embed_query("a cat sleeping on the sofa")
    assert dot(query, related) > dot(query, unrelated)