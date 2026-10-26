import pytest

from app.api.startup import INTERRUPTED, sweep_interrupted_documents
from app.db import repository


class FakeRetriever:
    def __init__(self):
        self.deleted = []

    def delete_document(self, document_id):
        self.deleted.append(document_id)


async def make_document(session_factory, document_id, status, deleted=False):
    async with session_factory() as db:
        await repository.create_document(
            db,
            document_id=document_id,
            filename=f"{document_id}.pdf",
            content_hash=f"hash-{document_id}",
            source_type="pdf",
            status=status,
            uploaded_by=None,
        )
        if deleted:
            await repository.soft_delete_document(db, document_id)


async def status_of(session_factory, document_id):
    async with session_factory() as db:
        document = await repository.get_document(db, document_id)
        return document.status, document.error_message


@pytest.mark.asyncio
async def test_sweep_fails_only_in_progress_documents(session_factory):
    for document_id, status in [
        ("sw-queued", "queued"),
        ("sw-parsing", "parsing"),
        ("sw-indexing", "indexing"),
        ("sw-success", "success"),
        ("sw-partial", "partial"),
        ("sw-failed", "failed"),
    ]:
        await make_document(session_factory, document_id, status)
    await make_document(session_factory, "sw-deleted", "parsing", deleted=True)

    retriever = FakeRetriever()
    count = await sweep_interrupted_documents(session_factory, retriever)

    assert count == 3
    for document_id in ("sw-queued", "sw-parsing", "sw-indexing"):
        assert await status_of(session_factory, document_id) == ("failed", INTERRUPTED)
    assert (await status_of(session_factory, "sw-success"))[0] == "success"
    assert (await status_of(session_factory, "sw-partial"))[0] == "partial"
    assert (await status_of(session_factory, "sw-failed"))[0] == "failed"
    assert retriever.deleted == ["sw-indexing"]  # only the one that could be in the index


@pytest.mark.asyncio
async def test_sweep_with_nothing_to_do_changes_nothing(session_factory):
    await make_document(session_factory, "sw-ok", "success")
    assert await sweep_interrupted_documents(session_factory, FakeRetriever()) == 0
    assert (await status_of(session_factory, "sw-ok"))[0] == "success"