from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models
from app.schemas.agent import AgentResponse


@dataclass
class StoredMessage:
    message: models.Message
    citations: list[models.MessageCitation]
    traces: list[models.AgentTrace]


async def get_source_files(db: AsyncSession, document_ids: set[str]) -> dict[str, str]:
    """document_id -> original filename. Soft-deleted documents still resolve."""
    if not document_ids:
        return {}
    result = await db.execute(
        select(models.Document.document_id, models.Document.filename).where(
            models.Document.document_id.in_(document_ids)
        )
    )
    return {document_id: filename for document_id, filename in result.all()}


async def save_exchange(
    db: AsyncSession,
    session_id: UUID,
    question: str,
    response: AgentResponse,
    source_files: dict[str, str],
) -> models.Message:
    """Saves the question, the answer, its citations and its trace in ONE transaction."""
    # Set in Python, not by the database: Postgres now() is the transaction's start time,
    # so both messages would get the same time and their order would be unclear.
    answered_at = datetime.now(timezone.utc)
    asked_at = answered_at - timedelta(milliseconds=max(round(response.latency_ms), 1))

    user_message = models.Message(
        session_id=session_id, role="user", content=question, created_at=asked_at
    )
    assistant_message = models.Message(
        session_id=session_id,
        role="assistant",
        content=response.answer,
        verification_status=response.verification_status,
        confidence=response.confidence,
        latency_ms=round(response.latency_ms),
        created_at=answered_at,
    )
    try:
        db.add_all([user_message, assistant_message])
        await db.flush()  # fails here if the session does not exist
        db.add_all(
            [
                models.MessageCitation(
                    message_id=assistant_message.id,
                    chunk_id=citation.chunk_id,
                    document_id=citation.document_id,
                    page_number=citation.page_number,
                    text_snippet=citation.text_snippet,
                    source_file=source_files.get(citation.document_id),
                )
                for citation in response.citations
            ]
        )
        db.add_all(
            [
                models.AgentTrace(
                    message_id=assistant_message.id,
                    step_order=order,
                    step_type=step.step_type.value,
                    content=step.content,
                    step_metadata=step.metadata,
                )
                for order, step in enumerate(response.trace)
            ]
        )
        await db.execute(
            update(models.ChatSession)
            .where(models.ChatSession.id == session_id)
            .values(updated_at=func.now())
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return assistant_message


async def load_history(db: AsyncSession, session_id: UUID) -> list[StoredMessage]:
    result = await db.execute(
        select(models.Message)
        .where(models.Message.session_id == session_id)
        .order_by(models.Message.created_at)
    )
    messages = result.scalars().all()
    if not messages:
        return []

    ids = [message.id for message in messages]
    citations_by_message: dict[UUID, list[models.MessageCitation]] = defaultdict(list)
    traces_by_message: dict[UUID, list[models.AgentTrace]] = defaultdict(list)

    citation_rows = await db.execute(
        select(models.MessageCitation).where(models.MessageCitation.message_id.in_(ids))
    )
    for citation in citation_rows.scalars():
        citations_by_message[citation.message_id].append(citation)

    trace_rows = await db.execute(
        select(models.AgentTrace)
        .where(models.AgentTrace.message_id.in_(ids))
        .order_by(models.AgentTrace.message_id, models.AgentTrace.step_order)
    )
    for trace in trace_rows.scalars():
        traces_by_message[trace.message_id].append(trace)

    return [
        StoredMessage(m, citations_by_message[m.id], traces_by_message[m.id]) for m in messages
    ]