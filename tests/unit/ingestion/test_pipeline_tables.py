import tiktoken

from app.ingestion.dedupe import clear_registry
from app.ingestion.parsers.docx_parser import parse_docx
from app.ingestion.parsers.pdf_parser import parse_pdf
from app.ingestion.pipeline import ingest_document
from app.ingestion.table_format import looks_like_table

DOCX = "tests/fixtures/sample_rich.docx"
PDF = "tests/fixtures/sample_rich.pdf"
encoding = tiktoken.get_encoding("cl100k_base")


def test_docx_tables_arrive_as_sentences():
    clear_registry()
    assert any(looks_like_table(c.text) for c in parse_docx(DOCX).chunks)  # the fixture really has a table
    clear_registry()
    result = ingest_document(DOCX)
    assert result.status == "success"
    assert not any(looks_like_table(c.text) for c in result.chunks)


def test_pdf_tables_arrive_as_sentences():
    clear_registry()
    assert any(looks_like_table(c.text) for c in parse_pdf(PDF).chunks)
    clear_registry()
    result = ingest_document(PDF)
    assert result.status == "success"
    assert not any(looks_like_table(c.text) for c in result.chunks)


def test_docx_chunk_ids_are_unchanged_by_the_conversion():
    clear_registry()
    parsed = parse_docx(DOCX)
    clear_registry()
    result = ingest_document(DOCX)
    assert [c.chunk_id for c in result.chunks] == [c.chunk_id for c in parsed.chunks]


def test_pdf_chunk_ids_are_unchanged_by_the_conversion():
    clear_registry()
    parsed = parse_pdf(PDF)
    clear_registry()
    result = ingest_document(PDF)
    assert [c.chunk_id for c in result.chunks] == [c.chunk_id for c in parsed.chunks]


def test_converted_chunks_have_matching_token_counts():
    clear_registry()
    parsed = {c.chunk_id: c for c in parse_docx(DOCX).chunks}
    clear_registry()
    result = ingest_document(DOCX)
    changed = [c for c in result.chunks if c.text != parsed[c.chunk_id].text]
    assert changed
    for chunk in changed:
        assert chunk.token_count == len(encoding.encode(chunk.text))