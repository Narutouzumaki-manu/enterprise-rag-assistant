from pydantic import BaseModel
from datetime import datetime
from enum import Enum


class SourceType(str, Enum):
    PDF = "pdf"
    DOCX = "docx"
    CSV = "csv"


class ChunkMetadata(BaseModel):
    document_id: str
    source_type: SourceType
    page_number: int | None = None
    section_title: str | None = None
    row_range: tuple[int, int] | None = None
    content_hash: str
    ingested_at: datetime


class Chunk(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    token_count: int
    metadata: ChunkMetadata


class IngestionResult(BaseModel):
    document_id: str
    filename: str
    status: str  # "success" | "failed" | "partial"
    chunks: list[Chunk]
    error_message: str | None = None