
import asyncio
import json
import time

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api.exchange import ChatStore, open_saved_stream
from app.api.main import create_app
from app.api.runtime import AgentRuntime
from app.core.config import Settings
from app.core.security import create_access_token
from app.db import models, repository
from app.schemas.agent import AgentResponse, AgentStep, AgentStepType, Citation

SETTINGS = Settings(_env_file=None, agent_enabled=False)


class StubAgent:
    """Blocks like the real agent. Its citation points at document 'doc_1'."""

    def __init__(self, delay: float = 0.0):
        self.delay = delay
        self.calls: list[str] = []

    def _response(self) -> AgentResponse:
        return AgentResponse(
            answer="Stub answer.",
            citations=[
                Citation(
                    chunk_id="c1",
                    document_id="doc_1",
                    page_number=3,
                    text_snippet="snippet",
                )
            ],
            trace=[AgentStep(step_type=AgentStepType.PLAN, content="Plan")],
            verification_status="verified",
            confidence=0.95,
            latency_ms=10.0,
        )

    def run(self, query, session_context=None, top_k=None) -> AgentResponse:
        self.calls.append(query)
        time.sleep(self.delay)
        return self._response()

    def run_streaming(self, query, session_context=None, top_k=None):
        self.calls.append(query)
        yield AgentStep(step_type=AgentStepType.PLAN, content="Plan")
        time.sleep(self.delay)
        yield self._response()


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id, SETTINGS)}"}


def _http(app) -> AsyncClient:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


def _body(chat, query: str = "What grew?") -> dict:
    return {"session_id": str(chat.id), "query": query}


def _parse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.split("\n\n"):
        block = block.strip("\n")
        if not block or block.startswith(":"):
            continue
        lines = block.split("\n")
        events.append(
            (
                lines[0].removeprefix("event: "),
                json.loads(lines[1].removeprefix("data: ")),
            )
        )
    return events


async def _message_count(session) -> int:
    return await session.scalar(
        select(func.count()).select_from(models.Message)
    )


@pytest.fixture
def agent():
    return StubAgent()


@pytest_asyncio.fixture
async def client(session_factory, agent):
    app = create_app(
        agent=agent,
        settings=SETTINGS,
        session_factory=session_factory,
    )
    async with _http(app) as http:
        yield http


@pytest_asyncio.fixture
async def alice(session):
    return await repository.create_user(
        session, "alice@example.com", "not-a-real-hash"
    )


@pytest_asyncio.fixture
async def bob(session):
    return await repository.create_user(
        session, "bob@example.com", "not-a-real-hash"
    )


@pytest.mark.asyncio
async def test_chat_saves_the_exchange_and_fills_in_the_source_file(
    client, session, alice
):
    session.add(
        models.Document(
            document_id="doc_1",
            filename="annual_report.pdf",
            content_hash="h1",
            source_type="pdf",
            status="success",
        )
    )
    await session.commit()
    chat = await repository.create_session(session, alice.id)

    r = await client.post(
        "/chat", json=_body(chat), headers=_auth(alice)
    )

    assert r.status_code == 200
    assert r.json()["citations"][0]["source_file"] == "annual_report.pdf"
    history = await repository.load_history(session, chat.id)
    assert [h.message.role for h in history] == ["user", "assistant"]
    assert history[1].message.content == "Stub answer."
    assert history[1].citations[0].source_file == "annual_report.pdf"
    assert [t.step_type for t in history[1].traces] == ["plan"]
    await session.refresh(chat)
    assert chat.title == "What grew?"


@pytest.mark.asyncio
async def test_someone_elses_session_gives_404_and_nothing_runs_or_is_saved(
    client, session, agent, alice, bob
):
    bobs_chat = await repository.create_session(session, bob.id)
    r = await client.post(
        "/chat", json=_body(bobs_chat), headers=_auth(alice)
    )
    assert r.status_code == 404
    assert r.json() == {
        "error": "Session not found.",
        "code": "NOT_FOUND",
    }
    assert agent.calls == []
    assert await _message_count(session) == 0


@pytest.mark.asyncio
async def test_without_a_token_the_answer_is_401_and_nothing_runs(
    client, session, agent, alice
):
    chat = await repository.create_session(session, alice.id)
    r = await client.post("/chat", json=_body(chat))
    assert r.status_code == 401
    assert agent.calls == []


@pytest.mark.asyncio
async def test_a_failed_save_still_returns_the_answer(
    client, session, alice, monkeypatch
):
    chat = await repository.create_session(session, alice.id)

    async def database_dropped(*args, **kwargs):
        raise RuntimeError("database dropped")

    monkeypatch.setattr(repository, "save_exchange", database_dropped)

    r = await client.post(
        "/chat", json=_body(chat), headers=_auth(alice)
    )

    assert r.status_code == 200
    assert r.json()["answer"] == "Stub answer."
    assert await _message_count(session) == 0


@pytest.mark.asyncio
async def test_no_database_connection_is_held_while_the_agent_runs(
    engine, session_factory, session, alice
):
    app = create_app(
        agent=StubAgent(delay=0.4),
        settings=SETTINGS,
        session_factory=session_factory,
    )
    chat = await repository.create_session(session, alice.id)
    await session.commit()

    async with _http(app) as http:
        request = asyncio.create_task(
            http.post(
                "/chat",
                json=_body(chat),
                headers=_auth(alice),
            )
        )
        await asyncio.sleep(0.2)
        assert engine.pool.checkedout() == 0
        r = await request
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_a_stream_saves_the_exchange_and_the_source_event_has_the_filename(
    client, session, alice
):
    session.add(
        models.Document(
            document_id="doc_1",
            filename="annual_report.pdf",
            content_hash="h1",
            source_type="pdf",
            status="success",
        )
    )
    await session.commit()
    chat = await repository.create_session(session, alice.id)

    r = await client.post(
        "/chat/stream",
        json=_body(chat),
        headers=_auth(alice),
    )

    assert r.status_code == 200
    events = _parse(r.text)
    assert events[-1][0] == "done"
    assert (
        next(d for n, d in events if n == "source")["source_file"]
        == "annual_report.pdf"
    )
    history = await repository.load_history(session, chat.id)
    assert [h.message.content for h in history] == [
        "What grew?",
        "Stub answer.",
    ]


@pytest.mark.asyncio
async def test_a_stream_for_someone_elses_session_is_a_404_and_nothing_runs(
    client, session, agent, alice, bob
):
    bobs_chat = await repository.create_session(session, bob.id)
    r = await client.post(
        "/chat/stream",
        json=_body(bobs_chat),
        headers=_auth(alice),
    )
    assert r.status_code == 404
    assert agent.calls == []
    assert await _message_count(session) == 0


@pytest.mark.asyncio
async def test_a_stream_without_a_token_is_a_401(
    client, session, agent, alice
):
    chat = await repository.create_session(session, alice.id)
    r = await client.post("/chat/stream", json=_body(chat))
    assert r.status_code == 401
    assert agent.calls == []


@pytest.mark.asyncio
async def test_a_failed_save_still_streams_the_answer(
    client, session, alice, monkeypatch
):
    chat = await repository.create_session(session, alice.id)

    async def database_dropped(*args, **kwargs):
        raise RuntimeError("database dropped")

    monkeypatch.setattr(repository, "save_exchange", database_dropped)

    r = await client.post(
        "/chat/stream",
        json=_body(chat),
        headers=_auth(alice),
    )

    events = _parse(r.text)
    assert events[-1][0] == "done"
    assert "".join(
        d["text"] for n, d in events if n == "token"
    ) == "Stub answer."
    assert await _message_count(session) == 0


@pytest.mark.asyncio
async def test_the_exchange_is_saved_even_if_the_client_leaves_mid_stream(
    session_factory, session, alice
):
    chat = await repository.create_session(session, alice.id)
    await session.commit()

    runtime = AgentRuntime(
        StubAgent(delay=0.3),
        max_concurrent=1,
        wait_seconds=1,
    )
    tasks: set = set()

    events = await open_saved_stream(
        runtime,
        ChatStore(session_factory),
        tasks,
        chat.id,
        "What grew?",
        8,
        {},
    )
    assert isinstance(await anext(events), AgentStep)
    await events.aclose()

    assert await _message_count(session) == 0
    await asyncio.gather(*tasks)
    history = await repository.load_history(session, chat.id)
    assert [h.message.content for h in history] == [
        "What grew?",
        "Stub answer.",
    ]


@pytest.mark.asyncio
async def test_no_database_connection_is_held_while_a_stream_runs(
    engine, session_factory, session, alice
):
    app = create_app(
        agent=StubAgent(delay=0.4),
        settings=SETTINGS,
        session_factory=session_factory,
    )
    chat = await repository.create_session(session, alice.id)
    await session.commit()

    async with _http(app) as http:
        request = asyncio.create_task(
            http.post(
                "/chat/stream",
                json=_body(chat),
                headers=_auth(alice),
            )
        )
        await asyncio.sleep(0.2)
        assert engine.pool.checkedout() == 0
        r = await request
    assert r.status_code == 200
