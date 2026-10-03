import tempfile
import uuid
from datetime import datetime, timezone

from app.retrieval.bm25_index import BM25Index
from app.retrieval.embeddings import EmbeddingService
from app.retrieval.hybrid_search import HybridRetriever
from app.retrieval.vector_store import VectorStore
from app.schemas.document import Chunk, ChunkMetadata, SourceType


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
            ingested_at=datetime.now(timezone.utc),
        ),
    )


chunks = [
    make_chunk("Revenue increased 18% in Q3 due to strong cloud sales.", 0, "finance", 12),
    make_chunk("Operating margin was 18.4% in the third quarter.", 1, "finance", 17),
    make_chunk("The company cafeteria serves lunch from noon to 2 pm.", 0, "hr", 3),
    make_chunk("Employees get 24 days of paid leave per year.", 1, "hr", 5),
]

embedding = EmbeddingService()
store = VectorStore(embedding, collection_name=f"check_{uuid.uuid4().hex}")
store.upsert(chunks)
bm25 = BM25Index()
bm25.upsert(chunks)

two_keys = {"document_id": "finance", "page_number": 12}

# Check 1: two filter keys at once, meaning search
try:
    found = store.search("revenue", k=3, filters=two_keys)
    print("Check 1 (two-key filter, VectorStore): worked ->", [c.chunk_id for c in found])
except Exception as e:
    print("Check 1 (two-key filter, VectorStore): FAILED ->", type(e).__name__, str(e)[:100])

# Check 2: the same two keys, keyword search
print("Check 2 (two-key filter, BM25):", [c.chunk_id for c in bm25.search("revenue", k=3, filters=two_keys)])

# Check 3: a filter key that only one index knows about
try:
    print("Check 3a (content_hash filter, VectorStore):", len(store.search("revenue", k=3, filters={"content_hash": "fakehash"})), "results")
except Exception as e:
    print("Check 3a FAILED ->", type(e).__name__, str(e)[:100])
print("Check 3b (content_hash filter, BM25):", len(bm25.search("revenue", k=3, filters={"content_hash": "fakehash"})), "results")

# Check 4: restart (reranker left out so no extra model loads)
path = tempfile.mkdtemp()
first = HybridRetriever(VectorStore(embedding, persist_path=path), BM25Index(), reranker=None)
first.index_chunks(chunks)
restarted = HybridRetriever(VectorStore(embedding, persist_path=path), BM25Index(), reranker=None)
print("Check 4 (after restart): vector store has", restarted.vector_store.count(),
      "chunks, BM25 has", restarted.bm25_index.count())