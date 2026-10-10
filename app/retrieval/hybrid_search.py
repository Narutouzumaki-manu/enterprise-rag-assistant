import time

from app.retrieval.bm25_index import BM25Index
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.reranker import Reranker
from app.retrieval.vector_store import VectorStore
from app.schemas.document import Chunk
from app.schemas.retrieval import RetrievalRequest, RetrievalResponse, RetrievedChunk


class HybridRetriever:
    """The one object Member 3 talks to: index chunks in, retrieve() out."""

    def __init__(
        self,
        vector_store: VectorStore,
        bm25_index: BM25Index,
        reranker: Reranker | None = None,
        fetch_k: int = 30,
         use_keyword: bool = True,
    ):
        self.vector_store = vector_store
        self.bm25_index = bm25_index
        self.reranker = reranker
        self.fetch_k = fetch_k  # fetch broad (cheap), then rerank narrow (precise)
        self.use_keyword = use_keyword
                # After a restart ChromaDB still has its data, but the in-memory keyword index is empty
        if self.bm25_index.count() == 0 and self.vector_store.count() > 0:
            self.rebuild_keyword_index()

    def rebuild_keyword_index(self) -> int:
        """Rebuild the keyword index from what the vector store holds.
        Returns how many chunks were restored."""
        self.bm25_index.clear()
        self.bm25_index.restore(self.vector_store.export_records())
        return self.bm25_index.count()
    

    def index_chunks(self, chunks: list[Chunk]) -> None:
        """Add chunks to BOTH indexes so they never drift apart."""
        self.vector_store.upsert(chunks)
        self.bm25_index.upsert(chunks)

    def delete_document(self, document_id: str) -> int:
        """Remove a document from BOTH indexes."""
        removed = self.vector_store.delete(document_id)
        self.bm25_index.delete(document_id)
        return removed

    def retrieve(self, request: RetrievalRequest) -> RetrievalResponse:
        start = time.perf_counter()
        query = request.query

        if not query or not query.strip():
            return self._response(query, [], "none", start)

        dense = self.vector_store.search(query, k=self.fetch_k, filters=request.filters)
        if self.use_keyword:
            sparse = self.bm25_index.search(query, k=self.fetch_k, filters=request.filters)
            candidates = reciprocal_rank_fusion(dense, sparse, limit=self.fetch_k)
        else:
            candidates = dense  # meaning search only, in the vector store's own order

        results: list[RetrievedChunk]
        reranker_model = "none"
        if self.reranker is not None and candidates:
            try:
                results = self.reranker.rerank(query, candidates, top_k=request.top_k)
                reranker_model = self.reranker.model_name
            except Exception:
                # Reranker broke: fall back to the candidate order instead of failing the request
                results = candidates[: request.top_k]
                reranker_model = "none (reranker failed, candidate order used)"
        else:
            results = candidates[: request.top_k]

        return self._response(query, results, reranker_model, start)

    def _response(
        self, query: str, results: list[RetrievedChunk], reranker_model: str, start: float
    ) -> RetrievalResponse:
        return RetrievalResponse(
            query=query,
            results=results,
            embedding_model=self.vector_store.embedding_service.model_name,
            reranker_model=reranker_model,
            latency_ms=(time.perf_counter() - start) * 1000,
        )