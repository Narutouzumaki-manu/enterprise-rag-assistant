from app.schemas.document import Chunk, ChunkMetadata, SourceType

meta = ChunkMetadata(document_id="doc1", source_type=SourceType.PDF, content_hash="abc123")
chunk = Chunk(chunk_id="c1", document_id="doc1", text="Hello world", token_count=2, metadata=meta)
print(chunk)