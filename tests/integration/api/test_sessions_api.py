from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.main import create_app
from app.core.config import Settings
from app.core.security import create_access_token
from app.db import repository
from app.schemas.agent import AgentResponse, AgentStep, AgentStepType, Citation

SETTINGS = Settings(_env_file=None, agent_enabled=False)


def _response() -> AgentResponse:
    return AgentResponse(
        answer="Revenue grew.",
        citations=[Citation(chunk_id="c1", document_id="d1", page_number=3, text_snippet="snippet")],
        trace=[AgentStep(step_type=AgentStepType.PLAN, content="Plan", metadata={"query_type": "simple"})],
        verification_status="verified",
        confidence=0.95,
        latency_ms=1.0,
    )


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id, SETTINGS)}"}


@pytest_asyncio.fixture
async def client(session_factory):
    app = create_app(settings=SETTINGS, session_factory=session_factory)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest_asyncio.fixture
async def alice(session):
    return await repository.create_user(session, "alice@example.com", "not-a-real-hash")


@pytest_asyncio.fixture
async def bob(session):
    return await repository.create_user(session, "bob@example.com", "not-a-real-hash")


@pytest.mark.asyncio
async def test_creating_a_session_needs_a_token(client):
    r = await client.post("/sessions")
    assert r.status_code == 401
    assert r.json()["code"] == "UNAUTHENTICATED"


@pytest.mark.asyncio
async def test_a_user_can_create_a_session_of_their_own(client, session, alice):
    r = await client.post("/sessions", headers=_auth(alice))
    assert r.status_code == 201
    data = r.json()
    assert data["title"] is None
    assert data["created_at"] and data["updated_at"]
    mine = await repository.get_user_session(session, alice.id, UUID(data["session_id"]))
    assert mine is not None


@pytest.mark.asyncio
async def test_the_list_shows_only_my_sessions_most_recently_active_first(client, session, alice, bob):
    first = await repository.create_session(session, alice.id)
    second = await repository.create_session(session, alice.id)
    await repository.create_session(session, bob.id)
    await repository.save_exchange(session, first.id, "What grew?", _response(), {})

    r = await client.get("/sessions", headers=_auth(alice))
    assert r.status_code == 200
    assert [s["session_id"] for s in r.json()] == [str(first.id), str(second.id)]
    assert r.json()[0]["title"] == "What grew?"

    bobs = await client.get("/sessions", headers=_auth(bob))
    assert len(bobs.json()) == 1


@pytest.mark.asyncio
async def test_the_list_limit_is_validated_and_applied(client, session, alice):
    for _ in range(3):
        await repository.create_session(session, alice.id)
    assert len((await client.get("/sessions?limit=2", headers=_auth(alice))).json()) == 2
    assert (await client.get("/sessions?limit=0", headers=_auth(alice))).status_code == 422
    assert (await client.get("/sessions?limit=101", headers=_auth(alice))).status_code == 422


@pytest.mark.asyncio
async def test_a_session_comes_back_with_messages_citations_and_trace(client, session, alice):
    chat = await repository.create_session(session, alice.id)
    await repository.save_exchange(
        session, chat.id, "What grew?", _response(), {"d1": "annual_report.pdf"}
    )

    r = await client.get(f"/sessions/{chat.id}", headers=_auth(alice))
    assert r.status_code == 200
    data = r.json()
    assert data["session_id"] == str(chat.id)
    assert data["title"] == "What grew?"
    assert [m["role"] for m in data["messages"]] == ["user", "assistant"]

    question, answer = data["messages"]
    assert question["content"] == "What grew?"
    assert question["citations"] == [] and question["trace"] == []
    assert answer["verification_status"] == "verified"
    assert answer["citations"] == [{
        "chunk_id": "c1", "document_id": "d1", "page_number": 3,
        "text_snippet": "snippet", "source_file": "annual_report.pdf",
    }]
    assert answer["trace"] == [
        {"step_type": "plan", "content": "Plan", "metadata": {"query_type": "simple"}}
    ]


@pytest.mark.asyncio
async def test_someone_elses_unknown_and_deleted_sessions_all_look_the_same(client, session, alice, bob):
    bobs_chat = await repository.create_session(session, bob.id)
    deleted = await repository.create_session(session, alice.id)
    deleted.deleted_at = datetime.now(UTC)
    await session.commit()

    responses = [
        await client.get(f"/sessions/{bobs_chat.id}", headers=_auth(alice)),
        await client.get(f"/sessions/{uuid4()}", headers=_auth(alice)),
        await client.get(f"/sessions/{deleted.id}", headers=_auth(alice)),
    ]
    for r in responses:
        assert r.status_code == 404
        assert r.json() == {"error": "Session not found.", "code": "NOT_FOUND"}


@pytest.mark.asyncio
async def test_a_malformed_session_id_is_a_validation_error(client, alice):
    r = await client.get("/sessions/not-a-uuid", headers=_auth(alice))
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"