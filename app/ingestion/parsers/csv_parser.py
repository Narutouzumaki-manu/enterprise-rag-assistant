import pandas as pd
import tiktoken
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from app.schemas.document import Chunk, ChunkMetadata, SourceType, IngestionResult


def parse_csv(path: str) -> IngestionResult:
    """
    Reads a CSV file and returns an IngestionResult containing
    a list of Chunk objects, one chunk per row (simple starting strategy).
    """
    df = pd.read_csv(path)
    document_id = Path(path).stem
    content_hash = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    now = datetime.now(timezone.utc)

    chunks = []
    encoding = tiktoken.get_encoding("cl100k_base")

    for i, row in df.iterrows():
        row_text = ", ".join(f"{col}: {val}" for col, val in row.items())
        chunk = Chunk(
            chunk_id=hashlib.sha256(f"{document_id}_{i}".encode()).hexdigest(),
            document_id=document_id,
            text=row_text,
            token_count=len(encoding.encode(row_text)),
            metadata=ChunkMetadata(
                document_id=document_id,
                source_type=SourceType.CSV,
                row_range=(i, i),
                content_hash=content_hash,
                ingested_at=now,
            ),
        )
        chunks.append(chunk)

    return IngestionResult(
        document_id=document_id,
        filename=Path(path).name,
        status="success",
        chunks=chunks,
    )


if __name__ == "__main__":
    sample_path = Path("tests/fixtures/sample.csv")
    result = parse_csv(str(sample_path))
    print(f"Status: {result.status}")
    print(f"Filename: {result.filename}")
    print(f"Chunk count: {len(result.chunks)}")
    for chunk in result.chunks:
        print(chunk)