# Technical Requirements Document (TRD)
## Module: Document Ingestion & Data Pipeline
### Owner: Member 1 — Document Ingestion & Data Pipeline Engineer
### Project: Enterprise RAG Assistant
### Date: September 2026

---

## 1. Scope

Technical design for the ingestion pipeline: parsers, chunker, OCR fallback, deduplication, and the pipeline orchestrator that ties them together.

---

## 2. Architecture Overview

```
Raw file (PDF/DOCX/CSV)
      │
      ▼
File type detector
      │
      ▼
Format-specific parser (PDF / DOCX / CSV)
      │
      ▼
Text + table + structure extraction
      │
      ▼
OCR fallback (PDF only, if text extraction is insufficient)
      │
      ▼
Content hash computed (SHA-256) → dedup check
      │
      ▼
Token-aware recursive chunker (with overlap)
      │
      ▼
Metadata attachment (page, section, source_type, hash)
      │
      ▼
Chunk objects → IngestionResult
```

---

## 3. Tech Stack

| Component | Tool | Reason |
|---|---|---|
| Language | Python 3.11+ | Async support, typing, ecosystem |
| PDF parsing | PyMuPDF (`fitz`), optionally `pdfplumber` for tables | Fast, table-aware |
| DOCX parsing | `python-docx` | Standard, reliable |
| CSV/tabular parsing | `pandas` | Direct, well-supported |
| OCR fallback | Tesseract + `pytesseract` | Local, open-source, no external API dependency |
| Tokenization | `tiktoken` | Accurate token counting for chunk sizing |
| Schema validation | Pydantic v2 | Type-safe, shared contract across team |
| Testing | `pytest` + fixtures | Standard, supports parametrized multi-format tests |
| Hashing | `hashlib` (SHA-256) | Deterministic deduplication key |
| Async execution (future) | Celery + Redis | Decouples slow ingestion from request/response cycle |

---

## 4. Module Breakdown

```
app/ingestion/
├── parsers/
│   ├── pdf_parser.py     — extracts text, tables, page numbers from PDF
│   ├── docx_parser.py    — extracts text, headings, tables from DOCX
│   └── csv_parser.py     — extracts rows/columns from CSV
├── chunker.py            — token-aware recursive text splitter
├── ocr.py                — Tesseract-based OCR fallback for scanned PDFs
├── dedupe.py             — SHA-256 content hashing + duplicate check
└── pipeline.py           — orchestrates: detect → parse → chunk → hash → return IngestionResult
```

---

## 5. Interface Contract (frozen, shared with Member 2)

```python
# app/schemas/document.py

class SourceType(str, Enum):
    PDF = "pdf"
    DOCX = "docx"
    CSV = "csv"

class ChunkMetadata(BaseModel):
    document_id: str
    source_type: SourceType
    page_number: int | None = None
    section_title: str | None = None
    row_range: tuple[int, int] | None = None   # for CSV/table chunks
    content_hash: str
    ingested_at: datetime

class Chunk(BaseModel):
    chunk_id: str          # deterministic hash of (document_id, position)
    document_id: str
    text: str
    token_count: int
    metadata: ChunkMetadata

class IngestionResult(BaseModel):
    document_id: str
    filename: str
    status: str            # "success" | "failed" | "partial"
    chunks: list[Chunk]
    error_message: str | None = None
```

Any change to this schema requires a team sync — not a silent edit, since Member 2, 4, and 5 all depend on it.

---

## 6. Chunking Strategy

- Split hierarchically: document → sections → paragraphs → sentences → token constraints
- Target chunk size: 300–500 tokens (to be benchmarked, not fixed)
- Overlap: ~50–60 tokens between adjacent chunks
- Never split mid-sentence if avoidable — use recursive character/sentence-boundary splitting before falling back to hard token cuts
- Tables are chunked separately from prose and never flattened into unstructured text

---

## 7. Deduplication Strategy

- Compute `SHA-256(file_bytes)` on every upload
- Maintain a document registry: `document_id`, `content_hash`, `version`, `status`
- If hash already exists → skip reprocessing, return cached `IngestionResult`
- If same filename but different hash → treat as a new version, preserve lineage (do not overwrite)

---

## 8. OCR Fallback Logic

```
Extract native text from PDF page
      │
      ▼
Text length below threshold?
      │
     YES
      │
      ▼
Render page to image
      │
      ▼
Run Tesseract OCR
      │
      ▼
Store extraction_method = "ocr", ocr_confidence in metadata
```

OCR confidence must be visible downstream so retrieval/evaluation can weigh low-confidence text appropriately.

---

## 9. Error Handling

| Failure case | Behavior |
|---|---|
| Corrupted file | Return `IngestionResult(status="failed", error_message=...)` — no crash |
| Password-protected file | Return `status="failed"`, flag reason clearly |
| Empty document | Return `status="failed"`, zero chunks |
| Partial parse failure (e.g., one bad page in a PDF) | Return `status="partial"`, include successfully parsed chunks |

---

## 10. Testing Plan

Unit tests required for:
- Normal PDF, scanned PDF, rotated PDF, multi-column PDF, PDF with tables
- DOCX with tables
- CSV with commas inside quoted fields
- Unicode content
- Empty file
- Corrupted file
- Password-protected file
- Duplicate upload (same hash) — verify skip behavior

---

## 11. Performance Considerations (future scaling)

- Stream large files rather than loading fully into memory
- Batch processing with backpressure via queue depth (once Celery is integrated)
- Idempotency keys to avoid duplicate processing under retries
