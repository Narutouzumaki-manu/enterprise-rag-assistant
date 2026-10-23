from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.db import models, repository
from app.db.repository import StoredMessage
from app.schemas.api import (
    ApiCitation,
    MessageResponse,
    SessionDetail,
    SessionSummary,
    TraceStepResponse,
)

router = APIRouter(prefix="/sessions")


def _summary(chat: models.ChatSession) -> SessionSummary:
    return SessionSummary(
        session_id=chat.id,
        title=chat.title,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    )


def _message(stored: StoredMessage) -> MessageResponse:
    message = stored.message
    return MessageResponse(
        message_id=message.id,
        role=message.role,
        content=message.content,
        created_at=message.created_at,
        verification_status=message.verification_status,
        confidence=message.confidence,
        latency_ms=message.latency_ms,
        citations=[
            ApiCitation(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                page_number=c.page_number,
                text_snippet=c.text_snippet,
                source_file=c.source_file,
            )
            for c in stored.citations
        ],
        trace=[
            TraceStepResponse(
                step_type=t.step_type, content=t.content, metadata=t.step_metadata or {}
            )
            for t in stored.traces
        ],
    )


@router.post("", response_model=SessionSummary, status_code=201)
async def create_session(
    user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionSummary:
    return _summary(await repository.create_session(db, user.id))


@router.get("", response_model=list[SessionSummary])
async def list_sessions(
    limit: int = Query(default=50, ge=1, le=100),
    user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SessionSummary]:
    return [_summary(chat) for chat in await repository.list_sessions(db, user.id, limit)]


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: UUID,
    user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionDetail:
    chat = await repository.get_user_session(db, user.id, session_id)
    if chat is None:  # not found, someone else's, or deleted: all look the same
        raise HTTPException(status_code=404, detail="Session not found.")
    history = await repository.load_history(db, chat.id)
    return SessionDetail(**_summary(chat).model_dump(), messages=[_message(h) for h in history])