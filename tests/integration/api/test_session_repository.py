from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.db import repository
from app.schemas.agent import AgentResponse, AgentStep, AgentStepType, Citation


def _response() -> AgentResponse:
    return AgentResponse(
        answer="Revenue grew.",
        citations=[Citation(chunk_id="c1", document_id="d1", text_snippet="s")],
        trace=[AgentStep(step_type=AgentStepType.PLAN, content="Plan")],
        verification_status="verified",
        confidence=0.95,
        latency_ms=1.0,
    )


async def _user(session, email="a@example.com"):
    return await repository.create_user(session, email, "not-a-real-hash")


@pytest.mark.asyncio
async def test_a_new_session_has_timestamps_and_no_title(session):
    user = await _user(session)
    chat = await repository.create_session(session, user.id)
    assert chat.user_id == user.id
    assert chat.title is None
    assert chat.created_at is not None and chat.updated_at is not None


@pytest.mark.asyncio
async def test_only_the_first_question_names_the_session(session):
    user = await _user(session)
    chat = await repository.create_session(session, user.id)
    await repository.save_exchange(session, chat.id, "What was revenue?", _response(), {})
    await repository.save_exchange(session, chat.id, "And profit?", _response(), {})
    await session.refresh(chat)
    assert chat.title == "What was revenue?"


@pytest.mark.asyncio
async def test_list_shows_only_own_live_sessions_most_recently_active_first(session):
    me = await _user(session, "me@example.com")
    someone_else = await _user(session, "other@example.com")
    first = await repository.create_session(session, me.id)
    second = await repository.create_session(session, me.id)
    await repository.create_session(session, someone_else.id)
    deleted = await repository.create_session(session, me.id)
    deleted.deleted_at = datetime.now(UTC)
    await session.commit()

    await repository.save_exchange(session, first.id, "q", _response(), {})  # now the most recent

    listed = await repository.list_sessions(session, me.id)
    assert [s.id for s in listed] == [first.id, second.id]


@pytest.mark.asyncio
async def test_a_session_is_found_only_by_its_owner_and_only_while_it_is_live(session):
    me = await _user(session, "me@example.com")
    someone_else = await _user(session, "other@example.com")
    mine = await repository.create_session(session, me.id)

    assert (await repository.get_user_session(session, me.id, mine.id)).id == mine.id
    assert await repository.get_user_session(session, someone_else.id, mine.id) is None
    assert await repository.get_user_session(session, me.id, uuid4()) is None

    mine.deleted_at = datetime.now(UTC)
    await session.commit()
    assert await repository.get_user_session(session, me.id, mine.id) is None