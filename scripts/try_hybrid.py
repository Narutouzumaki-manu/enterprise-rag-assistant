from datetime import UTC, datetime

from app.retrieval.bm25_index import BM25Index
from app.retrieval.embeddings import EmbeddingService
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.hybrid_search import HybridRetriever
from app.retrieval.reranker import Reranker
from app.retrieval.vector_store import VectorStore
from app.schemas.document import Chunk, ChunkMetadata, SourceType
from app.schemas.retrieval import RetrievalRequest, RetrievedChunk


def fmt(value):
    return "  -   " if value is None else f"{value:6.3f}"


def show(response):
    print(f"  models: {response.embedding_model} | {response.reranker_model} | {response.latency_ms:.0f} ms")
    print("  dense   sparse  fused   rerank  chunk")
    for r in response.results:
        print(f"  {fmt(r.dense_score)} {fmt(r.sparse_score)} {fmt(r.fused_score)} {fmt(r.rerank_score)}  {r.chunk_id}: {r.text[:55]}")


# ---- Part 1: fusion on its own, using the example from the project roadmap ----
def rc(chunk_id):
    return RetrievedChunk(chunk_id=chunk_id, document_id="d", text=chunk_id)


dense = [rc("A"), rc("B"), rc("C")]
sparse = [rc("C"), rc("A"), rc("D")]
print("Fusion order (expect A, C, B, D):", [c.chunk_id for c in reciprocal_rank_fusion(dense, sparse)])


# ---- Part 2: the whole pipeline ----
def make_chunk(text, position, doc_id, page):
    return Chunk(
        chunk_id=f"{doc_id}_{position}",
        document_id=doc_id,
        text=text,
        token_count=len(text.split()),
        metadata=ChunkMetadata(
            document_id=doc_id,
            source_type=SourceType.PDF,
            page_number=page,
            content_hash="fakehash",
            ingested_at=datetime.now(UTC),
        ),
    )


chunks = [
    make_chunk("Revenue increased 18% in Q3 due to strong cloud sales.", 0, "finance", 12),
    make_chunk("Operating margin was 18.4% in the third quarter.", 1, "finance", 17),
    make_chunk("The vendor holds a SOC 2 Type II certification, audited annually.", 0, "security", 4),
    make_chunk("Data is encrypted at rest using AES-256 and in transit using TLS 1.3.", 1, "security", 6),
    make_chunk("The company cafeteria serves lunch from noon to 2 pm.", 0, "hr", 3),
    make_chunk("Employees get 24 days of paid leave per year.", 1, "hr", 5),
    make_chunk("Cloud infrastructure costs fell 9% after moving to reserved instances.", 0, "ops", 2),
]

retriever = HybridRetriever(VectorStore(EmbeddingService()), BM25Index(), Reranker())
retriever.index_chunks(chunks)

for query in ["How did sales grow?", "SOC 2 Type II", "time off allowance"]:
    print(f"\nQuery: {query!r}")
    show(retriever.retrieve(RetrievalRequest(query=query, top_k=3)))

print("\nOnly inside 'hr': 'time off allowance'")
show(retriever.retrieve(RetrievalRequest(query="time off allowance", top_k=3, filters={"document_id": "hr"})))

print("\nDeleted from 'finance':", retriever.delete_document("finance"))
print("Query 'How did sales grow?' after delete:")
show(retriever.retrieve(RetrievalRequest(query="How did sales grow?", top_k=3)))