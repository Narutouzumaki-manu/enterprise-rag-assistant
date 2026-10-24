
import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.api.ingestion_service import FAILED_GENERIC, INDEXING_FAILED, NO_TEXT, IngestionRunner
from app.db import models, repository
from .stubs import StubIngestion, StubRetriever


def _runner(session_factory, ingestion, retriever, max_concurrent=1) -> IngestionRunner:
    return IngestionRunner(session_factory, retriever, ingestion, max_concurrent)


async def _queued(session, document_id="d1"):
    return await repository.create_document(
        session, document_id=document_id, filename="report.pdf",
        content_hash=f"hash-{document_id}", source_type="pdf",
        status="queued", uploaded_by=None,
    )


async def _chunk_rows(session, document_id="d1"):
    result = await session.execute(
        select(models.DocumentChunk)
        .where(models.DocumentChunk.document_id == document_id)
        .order_by(models.DocumentChunk.chunk_id)
    )
    return result.scalars().all()


@pytest.mark.asyncio
async def test_a_good_file_ends_as_success_with_chunks_saved_and_indexed(session, session_factory):
    document = await _queued(session)
    retriever = StubRetriever()
    await _runner(session_factory, StubIngestion(chunk_count=3), retriever).process(
        "d1", Path("uploads/d1.pdf")
    )
    await session.refresh(document)
    assert document.status == "success"
    assert document.error_message is None
    rows = await _chunk_rows(session)
    assert [r.chunk_id for r in rows] == ["d1_chunk_0", "d1_chunk_1", "d1_chunk_2"]
    assert (rows[0].page_number, rows[0].section_title, rows[0].text) == (1, "Intro", "Chunk 0 text.")
    assert retriever.indexed == [r.chunk_id for r in rows]


@pytest.mark.asyncio
async def test_the_status_moves_through_parsing_and_indexing(session, session_factory, monkeypatch):
    await _queued(session)
    seen: list[str] = []
    original = repository.set_document_status

    async def recording(db, document_id, status, error_message=None):
        seen.append(status)
        await original(db, document_id, status, error_message)

    monkeypatch.setattr(repository, "set_document_status", recording)
    await _runner(session_factory, StubIngestion(), StubRetriever()).process("d1", Path("d1.pdf"))
    assert seen == ["parsing", "indexing"]  # the final status is written with the chunks


@pytest.mark.asyncio
async def test_a_partial_result_keeps_its_chunks_and_its_message(session, session_factory):
    document = await _queued(session)
    ingestion = StubIngestion(status="partial", chunk_count=2, error_message="Some pages could not be read.")
    retriever = StubRetriever()
    await _runner(session_factory, ingestion, retriever).process("d1", Path("d1.pdf"))
    await session.refresh(document)
    assert document.status == "partial"
    assert document.error_message == "Some pages could not be read."
    assert len(await _chunk_rows(session)) == 2 and len(retriever.indexed) == 2


@pytest.mark.asyncio
async def test_a_failed_file_shows_the_pipelines_own_message_and_nothing_is_indexed(session, session_factory):
    document = await _queued(session)
    ingestion = StubIngestion(status="failed", error_message="The file is password-protected.")
    retriever = StubRetriever()
    await _runner(session_factory, ingestion, retriever).process("d1", Path("d1.pdf"))
    await session.refresh(document)
    assert document.status == "failed"
    assert document.error_message == "The file is password-protected."
    assert retriever.indexed == [] and await _chunk_rows(session) == []


@pytest.mark.asyncio
async def test_a_result_without_chunks_is_a_failure(session, session_factory):
    document = await _queued(session)
    await _runner(session_factory, StubIngestion(chunk_count=0), StubRetriever()).process(
        "d1", Path("d1.pdf")
    )
    await session.refresh(document)
    assert (document.status, document.error_message) == ("failed", NO_TEXT)


@pytest.mark.asyncio
async def test_an_unexpected_error_never_leaves_the_document_stuck(session, session_factory):
    document = await _queued(session)
    ingestion = StubIngestion(error=RuntimeError("boom with internal details"))
    await _runner(session_factory, ingestion, StubRetriever()).process("d1", Path("d1.pdf"))
    await session.refresh(document)
    assert (document.status, document.error_message) == ("failed", FAILED_GENERIC)


@pytest.mark.asyncio
async def test_an_indexing_failure_cleans_the_index_and_saves_no_rows(session, session_factory):
    document = await _queued(session)
    retriever = StubRetriever(index_error=RuntimeError("index down"))
    await _runner(session_factory, StubIngestion(), retriever).process("d1", Path("d1.pdf"))
    await session.refresh(document)
    assert (document.status, document.error_message) == ("failed", INDEXING_FAILED)
    assert retriever.deleted == ["d1"]
    assert await _chunk_rows(session) == []


@pytest.mark.asyncio
async def test_a_failure_while_saving_the_rows_cleans_the_index(session, session_factory, monkeypatch):
    document = await _queued(session)

    async def cannot_save(*args, **kwargs):
        raise RuntimeError("database dropped")

    monkeypatch.setattr(repository, "complete_document", cannot_save)
    retriever = StubRetriever()
    await _runner(session_factory, StubIngestion(), retriever).process("d1", Path("d1.pdf"))
    await session.refresh(document)
    assert (document.status, document.error_message) == ("failed", FAILED_GENERIC)
    assert retriever.deleted == ["d1"]


@pytest.mark.asyncio
async def test_a_result_with_a_different_document_id_is_refused(session, session_factory):
    document = await _queued(session)
    retriever = StubRetriever()
    await _runner(session_factory, StubIngestion(wrong_id=True), retriever).process(
        "d1", Path("d1.pdf")
    )
    await session.refresh(document)
    assert document.status == "failed"
    assert retriever.indexed == []


@pytest.mark.asyncio
async def test_only_one_document_is_processed_at_a_time_by_default(session, session_factory):
    for i in range(3):
        await _queued(session, f"d{i}")
    ingestion = StubIngestion(delay=0.05)
    runner = _runner(session_factory, ingestion, StubRetriever(), max_concurrent=1)
    await asyncio.gather(*(runner.process(f"d{i}", Path(f"d{i}.pdf")) for i in range(3)))
    assert ingestion.peak == 1
    assert await session.scalar(select(func.count()).select_from(models.DocumentChunk)) == 9
