import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_current_user
from app.api.main import create_app
from app.api.uploads import MIB
from app.core.config import Settings

from .mocks import FakeUser


def _client(app) -> AsyncClient:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


def _app():
    app = create_app(settings=Settings(_env_file=None, max_upload_mb=1, agent_enabled=False))
    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    return app


@pytest.mark.asyncio
async def test_a_clearly_oversized_upload_is_refused_before_the_route_runs():
    files = {"file": ("big.pdf", b"%PDF-" + b"x" * (3 * MIB), "application/pdf")}
    async with _client(_app()) as client:
        r = await client.post("/documents/upload", files=files)
    assert r.status_code == 413
    assert r.json()["code"] == "FILE_TOO_LARGE"


@pytest.mark.asyncio
async def test_a_normal_upload_gets_past_the_size_check():
    files = {"file": ("small.pdf", b"%PDF-1.4 small", "application/pdf")}
    async with _client(_app()) as client:
        r = await client.post("/documents/upload", files=files)
    assert r.status_code == 503  # no ingestion runner in this app: it got as far as the route
    assert r.json()["code"] == "DEPENDENCY_UNAVAILABLE"