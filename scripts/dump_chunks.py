import sys
from collections import Counter
from pathlib import Path

from app.ingestion.pipeline import ingest_document

PDF_PATH = "data/eval/documents/tcs_annual_report.pdf"
OUT_PATH = Path("data/eval/chunks_dump.txt")

result = ingest_document(PDF_PATH)
print("status:", result.status)
print("document_id:", result.document_id)
print("error:", result.error_message)
print("chunks:", len(result.chunks))

if not result.chunks:
    sys.exit("No chunks came out, so there is nothing to look at.")

tokens = [c.token_count for c in result.chunks]
print(f"tokens per chunk: min {min(tokens)}, average {sum(tokens) / len(tokens):.0f}, max {max(tokens)}")

pages = Counter(c.metadata.page_number for c in result.chunks)
print("pages that produced chunks:", len(pages), "| most chunks on one page:", max(pages.values()))
print("chunks with a section title:", sum(1 for c in result.chunks if c.metadata.section_title))
print("very short chunks (under 30 tokens):", sum(1 for t in tokens if t < 30))

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
with OUT_PATH.open("w", encoding="utf-8") as f:
    for i, c in enumerate(result.chunks):
        f.write(
            f"=== #{i} | id {c.chunk_id[:10]} | page {c.metadata.page_number} "
            f"| section: {c.metadata.section_title} | {c.token_count} tokens ===\n"
        )
        f.write(c.text.strip() + "\n\n")
print("written to", OUT_PATH)
