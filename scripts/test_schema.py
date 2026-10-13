from datetime import datetime, timezone

from app.schemas.document import Chunk, ChunkMetadata, SourceType



meta = ChunkMetadata(
    document_id="doc1",
    source_type=SourceType.PDF,
    content_hash="abc123",
    ingested_at=datetime.now(timezone.utc).isoformat()
)