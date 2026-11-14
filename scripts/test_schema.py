from datetime import UTC, datetime

from app.schemas.document import ChunkMetadata, SourceType

meta = ChunkMetadata(
    document_id="doc1",
    source_type=SourceType.PDF,
    content_hash="abc123",
    ingested_at=datetime.now(UTC).isoformat()
)