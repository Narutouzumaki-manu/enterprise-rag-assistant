import uuid

import pytest
from sqlalchemy import select

from app.db import models, repository


async def make_world(session_factory):
    """A user with one live session holding one user message and one assistant message."""
    async with session_factory() as db:
        user = models.User(email=f"{uuid.uuid4().hex}@example.com", password_hash="x")
        db.add(user)
        await db.commit()
        chat = await repository.create_session(db, user.id)
        asked = models.Message(session_id=chat.id, role="user", content="q")
        answered = models.Message(session_id=chat.id, role="assistant", content="a")
        db.add_all([asked, answered])
        await db.commit()
        return user.id, asked.id, answered.id


@pytest.mark.asyncio
async def test_only_own_assistant_messages_can_be_rated(session_factory):
    user_id, user_message, assistant_message = await make_world(session_factory)
    other_user_id, _, _ = await make_world(session_factory)
    async with session_factory() as db:
        assert await repository.get_rateable_message(db, user_id, assistant_message) is not None
        assert await repository.get_rateable_message(db, user_id, user_message) is None
        assert await repository.get_rateable_message(db, other_user_id, assistant_message) is None
        assert await repository.get_rateable_message(db, user_id, uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_a_second_rating_replaces_the_first(session_factory):
    user_id, _, assistant_message = await make_world(session_factory)
    async with session_factory() as db:
        await repository.save_feedback(
            db, message_id=assistant_message, user_id=user_id, rating=1, comment="first"
        )
        await repository.save_feedback(
            db, message_id=assistant_message, user_id=user_id, rating=-1, comment="second"
        )
        rows = (
            await db.execute(
                select(models.Feedback).where(models.Feedback.message_id == assistant_message)
            )
        ).scalars().all()
    assert len(rows) == 1
    assert (rows[0].rating, rows[0].comment) == (-1, "second")