import pytest

from app.ingestion.dedupe import clear_registry
from app.ingestion.pipeline import detect_source_type, ingest_document
from app.schemas.document import SourceType


@pytest.fixture(autouse=True)
def reset_registry():
    """Ensures dedupe state doesn't leak between tests."""
    clear_registry()
    yield
    clear_registry()


def test_detect_source_type_csv():
    assert detect_source_type("file.csv") == SourceType.CSV


def test_detect_source_type_docx():
    assert detect_source_type("file.docx") == SourceType.DOCX


def test_detect_source_type_pdf():
    assert detect_source_type("file.pdf") == SourceType.PDF


def test_detect_source_type_unsupported_returns_none():
    assert detect_source_type("file.txt") is None


def test_ingest_document_csv_succeeds():
    result = ingest_document("tests/fixtures/sample.csv")
    assert result.status == "success"
    assert len(result.chunks) > 0


def test_ingest_document_docx_succeeds():
    result = ingest_document("tests/fixtures/sample.docx")
    assert result.status == "success"
    assert len(result.chunks) > 0


def test_ingest_document_pdf_succeeds():
    result = ingest_document("tests/fixtures/sample.pdf")
    assert result.status == "success"
    assert len(result.chunks) > 0


def test_ingest_document_missing_file_fails_gracefully():
    result = ingest_document("tests/fixtures/does_not_exist.pdf")
    assert result.status == "failed"
    assert result.error_message is not None
    assert len(result.chunks) == 0


def test_ingest_document_unsupported_extension_fails_gracefully():
    result = ingest_document("tests/fixtures/sample.txt")
    assert result.status == "failed"
    assert "Unsupported" in result.error_message


def test_ingest_document_detects_duplicate_on_second_call():
    first = ingest_document("tests/fixtures/sample.csv")
    second = ingest_document("tests/fixtures/sample.csv")

    assert first.status == "success"
    assert second.status == "duplicate"
    assert second.error_message is not None


def test_ingest_document_never_raises_unhandled_exception():
    """Even a completely bogus path should return a result, not throw."""
    try:
        result = ingest_document("this/path/does/not/exist/at/all.pdf")
        assert result.status == "failed"
    except Exception:
        pytest.fail("ingest_document raised an unhandled exception")