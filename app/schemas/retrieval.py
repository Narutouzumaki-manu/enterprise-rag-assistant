from pydantic import BaseModel


class RetrievedChunk(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    dense_score: float | None = None
    sparse_score: float | None = None
    fused_score: float | None = None
    rerank_score: float | None = None
    page_number: int | None = None
    section_title: str | None = None


class RetrievalRequest(BaseModel):
    query: str
    top_k: int = 5
    filters: dict | None = None


class RetrievalResponse(BaseModel):
    query: str
    results: list[RetrievedChunk]
    embedding_model: str
    reranker_model: str
    latency_ms: float