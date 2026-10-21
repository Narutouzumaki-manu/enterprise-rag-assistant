import time

import pytest

from .mocks import MockIngestion


def test_success_builds_chunks_and_takes_id_from_filename():
    result = MockIngestion(chunk_count=2).ingest_document("no/such/folder/q3_report.pdf")
    assert result.document_id == "q3_report"
    assert result.filename == "q3_report.pdf"
    assert result.status == "success"
    assert len(result.chunks) == 2
    assert result.error_message is None


def test_failed_has_no_chunks_and_a_readable_message():
    result = MockIngestion(status="failed").ingest_document("a.pdf")
    assert result.status == "failed"
    assert result.chunks == []
    assert result.error_message


def test_partial_has_chunks_and_a_message():
    result = MockIngestion(status="partial", chunk_count=2).ingest_document("a.pdf")
    assert len(result.chunks) == 2
    assert result.error_message


def test_duplicate_has_no_chunks():
    result = MockIngestion(status="duplicate").ingest_document("a.pdf")
    assert result.status == "duplicate"
    assert result.chunks == []


def test_delay_really_blocks():
    start = time.monotonic()
    MockIngestion(delay=0.1).ingest_document("a.pdf")
    assert time.monotonic() - start >= 0.1


def test_error_is_raised():
    with pytest.raises(RuntimeError):
        MockIngestion(error=RuntimeError("boom")).ingest_document("a.pdf")


def test_calls_are_recorded():
    mock = MockIngestion()
    mock.ingest_document("a.pdf")
    mock.ingest_document("b.docx")
    assert mock.calls == ["a.pdf", "b.docx"]