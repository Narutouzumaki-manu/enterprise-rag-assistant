from app.schemas.retrieval import RetrievedChunk

RRF_K = 60


def reciprocal_rank_fusion(
    dense_results: list[RetrievedChunk],
    sparse_results: list[RetrievedChunk],
    k: int = RRF_K,
    limit: int | None = None,
) -> list[RetrievedChunk]:
    """Merge two ranked lists. Each appearance adds 1 / (k + rank) to a chunk's score."""
    merged: dict[str, RetrievedChunk] = {}
    scores: dict[str, float] = {}

    for results in (dense_results, sparse_results):
        seen: set[str] = set()
        for rank, chunk in enumerate(results):
            if chunk.chunk_id in seen:
                continue  # count a chunk only once per list
            seen.add(chunk.chunk_id)
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (k + rank + 1)

            if chunk.chunk_id not in merged:
                merged[chunk.chunk_id] = chunk.model_copy()  # copy: never edit the caller's objects
            else:
                existing = merged[chunk.chunk_id]
                if chunk.dense_score is not None:
                    existing.dense_score = chunk.dense_score
                if chunk.sparse_score is not None:
                    existing.sparse_score = chunk.sparse_score

    ranked = sorted(merged.values(), key=lambda c: scores[c.chunk_id], reverse=True)
    for chunk in ranked:
        chunk.fused_score = scores[chunk.chunk_id]

    return ranked[:limit] if limit is not None else ranked