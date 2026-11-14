import hashlib
from datetime import UTC, datetime
from pathlib import Path

import tiktoken
from docx import Document

from app.ingestion.chunker import chunk_text
from app.schemas.document import Chunk, ChunkMetadata, IngestionResult, SourceType


def _extract_sections(doc: Document) -> list[tuple[str | None, str]]:
    """
    Groups paragraph text by the heading it falls under.
    Returns a list of (section_title, section_text) tuples.
    Text before the first heading has section_title=None.
    """
    sections = []
    current_title = None
    current_paragraphs = []

    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue

        is_heading = paragraph.style.name.startswith("Heading")

        if is_heading:
            if current_paragraphs:
                sections.append((current_title, " ".join(current_paragraphs)))
            current_title = text
            current_paragraphs = []
        else:
            current_paragraphs.append(text)

    if current_paragraphs:
        sections.append((current_title, " ".join(current_paragraphs)))

    return sections


def _extract_tables(doc: Document) -> list[str]:
    """
    Extracts each table as a structured, pipe-delimited text block,
    preserving row/column structure instead of flattening into prose.
    """
    table_texts = []
    for table in doc.tables:
        rows_text = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            rows_text.append(" | ".join(cells))
        table_texts.append("\n".join(rows_text))
    return table_texts


def parse_docx(path: str) -> IngestionResult:
    """
    Reads a DOCX file, extracting:
    - Prose text grouped by section (heading), chunked with chunk_text
    - Tables extracted separately as structured chunks (never flattened)
    """
    doc = Document(path)
    document_id = Path(path).stem
    content_hash = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    now = datetime.now(UTC)
    encoding = tiktoken.get_encoding("cl100k_base")

    chunks = []
    position = 0

    # --- Prose, grouped by section ---
    for section_title, section_text in _extract_sections(doc):
        for chunk_str in chunk_text(section_text, max_tokens=400, overlap_tokens=50):
            chunk = Chunk(
                chunk_id=hashlib.sha256(f"{document_id}_{position}".encode()).hexdigest(),
                document_id=document_id,
                text=chunk_str,
                token_count=len(encoding.encode(chunk_str)),
                metadata=ChunkMetadata(
                    document_id=document_id,
                    source_type=SourceType.DOCX,
                    section_title=section_title,
                    content_hash=content_hash,
                    ingested_at=now,
                ),
            )
            chunks.append(chunk)
            position += 1

    # --- Tables, extracted separately, never flattened ---
    for table_index, table_text in enumerate(_extract_tables(doc)):
        row_count = table_text.count("\n") + 1
        chunk = Chunk(
            chunk_id=hashlib.sha256(f"{document_id}_{position}".encode()).hexdigest(),
            document_id=document_id,
            text=table_text,
            token_count=len(encoding.encode(table_text)),
            metadata=ChunkMetadata(
                document_id=document_id,
                source_type=SourceType.DOCX,
                section_title=f"Table {table_index + 1}",
                row_range=(0, row_count - 1),
                content_hash=content_hash,
                ingested_at=now,
            ),
        )
        chunks.append(chunk)
        position += 1

    return IngestionResult(
        document_id=document_id,
        filename=Path(path).name,
        status="success",
        chunks=chunks,
    )


if __name__ == "__main__":
    sample_path = Path("tests/fixtures/sample_rich.docx")
    result = parse_docx(str(sample_path))
    print(f"Status: {result.status}")
    print(f"Filename: {result.filename}")
    print(f"Chunk count: {len(result.chunks)}")
    for chunk in result.chunks:
        print(f"\n[section: {chunk.metadata.section_title}, row_range: {chunk.metadata.row_range}]")
        print(chunk.text[:100])