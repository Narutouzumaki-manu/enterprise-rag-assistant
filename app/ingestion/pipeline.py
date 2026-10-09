import hashlib
from pathlib import Path
from app.schemas.document import IngestionResult, SourceType
from app.ingestion.parsers.csv_parser import parse_csv
from app.ingestion.parsers.docx_parser import parse_docx
from app.ingestion.parsers.pdf_parser import parse_pdf
from app.ingestion.dedupe import is_duplicate, register_document, get_registered_document
from app.ingestion.table_format import convert_table_chunks



_PARSERS = {
    SourceType.CSV: parse_csv,
    SourceType.DOCX: parse_docx,
    SourceType.PDF: parse_pdf,
}

_EXTENSION_MAP = {
    ".csv": SourceType.CSV,
    ".docx": SourceType.DOCX,
    ".pdf": SourceType.PDF,
}


def detect_source_type(path: str) -> SourceType | None:
    """
    Determines the file type from its extension.
    Returns None if the extension is unsupported.
    """
    suffix = Path(path).suffix.lower()
    return _EXTENSION_MAP.get(suffix)


def ingest_document(file_path: str) -> IngestionResult:
    """
    The main entry point for ingestion. Orchestrates:
    detect -> dedupe check -> parse -> register -> IngestionResult

    Never raises an unhandled exception — always returns a structured
    IngestionResult, even on failure (per the UI/UX interface contract).
    """
    path = Path(file_path)
    document_id = path.stem

    # 1. Does the file even exist?
    if not path.exists():
        return IngestionResult(
            document_id=document_id,
            filename=path.name,
            status="failed",
            chunks=[],
            error_message=f"File not found: {file_path}",
        )

    # 2. Detect type
    source_type = detect_source_type(file_path)
    if source_type is None:
        return IngestionResult(
            document_id=document_id,
            filename=path.name,
            status="failed",
            chunks=[],
            error_message=f"Unsupported file type: {path.suffix}",
        )

    # 3. Dedup check
    try:
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception as e:
        return IngestionResult(
            document_id=document_id,
            filename=path.name,
            status="failed",
            chunks=[],
            error_message=f"Could not read file: {e}",
        )

    if is_duplicate(content_hash):
        existing = get_registered_document(content_hash)
        return IngestionResult(
            document_id=document_id,
            filename=path.name,
            status="duplicate",
            chunks=[],
            error_message=f"Already ingested as '{existing['filename']}' (document_id={existing['document_id']})",
        )

       # 4. Parse
    parser_fn = _PARSERS[source_type]
    try:
        result = parser_fn(file_path)
    except Exception as e:
        return IngestionResult(
            document_id=document_id,
            filename=path.name,
            status="failed",
            chunks=[],
            error_message=f"Parsing failed: {e}",
        )

    # 4b. Rewrite table chunks as sentences (the retrieval models read these far better than rows)
    try:
        result = result.model_copy(update={"chunks": convert_table_chunks(result.chunks)})
    except Exception as e:
        return IngestionResult(
            document_id=document_id,
            filename=path.name,
            status="failed",
            chunks=[],
            error_message=f"Table formatting failed: {e}",
        )



    # 5. Register on success
    if result.status == "success":
        register_document(content_hash, document_id=result.document_id, filename=result.filename)

    return result


if __name__ == "__main__":
    for sample in ["tests/fixtures/sample.csv", "tests/fixtures/sample.docx", "tests/fixtures/sample.pdf"]:
        print(f"\n--- Ingesting {sample} ---")
        result = ingest_document(sample)
        print(f"Status: {result.status}")
        print(f"Chunk count: {len(result.chunks)}")
        if result.error_message:
            print(f"Error: {result.error_message}")

    print("\n--- Re-ingesting sample.csv (should be duplicate) ---")
    result = ingest_document("tests/fixtures/sample.csv")
    print(f"Status: {result.status}")
    print(f"Error: {result.error_message}")

    print("\n--- Ingesting a nonexistent file ---")
    result = ingest_document("tests/fixtures/does_not_exist.pdf")
    print(f"Status: {result.status}")
    print(f"Error: {result.error_message}")