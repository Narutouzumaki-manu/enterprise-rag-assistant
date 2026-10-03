from app.retrieval.fusion import reciprocal_rank_fusion
from app.schemas.retrieval import RetrievedChunk


def rc(chunk_id, dense=None, sparse=None):
    return RetrievedChunk(
        chunk_id=chunk_id, document_id="d", text=chunk_id,
        dense_score=dense, sparse_score=sparse,
    )


def fmt(value, places):
    return "  -  " if value is None else f"{value:.{places}f}"


dense = [rc("A", dense=0.9), rc("B", dense=0.8), rc("C", dense=0.7)]
sparse = [rc("C", sparse=7.5), rc("A", sparse=5.0), rc("D", sparse=3.0)]

fused = reciprocal_rank_fusion(dense, sparse)

print("chunk  dense  sparse  fused")
for c in fused:
    print(f"  {c.chunk_id}    {fmt(c.dense_score, 1)}   {fmt(c.sparse_score, 1)}   {fmt(c.fused_score, 4)}")

print("\nOriginal input untouched? dense[0].fused_score =", dense[0].fused_score)
print("Limit of 2:", [c.chunk_id for c in reciprocal_rank_fusion(dense, sparse, limit=2)])