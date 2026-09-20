# Member 1 — Ingestion: Completion Checklist

**Status:** ✅ DONE (core scope) | 🟡 OCR knowingly deferred, logged as open item in PRD
**Last corrected:** September 2026 — supersedes an earlier stale checklist generated before `dedupe.py`, `pipeline.py`, integration tests, and section/table extraction were completed.

---

## 1. Environment & Project Foundation
- [x] Python environment created and working
- [x] Virtual environment configured
- [x] Required Python dependencies installed
- [x] Project package structure created
- [x] `__init__.py` files added
- [x] Pytest configured and runnable

## 2. Shared Ingestion Schema
- [x] `SourceType` supports PDF, DOCX, CSV
- [x] `Chunk` model implemented
- [x] `ChunkMetadata` model implemented
- [x] `document_id` field implemented
- [x] `source_type` field implemented
- [x] `page_number` field implemented
- [x] `section_title` field implemented
- [x] `content_hash` field implemented
- [x] `row_range` field implemented
- [x] `ingested_at` field implemented
- [x] `token_count` field implemented
- [x] `IngestionResult` implemented
- [x] Schema verified against the project contract

## 3. CSV Ingestion
- [x] CSV files can be read
- [x] CSV rows converted into structured chunks
- [x] One CSV record remains one logical chunk
- [x] SHA-256 hashing implemented
- [x] Deterministic chunk IDs implemented
- [x] tiktoken token counting implemented
- [x] `row_range` metadata populated
- [x] `ingested_at` metadata populated
- [x] `IngestionResult` returned
- [x] CSV unit tests implemented
- [x] CSV unit tests passing (7/7)

## 4. DOCX Ingestion
- [x] DOCX files can be opened
- [x] Non-empty paragraph text extracted
- [x] Paragraph text combined appropriately
- [x] Token-aware chunker integrated
- [x] Token count generated using tiktoken
- [x] Deterministic hashing implemented
- [x] Deterministic chunk IDs implemented
- [x] `IngestionResult` returned
- [x] Metadata preserved
- [x] Empty paragraphs handled
- [x] Section/heading detection implemented (via heading styles) — *corrected: not in original checklist*
- [x] Table extraction implemented, structured, never flattened — *corrected: was missing from original checklist*
- [x] DOCX unit tests implemented
- [x] DOCX unit tests passing (12/12, incl. section & table tests)
- [ ] Embedded DOCX images extracted
- [ ] Embedded DOCX images processed through OCR

> **Note:** Embedded DOCX image processing remains a deliberately deferred open item, logged in the PRD. Not required for core pipeline functionality.

## 5. PDF Ingestion
- [x] PDF files can be opened
- [x] PDF text extracted
- [x] Page numbers preserved
- [x] Human-readable page numbering implemented
- [x] Page-level processing preserves source location
- [x] Token-aware chunking integrated
- [x] Deterministic hashing implemented
- [x] Deterministic chunk IDs implemented
- [x] `IngestionResult` returned
- [x] Section/heading detection implemented (via font-size heuristic) — *corrected: not in original checklist*
- [x] PDF table extraction implemented **and** validated (via PyMuPDF `find_tables()`) — *corrected: was incorrectly marked optional/unchecked; project PRD required this and it is done*
- [x] PDF unit tests implemented
- [x] PDF unit tests passing (12/12, incl. section & table tests)
- [ ] Scanned/image-only PDF OCR fallback implemented
- [ ] Scanned PDF OCR tests implemented

> **Note:** PDF table extraction was previously flagged as conditional — confirmed as required by the project's own PRD (table content must be preserved, not flattened) and is complete.

## 6. Text Chunking
- [x] Text chunking implemented
- [x] Token-aware chunk size implemented
- [x] Configurable maximum token limit implemented
- [x] Sentence-aware splitting implemented
- [x] Chunk overlap implemented
- [x] Sentence boundaries preserved
- [x] Empty input handled
- [x] Multiple chunks handled
- [x] Overlap behavior tested
- [x] Token limit tested
- [x] Sentence boundary behavior tested
- [x] Chunker integrated with DOCX
- [x] Chunker integrated with PDF
- [x] Chunker unit tests passing (7/7)

## 7. Duplicate Detection — *corrected: fully complete*
- [x] `dedupe.py` implemented
- [x] Duplicate document/content hashes detected
- [x] Duplicate ingestion behavior defined
- [x] Duplicate status/result implemented
- [x] Deterministic duplicate detection verified
- [x] Deduplication unit tests implemented
- [x] Deduplication unit tests passing (6/6)

> **Note:** Original checklist incorrectly showed this entire section as not started. `dedupe.py` was built and fully tested (in-memory SHA-256 registry).

## 8. OCR — genuinely not started (deferred for now, by request)
- [ ] `ocr.py` implemented
- [ ] Scanned PDF detection implemented
- [ ] OCR fallback triggered when normal PDF extraction is insufficient
- [ ] OCR text converted into the ingestion representation
- [ ] PDF page metadata preserved after OCR
- [ ] Token counts generated for OCR text
- [ ] Content hashes generated for OCR text
- [ ] OCR failure handling implemented
- [ ] OCR unit tests implemented
- [ ] Scanned PDF test fixture created
- [ ] OCR tests passing

## 9. Ingestion Pipeline — *corrected: fully complete (excl. OCR routing)*
- [x] `pipeline.py` implemented
- [x] Input file accepted by pipeline
- [x] File type detected
- [x] CSV routed to CSV parser
- [x] DOCX routed to DOCX parser
- [x] PDF routed to PDF parser
- [x] Chunking applied where appropriate
- [x] Hashing applied
- [x] Deduplication applied
- [x] Metadata validated/preserved
- [x] Consistent `IngestionResult` returned
- [x] Unsupported file type handled
- [x] Parser errors handled
- [x] Pipeline failure status implemented
- [ ] OCR invoked when required
- [ ] OCR errors handled

> **Note:** Original checklist incorrectly showed this entire section as not started. `pipeline.py` (`ingest_document`) was built and fully tested — 11 passing unit tests. Only the OCR-routing sub-items remain open, tied to Section 8.

## 10. End-to-End / Integration Tests — *corrected: complete (excl. OCR)*
- [x] CSV → pipeline → `IngestionResult` test passing
- [x] DOCX → pipeline → `IngestionResult` test passing
- [x] PDF → pipeline → `IngestionResult` test passing
- [x] Duplicate document → deduplication test passing
- [x] Chunk token limit verified through pipeline
- [x] Chunk overlap verified through pipeline
- [x] PDF page metadata preserved through pipeline
- [x] CSV row metadata preserved through pipeline
- [x] Deterministic hashing verified through pipeline
- [x] Invalid file handling tested
- [x] Unsupported file type handling tested
- [x] Parser failure handling tested
- [ ] Scanned PDF → OCR → pipeline test passing
- [ ] Empty document handling tested
- [ ] OCR failure handling tested

> **Note:** Original checklist incorrectly showed this entire section as not started. 3 integration tests written and passing, covering full multi-format batches, repeat-batch duplicate detection, and mixed-batch failure isolation.

## 11. Final Member 1 Validation — *corrected*
- [x] All CSV unit tests passing
- [x] All DOCX unit tests passing
- [x] All PDF unit tests passing
- [x] All chunker unit tests passing
- [x] All deduplication tests passing
- [x] All pipeline tests passing
- [x] All integration tests passing
- [x] No existing tests are broken
- [x] CSV ingestion verified end-to-end
- [x] DOCX ingestion verified end-to-end
- [x] PDF ingestion verified end-to-end
- [x] Duplicate detection verified
- [x] Metadata preservation verified
- [x] Error handling verified
- [ ] All OCR tests passing
- [ ] OCR fallback verified

> **66 total automated tests passing** (63 unit + 3 integration) as of the final gap review session. The only remaining required Member 1 functionality is OCR, which was explicitly deferred as a documented, deliberate decision — not an oversight.

## 12. Member 1 Completion Gate
- [x] `dedupe.py` complete
- [x] `pipeline.py` complete
- [x] Integration tests complete
- [x] Final validation complete (excl. OCR)
- [x] All required non-OCR Member 1 tests passing
- [x] All required non-OCR Member 1 functionality verified
- [ ] `ocr.py` complete

---

**MEMBER 1 — INGESTION STATUS:** ✅ **DONE** (core scope) — 🟡 **OCR** deferred, tracked as an open item
