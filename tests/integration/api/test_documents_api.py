import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api.main import create_app
from app.api.uploads import MIB
from app.core.config import Settings
from app.core.security import create_access_token
from app.db import models, repository

from .stubs import StubIngestion, StubRetriever

TOKEN_SETTINGS = Settings(_env_file=None)
PDF = b"%PDF-1.4\nfirst document"


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None, agent_enabled=False,
        upload_dir=str(tmp_path / "uploads"), max_upload_mb=1,
    )


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id, TOKEN_SETTINGS)}"}


def _http(app) -> AsyncClient:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


def _stored_files(tmp_path) -> list[str]:
    folder = tmp_path / "uploads"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


async def _count(session, table) -> int:
    return await session.scalar(select(func.count()).select_from(table))


async def _upload(client, user, data=PDF, name="report.pdf"):
    return await client.post(
        "/documents/upload",
        files={"file": (name, data, "application/octet-stream")},
        headers=_auth(user),
    )


async def _finish(app) -> None:
    await asyncio.gather(*list(app.state.background_tasks))


@pytest.fixture
def ingestion():
    return StubIngestion()


@pytest.fixture
def retriever():
    return StubRetriever()


@pytest.fixture
def app(session_factory, ingestion, retriever, tmp_path):
    return create_app(
        settings=_settings(tmp_path),
        session_factory=session_factory,
        retriever=retriever,
        ingest=ingestion,
    )


@pytest_asyncio.fixture
async def client(app):
    async with _http(app) as http:
        yield http


@pytest_asyncio.fixture
async def alice(session):
    return await repository.create_user(session, "alice@example.com", "not-a-real-hash")


@pytest_asyncio.fixture
async def bob(session):
    return await repository.create_user(session, "bob@example.com", "not-a-real-hash")


@pytest.mark.asyncio
async def test_an_upload_is_accepted_stored_processed_and_visible(client, app, session, alice, retriever, tmp_path):
    r = await _upload(client, alice)
    assert r.status_code == 202
    data = r.json()
    assert data["status"] == "queued" and data["filename"] == "report.pdf"
    assert _stored_files(tmp_path) == [f"{data['document_id']}.pdf"]

    await _finish(app)
    detail = (await client.get(f"/documents/{data['document_id']}", headers=_auth(alice))).json()
    assert detail["status"] == "success"
    assert detail["source_type"] == "pdf" and detail["uploaded_by_me"] is True
    assert len(retriever.indexed) == 3
    assert await _count(session, models.DocumentChunk) == 3


@pytest.mark.asyncio
async def test_an_upload_without_a_token_is_a_401_and_stores_nothing(client, tmp_path):
    r = await client.post("/documents/upload", files={"file": ("report.pdf", PDF, "application/pdf")})
    assert r.status_code == 401
    assert _stored_files(tmp_path) == []


@pytest.mark.asyncio
async def test_an_unsupported_type_is_refused_and_nothing_is_kept(client, session, alice, tmp_path):
    r = await _upload(client, alice, b"hello", "malware.exe")
    assert r.status_code == 415
    assert r.json()["code"] == "UNSUPPORTED_FILE_TYPE"
    assert _stored_files(tmp_path) == []
    assert await _count(session, models.Document) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [3 * MIB, int(1.5 * MIB)])
async def test_a_file_over_the_limit_is_refused_and_nothing_is_kept(client, session, alice, tmp_path, size):
    # 3 MiB is stopped early by the middleware; 1.5 MiB passes it and is counted while it is read
    r = await _upload(client, alice, b"%PDF-" + b"x" * size, "big.pdf")
    assert r.status_code == 413
    assert r.json()["code"] == "FILE_TOO_LARGE"
    assert _stored_files(tmp_path) == []
    assert await _count(session, models.Document) == 0


@pytest.mark.asyncio
async def test_the_same_file_twice_is_a_duplicate_of_the_first(client, app, session, alice, tmp_path):
    first = await _upload(client, alice)
    second = await _upload(client, alice)
    assert (first.status_code, second.status_code) == (202, 200)
    assert second.json()["status"] == "duplicate"
    assert second.json()["document_id"] == first.json()["document_id"]
    await _finish(app)
    assert len(_stored_files(tmp_path)) == 1
    assert await _count(session, models.Document) == 1


@pytest.mark.asyncio
async def test_a_failed_file_can_be_uploaded_again_and_replaces_the_failed_one(client, app, alice, ingestion, tmp_path):
    ingestion.status, ingestion.error_message = "failed", "Could not read the file."
    first = (await _upload(client, alice)).json()
    await _finish(app)
    failed = (await client.get(f"/documents/{first['document_id']}", headers=_auth(alice))).json()
    assert failed["status"] == "failed" and failed["error_message"] == "Could not read the file."

    ingestion.status, ingestion.error_message = "success", None
    second_response = await _upload(client, alice)
    second = second_response.json()
    assert second_response.status_code == 202
    assert second["document_id"] != first["document_id"]
    await _finish(app)

    assert (await client.get(f"/documents/{first['document_id']}", headers=_auth(alice))).status_code == 404
    assert (await client.get(f"/documents/{second['document_id']}", headers=_auth(alice))).json()["status"] == "success"
    assert _stored_files(tmp_path) == [f"{second['document_id']}.pdf"]


@pytest.mark.asyncio
async def test_without_a_retriever_uploads_are_a_503_and_nothing_is_stored(session_factory, alice, tmp_path):
    app = create_app(settings=_settings(tmp_path), session_factory=session_factory)
    async with _http(app) as client:
        r = await _upload(client, alice)
    assert r.status_code == 503
    assert r.json()["code"] == "DEPENDENCY_UNAVAILABLE"
    assert _stored_files(tmp_path) == []


@pytest.mark.asyncio
async def test_the_list_shows_everyones_documents_newest_first_with_ownership(client, app, alice, bob):
    await _upload(client, alice, PDF, "alice.pdf")
    await _upload(client, bob, b"%PDF-1.4\nbob's document", "bob.pdf")
    await _finish(app)
    r = await client.get("/documents", headers=_auth(alice))
    assert [(d["filename"], d["uploaded_by_me"]) for d in r.json()] == [
        ("bob.pdf", False),
        ("alice.pdf", True),
    ]


@pytest.mark.asyncio
async def test_an_unknown_document_is_a_404(client, alice):
    r = await client.get("/documents/does-not-exist", headers=_auth(alice))
    assert r.status_code == 404
    assert r.json() == {"error": "Document not found.", "code": "NOT_FOUND"}


@pytest.mark.asyncio
async def test_the_uploader_can_delete_and_the_same_file_can_come_back(client, app, alice, retriever, tmp_path):
    document_id = (await _upload(client, alice)).json()["document_id"]
    await _finish(app)

    r = await client.delete(f"/documents/{document_id}", headers=_auth(alice))
    assert r.status_code == 204
    assert retriever.deleted == [document_id]
    assert (await client.get(f"/documents/{document_id}", headers=_auth(alice))).status_code == 404
    assert _stored_files(tmp_path) == []

    again = await _upload(client, alice)
    assert again.status_code == 202  # the fingerprint is free again
    await _finish(app)


@pytest.mark.asyncio
async def test_someone_else_cannot_delete_a_document(client, app, alice, bob, retriever):
    document_id = (await _upload(client, alice)).json()["document_id"]
    await _finish(app)

    r = await client.delete(f"/documents/{document_id}", headers=_auth(bob))
    assert r.status_code == 403
    assert r.json()["code"] == "FORBIDDEN"
    assert retriever.deleted == []
    assert (await client.get(f"/documents/{document_id}", headers=_auth(alice))).json()["status"] == "success"


@pytest.mark.asyncio
async def test_a_document_that_is_still_being_processed_cannot_be_deleted(client, app, alice, ingestion, retriever):
    ingestion.delay = 0.3
    document_id = (await _upload(client, alice)).json()["document_id"]

    r = await client.delete(f"/documents/{document_id}", headers=_auth(alice))
    assert r.status_code == 409
    assert r.json()["code"] == "CONFLICT"
    assert retriever.deleted == []
    await _finish(app)


@pytest.mark.asyncio
async def test_if_the_index_cannot_remove_the_document_it_stays(client, app, alice, retriever, tmp_path):
    document_id = (await _upload(client, alice)).json()["document_id"]
    await _finish(app)
    retriever.delete_error = RuntimeError("index down")

    r = await client.delete(f"/documents/{document_id}", headers=_auth(alice))
    assert r.status_code == 503
    assert r.json()["code"] == "DEPENDENCY_UNAVAILABLE"
    assert (await client.get(f"/documents/{document_id}", headers=_auth(alice))).json()["status"] == "success"
    assert _stored_files(tmp_path) == [f"{document_id}.pdf"]