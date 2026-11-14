from app.ingestion.parsers.pdf_parser import parse_pdf
from app.schemas.document import IngestionResult, SourceType

SAMPLE_PDF_PATH = "tests/fixtures/sample.pdf"


def test_parse_pdf_returns_ingestion_result():
    """The function should return an IngestionResult, not a raw list."""
    result = parse_pdf(SAMPLE_PDF_PATH)
    assert isinstance(result, IngestionResult)


def test_parse_pdf_status_is_success():
    """A valid PDF should always report status='success'."""
    result = parse_pdf(SAMPLE_PDF_PATH)
    assert result.status == "success"


def test_parse_pdf_creates_one_chunk_per_page():
    """sample.pdf has 2 pages, so we expect exactly 2 chunks."""
    result = parse_pdf(SAMPLE_PDF_PATH)
    assert len(result.chunks) == 2


def test_parse_pdf_chunk_has_correct_source_type():
    """Every chunk's metadata should be tagged as PDF."""
    result = parse_pdf(SAMPLE_PDF_PATH)
    for chunk in result.chunks:
        assert chunk.metadata.source_type == SourceType.PDF


def test_parse_pdf_page_numbers_are_correct():
    """Page numbers should be 1-indexed and match actual page order."""
    result = parse_pdf(SAMPLE_PDF_PATH)
    assert result.chunks[0].metadata.page_number == 1
    assert result.chunks[1].metadata.page_number == 2


def test_parse_pdf_chunk_ids_are_unique():
    """No two chunks should ever share the same chunk_id."""
    result = parse_pdf(SAMPLE_PDF_PATH)
    chunk_ids = [chunk.chunk_id for chunk in result.chunks]
    assert len(chunk_ids) == len(set(chunk_ids))


def test_parse_pdf_is_deterministic():
    """Parsing the same file twice should produce identical chunk_ids (idempotency)."""
    result1 = parse_pdf(SAMPLE_PDF_PATH)
    result2 = parse_pdf(SAMPLE_PDF_PATH)

    ids1 = [chunk.chunk_id for chunk in result1.chunks]
    ids2 = [chunk.chunk_id for chunk in result2.chunks]

    assert ids1 == ids2


def test_parse_pdf_row_range_is_none():
    """PDF chunks are not table-based, so row_range should always be None."""
    result = parse_pdf(SAMPLE_PDF_PATH)
    for chunk in result.chunks:
        assert chunk.metadata.row_range is None

SAMPLE_RICH_PDF_PATH = "tests/fixtures/sample_rich.pdf"


def test_parse_pdf_extracts_section_titles():
    """Font-size-based heading detection should capture section titles."""
    result = parse_pdf(SAMPLE_RICH_PDF_PATH)
    section_titles = {chunk.metadata.section_title for chunk in result.chunks}

    assert "Revenue Overview" in section_titles
    assert "Cost Breakdown" in section_titles


def test_parse_pdf_extracts_table_as_structured_chunk():
    """Tables should appear as their own chunk, never flattened into prose."""
    result = parse_pdf(SAMPLE_RICH_PDF_PATH)
    table_chunks = [c for c in result.chunks if c.metadata.section_title == "Table 1"]

    assert len(table_chunks) == 1
    assert "Category | Amount" in table_chunks[0].text
    assert "Revenue | 100000" in table_chunks[0].text


def test_parse_pdf_table_chunk_has_row_range():
    """A 3-row table should report row_range covering all 3 rows."""
    result = parse_pdf(SAMPLE_RICH_PDF_PATH)
    table_chunks = [c for c in result.chunks if c.metadata.section_title == "Table 1"]

    assert table_chunks[0].metadata.row_range == (0, 2)


def test_parse_pdf_table_text_not_duplicated_in_prose():
    """Table cell content shouldn't also leak into prose section chunks."""
    result = parse_pdf(SAMPLE_RICH_PDF_PATH)
    prose_chunks = [c for c in result.chunks if not (c.metadata.section_title or "").startswith("Table")]

    for chunk in prose_chunks:
        assert "100000" not in chunk.text
        assert "45000" not in chunk.text