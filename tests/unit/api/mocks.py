import time
from collections.abc import Iterator
from datetime import datetime, timezone

import app
from app.schemas.agent import AgentResponse, AgentStep, AgentStepType, Citation
from app.schemas.document import Chunk, ChunkMetadata,  IngestionResult ,SourceType
from app.schemas.retrieval import RetrievalRequest, RetrievalResponse, RetrievedChunk
from pathlib import Path

def make_response(
    answer: str = "Mock answer.",
    status: str = "verified",
    confidence: float = 0.95,
) -> AgentResponse:
    return AgentResponse(
        answer=answer,
        citations=[
            Citation(
                chunk_id="chunk_1",
                document_id="doc_1",
                page_number=3,
                text_snippet="A mock snippet.",
            )
        ],
        trace=[],
        verification_status=status,
        confidence=confidence,
        latency_ms=10.0,
    )


def make_steps() -> list[AgentStep]:
    return [
        AgentStep(step_type=AgentStepType.PLAN, content="Classified as simple; 1 sub-query"),
        AgentStep(step_type=AgentStepType.RETRIEVE, content="Retrieved 8 passages across 1 sub-query"),
        AgentStep(step_type=AgentStepType.SYNTHESIZE, content="Draft answer generated with 1 citation"),
        AgentStep(step_type=AgentStepType.FACT_CHECK, content="1 of 1 claim verified"),
    ]


class MockAgent:
    """Stands in for app.agents.agent.Agent. Blocks like the real one."""

    def __init__(self, response=None, steps=None, delay: float = 0.0, error: Exception | None = None):
        self.response = response if response is not None else make_response()
        self.steps = steps if steps is not None else make_steps()
        self.delay = delay      # total seconds a call blocks
        self.error = error      # raised instead of answering
        self.calls: list[dict] = []

    def run(self, query: str, session_context: dict | None = None, top_k: int | None = None) -> AgentResponse:
        self.calls.append({"query": query, "top_k": top_k})
        time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.response.model_copy(deep=True)

    def run_streaming(
        self, query: str, session_context: dict | None = None, top_k: int | None = None
    ) -> Iterator[AgentStep | AgentResponse]:
        self.calls.append({"query": query, "top_k": top_k})
        pause = self.delay / (len(self.steps) + 1)
        for step in self.steps:
            time.sleep(pause)
            yield step.model_copy(deep=True)
        time.sleep(pause)
        if self.error is not None:
            raise self.error
        yield self.response.model_copy(deep=True)

def make_chunk(document_id: str = "doc_1", index: int = 0, text: str = "Mock chunk text.") -> Chunk:
    return Chunk(
        chunk_id=f"{document_id}_chunk_{index}",
        document_id=document_id,
        text=text,
        token_count=len(text.split()),
        metadata=ChunkMetadata(
            document_id=document_id,
            source_type=SourceType.PDF,
            page_number=index + 1,
            section_title=None,
            content_hash=f"hash_{document_id}",
            ingested_at=datetime.now(timezone.utc),
        ),
    )


class MockRetriever:
    """Stands in for Member 2's retriever. Keeps chunks in a dict; does no real search."""

    embedding_model = "mock-embedding"

    def __init__(self, index_error: Exception | None = None, delete_error: Exception | None = None):
        self._chunks: dict[str, Chunk] = {}
        self.index_error = index_error
        self.delete_error = delete_error
        self.calls: list[tuple] = []

    @property
    def chunk_count(self) -> int:  # mock-only convenience, not on the real retriever
        return len(self._chunks)

    def index_chunks(self, chunks: list[Chunk]) -> None:
        self.calls.append(("index_chunks", len(chunks)))
        if self.index_error is not None:
            raise self.index_error  # nothing is stored when indexing fails
        for chunk in chunks:
            self._chunks[chunk.chunk_id] = chunk  # upsert by chunk_id

    def delete_document(self, document_id: str) -> None:
        self.calls.append(("delete_document", document_id))
        if self.delete_error is not None:
            raise self.delete_error
        self._chunks = {k: v for k, v in self._chunks.items() if v.document_id != document_id}

    def retrieve(self, request: RetrievalRequest) -> RetrievalResponse:
        self.calls.append(("retrieve", request.query))
        filters = request.filters or {}
        unknown = set(filters) - {"document_id"}
        if unknown:
            raise ValueError(f"Unknown filter keys: {sorted(unknown)}")

        results: list[RetrievedChunk] = []
        if request.query.strip():
            candidates = [
                c
                for c in self._chunks.values()
                if "document_id" not in filters or c.document_id == filters["document_id"]
            ]
            for rank, chunk in enumerate(candidates[: request.top_k]):
                results.append(
                    RetrievedChunk(
                        chunk_id=chunk.chunk_id,
                        document_id=chunk.document_id,
                        text=chunk.text,
                        dense_score=round(0.9 - 0.01 * rank, 2),
                        page_number=chunk.metadata.page_number,
                        section_title=chunk.metadata.section_title,
                    )
                )
        return RetrievalResponse(
            query=request.query,
            results=results,
            embedding_model=self.embedding_model,
            reranker_model="none",
            latency_ms=1.0,
        )

class MockIngestion:
    """Stands in for Member 1's ingest_document. Never reads the file."""

    def __init__(
        self,
        status: str = "success",
        chunk_count: int = 3,
        delay: float = 0.0,
        error_message: str | None = None,
        error: Exception | None = None,
    ):
        self.status = status
        self.chunk_count = chunk_count
        self.delay = delay
        self.error_message = error_message
        self.error = error
        self.calls: list[str] = []

    def ingest_document(self, file_path) -> IngestionResult:
        self.calls.append(str(file_path))
        time.sleep(self.delay)
        if self.error is not None:
            raise self.error

        path = Path(file_path)
        document_id = path.stem  # like the real pipeline: id comes from the filename
        has_chunks = self.status in ("success", "partial")
        chunks = [make_chunk(document_id, i) for i in range(self.chunk_count)] if has_chunks else []

        message = self.error_message
        if message is None and self.status == "failed":
            message = "Could not read the file."
        if message is None and self.status == "partial":
            message = "Some pages could not be read."

        return IngestionResult(
            document_id=document_id,
            filename=path.name,
            status=self.status,
            chunks=chunks,
            error_message=message,
        )