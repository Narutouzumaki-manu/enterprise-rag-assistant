from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_app_settings, get_runtime
from app.api.runtime import AgentRuntime
from app.core.config import Settings
from app.schemas.api import ApiCitation, ChatRequest, ChatResponse

router = APIRouter()


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
async def chat(
    body: ChatRequest,
    runtime: AgentRuntime = Depends(get_runtime),
    settings: Settings = Depends(get_app_settings),
) -> ChatResponse:
    query = clean_query(body.query, settings)
    response = await runtime.run(query, top_k=body.top_k)
    return ChatResponse(
        request_id=uuid4(),
        answer=response.answer,
        citations=[ApiCitation.model_validate(c.model_dump()) for c in response.citations],
        verification_status=response.verification_status,
        confidence=response.confidence,
        latency_ms=round(response.latency_ms),
    )