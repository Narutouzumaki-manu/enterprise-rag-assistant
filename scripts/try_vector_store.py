from datetime import datetime, timezone

from app.retrieval.embeddings import EmbeddingService
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

store = VectorStore(EmbeddingService())

store.upsert(chunks)
print("count after first save:", store.count())

store.upsert(chunks)
print("count after saving the same chunks again:", store.count())

print("\nSearch: 'How did sales grow?'")
for r in store.search("How did sales grow?", k=2):
    print(f"  {r.dense_score:.3f}  p.{r.page_number}  {r.text}")

print("\nSearch only inside the 'hr' document: 'time off'")
for r in store.search("time off", k=2, filters={"document_id": "hr"}):
    print(f"  {r.dense_score:.3f}  {r.document_id}  {r.text}")

print("\ndeleted from 'finance':", store.delete("finance"))
print("count after delete:", store.count())