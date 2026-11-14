from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.sse import EventSourceResponse

from app.api.dependencies import (
    get_app_settings,
    get_chat_store,
    get_current_user,
    get_runtime,
)
from app.api.exchange import ChatStore, open_saved_stream
from app.api.limits import CHAT_LIMIT, limiter
from app.api.runtime import AgentRuntime
from app.api.streaming import build_chat_events, sse_lines
from app.core.config import Settings
from app.db import models
from app.schemas.api import ApiCitation, ChatRequest, ChatResponse

router = APIRouter()
STREAM_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def clean_query(raw: str, settings: Settings) -> str:
    query = raw.strip()
    if not query:
        raise HTTPException(status_code=422, detail="Query must not be blank.")
    if len(query) > settings.max_query_chars:
        raise HTTPException(
            status_code=422,
            detail=f"Query is too long (maximum {settings.max_query_chars} characters).",
        )
    return query


@router.post("/chat", response_model=ChatResponse)
@limiter.shared_limit(CHAT_LIMIT, scope="chat")
async def chat(
    request: Request,
    body: ChatRequest,
    user: models.User = Depends(get_current_user),  # first, so a missing token is a 401
    runtime: AgentRuntime = Depends(get_runtime),
    store: ChatStore = Depends(get_chat_store),
    settings: Settings = Depends(get_app_settings),
) -> ChatResponse:
    query = clean_query(body.query, settings)
    if not await store.session_belongs_to(user.id, body.session_id):
        raise HTTPException(status_code=404, detail="Session not found.")  # before any model call

    response = await runtime.run(query, top_k=body.top_k)
    source_files = await store.source_files_for(response)
    await store.save(body.session_id, query, response, source_files)  # a failed save is logged, not fatal

    return ChatResponse(
        request_id=uuid4(),
        answer=response.answer,
        citations=[
            ApiCitation.model_validate(
                {**citation.model_dump(), "source_file": source_files.get(citation.document_id)}
            )
            for citation in response.citations
        ],
        verification_status=response.verification_status,
        confidence=response.confidence,
        latency_ms=round(response.latency_ms),
    )


@router.post(
    "/chat/stream",
    response_model=None,
    responses={
        200: {
            "description": "Server-Sent Events stream",
            "content": {"text/event-stream": {}},
        }
    },
)
@limiter.shared_limit(CHAT_LIMIT, scope="chat")
async def chat_stream(
    request: Request,
    body: ChatRequest,
    user: models.User = Depends(get_current_user),
    runtime: AgentRuntime = Depends(get_runtime),
    store: ChatStore = Depends(get_chat_store),
    settings: Settings = Depends(get_app_settings),
) -> EventSourceResponse:
    query = clean_query(body.query, settings)
    if not await store.session_belongs_to(user.id, body.session_id):
        raise HTTPException(status_code=404, detail="Session not found.")  # before any model call

    source_files: dict[str, str] = {}  # filled by the pump, read when the source events are built
    agent_events = await open_saved_stream(
        runtime,
        store,
        request.app.state.background_tasks,
        body.session_id,
        query,
        body.top_k,
        source_files,
    )  # a busy error is raised here, before any bytes

    events = build_chat_events(
        agent_events,
        uuid4(),
        settings.sse_heartbeat_seconds,
        source_files,
    )
    return EventSourceResponse(sse_lines(events), headers=STREAM_HEADERS)