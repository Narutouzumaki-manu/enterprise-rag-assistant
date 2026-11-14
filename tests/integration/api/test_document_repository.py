from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.db import repository


async def _make(session, document_id="d1", content_hash="h1", uploaded_by=None, status="queued"):
    return await repository.create_document(
        session,
        document_id=document_id,
        filename=f"{document_id}.pdf",
        content_hash=content_hash,
        source_type="pdf",
        status=status,
        uploaded_by=uploaded_by,
    )


@pytest.mark.asyncio
async def test_a_created_document_has_its_fields_and_timestamps(session):
    user = await repository.create_user(session, "a@example.com", "not-a-real-hash")
    document = await _make(session, uploaded_by=user.id)
    assert document.document_id == "d1"
    assert document.uploaded_by == user.id
    assert document.status == "queued"
    assert document.version == 1
    assert document.created_at is not None and document.deleted_at is None


@pytest.mark.asyncio
async def test_a_document_can_have_no_uploader(session):
    assert (await _make(session, uploaded_by=None)).uploaded_by is None


@pytest.mark.asyncio
async def test_an_unknown_uploader_is_rejected(session):
    with pytest.raises(IntegrityError):
        await _make(session, uploaded_by=uuid4())


@pytest.mark.asyncio
async def test_the_hash_lookup_finds_live_documents_only(session):
    await _make(session, "d1", "h1")
    assert (await repository.get_active_document_by_hash(session, "h1")).document_id == "d1"
    assert await repository.get_active_document_by_hash(session, "other") is None

    await repository.soft_delete_document(session, "d1")
    assert await repository.get_active_document_by_hash(session, "h1") is None


@pytest.mark.asyncio
async def test_a_second_live_document_with_the_same_hash_is_rejected_until_the_first_is_deleted(session):
    await _make(session, "d1", "h1")
    with pytest.raises(IntegrityError):
        await _make(session, "d2", "h1")

    await repository.soft_delete_document(session, "d1")
    await _make(session, "d3", "h1")  # re-uploading after a delete is allowed


@pytest.mark.asyncio
async def test_the_list_is_newest_first_and_skips_deleted_documents(session):
    await _make(session, "old", "h1")
    await _make(session, "new", "h2")
    await _make(session, "gone", "h3")
    await repository.soft_delete_document(session, "gone")
    assert [d.document_id for d in await repository.list_documents(session)] == ["new", "old"]


@pytest.mark.asyncio
async def test_get_document_hides_unknown_and_deleted_documents(session):
    await _make(session, "d1", "h1")
    assert (await repository.get_document(session, "d1")).document_id == "d1"
    assert await repository.get_document(session, "missing") is None
    await repository.soft_delete_document(session, "d1")
    assert await repository.get_document(session, "d1") is None


@pytest.mark.asyncio
async def test_status_and_error_message_are_updated(session):
    document = await _make(session, "d1", "h1")
    await repository.set_document_status(session, "d1", "failed", "Could not read the file.")
    await session.refresh(document)
    assert document.status == "failed"
    assert document.error_message == "Could not read the file."


@pytest.mark.asyncio
async def test_soft_delete_reports_whether_anything_was_deleted(session):
    await _make(session, "d1", "h1")
    assert await repository.soft_delete_document(session, "d1") is True
    assert await repository.soft_delete_document(session, "d1") is False
    assert await repository.soft_delete_document(session, "missing") is False