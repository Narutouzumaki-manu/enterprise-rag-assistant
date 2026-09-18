from app.ingestion.parsers.csv_parser import parse_csv
from app.schemas.document import IngestionResult, SourceType


SAMPLE_CSV_PATH = "tests/fixtures/sample.csv"


def test_parse_csv_returns_ingestion_result():
    """The function should return an IngestionResult, not a raw list."""
    result = parse_csv(SAMPLE_CSV_PATH)
    assert isinstance(result, IngestionResult)


def test_parse_csv_status_is_success():
    """A valid CSV should always report status='success'."""
    result = parse_csv(SAMPLE_CSV_PATH)
    assert result.status == "success"


def test_parse_csv_creates_one_chunk_per_row():
    """sample.csv has 2 rows, so we expect exactly 2 chunks."""
    result = parse_csv(SAMPLE_CSV_PATH)
    assert len(result.chunks) == 2


def test_parse_csv_chunk_has_correct_source_type():
    """Every chunk's metadata should be tagged as CSV."""
    result = parse_csv(SAMPLE_CSV_PATH)
    for chunk in result.chunks:
        assert chunk.metadata.source_type == SourceType.CSV


def test_parse_csv_chunk_ids_are_unique():
    """No two chunks should ever share the same chunk_id."""
    result = parse_csv(SAMPLE_CSV_PATH)
    chunk_ids = [chunk.chunk_id for chunk in result.chunks]
    assert len(chunk_ids) == len(set(chunk_ids))


def test_parse_csv_is_deterministic():
    """Parsing the same file twice should produce identical chunk_ids (idempotency)."""
    result1 = parse_csv(SAMPLE_CSV_PATH)
    result2 = parse_csv(SAMPLE_CSV_PATH)

    ids1 = [chunk.chunk_id for chunk in result1.chunks]
    ids2 = [chunk.chunk_id for chunk in result2.chunks]

    assert ids1 == ids2


def test_parse_csv_row_range_matches_row_index():
    """Each chunk's row_range should match its actual row position in the CSV."""
    result = parse_csv(SAMPLE_CSV_PATH)
    assert result.chunks[0].metadata.row_range == (0, 0)
    assert result.chunks[1].metadata.row_range == (1, 1)