from sentence_transformers import CrossEncoder

from app.schemas.retrieval import RetrievedChunk

DEFAULT_RERANKER = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class Reranker:
    """Re-scores candidate chunks by reading the query and each chunk together."""

    def __init__(self, model_name: str = DEFAULT_RERANKER):
        self.model_name = model_name
        self.model = CrossEncoder(model_name)

    def rerank(
        self, query: str, candidates: list[RetrievedChunk], top_k: int = 5
    ) -> list[RetrievedChunk]:
        if not query or not query.strip() or not candidates:
            return []
        pairs = [(query, chunk.text) for chunk in candidates]
        scores = self.model.predict(pairs)

        reranked = []
        for chunk, score in zip(candidates, scores):
            updated = chunk.model_copy()
            updated.rerank_score = float(score)
            reranked.append(updated)

        reranked.sort(key=lambda c: c.rerank_score, reverse=True)
        return reranked[:top_k]