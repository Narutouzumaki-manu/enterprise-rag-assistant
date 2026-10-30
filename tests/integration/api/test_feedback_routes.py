import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.main import create_app
from app.core.config import Settings
from app.core.security import create_access_token, hash_password
from app.db import models, repository

SETTINGS = Settings(_env_file=None, agent_enabled=False)


@pytest_asyncio.fixture
async def client(session_factory):
    app = create_app(settings=SETTINGS, session_factory=session_factory)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def make_user_with_answer(session_factory, email):
    """A user with one live session holding a user message and an assistant message."""
    async with session_factory() as db:
        user = await repository.create_user(db, email, hash_password("pw-for-tests"))
        chat = await repository.create_session(db, user.id)
        asked = models.Message(session_id=chat.id, role="user", content="q")
        answered = models.Message(
            session_id=chat.id, role="assistant", content="a",
            verification_status="verified", confidence=0.95, latency_ms=10,
        )
        db.add_all([asked, answered])
        await db.commit()
        headers = {"Authorization": f"Bearer {create_access_token(user.id, SETTINGS)}"}
        return headers, str(asked.id), str(answered.id)


@pytest.mark.asyncio
async def test_no_token_is_401(client):
    r = await client.post("/feedback", json={"message_id": "x", "rating": 1})
    assert r.status_code == 401
    assert r.json()["code"] == "UNAUTHENTICATED"


@pytest.mark.asyncio
async def test_rating_an_answer_works(client, session_factory):
    headers, _, answer = await make_user_with_answer(session_factory, "a@example.com")
    r = await client.post("/feedback", headers=headers, json={"message_id": answer, "rating": 1, "comment": " good "})
    assert r.status_code == 200
    assert r.json() == {"message_id": answer, "rating": 1, "comment": "good"}


@pytest.mark.asyncio
async def test_a_second_rating_replaces_the_first(client, session_factory):
    headers, _, answer = await make_user_with_answer(session_factory, "a@example.com")
    await client.post("/feedback", headers=headers, json={"message_id": answer, "rating": 1, "comment": "first"})
    await client.post("/feedback", headers=headers, json={"message_id": answer, "rating": -1, "comment": "second"})
    async with session_factory() as db:
        rows = (await db.execute(select(models.Feedback))).scalars().all()
    assert len(rows) == 1
    assert (rows[0].rating, rows[0].comment) == (-1, "second")


@pytest.mark.asyncio
async def test_a_blank_comment_is_stored_as_none(client, session_factory):
    headers, _, answer = await make_user_with_answer(session_factory, "a@example.com")
    r = await client.post("/feedback", headers=headers, json={"message_id": answer, "rating": 1, "comment": "   "})
    assert r.json()["comment"] is None


@pytest.mark.asyncio
async def test_user_messages_unknown_ids_and_other_users_messages_are_404(client, session_factory):
    headers, question, answer = await make_user_with_answer(session_factory, "a@example.com")
    other_headers, _, _ = await make_user_with_answer(session_factory, "b@example.com")
    unknown = "00000000-0000-0000-0000-000000000000"
    for message_id, who in [(question, headers), (unknown, headers), (answer, other_headers)]:
        r = await client.post("/feedback", headers=who, json={"message_id": message_id, "rating": 1})
        assert r.status_code == 404
        assert r.json()["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_invalid_input_is_422(client, session_factory):
    headers, _, answer = await make_user_with_answer(session_factory, "a@example.com")
    for body in [
        {"message_id": answer, "rating": 5},
        {"message_id": answer, "rating": 1, "comment": "x" * 1001},
        {"message_id": "not-a-uuid", "rating": 1},
    ]:
        r = await client.post("/feedback", headers=headers, json=body)
        assert r.status_code == 422
        assert r.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_the_audit_event_never_holds_the_comment(client, session_factory):
    headers, _, answer = await make_user_with_answer(session_factory, "a@example.com")
    await client.post(
        "/feedback",
        headers={**headers, "X-Request-ID": "fb-1"},
        json={"message_id": answer, "rating": 1, "comment": "SECRET-COMMENT-TEST"},
    )
    async with session_factory() as db:
        events = (
            await db.execute(select(models.AuditEvent).where(models.AuditEvent.event_type == "feedback"))
        ).scalars().all()
    assert len(events) == 1
    assert events[0].request_id == "fb-1"
    assert events[0].payload["rating"] == 1
    assert "SECRET-COMMENT-TEST" not in str(events[0].payload)