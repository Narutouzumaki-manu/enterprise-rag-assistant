import asyncio
import json
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.main import create_app
from app.api.streaming import format_comment, format_sse
from app.core.config import Settings

from .mocks import MockAgent


def _make_app(agent=None, settings: Settings | None = None):
    return create_app(agent=agent, settings=settings or Settings(_env_file=None))


def _client(app) -> AsyncClient:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


def _body(**overrides) -> dict:
    body = {"session_id": str(uuid4()), "query": "hi"}
    body.update(overrides)
    return body


def _parse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.split("\n\n"):
        block = block.strip("\n")
        if not block or block.startswith(":"):
            continue  # skip blanks and keep-alive comments
        lines = block.split("\n")
        name = lines[0].removeprefix("event: ")
        data = json.loads(lines[1].removeprefix("data: "))
        events.append((name, data))
    return events


def test_format_sse_is_exact():
    assert format_sse("token", {"text": "Hi "}) == 'event: token\ndata: {"text": "Hi "}\n\n'


def test_format_sse_keeps_unicode_and_comment_format():
    assert "₹" in format_sse("token", {"text": "₹5"})
    assert format_comment() == ": keep-alive\n\n"


@pytest.mark.asyncio
async def test_stream_has_the_right_headers_events_and_frees_the_slot():
    app = _make_app(MockAgent())
    async with _client(app) as client:
        r = await client.post("/chat/stream", json=_body())
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["x-accel-buffering"] == "no"

    events = _parse(r.text)
    names = [name for name, _ in events]
    assert names == [
        "status", "status", "status", "status",
        "source", "token", "token", "verification", "done",
    ]
    assert "".join(d["text"] for n, d in events if n == "token") == "Mock answer."
    UUID(events[-1][1]["request_id"])
    await asyncio.sleep(0)
    assert app.state.runtime.in_use == 0


@pytest.mark.asyncio
async def test_blank_query_is_a_normal_422_not_a_stream():
    agent = MockAgent()
    async with _client(_make_app(agent)) as client:
        r = await client.post("/chat/stream", json=_body(query="   "))
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["code"] == "VALIDATION_ERROR"
    assert agent.calls == []


@pytest.mark.asyncio
async def test_busy_service_is_a_real_503_before_any_stream():
    settings = Settings(_env_file=None, agent_max_concurrent=1, agent_wait_seconds=0.05)
    async with _client(_make_app(MockAgent(delay=0.3), settings)) as client:
        first = asyncio.create_task(client.post("/chat/stream", json=_body()))
        await asyncio.sleep(0.05)
        second = await client.post("/chat/stream", json=_body())
        first_response = await first
    assert second.status_code == 503
    assert second.json()["code"] == "AGENT_BUSY"
    assert "retry-after" in second.headers
    assert first_response.status_code == 200
    assert _parse(first_response.text)[-1][0] == "done"


@pytest.mark.asyncio
async def test_no_agent_gives_503_dependency_unavailable():
    async with _client(_make_app(agent=None)) as client:
        r = await client.post("/chat/stream", json=_body())
    assert r.status_code == 503
    assert r.json()["code"] == "DEPENDENCY_UNAVAILABLE"


@pytest.mark.asyncio
async def test_agent_error_ends_the_stream_with_an_error_event():
    async with _client(_make_app(MockAgent(error=RuntimeError("secret detail")))) as client:
        r = await client.post("/chat/stream", json=_body())
    assert r.status_code == 200  # the stream had already started
    events = _parse(r.text)
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "INTERNAL_ERROR"
    assert "done" not in [name for name, _ in events]
    assert "secret detail" not in r.text


@pytest.mark.asyncio
async def test_keep_alive_comments_appear_while_the_agent_is_silent():
    settings = Settings(_env_file=None, sse_heartbeat_seconds=0.05)
    async with _client(_make_app(MockAgent(delay=0.4), settings)) as client:
        r = await client.post("/chat/stream", json=_body())
    assert ": keep-alive" in r.text
    assert _parse(r.text)[-1][0] == "done"