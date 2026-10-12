from enum import Enum

from pydantic import BaseModel


class AgentStepType(str, Enum):
    PLAN = "plan"
    RETRIEVE = "retrieve"
    FACT_CHECK = "fact_check"
    SYNTHESIZE = "synthesize"


class AgentStep(BaseModel):
    step_type: AgentStepType
    content: str
    metadata: dict = {}


class Citation(BaseModel):
    chunk_id: str
    document_id: str
    page_number: int | None = None
    text_snippet: str


class AgentResponse(BaseModel):
    answer: str
    citations: list[Citation]
    trace: list[AgentStep]
    verification_status: str   # "verified" | "partially_verified" | "unverified"
    confidence: float
    latency_ms: float