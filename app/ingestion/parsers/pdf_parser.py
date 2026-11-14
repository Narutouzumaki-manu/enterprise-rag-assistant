import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pymupdf
import tiktoken

from app.ingestion.chunker import chunk_text
from app.schemas.document import Chunk, ChunkMetadata, IngestionResult, SourceType


def _extract_tables_pdf(page) -> tuple[list[str], list[tuple]]:
    """
    Finds tables on a page using PyMuPDF's built-in table detector.
    Returns (list of structured pipe-delimited table texts, list of their bounding boxes).
    The bounding boxes let us exclude table text from prose extraction later.
    """
    table_texts = []
    bboxes = []
    try:
        found = page.find_tables()
    except Exception:
        return [], []

    for table in found:
        data = table.extract()
        rows_text = [" | ".join((cell or "").strip() for cell in row) for row in data]
        table_texts.append("\n".join(rows_text))
        bboxes.append(table.bbox)

    return table_texts, bboxes


def _line_in_any_bbox(line_bbox, bboxes) -> bool:
    """Checks if a line's center point falls inside any given bounding box."""
    lx0, ly0, lx1, ly1 = line_bbox
    cx, cy = (lx0 + lx1) / 2, (ly0 + ly1) / 2
    for (bx0, by0, bx1, by1) in bboxes:
        if bx0 <= cx <= bx1 and by0 <= cy <= by1:
            return True
    return False


def _extract_sections_pdf(page, exclude_bboxes: list[tuple]) -> list[tuple[str | None, str]]:
    """
    Groups page text by heading, using font size as the heading signal
    (lines notably larger than the page's average font size are treated as headings).
    Text inside exclude_bboxes (table regions) is skipped to avoid duplication.
    """
    page_dict = page.get_text("dict")
    lines_info = []

    for block in page_dict["blocks"]:
        if block.get("type") != 0:  # skip non-text blocks (e.g. images)
            continue
        for line in block["lines"]:
            spans = line["spans"]
            if not spans:
                continue
            line_text = "".join(s["text"] for s in spans).strip()
            if not line_text:
                continue
            if _line_in_any_bbox(line["bbox"], exclude_bboxes):
                continue
            max_size = max(s["size"] for s in spans)
            lines_info.append((line_text, max_size))

    if not lines_info:
        return []

    avg_size = sum(size for _, size in lines_info) / len(lines_info)
    heading_threshold = avg_size * 1.15

    sections = []
    current_title = None
    current_texts = []

    for text, size in lines_info:
        if size >= heading_threshold and len(text) < 100:
            if current_texts:
                sections.append((current_title, " ".join(current_texts)))
            current_title = text
            current_texts = []
        else:
            current_texts.append(text)

    if current_texts:
        sections.append((current_title, " ".join(current_texts)))

    return sections


def parse_pdf(path: str) -> IngestionResult:
    """
    Reads a PDF file, extracting per page:
    - Prose text grouped by detected section headings, chunked with chunk_text
    - Tables extracted separately as structured chunks (never flattened)
    """
    pdf = pymupdf.open(path)
    document_id = Path(path).stem
    content_hash = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    now = datetime.now(UTC)
    encoding = tiktoken.get_encoding("cl100k_base")

    chunks = []
    position = 0

    for page_index, page in enumerate(pdf):
        table_texts, table_bboxes = _extract_tables_pdf(page)

        # --- Prose, grouped by section, excluding table regions ---
        for section_title, section_text in _extract_sections_pdf(page, table_bboxes):
            for chunk_str in chunk_text(section_text, max_tokens=400, overlap_tokens=50):
                chunk = Chunk(
                    chunk_id=hashlib.sha256(f"{document_id}_{position}".encode()).hexdigest(),
                    document_id=document_id,
                    text=chunk_str,
                    token_count=len(encoding.encode(chunk_str)),
                    metadata=ChunkMetadata(
                        document_id=document_id,
                        source_type=SourceType.PDF,
                        page_number=page_index + 1,
                        section_title=section_title,
                        content_hash=content_hash,
                        ingested_at=now,
                    ),
                )
                chunks.append(chunk)
                position += 1

        # --- Tables, extracted separately, never flattened ---
        for table_index, table_text in enumerate(table_texts):
            row_count = table_text.count("\n") + 1
            chunk = Chunk(
                chunk_id=hashlib.sha256(f"{document_id}_{position}".encode()).hexdigest(),
                document_id=document_id,
                text=table_text,
                token_count=len(encoding.encode(table_text)),
                metadata=ChunkMetadata(
                    document_id=document_id,
                    source_type=SourceType.PDF,
                    page_number=page_index + 1,
                    section_title=f"Table {table_index + 1}",
                    row_range=(0, row_count - 1),
                    content_hash=content_hash,
                    ingested_at=now,
                ),
            )
            chunks.append(chunk)
            position += 1

    pdf.close()

    return IngestionResult(
        document_id=document_id,
        filename=Path(path).name,
        status="success",
        chunks=chunks,
    )


if __name__ == "__main__":
    sample_path = Path("tests/fixtures/sample_rich.pdf")
    result = parse_pdf(str(sample_path))
    print(f"Status: {result.status}")
    print(f"Filename: {result.filename}")
    print(f"Chunk count: {len(result.chunks)}")
    for chunk in result.chunks:
        print(f"\n[page: {chunk.metadata.page_number}, section: {chunk.metadata.section_title}, row_range: {chunk.metadata.row_range}]")
        print(chunk.text[:100])