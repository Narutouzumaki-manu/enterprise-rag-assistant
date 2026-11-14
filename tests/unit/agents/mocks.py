"""Fake collaborators for testing the agent without a model or network."""
from collections import deque
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.agents.llm import LLMError
from app.schemas.retrieval import (
    RetrievalRequest,
    RetrievalResponse,
    RetrievedChunk,
)

T = TypeVar("T", bound=BaseModel)

# Same list Member 2's filters.py allows; unknown keys raise ValueError.
ALLOWED_FILTER_KEYS = {
    "document_id",
    "source_type",
    "page_number",
    "section_title",
    "content_hash",
}


def make_chunk(
    chunk_id: str,
    text: str | None = None,
    dense_score: float = 0.8,
    document_id: str = "doc1",
    page_number: int | None = 1,
    section_title: str | None = None,
) -> RetrievedChunk:
    """Build a RetrievedChunk the way the shipped retriever returns it:
    only dense_score filled in, the other scores None."""
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text if text is not None else f"text of {chunk_id}",
        dense_score=dense_score,
        page_number=page_number,
        section_title=section_title,
    )


class MockRetriever:
    """Replays scripted results. Mirrors Member 2's real behaviour:
    cuts to top_k, empty query -> empty results, unknown filter key -> ValueError.

    responses: exact query text -> list of chunks (best first, as the tests supply them)
    default:   what to return for any query not in `responses`
    error:     if set, retrieve() raises it (to test failure handling)
    calls:     every RetrievalRequest received, in order
    """

    def __init__(
        self,
        responses: dict[str, list[RetrievedChunk]] | None = None,
        default: list[RetrievedChunk] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.responses = responses or {}
        self.default = default or []
        self.error = error
        self.calls: list[RetrievalRequest] = []

    def retrieve(self, request: RetrievalRequest) -> RetrievalResponse:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        if request.filters:
            unknown = set(request.filters) - ALLOWED_FILTER_KEYS
            if unknown:
                raise ValueError(f"Unknown filter keys: {sorted(unknown)}")

        if not request.query.strip():
            chunks: list[RetrievedChunk] = []
        else:
            chunks = self.responses.get(request.query, self.default)

        return RetrievalResponse(
            query=request.query,
            results=[c.model_copy() for c in chunks[: request.top_k]],
            embedding_model="mock",
            reranker_model="none",
            latency_ms=0.0,
        )


@dataclass
class LLMCall:
    kind: str                              # "complete" or "structured"
    system: str
    prompt: str
    schema: type[BaseModel] | None = None


class MockLLM:
    """Replays scripted LLM answers. Never invents one.

    completions: texts returned by complete(), in order. An Exception item is raised.
    structured:  schema class -> queue of answers for complete_structured().
                 Each item is a schema instance, a dict to validate, or an Exception.
    calls:       every call received, in order (also the ones that fail).
    """

    def __init__(
        self,
        completions: list[str | Exception] | None = None,
        structured: dict[type[BaseModel], list[Any]] | None = None,
    ) -> None:
        self._completions = deque(completions or [])
        self._structured = {
            schema: deque(items) for schema, items in (structured or {}).items()
        }
        self.calls: list[LLMCall] = []

    @property
    def complete_calls(self) -> list[LLMCall]:
        return [c for c in self.calls if c.kind == "complete"]

    def structured_calls(self, schema: type[BaseModel] | None = None) -> list[LLMCall]:
        return [
            c for c in self.calls
            if c.kind == "structured" and (schema is None or c.schema is schema)
        ]

    def complete(self, system: str, prompt: str) -> str:
        self.calls.append(LLMCall("complete", system, prompt))
        if not self._completions:
            raise LLMError("MockLLM: no scripted completion left")
        item = self._completions.popleft()
        if isinstance(item, Exception):
            raise item
        return item

    def complete_structured(self, system: str, prompt: str, schema: type[T]) -> T:
        self.calls.append(LLMCall("structured", system, prompt, schema))
        queue = self._structured.get(schema)
        if not queue:
            raise LLMError(f"MockLLM: no scripted response left for {schema.__name__}")
        item = queue.popleft()
        if isinstance(item, Exception):
            raise item
        if isinstance(item, schema):
            return item.model_copy()
        try:
            return schema.model_validate(item)
        except ValidationError as error:
            raise LLMError(
                f"MockLLM: scripted response is not a valid {schema.__name__}: {error}"
            ) from error