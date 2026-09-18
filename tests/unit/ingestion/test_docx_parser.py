from app.ingestion.parsers.docx_parser import parse_docx
from app.schemas.document import IngestionResult, SourceType


SAMPLE_DOCX_PATH = "tests/fixtures/sample.docx"


def test_parse_docx_returns_ingestion_result():
    """The function should return an IngestionResult, not a raw list."""
    result = parse_docx(SAMPLE_DOCX_PATH)
    assert isinstance(result, IngestionResult)


def test_parse_docx_status_is_success():
    """A valid DOCX should always report status='success'."""
    result = parse_docx(SAMPLE_DOCX_PATH)
    assert result.status == "success"


def test_parse_docx_respects_token_limit_per_chunk():
    """No chunk should significantly exceed the chunker's max_tokens setting."""
    result = parse_docx(SAMPLE_DOCX_PATH)
    for chunk in result.chunks:
        assert chunk.token_count <= 450  # small buffer above max_tokens=400


def test_parse_docx_chunk_has_correct_source_type():
    """Every chunk's metadata should be tagged as DOCX."""
    result = parse_docx(SAMPLE_DOCX_PATH)
    for chunk in result.chunks:
        assert chunk.metadata.source_type == SourceType.DOCX


def test_parse_docx_chunk_ids_are_unique():
    """No two chunks should ever share the same chunk_id."""
    result = parse_docx(SAMPLE_DOCX_PATH)
    chunk_ids = [chunk.chunk_id for chunk in result.chunks]
    assert len(chunk_ids) == len(set(chunk_ids))


def test_parse_docx_is_deterministic():
    """Parsing the same file twice should produce identical chunk_ids (idempotency)."""
    result1 = parse_docx(SAMPLE_DOCX_PATH)
    result2 = parse_docx(SAMPLE_DOCX_PATH)

    ids1 = [chunk.chunk_id for chunk in result1.chunks]
    ids2 = [chunk.chunk_id for chunk in result2.chunks]

    assert ids1 == ids2


def test_parse_docx_skips_empty_paragraphs():
    """No chunk should ever contain empty/whitespace-only text."""
    result = parse_docx(SAMPLE_DOCX_PATH)
    for chunk in result.chunks:
        assert chunk.text.strip() != ""


def test_parse_docx_row_range_is_none():
    """DOCX chunks are not table-based, so row_range should always be None."""
    result = parse_docx(SAMPLE_DOCX_PATH)
    for chunk in result.chunks:
        assert chunk.metadata.row_range is None

SAMPLE_RICH_DOCX_PATH = "tests/fixtures/sample_rich.docx"


def test_parse_docx_extracts_section_titles():
    """Headings should be captured as section_title on the chunks that follow them."""
    result = parse_docx(SAMPLE_RICH_DOCX_PATH)
    section_titles = {chunk.metadata.section_title for chunk in result.chunks}

    assert "Revenue Overview" in section_titles
    assert "Cost Breakdown" in section_titles


def test_parse_docx_extracts_table_as_structured_chunk():
    """Tables should appear as their own chunk, never flattened into prose."""
    result = parse_docx(SAMPLE_RICH_DOCX_PATH)
    table_chunks = [c for c in result.chunks if c.metadata.section_title == "Table 1"]

    assert len(table_chunks) == 1
    assert "Category | Amount" in table_chunks[0].text
    assert "Revenue | 100000" in table_chunks[0].text


def test_parse_docx_table_chunk_has_row_range():
    """A 3-row table should report row_range covering all 3 rows."""
    result = parse_docx(SAMPLE_RICH_DOCX_PATH)
    table_chunks = [c for c in result.chunks if c.metadata.section_title == "Table 1"]

    assert table_chunks[0].metadata.row_range == (0, 2)


def test_parse_docx_prose_chunks_have_no_row_range():
    """Only table chunks should have row_range set; prose chunks should not."""
    result = parse_docx(SAMPLE_RICH_DOCX_PATH)
    prose_chunks = [c for c in result.chunks if not (c.metadata.section_title or "").startswith("Table")]

    for chunk in prose_chunks:
        assert chunk.metadata.row_range is None