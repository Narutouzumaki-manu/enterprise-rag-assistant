import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.document import Chunk, ChunkMetadata, IngestionResult, SourceType


def make_chunk(document_id: str, index: int) -> Chunk:
    return Chunk(
        chunk_id=f"{document_id}_chunk_{index}",
        document_id=document_id,
        text=f"Chunk {index} text.",
        token_count=4,
        metadata=ChunkMetadata(
            document_id=document_id,
            source_type=SourceType.PDF,
            page_number=index + 1,
            section_title="Intro",
            content_hash="h",
            ingested_at=datetime.now(timezone.utc),
        ),
    )


class StubIngestion:
    """Stands in for Member 1's pipeline: takes a path, returns an IngestionResult."""

    def __init__(self, status="success", chunk_count=3, error_message=None, error=None,
                 delay=0.0, wrong_id=False):
        self.status, self.chunk_count = status, chunk_count
        self.error_message, self.error = error_message, error
        self.delay, self.wrong_id = delay, wrong_id
        self.active = self.peak = 0
        self._lock = threading.Lock()

    def __call__(self, path: str) -> IngestionResult:
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(self.delay)
            if self.error is not None:
                raise self.error
            document_id = "someone-else" if self.wrong_id else Path(path).stem
            has_chunks = self.status in ("success", "partial")
            chunks = [make_chunk(document_id, i) for i in range(self.chunk_count)] if has_chunks else []
            return IngestionResult(
                document_id=document_id, filename=Path(path).name, status=self.status,
                chunks=chunks, error_message=self.error_message,
            )
        finally:
            with self._lock:
                self.active -= 1


class StubRetriever:
    def __init__(self, index_error=None, delete_error=None):
        self.index_error = index_error
        self.delete_error = delete_error
        self.indexed: list[str] = []
        self.deleted: list[str] = []

    def index_chunks(self, chunks) -> None:
        if self.index_error is not None:
            raise self.index_error
        self.indexed.extend(chunk.chunk_id for chunk in chunks)

    def delete_document(self, document_id: str) -> None:
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted.append(document_id)