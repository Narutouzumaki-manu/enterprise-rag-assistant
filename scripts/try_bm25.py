from datetime import datetime, timezone

from app.retrieval.bm25_index import BM25Index
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
    make_chunk("The vendor holds a SOC 2 Type II certification, audited annually.", 0, "security", 4),
    make_chunk("The company cafeteria serves lunch from noon to 2 pm.", 0, "hr", 3),
    make_chunk("Employees get 24 days of paid leave per year.", 1, "hr", 5),
]

index = BM25Index()
index.upsert(chunks)
print("count:", index.count())

index.upsert(chunks)
print("count after saving the same chunks again:", index.count())

print("\nSearch: 'SOC 2 Type II'")
for r in index.search("SOC 2 Type II", k=3):
    print(f"  {r.sparse_score:.3f}  {r.chunk_id}  {r.text}")

print("\nSearch: 'xylophone' (a word nobody used)")
print("  results:", index.search("xylophone"))

print("\nSearch only inside 'hr': 'the company year'")
for r in index.search("the company year", k=3, filters={"document_id": "hr"}):
    print(f"  {r.sparse_score:.3f}  {r.chunk_id}  {r.text}")

print("\ndeleted from 'security':", index.delete("security"))
print("search 'SOC 2 Type II' after delete:", [r.chunk_id for r in index.search("SOC 2 Type II")])