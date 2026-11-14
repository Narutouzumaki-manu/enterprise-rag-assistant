from datetime import UTC, datetime

import tiktoken

from app.ingestion.table_format import (
    convert_table_chunks,
    linearize_table,
    looks_like_table,
)
from app.schemas.document import Chunk, ChunkMetadata, SourceType

TABLE = (
    "Quarter end | Closing headcount | Change in quarter\n"
    "Q1 FY26 (30 Jun 2025) | 613,069 | +6,071\n"
    "Q2 FY26 (30 Sep 2025) | 593,314 | -19,755"
)
TABLE_AS_SENTENCES = (
    "Quarter end: Q1 FY26 (30 Jun 2025); Closing headcount: 613,069; Change in quarter: +6,071. "
    "Quarter end: Q2 FY26 (30 Sep 2025); Closing headcount: 593,314; Change in quarter: -19,755."
)
encoding = tiktoken.get_encoding("cl100k_base")


def make_chunk(text, source_type=SourceType.PDF, position=1):
    return Chunk(
        chunk_id=f"doc_{position}",
        document_id="doc",
        text=text,
        token_count=999,  # deliberately wrong, to prove when it is (not) recomputed
        metadata=ChunkMetadata(
            document_id="doc",
            source_type=source_type,
            page_number=3,
            section_title="Table 1",
            content_hash="filehash",
            ingested_at=datetime.now(UTC),
        ),
    )


# ---- looks_like_table ----

def test_two_pipe_lines_look_like_a_table():
    assert looks_like_table(TABLE)


def test_prose_does_not_look_like_a_table():
    assert not looks_like_table("Revenue grew 4.6% in rupees. Margins were stable.")


def test_a_single_pipe_line_is_not_a_table():
    assert not looks_like_table("A | B")


# ---- linearize_table ----

def test_rows_become_sentences():
    assert linearize_table(TABLE) == TABLE_AS_SENTENCES


def test_non_table_lines_are_kept_in_front():
    assert linearize_table("Table 1\nA | B\n1 | 2") == "Table 1 A: 1; B: 2."


def test_empty_cells_are_skipped():
    assert linearize_table("A | B\n1 | ") == "A: 1."


def test_cell_beyond_the_header_is_kept_unlabelled():
    assert linearize_table("A | B\n1 | 2 | 3") == "A: 1; B: 2; 3."


def test_blank_header_cell_uses_the_cell_alone():
    assert linearize_table(" | B\nx | 2") == "x; B: 2."


def test_text_that_is_not_a_table_is_returned_unchanged():
    assert linearize_table("Just a sentence.") == "Just a sentence."


# ---- convert_table_chunks ----

def test_convert_rewrites_text_and_recomputes_token_count():
    converted = convert_table_chunks([make_chunk(TABLE)])[0]
    assert converted.text == TABLE_AS_SENTENCES
    assert converted.token_count == len(encoding.encode(TABLE_AS_SENTENCES))
    assert converted.token_count != 999


def test_convert_keeps_ids_and_metadata():
    original = make_chunk(TABLE)
    converted = convert_table_chunks([original])[0]
    assert converted.chunk_id == original.chunk_id
    assert converted.document_id == original.document_id
    assert converted.metadata == original.metadata


def test_convert_leaves_prose_untouched():
    prose = make_chunk("Revenue grew 4.6% in rupees.")
    converted = convert_table_chunks([prose])[0]
    assert converted.text == "Revenue grew 4.6% in rupees."
    assert converted.token_count == 999


def test_convert_leaves_csv_chunks_untouched():
    csv_chunk = make_chunk(TABLE, source_type=SourceType.CSV)
    converted = convert_table_chunks([csv_chunk])[0]
    assert converted.text == TABLE
    assert converted.token_count == 999


def test_convert_does_not_modify_the_input():
    original = make_chunk(TABLE)
    convert_table_chunks([original])
    assert original.text == TABLE
    assert original.token_count == 999


def test_convert_keeps_order_and_length():
    chunks = [make_chunk("prose one", position=1), make_chunk(TABLE, position=2), make_chunk("prose three", position=3)]
    converted = convert_table_chunks(chunks)
    assert [c.chunk_id for c in converted] == ["doc_1", "doc_2", "doc_3"]


def test_convert_empty_list():
    assert convert_table_chunks([]) == []


def test_converting_twice_changes_nothing_more():
    once = convert_table_chunks([make_chunk(TABLE)])
    twice = convert_table_chunks(once)
    assert twice[0].text == once[0].text
    assert twice[0].token_count == once[0].token_count