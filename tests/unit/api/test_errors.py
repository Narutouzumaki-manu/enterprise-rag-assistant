from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.main import create_app
from app.api.runtime import AgentBusyError
from app.core.config import get_settings
from app.schemas.api import ChatRequest


def _app():
    app = create_app()

    @app.get("/test/busy")
    async def busy():
        raise AgentBusyError("The service is busy. Please try again shortly.")

    @app.get("/test/boom")
    async def boom():
        raise RuntimeError("secret internal detail")

    @app.post("/test/chat")
    async def chat(body: ChatRequest):
        return {"ok": True}

    return app


async def _call(method: str, path: str, **kwargs):
    transport = ASGITransport(app=_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


@pytest.mark.asyncio
async def test_busy_gives_503_with_retry_after():
    r = await _call("GET", "/test/busy")
    assert r.status_code == 503
    assert r.json() == {
        "error": "The service is busy. Please try again shortly.",
        "code": "AGENT_BUSY",
    }
    assert r.headers["retry-after"] == str(get_settings().retry_after_seconds)


@pytest.mark.asyncio
async def test_validation_error_is_structured_and_does_not_echo_input():
    body = {"session_id": str(uuid4()), "query": "hi", "top_k": 21}
    r = await _call("POST", "/test/chat", json=body)
    assert r.status_code == 422
    data = r.json()
    assert set(data) == {"error", "code"}
    assert data["code"] == "VALIDATION_ERROR"
    assert "top_k" in data["error"]
    assert "21" not in data["error"]


@pytest.mark.asyncio
async def test_missing_field_is_a_validation_error():
    r = await _call("POST", "/test/chat", json={})
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_unexpected_exception_gives_generic_500_without_details():
    r = await _call("GET", "/test/boom")
    assert r.status_code == 500
    assert r.json()["code"] == "INTERNAL_ERROR"
    assert "secret internal detail" not in r.text
    assert "Traceback" not in r.text


@pytest.mark.asyncio
async def test_unknown_route_is_a_structured_404():
    r = await _call("GET", "/nope")
    assert r.status_code == 404
    assert r.json() == {"error": "Not Found", "code": "NOT_FOUND"}


@pytest.mark.asyncio
async def test_wrong_method_is_a_structured_405():
    r = await _call("POST", "/health")
    assert r.status_code == 405
    assert r.json()["code"] == "BAD_REQUEST"