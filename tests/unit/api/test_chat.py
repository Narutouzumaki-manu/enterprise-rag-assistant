import asyncio
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.main import create_app
from app.core.config import Settings

from .mocks import MockAgent, make_response
from app.api.dependencies import get_current_user
from app.api.main import create_app
from app.core.config import Settings

from .mocks import FakeUser, MockAgent, MockChatStore, make_chat_app, make_response


def _client(agent=None, settings: Settings | None = None, store=None) -> AsyncClient:
    app = make_chat_app(agent=agent, settings=settings, store=store)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


def _body(**overrides) -> dict:
    body = {"session_id": str(uuid4()), "query": "hi"}
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_chat_returns_the_mapped_response():
    agent = MockAgent()
    async with _client(agent) as client:
        r = await client.post("/chat", json=_body())
    assert r.status_code == 200
    data = r.json()
    UUID(data["request_id"])  # a valid UUID
    assert data["answer"] == "Mock answer."
    assert data["verification_status"] == "verified"
    assert data["confidence"] == 0.95
    assert data["latency_ms"] == 10
    assert data["citations"] == [
        {
            "chunk_id": "chunk_1",
            "document_id": "doc_1",
            "page_number": 3,
            "text_snippet": "A mock snippet.",
            "source_file": None,
        }
    ]
    assert agent.calls == [{"query": "hi", "top_k": 8}]


@pytest.mark.asyncio
async def test_top_k_and_trimmed_query_reach_the_agent():
    agent = MockAgent()
    async with _client(agent) as client:
        await client.post("/chat", json=_body(query="  hello  ", top_k=5))
    assert agent.calls == [{"query": "hello", "top_k": 5}]


@pytest.mark.asyncio
async def test_blank_query_is_rejected_before_the_agent_is_called():
    agent = MockAgent()
    async with _client(agent) as client:
        r = await client.post("/chat", json=_body(query="   "))
    assert r.status_code == 422
    assert r.json() == {"error": "Query must not be blank.", "code": "VALIDATION_ERROR"}
    assert agent.calls == []


@pytest.mark.asyncio
async def test_too_long_query_is_rejected():
    agent = MockAgent()
    settings = Settings(_env_file=None, max_query_chars=10)
    async with _client(agent, settings) as client:
        r = await client.post("/chat", json=_body(query="x" * 11))
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"
    assert agent.calls == []


@pytest.mark.asyncio
async def test_invalid_session_id_is_rejected():
    async with _client(MockAgent()) as client:
        r = await client.post("/chat", json=_body(session_id="not-a-uuid"))
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_no_agent_gives_503_dependency_unavailable():
    async with _client(agent=None) as client:
        r = await client.post("/chat", json=_body())
    assert r.status_code == 503
    assert r.json()["code"] == "DEPENDENCY_UNAVAILABLE"


@pytest.mark.asyncio
async def test_busy_service_gives_503_agent_busy():
    settings = Settings(_env_file=None, agent_max_concurrent=1, agent_wait_seconds=0.05)
    async with _client(MockAgent(delay=0.3), settings) as client:
        first = asyncio.create_task(client.post("/chat", json=_body()))
        await asyncio.sleep(0.05)
        second = await client.post("/chat", json=_body())
        first_response = await first
    assert second.status_code == 503
    assert second.json()["code"] == "AGENT_BUSY"
    assert "retry-after" in second.headers
    assert first_response.status_code == 200


@pytest.mark.asyncio
async def test_unverified_answer_is_a_normal_200_response():
    refusal = make_response(
        answer="I don't have sufficient evidence in the provided documents.",
        status="unverified",
        confidence=0.0,
    )
    async with _client(MockAgent(response=refusal)) as client:
        r = await client.post("/chat", json=_body())
    assert r.status_code == 200
    assert r.json()["verification_status"] == "unverified"
    assert r.json()["confidence"] == 0.0


@pytest.mark.asyncio
async def test_unexpected_agent_error_gives_generic_500():
    async with _client(MockAgent(error=RuntimeError("secret detail"))) as client:
        r = await client.post("/chat", json=_body())
    assert r.status_code == 500
    assert r.json()["code"] == "INTERNAL_ERROR"
    assert "secret detail" not in r.text

@pytest.mark.asyncio
async def test_the_session_is_checked_and_the_exchange_is_saved():
    store = MockChatStore()
    body = _body()
    async with _client(MockAgent(), store=store) as client:
        r = await client.post("/chat", json=body)
    assert r.status_code == 200
    assert [sid for _, sid in store.ownership_checks] == [UUID(body["session_id"])]
    assert store.saved == [
        {"session_id": UUID(body["session_id"]), "question": "hi", "answer": "Mock answer."}
    ]


@pytest.mark.asyncio
async def test_someone_elses_session_gives_404_and_the_agent_is_never_called():
    agent, store = MockAgent(), MockChatStore(owns=False)
    async with _client(agent, store=store) as client:
        r = await client.post("/chat", json=_body())
    assert r.status_code == 404
    assert r.json() == {"error": "Session not found.", "code": "NOT_FOUND"}
    assert agent.calls == []
    assert store.saved == []


@pytest.mark.asyncio
async def test_source_files_from_the_store_appear_in_the_citations():
    store = MockChatStore(source_files={"doc_1": "annual_report.pdf"})
    async with _client(MockAgent(), store=store) as client:
        r = await client.post("/chat", json=_body())
    assert r.json()["citations"][0]["source_file"] == "annual_report.pdf"


@pytest.mark.asyncio
async def test_a_failed_save_still_delivers_the_answer():
    async with _client(MockAgent(), store=MockChatStore(save_ok=False)) as client:
        r = await client.post("/chat", json=_body())
    assert r.status_code == 200
    assert r.json()["answer"] == "Mock answer."


@pytest.mark.asyncio
async def test_no_database_gives_503():
    app = create_app(agent=MockAgent(), settings=Settings(_env_file=None))  # no factory, no store
    app.dependency_overrides[get_current_user] = lambda: FakeUser()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/chat", json=_body())
    assert r.status_code == 503
    assert r.json()["code"] == "DEPENDENCY_UNAVAILABLE"