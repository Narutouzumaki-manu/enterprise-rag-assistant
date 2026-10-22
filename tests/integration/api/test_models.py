from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, func, inspect, select
from sqlalchemy.exc import IntegrityError

from app.db import models


async def _user_and_chat(session):
    user = models.User(email="a@example.com", password_hash="x")
    session.add(user)
    await session.flush()
    chat = models.ChatSession(user_id=user.id)
    session.add(chat)
    await session.flush()
    return user, chat


async def _message(session, chat):
    message = models.Message(session_id=chat.id, role="assistant", content="Answer")
    session.add(message)
    await session.flush()
    return message


def _doc(document_id: str) -> models.Document:
    return models.Document(
        document_id=document_id,
        filename=f"{document_id}.pdf",
        content_hash="same-hash",
        source_type="pdf",
        status="success",
    )


@pytest.mark.asyncio
async def test_all_tables_are_created(engine):
    async with engine.connect() as conn:
        names = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
    expected = {
        "users", "sessions", "documents", "chunks", "messages",
        "citations", "agent_traces", "feedback", "audit_events",
    }
    assert expected <= names


@pytest.mark.asyncio
async def test_an_answer_round_trips_with_citations_and_ordered_traces(session):
    _, chat = await _user_and_chat(session)
    message = models.Message(
        session_id=chat.id, role="assistant", content="Answer",
        verification_status="verified", confidence=0.95, latency_ms=1200,
    )
    session.add(message)
    await session.flush()
    session.add_all([
        models.MessageCitation(
            message_id=message.id, chunk_id="c1", document_id="d1",
            page_number=3, text_snippet="snippet", source_file="a.pdf",
        ),
        models.AgentTrace(
            message_id=message.id, step_order=1, step_type="retrieve",
            content="Retrieved", step_metadata={"chunks_after_merge": 8},
        ),
        models.AgentTrace(
            message_id=message.id, step_order=0, step_type="plan",
            content="Plan", step_metadata={},
        ),
    ])
    await session.commit()
    await session.refresh(message)
    assert message.created_at is not None

    result = await session.execute(
        select(models.AgentTrace)
        .where(models.AgentTrace.message_id == message.id)
        .order_by(models.AgentTrace.step_order)
    )
    traces = result.scalars().all()
    assert [t.step_type for t in traces] == ["plan", "retrieve"]
    assert traces[1].step_metadata == {"chunks_after_merge": 8}


@pytest.mark.asyncio
async def test_duplicate_email_is_rejected(session):
    session.add(models.User(email="a@example.com", password_hash="x"))
    await session.commit()
    session.add(models.User(email="a@example.com", password_hash="y"))
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_same_content_hash_is_rejected_until_the_first_document_is_deleted(session):
    session.add(_doc("d1"))
    await session.commit()

    session.add(_doc("d2"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

    first = await session.get(models.Document, "d1")
    first.deleted_at = datetime.now(timezone.utc)
    await session.commit()

    session.add(_doc("d3"))  # re-upload after a soft delete is allowed
    await session.commit()


@pytest.mark.asyncio
async def test_a_chunk_needs_an_existing_document(session):
    now = datetime.now(timezone.utc)
    session.add(models.DocumentChunk(
        chunk_id="c1", document_id="missing", text="t", token_count=1, ingested_at=now,
    ))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

    session.add(_doc("d1"))
    await session.flush()
    session.add(models.DocumentChunk(
        chunk_id="c1", document_id="d1", text="t", token_count=1, ingested_at=now,
    ))
    await session.commit()


@pytest.mark.asyncio
async def test_a_citation_can_outlive_its_document(session):
    _, chat = await _user_and_chat(session)
    message = await _message(session, chat)
    session.add(models.MessageCitation(
        message_id=message.id, chunk_id="gone_1", document_id="gone", text_snippet="s",
    ))
    await session.commit()  # no foreign key to documents, so this must work


@pytest.mark.asyncio
async def test_deleting_a_message_deletes_its_citations_and_traces(session):
    _, chat = await _user_and_chat(session)
    message = await _message(session, chat)
    session.add_all([
        models.MessageCitation(message_id=message.id, chunk_id="c", document_id="d", text_snippet="s"),
        models.AgentTrace(message_id=message.id, step_order=0, step_type="plan", content="p"),
    ])
    await session.commit()

    await session.execute(delete(models.Message).where(models.Message.id == message.id))
    await session.commit()

    for table in (models.MessageCitation, models.AgentTrace):
        count = await session.scalar(select(func.count()).select_from(table))
        assert count == 0


@pytest.mark.asyncio
async def test_feedback_rating_must_be_minus_one_or_one(session):
    user, chat = await _user_and_chat(session)
    message = await _message(session, chat)
    session.add(models.Feedback(message_id=message.id, user_id=user.id, rating=1))
    await session.commit()

    session.add(models.Feedback(message_id=message.id, user_id=user.id, rating=2))
    with pytest.raises(IntegrityError):
        await session.commit()