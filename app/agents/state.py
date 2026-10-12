"""Shared state passed between the agent's nodes (TRD Section 6).

Per request, in memory only. Only the final AgentResponse is persisted.
"""
import operator
from typing import Annotated, TypedDict

from app.schemas.agent import AgentStep
from app.schemas.retrieval import RetrievedChunk


class AgentState(TypedDict):
    query: str
    query_type: str                    # simple | multi-hop | comparison | aggregation | ambiguous
    subqueries: list[str]              # max 5
    search_queries: list[str]          # originals + rewrites sent to retrieve()
    top_k: int                         # starts at 8; widened on retry 2
    retrieved_chunks: list[RetrievedChunk]  # merged, deduped by chunk_id
    draft_answer: str
    claims: list[str]
    verification_results: list[dict]   # per claim: supported, chunk_ids, reason
    unsupported_claims: list[str]
    coverage: float                    # supported claims / total claims
    confidence: float
    retry_count: int
    step_count: int
    # Annotated + operator.add = each node APPENDS to the trace
    # (every other field is overwritten by default).
    trace: Annotated[list[AgentStep], operator.add]
    final_answer: str | None
    verification_status: str


def initial_state(query: str, top_k: int = 8) -> AgentState:
    """Fresh state for one request. Fails safe: starts 'unverified', confidence 0."""
    return AgentState(
        query=query,
        query_type="",
        subqueries=[],
        search_queries=[],
        top_k=top_k,
        retrieved_chunks=[],
        draft_answer="",
        claims=[],
        verification_results=[],
        unsupported_claims=[],
        coverage=0.0,
        confidence=0.0,
        retry_count=0,
        step_count=0,
        trace=[],
        final_answer=None,
        verification_status="unverified",
    )