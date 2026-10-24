
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.document import Chunk

from app.db import models
from app.schemas.agent import AgentResponse

TITLE_MAX_CHARS = 60


def make_title(question: str) -> str:
    text = " ".join(question.split())  # collapses spaces, tabs and newlines
    if len(text) <= TITLE_MAX_CHARS:
        return text
    cut = text[:TITLE_MAX_CHARS]
    if " " in cut[TITLE_MAX_CHARS // 2 :]:  # break at a word, unless that leaves a tiny title
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:-") + "…"


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
            .values(
                updated_at=func.now(),
                # COALESCE keeps an existing title: only the first question names the session
                title=func.coalesce(models.ChatSession.title, make_title(question) or None),
            )
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


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def get_user_by_email(db: AsyncSession, email: str) -> models.User | None:
    result = await db.execute(
        select(models.User).where(models.User.email == normalize_email(email))
    )
    return result.scalar_one_or_none()


async def create_user(db: AsyncSession, email: str, password_hash: str) -> models.User:
    user = models.User(email=normalize_email(email), password_hash=password_hash)
    db.add(user)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return user


async def get_user_by_id(db: AsyncSession, user_id: UUID) -> models.User | None:
    return await db.get(models.User, user_id)


async def create_session(db: AsyncSession, user_id: UUID) -> models.ChatSession:
    chat = models.ChatSession(user_id=user_id)
    db.add(chat)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(chat)  # loads created_at / updated_at, which the database filled in
    return chat


async def list_sessions(
    db: AsyncSession, user_id: UUID, limit: int = 50
) -> list[models.ChatSession]:
    result = await db.execute(
        select(models.ChatSession)
        .where(
            models.ChatSession.user_id == user_id,
            models.ChatSession.deleted_at.is_(None),
        )
        .order_by(
            models.ChatSession.updated_at.desc(),
            models.ChatSession.created_at.desc(),
        )
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_user_session(
    db: AsyncSession, user_id: UUID, session_id: UUID
) -> models.ChatSession | None:
    """The session, only if it exists, is not deleted AND belongs to this user."""
    result = await db.execute(
        select(models.ChatSession).where(
            models.ChatSession.id == session_id,
            models.ChatSession.user_id == user_id,
            models.ChatSession.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()

async def get_active_document_by_hash(db: AsyncSession, content_hash: str) -> models.Document | None:
    result = await db.execute(
        select(models.Document).where(
            models.Document.content_hash == content_hash,
            models.Document.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def create_document(
    db: AsyncSession,
    *,
    document_id: str,
    filename: str,
    content_hash: str,
    source_type: str,
    status: str,
    uploaded_by: UUID | None,
) -> models.Document:
    """Raises IntegrityError if a live document with the same content hash already exists."""
    document = models.Document(
        document_id=document_id,
        filename=filename,
        content_hash=content_hash,
        source_type=source_type,
        status=status,
        uploaded_by=uploaded_by,
    )
    db.add(document)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(document)  # loads the timestamps the database filled in
    return document


async def get_document(db: AsyncSession, document_id: str) -> models.Document | None:
    result = await db.execute(
        select(models.Document).where(
            models.Document.document_id == document_id,
            models.Document.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def list_documents(db: AsyncSession, limit: int = 100) -> list[models.Document]:
    result = await db.execute(
        select(models.Document)
        .where(models.Document.deleted_at.is_(None))
        .order_by(models.Document.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def set_document_status(
    db: AsyncSession, document_id: str, status: str, error_message: str | None = None
) -> None:
    await db.execute(
        update(models.Document)
        .where(models.Document.document_id == document_id)
        .values(status=status, error_message=error_message, updated_at=func.now())
    )
    await db.commit()


async def soft_delete_document(db: AsyncSession, document_id: str) -> bool:
    """True if a live document was deleted, False if there was none."""
    result = await db.execute(
        update(models.Document)
        .where(models.Document.document_id == document_id, models.Document.deleted_at.is_(None))
        .values(deleted_at=func.now(), updated_at=func.now())
    )
    await db.commit()
    return result.rowcount > 0

async def complete_document(
    db: AsyncSession,
    document_id: str,
    chunks: list[Chunk],
    status: str,
    error_message: str | None = None,
) -> None:
    """Saves the chunk rows and the final status in ONE transaction."""
    rows = [
        models.DocumentChunk(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            text=chunk.text,
            token_count=chunk.token_count,
            page_number=chunk.metadata.page_number,
            section_title=chunk.metadata.section_title,
            row_range_start=chunk.metadata.row_range[0] if chunk.metadata.row_range else None,
            row_range_end=chunk.metadata.row_range[1] if chunk.metadata.row_range else None,
            ingested_at=chunk.metadata.ingested_at,
        )
        for chunk in chunks
    ]
    try:
        db.add_all(rows)
        await db.execute(
            update(models.Document)
            .where(models.Document.document_id == document_id)
            .values(status=status, error_message=error_message, updated_at=func.now())
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise