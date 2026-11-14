import pytest

from app.ingestion.dedupe import clear_registry
from app.ingestion.pipeline import ingest_document
from app.schemas.document import IngestionResult


@pytest.fixture(autouse=True)
def reset_registry():
    clear_registry()
    yield
    clear_registry()


def test_full_ingestion_flow_across_all_formats():
    """
    Simulates a realistic sequence: ingest one of each supported format
    in a single session, confirming the whole pipeline works together,
    not just each piece in isolation.
    """
    files = [
        "tests/fixtures/sample.csv",
        "tests/fixtures/sample.docx",
        "tests/fixtures/sample.pdf",
    ]

    results = [ingest_document(f) for f in files]

    for result in results:
        assert isinstance(result, IngestionResult)
        assert result.status == "success"
        assert len(result.chunks) > 0

        for chunk in result.chunks:
            assert chunk.chunk_id
            assert chunk.token_count > 0
            assert chunk.metadata.content_hash


def test_reingesting_same_batch_all_show_as_duplicates():
    """
    After ingesting a batch once, running the exact same batch again
    should mark every file as a duplicate, not reprocess anything.
    """
    files = [
        "tests/fixtures/sample.csv",
        "tests/fixtures/sample.docx",
        "tests/fixtures/sample.pdf",
    ]

    first_pass = [ingest_document(f) for f in files]
    second_pass = [ingest_document(f) for f in files]

    assert all(r.status == "success" for r in first_pass)
    assert all(r.status == "duplicate" for r in second_pass)


def test_mixed_batch_with_one_bad_file_does_not_break_others():
    """
    A realistic failure scenario: one file in a batch is missing/invalid.
    The other valid files should still succeed independently.
    """
    files = [
        "tests/fixtures/sample.csv",
        "tests/fixtures/does_not_exist.pdf",
        "tests/fixtures/sample.pdf",
    ]

    results = [ingest_document(f) for f in files]

    assert results[0].status == "success"
    assert results[1].status == "failed"
    assert results[2].status == "success"