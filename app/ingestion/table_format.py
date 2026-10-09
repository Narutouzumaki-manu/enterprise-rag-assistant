import tiktoken

from app.schemas.document import Chunk, SourceType

_encoding = tiktoken.get_encoding("cl100k_base")
_TABLE_SOURCES = {SourceType.PDF, SourceType.DOCX}


def looks_like_table(text: str) -> bool:
    """A table chunk has at least two lines containing a pipe (header + a row)."""
    return sum(1 for line in text.split("\n") if "|" in line) >= 2


def linearize_table(text: str) -> str:
    """Turn pipe-separated rows into short sentences: 'Header: value; Header: value.'"""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    table_lines = [line for line in lines if "|" in line]
    if len(table_lines) < 2:
        return text  # not a table: leave it alone
    other_lines = [line for line in lines if "|" not in line]
    header = [cell.strip() for cell in table_lines[0].split("|")]

    sentences = []
    for line in table_lines[1:]:
        cells = [cell.strip() for cell in line.split("|")]
        parts = []
        for index, cell in enumerate(cells):
            if not cell:
                continue
            head = header[index] if index < len(header) else ""
            parts.append(f"{head}: {cell}" if head else cell)
        if parts:
            sentences.append("; ".join(parts) + ".")
    return " ".join(other_lines + sentences)


def convert_table_chunks(chunks: list[Chunk]) -> list[Chunk]:
    """Rewrite table chunks (PDF and DOCX only) as sentences. IDs and metadata are unchanged."""
    converted = []
    for chunk in chunks:
        if chunk.metadata.source_type in _TABLE_SOURCES and looks_like_table(chunk.text):
            new_text = linearize_table(chunk.text)
            chunk = chunk.model_copy(update={
                "text": new_text,
                "token_count": len(_encoding.encode(new_text)),
            })
        converted.append(chunk)
    return converted