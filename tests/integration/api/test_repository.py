from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.db import models, repository
from app.schemas.agent import AgentResponse, AgentStep, AgentStepType, Citation


def _response(**overrides) -> AgentResponse:
    data = dict(
        answer="Revenue grew.",
        citations=[Citation(chunk_id="c1", document_id="d1", page_number=3, text_snippet="snippet")],
        trace=[
            AgentStep(step_type=AgentStepType.PLAN, content="Plan", metadata={"query_type": "simple"}),
            AgentStep(step_type=AgentStepType.RETRIEVE, content="Retrieved", metadata={"chunks_after_merge": 8}),
        ],
        verification_status="verified",
        confidence=0.95,
        latency_ms=1500.0,
    )
    data.update(overrides)
    return AgentResponse(**data)


async def _chat(session) -> models.ChatSession:
    user = models.User(email="a@example.com", password_hash="x")
    session.add(user)
    await session.flush()
    chat = models.ChatSession(user_id=user.id)
    session.add(chat)
    await session.commit()
    return chat


async def _count(session, table) -> int:
    return await session.scalar(select(func.count()).select_from(table))


@pytest.mark.asyncio
async def test_save_exchange_stores_the_question_and_the_answer_in_order(session):
    chat = await _chat(session)
    assistant = await repository.save_exchange(session, chat.id, "What grew?", _response(), {})
    history = await repository.load_history(session, chat.id)

    assert [h.message.role for h in history] == ["user", "assistant"]
    assert history[0].message.content == "What grew?"
    stored = history[1].message
    assert stored.id == assistant.id
    assert stored.content == "Revenue grew."
    assert stored.verification_status == "verified"
    assert stored.confidence == 0.95
    assert stored.latency_ms == 1500


@pytest.mark.asyncio
async def test_citations_get_their_source_file_from_the_documents_table(session):
    chat = await _chat(session)
    session.add(models.Document(
        document_id="d1", filename="annual_report.pdf", content_hash="h1",
        source_type="pdf", status="success",
    ))
    await session.commit()
    response = _response(citations=[
        Citation(chunk_id="c1", document_id="d1", page_number=3, text_snippet="a"),
        Citation(chunk_id="c2", document_id="gone", page_number=None, text_snippet="b"),
    ])
    source_files = await repository.get_source_files(session, {"d1", "gone"})
    assert source_files == {"d1": "annual_report.pdf"}

    await repository.save_exchange(session, chat.id, "q", response, source_files)
    citations = (await repository.load_history(session, chat.id))[1].citations
    by_chunk = {c.chunk_id: c.source_file for c in citations}
    assert by_chunk == {"c1": "annual_report.pdf", "c2": None}


@pytest.mark.asyncio
async def test_a_soft_deleted_document_still_resolves_to_its_filename(session):
    session.add(models.Document(
        document_id="d1", filename="old.pdf", content_hash="h1", source_type="pdf",
        status="success", deleted_at=datetime.now(UTC),
    ))
    await session.commit()
    assert await repository.get_source_files(session, {"d1"}) == {"d1": "old.pdf"}
    assert await repository.get_source_files(session, set()) == {}


@pytest.mark.asyncio
async def test_trace_steps_are_stored_in_order_with_their_metadata(session):
    chat = await _chat(session)
    await repository.save_exchange(session, chat.id, "q", _response(), {})
    traces = (await repository.load_history(session, chat.id))[1].traces
    assert [(t.step_order, t.step_type) for t in traces] == [(0, "plan"), (1, "retrieve")]
    assert traces[1].step_metadata == {"chunks_after_merge": 8}


@pytest.mark.asyncio
async def test_history_keeps_several_exchanges_in_order(session):
    chat = await _chat(session)
    quick = _response(latency_ms=1.0)  # short latency keeps the two exchanges clearly apart
    await repository.save_exchange(session, chat.id, "q1", quick, {})
    await repository.save_exchange(session, chat.id, "q2", quick, {})
    history = await repository.load_history(session, chat.id)
    assert [h.message.content for h in history] == ["q1", "Revenue grew.", "q2", "Revenue grew."]
    assert history[0].citations == [] and history[0].traces == []


@pytest.mark.asyncio
async def test_a_failure_stores_nothing(session):
    chat = await _chat(session)
    too_long = _response(citations=[
        Citation(chunk_id="x" * 300, document_id="d1", text_snippet="s"),
    ])
    with pytest.raises(SQLAlchemyError):
        await repository.save_exchange(session, chat.id, "q", too_long, {})
    assert await _count(session, models.Message) == 0
    assert await _count(session, models.MessageCitation) == 0
    assert await _count(session, models.AgentTrace) == 0


@pytest.mark.asyncio
async def test_saving_into_a_missing_session_stores_nothing(session):
    with pytest.raises(IntegrityError):
        await repository.save_exchange(session, uuid4(), "q", _response(), {})
    assert await _count(session, models.Message) == 0
    