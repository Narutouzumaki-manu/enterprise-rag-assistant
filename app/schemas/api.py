from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.agent import Citation


class ChatRequest(BaseModel):
    session_id: UUID
    query: str
    top_k: int = Field(default=8, ge=1, le=20)


class ApiCitation(Citation):
    source_file: str | None = None  # filename, looked up by document_id


class ChatResponse(BaseModel):
    request_id: UUID
    answer: str
    citations: list[ApiCitation]
    verification_status: str  # "verified" | "partially_verified" | "unverified"
    confidence: float
    latency_ms: int


class DocumentStatusResponse(BaseModel):
    document_id: str
    filename: str
    status: str  # queued | parsing | ocr_fallback | indexing | success | partial | failed | duplicate
    error_message: str | None = None


class HealthResponse(BaseModel):
    status: str  # "ok" | "degraded"
    checks: dict  # {"postgres": "ok", "redis": "ok", "retriever": "ok"}


class ErrorResponse(BaseModel):
    error: str  # human readable, never a stack trace
    code: str  # e.g. AGENT_BUSY