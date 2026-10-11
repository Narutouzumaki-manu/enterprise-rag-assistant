# Product Requirements Document (PRD)
## Module: Document Ingestion & Data Pipeline
### Owner: Member 1 — Document Ingestion & Data Pipeline Engineer
### Project: Enterprise RAG Assistant
### Date: September 2026

---

## 1. Purpose

The Ingestion module is the entry point of the Enterprise RAG Assistant. Its job is to take raw, messy enterprise documents (PDF, DOCX, CSV) and convert them into clean, structured, traceable `Chunk` objects that downstream modules (Retrieval, Agents) can search and reason over.

If this module produces low-quality or poorly-structured chunks, the entire system's answer quality suffers — regardless of how sophisticated retrieval or agent logic is downstream.

---

## 2. Problem Statement

Enterprise documents are unstructured, inconsistent, and often messy:
- Mixed formats (PDF, Word, CSV/Excel)
- Tables that lose meaning if flattened into plain text
- Scanned PDFs with no extractable text
- Duplicate or re-uploaded files
- Broken encodings, empty files, corrupted uploads

Without a robust ingestion layer, the RAG system either fails outright on real-world documents or silently produces low-quality, ungrounded answers.

---

## 3. Goals

| Goal | Description |
|---|---|
| G1 | Reliably parse PDF, DOCX, and CSV files into normalized text |
| G2 | Preserve document structure (pages, sections, tables) as metadata |
| G3 | Split text into token-aware chunks with configurable overlap |
| G4 | Detect and skip duplicate documents via content hashing |
| G5 | Fall back to OCR for scanned/image-based PDFs |
| G6 | Expose a single, stable interface (`Chunk`, `ChunkMetadata`, `IngestionResult`) for downstream teams |
| G7 | Fail gracefully on corrupted/malformed/empty files without crashing the pipeline |

---

## 4. Non-Goals

- This module does **not** perform embedding, indexing, or retrieval (Member 2's responsibility)
- This module does **not** decide chunk relevance or ranking
- This module does **not** build any user-facing UI
- Real-time collaborative editing of documents is out of scope

---

## 5. Users of This Module

| User | How they use it |
|---|---|
| Member 2 (Retrieval) | Consumes `Chunk` objects to build dense/sparse indexes |
| Member 4 (Backend/API) | Triggers ingestion via `/ingest` endpoint, stores `IngestionResult` status |
| Member 5 (Eval/QA) | Uses ingestion output to build the golden Q&A benchmark dataset |
| End users (indirect) | Upload documents via frontend; ingestion happens invisibly in the background |

---

## 6. Functional Requirements

1. Accept a file path (PDF, DOCX, or CSV) as input
2. Detect file type automatically
3. Route to the correct parser (`pdf_parser.py`, `docx_parser.py`, `csv_parser.py`)
4. Extract raw text while preserving page numbers / section titles / row ranges where applicable
5. Detect and extract tables separately from prose text (never flatten into meaningless strings)
6. Compute a SHA-256 content hash per file for deduplication
7. Chunk extracted text using a token-aware recursive splitter (target ~300–500 tokens, ~50 token overlap)
8. Attach `ChunkMetadata` (document_id, source_type, page_number, section_title, content_hash) to every chunk
9. Fall back to OCR (Tesseract) when a PDF page yields near-zero extractable text
10. Return a structured `IngestionResult` (status: success/failed/partial, list of chunks, error message if any)

---

## 7. Success Metrics

| Metric | Target |
|---|---|
| Parsing success rate across test corpus | ≥ 95% |
| Duplicate re-ingestion prevented | 100% (via hash check) |
| Table content preserved (not flattened) | 100% of detected tables |
| Scanned PDF fallback triggers correctly | 100% of test scanned samples |
| Pipeline crash rate on malformed input | 0% (graceful failure only) |

---

## 8. Risks & Open Questions

- OCR accuracy on low-quality scans may be poor — confidence score must be surfaced in metadata
- Very large files may need streaming rather than full in-memory loads (future scaling concern)
- Chunk size (300–500 tokens) is a starting assumption — needs benchmarking once Member 2's retrieval eval is live
- **Embedded images in DOCX files are currently silently ignored.** `python-docx`'s `doc.paragraphs` only exposes text; images (screenshots, charts, diagrams) embedded in a DOCX are not detected, extracted, or represented in any chunk. A paragraph that is *only* an image produces no chunk at all. This is a known gap, not a crash — no error is raised. Future improvement: detect embedded images, run them through the planned OCR module (`ocr.py`), and create image-derived chunks tagged with `extraction_method="ocr"`, reusing the same OCR fallback infrastructure planned for scanned PDFs. Not addressed in the current build phase (text-first ingestion).

---

## 9. Dependencies on Other Members

- **Member 2**: co-owns the `Chunk`/`ChunkMetadata` schema; must confirm it before parser development finalizes
- **Member 4**: will wrap this pipeline in a Celery task callable from the `/ingest` API endpoint
