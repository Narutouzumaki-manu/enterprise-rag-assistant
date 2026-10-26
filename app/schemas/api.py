from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.agent import Citation
from datetime import datetime

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

class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds

class SessionSummary(BaseModel):
    session_id: UUID
    title: str | None = None
    created_at: datetime
    updated_at: datetime


class TraceStepResponse(BaseModel):
    step_type: str
    content: str
    metadata: dict = {}


class MessageResponse(BaseModel):
    message_id: UUID
    role: str  # "user" or "assistant"
    content: str
    created_at: datetime
    verification_status: str | None = None
    confidence: float | None = None
    latency_ms: int | None = None
    citations: list[ApiCitation] = []
    trace: list[TraceStepResponse] = []


class SessionDetail(SessionSummary):
    messages: list[MessageResponse] 

class DocumentDetail(DocumentStatusResponse):
    source_type: str
    created_at: datetime
    uploaded_by_me: bool


class FeedbackRequest(BaseModel):
    message_id: UUID
    rating: Literal[-1, 1]  # 1 = helpful, -1 = not helpful
    comment: str | None = Field(default=None, max_length=1000)


class FeedbackResponse(BaseModel):
    message_id: UUID
    rating: int
    comment: str | None = None