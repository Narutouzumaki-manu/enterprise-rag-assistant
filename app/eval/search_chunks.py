import argparse
import sys
from typing import Any

# Ensure stdout encodes Unicode safely on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def load_chunks(pdf_path: str = "data/eval/documents/tcs_annual_report.pdf") -> list[Any]:
    """Load chunks from the TCS Annual Report PDF using the standard ingestion pipeline."""
    from app.ingestion.pipeline import ingest_document

    result = ingest_document(pdf_path)
    if not result.chunks:
        raise RuntimeError(
            f"Failed to ingest chunks from '{pdf_path}': {result.error_message or 'No chunks produced'}"
        )
    return result.chunks


def extract_snippet(text: str, term: str, max_length: int = 120) -> str:
    """Extract a single-line snippet of up to max_length characters around the matching term."""
    clean_text = " ".join(text.split())
    clean_term = " ".join(term.split()).lower()
    lower_text = clean_text.lower()

    pos = lower_text.find(clean_term)
    if pos == -1:
        snippet = clean_text[:max_length]
    else:
        # Center the term within max_length
        half = max_length // 2
        start = max(0, pos - half)
        end = min(len(clean_text), start + max_length)
        # Adjust if near end
        if end - start < max_length:
            start = max(0, end - max_length)
        snippet = clean_text[start:end]

    return snippet.strip()


def search_term_in_chunks(
    term: str,
    chunks: list[Any],
    max_preview: int = 5,
) -> tuple[int, list[dict[str, Any]]]:
    """Search for term in chunks case-insensitively and return (total_count, previews)."""
    term_lower = term.lower().strip()
    matches = []

    for c in chunks:
        text = getattr(c, "text", str(c))
        if term_lower in text.lower():
            cid = getattr(c, "chunk_id", "unknown")
            page = getattr(getattr(c, "metadata", None), "page_number", None)
            snippet = extract_snippet(text, term, max_length=120)
            matches.append({
                "chunk_id": cid,
                "page": page,
                "snippet": snippet,
            })

    return len(matches), matches[:max_preview]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Search chunks for terms to inspect occurrences or prove absence for unanswerable questions."
    )
    parser.add_argument(
        "terms",
        nargs="+",
        help="One or more terms to search in chunks (e.g. 'cash' 'q3' 'attrition').",
    )
    parser.add_argument(
        "--pdf",
        default="data/eval/documents/tcs_annual_report.pdf",
        help="Path to the PDF document to ingest (default: data/eval/documents/tcs_annual_report.pdf)",
    )
    args = parser.parse_args()

    try:
        chunks = load_chunks(args.pdf)
    except Exception as exc:
        print(f"ERROR: Could not load chunks: {exc}", file=sys.stderr)
        return 1

    print(f"Loaded {len(chunks)} chunks from {args.pdf}\n")

    for term in args.terms:
        count, previews = search_term_in_chunks(term, chunks, max_preview=5)
        print("=" * 80)
        print(f"SEARCH TERM: \"{term}\"")
        print(f"Matches found: {count} chunk(s)")
        print("-" * 80)

        if count == 0:
            print(f"  [ABSENT] 0 chunks contain '{term}'. This topic is absent from the report.")
        else:
            for idx, p in enumerate(previews, 1):
                page_str = f"page {p['page']}" if p['page'] is not None else "page N/A"
                print(f"  {idx}. [id: {p['chunk_id'][:12]}... | {page_str}]")
                print(f"     \"{p['snippet']}\"")
            if count > len(previews):
                print(f"  ... and {count - len(previews)} more chunk(s).")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())

