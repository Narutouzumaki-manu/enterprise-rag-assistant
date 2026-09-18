# Enterprise RAG Assistant — Ingestion Module

> **Member 1 — Document Ingestion & Preprocessing**

This section documents the development and implementation of the **Ingestion Module** for the Enterprise RAG Assistant.

The ingestion layer is responsible for accepting source documents, extracting their content, preserving important metadata, creating retrieval-ready chunks, detecting duplicates, and returning a consistent `IngestionResult` to downstream components.

---

## 📌 Current Status

**Status: ✅ Core Ingestion Module Complete**

**Development period:** September 10–18, 2026

### Supported formats

- ✅ CSV
- ✅ DOCX
- ✅ PDF

### Core capabilities

- ✅ Source-type detection
- ✅ Format-specific parsing
- ✅ Token-aware chunking
- ✅ Sentence-aware overlap
- ✅ Section-title extraction
- ✅ Structured table extraction
- ✅ Page metadata for PDFs
- ✅ Row metadata for CSV/table content
- ✅ Deterministic SHA-256 hashing
- ✅ Duplicate detection
- ✅ Unified ingestion pipeline
- ✅ Unit tests
- ✅ Integration tests

### Intentionally deferred

- 🟡 OCR for scanned PDFs
- 🟡 OCR/extraction of embedded DOCX images
- 🟡 Persistent Postgres-backed deduplication

---

# 🏗️ Ingestion Architecture

```text
                    ┌─────────────────┐
                    │ Input Document  │
                    └────────┬────────┘
                             │
                             ▼
                   ┌──────────────────┐
                   │ Source Detection  │
                   └────────┬─────────┘
                            │
           ┌────────────────┼────────────────┐
           ▼                ▼                ▼
      CSV Parser       DOCX Parser      PDF Parser
           │                │                │
           │                ├─ Sections      ├─ Sections
           │                ├─ Tables        ├─ Tables
           │                │                └─ Page metadata
           ▼                ▼                ▼
       Row chunks      Text/Table chunks  Page chunks
           │                │                │
           │                └───────┬────────┘
           │                        ▼
           │                 ┌──────────────┐
           │                 │   Chunker    │
           │                 │ token-aware  │
           │                 │ + overlap    │
           │                 └──────┬───────┘
           │                        │
           └────────────────────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │ SHA-256 Hash │
                     └──────┬───────┘
                            │
                            ▼
                     ┌──────────────┐
                     │ Deduplication│
                     └──────┬───────┘
                            │
                            ▼
                   ┌──────────────────┐
                   │ IngestionResult  │
                   │    + Chunk[]     │
                   └────────┬─────────┘
                            │
                            ▼
                     Member 2 Retrieval
```

---

# 📂 Module Structure

```text
app/
├── ingestion/
│   ├── parsers/
│   │   ├── csv_parser.py
│   │   ├── docx_parser.py
│   │   └── pdf_parser.py
│   ├── chunker.py
│   ├── dedupe.py
│   └── pipeline.py
│
├── schemas/
│   └── document.py
│
├── core/
│
tests/
├── unit/
│   └── ingestion/
│       ├── test_csv_parser.py
│       ├── test_docx_parser.py
│       ├── test_pdf_parser.py
│       ├── test_chunker.py
│       ├── test_dedupe.py
│       └── test_pipeline.py
│
└── integration/
    └── test_ingestion_integration.py
```

---

# 🧱 Shared Data Contract

The ingestion module is built around the shared schema defined in:

```text
app/schemas/document.py
```

The schema contains:

### `SourceType`

Identifies the source format:

- `PDF`
- `DOCX`
- `CSV`

### `ChunkMetadata`

Contains metadata such as:

- `document_id`
- `source_type`
- `page_number`
- `section_title`
- `content_hash`
- `row_range`
- `ingested_at`

### `Chunk`

Represents a retrieval-ready piece of source content:

- `chunk_id`
- `document_id`
- `text`
- `token_count`
- `metadata`

### `IngestionResult`

Provides a consistent result contract for the ingestion pipeline.

---

# 📄 Format Support

## CSV

CSV files are treated as **structured records** rather than flowing prose.

The current design intentionally uses:

```text
1 CSV row → 1 Chunk
```

Each chunk contains:

- Row data formatted as readable text
- Source type
- Row range
- Content hash
- Ingestion timestamp
- Deterministic chunk ID
- Real tokenizer-based token count

### Why CSV is different

Applying prose-oriented chunking across unrelated CSV rows could combine independent records and reduce retrieval quality.

A future refinement may support chunking of exceptionally long text cells, such as a `notes` column.

---

## DOCX

DOCX ingestion supports:

- Paragraph extraction
- Heading-based section detection
- Structured table extraction
- Token-aware chunking
- Sentence-level overlap

### Section extraction

Paragraphs are grouped according to DOCX heading styles such as:

```text
Heading 1
Heading 2
...
```

Each section is then independently processed by the chunker.

### Table extraction

Tables are extracted separately from prose.

Example representation:

```text
Category | Amount
Revenue  | 100000
Costs    | 75000
Profit   | 25000
```

Tables receive:

```text
section_title = "Table N"
```

and appropriate `row_range` metadata.

This prevents table content from being silently flattened into normal prose.

---

## PDF

PDF ingestion supports:

- Page-by-page extraction
- Human-readable page numbers
- Section detection
- Structured table extraction
- Token-aware chunking
- Table/prose duplication prevention

### Page preservation

PyMuPDF internally uses zero-based page indexes.

The ingestion layer converts these to human-readable page numbers:

```text
page_index + 1
```

Therefore:

```text
Internal page 0 → page_number = 1
Internal page 1 → page_number = 2
```

### Page-aware chunking

PDFs are chunked **per page**, rather than across the entire document.

This preserves accurate:

```text
page_number
```

metadata even when a single page produces multiple chunks.

### Section detection

PDF headings are detected using font-size information.

The current heuristic considers lines that are:

- Approximately 1.15× or more than the page's average font size
- Under 100 characters

as heading candidates.

### Table extraction

PyMuPDF's table detection functionality is used to identify ruled table grids.

A bounding-box exclusion mechanism prevents table-cell text from being extracted a second time as normal prose.

This avoids duplicated retrieval content.

---

# ✂️ Token-Aware Chunking

The chunker lives in:

```text
app/ingestion/chunker.py
```

The chunker was intentionally implemented as a separate module rather than embedding complex splitting logic inside each parser.

### Features

- Token-aware chunk limits
- Configurable `max_tokens`
- Configurable overlap
- Sentence-aware splitting
- Sentence-level overlap
- Avoids intentionally splitting in the middle of sentences

Default configuration established during development:

```text
max_tokens = 400
overlap_tokens ≈ 50
```

The implementation uses `tiktoken` with:

```text
cl100k_base
```

for token counting.

### Example flow

```text
Long document
     ↓
Sentence extraction
     ↓
Token-aware packing
     ↓
Chunk 1
     ↓
Overlap
     ↓
Chunk 2
     ↓
Overlap
     ↓
Chunk 3
```

The overlap exists to preserve context between adjacent chunks.

---

# 🔐 Hashing & Deduplication

Deduplication is implemented in:

```text
app/ingestion/dedupe.py
```

The current implementation uses SHA-256 content hashes.

Functions include:

```text
is_duplicate(content_hash, registry)
register_document(content_hash, document_id, registry)
```

A registry reset/clear mechanism is also provided for test isolation.

## Current implementation

The registry is intentionally **in-memory**.

This is temporary scaffolding.

## Planned implementation

The in-memory registry will eventually be replaced by the shared Postgres-backed document registry.

This allows the ingestion layer to integrate with the persistent document registry once the database component is available.

---

# 🔄 Unified Ingestion Pipeline

The unified entry point is:

```text
app/ingestion/pipeline.py
```

with:

```text
ingest_document()
```

The pipeline provides a single entry point regardless of source format.

Conceptually:

```text
Input file
    ↓
Detect extension
    ↓
Select parser
    ↓
Extract content
    ↓
Chunk where appropriate
    ↓
Generate hashes
    ↓
Check duplicates
    ↓
Return IngestionResult
```

The pipeline also handles:

- Missing files
- Unsupported extensions
- Invalid input
- Duplicate documents

Failures are returned through `IngestionResult` rather than producing unhandled exceptions.

---

# 🧪 Testing

The ingestion module was developed with unit and integration tests throughout the implementation.

## Final test breakdown

| Component | Tests |
|---|---:|
| CSV parser | 7 |
| DOCX parser | 12 |
| PDF parser | 12 |
| Chunker | 7 |
| Deduplication | 6 |
| Pipeline | 11 |
| Integration | 3 |
| **Total** | **58** |

The complete test suite was run after the final PRD/TRD gap review and reported green.

## Integration coverage

The integration suite verifies:

1. Full multi-format ingestion.
2. Duplicate detection during re-ingestion.
3. Isolation of invalid files from valid files in the same batch.

---

# 🐛 Engineering Lessons & Debugging History

The ingestion module was developed incrementally, and several real implementation issues were encountered and resolved.

### PowerShell execution policy

The initial environment required:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

before the virtual environment could be activated normally.

### Python module imports

Running parser files directly caused:

```text
ModuleNotFoundError
```

The project was correctly executed as a package module:

```bash
python -m app.ingestion.parsers.csv_parser
```

A project-level `pytest.ini` with:

```text
pythonpath = .
```

was also added to resolve pytest import behavior.

### CSV formatting

An initial sample CSV contained tabs rather than commas.

The fixture was corrected before parser validation continued.

### Early return indentation bug

The CSV parser initially returned from inside the row-processing loop.

Result:

```text
Only first row processed
```

The return statement was moved outside the loop.

This became an important reminder that seemingly small indentation errors can alter the entire control flow of a parser.

### Invalid DOCX fixture

An initial DOCX test file was invalid and only 168 bytes.

Rather than debugging the parser against a malformed fixture, a valid DOCX was generated programmatically using `python-docx`.

### PDF binary structure

Opening a PDF in a text editor initially produced apparently unreadable object/stream syntax.

This was confirmed to be normal PDF internal structure rather than evidence of corruption.

### PyMuPDF deprecation warning

The older:

```python
import fitz
```

usage was replaced with:

```python
import pymupdf
```

and corresponding API calls were updated.

### Brittle test versus invariant-based test

When DOCX chunking changed from one chunk per paragraph to real token-aware chunking, an old test expected exactly three chunks.

That test was tied to an implementation detail rather than a system requirement.

It was replaced with an invariant-based test checking the actual requirement:

```text
chunk token count stays within the configured limit
```

This distinction became an important engineering lesson during development.

---

# 🎯 Important Design Decisions

## 1. Start simple, then add sophistication

The initial parsers deliberately used a walking-skeleton approach.

The first goal was:

```text
Input → parser → valid Chunk
```

Once that baseline was working, more advanced functionality was added independently:

```text
sections
tables
token-aware chunking
overlap
deduplication
pipeline orchestration
```

This kept the implementation testable while allowing complexity to be introduced incrementally.

---

## 2. CSV rows remain discrete chunks

CSV is treated differently from prose documents.

```text
1 row → 1 chunk
```

This preserves record boundaries.

---

## 3. PDF chunking is page-aware

PDF content is chunked independently per page so that every resulting chunk can retain accurate page metadata.

---

## 4. Tables are extracted separately

Tables should not simply disappear into prose extraction.

Both DOCX and PDF table content therefore receive dedicated extraction paths.

---

## 5. Deterministic identifiers

Content hashing is used to make chunk/document identity deterministic.

This supports:

- Repeatable processing
- Duplicate detection
- Idempotency testing

---

## 6. Separate chunking from parsing

Parsers are responsible for understanding the source format.

The chunker is responsible for token-aware segmentation.

This separation allows parsing and chunking strategies to evolve independently.

---

# 🔎 Final PRD/TRD Gap Review

Before declaring the module complete, the implementation was audited against the documented PRD/TRD requirements.

Two previously undocumented-as-deferred gaps were discovered:

### `section_title`

The field existed in the frozen schema but was not populated.

**Resolution:** implemented section detection for DOCX and PDF.

### Structured table preservation

The PRD required detected tables to be preserved rather than flattened into prose.

**Resolution:** implemented dedicated table extraction for DOCX and PDF.

Both gaps were fixed before completion.

---

# ⚠️ Deferred Work

## OCR

OCR remains intentionally deferred.

Planned scope:

```text
Scanned PDF
    ↓
OCR
    ↓
Extracted text
    ↓
Normal ingestion flow
```

The same capability is expected to eventually support embedded images inside DOCX documents.

The DOCX embedded-image limitation is explicitly tracked in PRD Section 8.

---

## Persistent Deduplication

Current:

```text
In-memory registry
```

Future:

```text
Postgres documents table
```

The temporary implementation exists so the ingestion pipeline can be developed and tested independently of the database layer.

---

## Advanced PDF Layout Analysis

PyMuPDF surfaced an informational suggestion regarding the optional:

```text
pymupdf_layout
```

package.

This is considered a potential future enhancement for more sophisticated layout analysis rather than a current requirement.

---

# 📅 Development History

## September 10 — Session 1

### Environment & Foundation

- Set up VS Code, Python, and Git.
- Created the project structure.
- Created and activated the virtual environment.
- Installed core dependencies.
- Built the shared document schema.
- Created the initial CSV parser.
- Resolved CSV fixture formatting.
- Resolved Python package import behavior.
- Verified the first CSV chunks.

**Milestone:** basic ingestion foundation established.

---

## September 13 — Session 2

### Schema Hardening & DOCX

- Closed missing schema fields:
  - `row_range`
  - `ingested_at`
- Added real `tiktoken` tokenization.
- Added deterministic SHA-256 chunk IDs.
- Changed parser output to `IngestionResult`.
- Fixed the CSV early-return indentation bug.
- Added seven CSV tests.
- Built the DOCX parser.
- Created a valid DOCX test fixture.
- Added eight DOCX tests.

**Milestone:** CSV and DOCX ingestion working against the shared contract.

---

## September 14 — Session 3

### PDF & Initial Chunker

- Recovered project state after accidentally closing the terminal.
- Built the PDF parser.
- Created a real PDF test fixture.
- Added page-number metadata.
- Updated PyMuPDF imports.
- Added eight PDF tests.
- Completed the initial three-format parser baseline.
- Started the token-aware chunker.

**Milestone:** CSV, DOCX, and PDF parsers complete.

---

## September 16 — Session 4

### Real Chunking

- Verified token-aware chunking.
- Confirmed sentence-level overlap.
- Added seven chunker tests.
- Integrated chunking into DOCX.
- Integrated chunking into PDF.
- Preserved PDF page metadata during chunking.
- Confirmed CSV should remain row-based.
- Identified and documented the DOCX embedded-image gap.

**Milestone:** real chunking is now part of DOCX/PDF ingestion.

---

## September 17 — Session 5

### Deduplication & Pipeline

- Built SHA-256-based deduplication.
- Added six deduplication tests.
- Built the unified ingestion pipeline.
- Added source detection.
- Added graceful failure handling.
- Added duplicate detection.
- Added eleven pipeline tests.
- Ran integration tests across CSV, DOCX, and PDF.
- Confirmed duplicate re-ingestion behavior.
- Confirmed one bad file does not break a valid batch.

**Milestone:** core ingestion flow end-to-end verified.

**Test baseline:** 50 tests.

---

## September 18 — Session 5.5

### Final Gap Review & Completion

A final audit against the PRD/TRD identified two genuine gaps:

1. Missing `section_title` population.
2. Missing structured table preservation.

Both were implemented.

### DOCX

- Added heading-based section detection.
- Added separate table extraction.
- Added row metadata.
- Added four additional tests.

### PDF

- Added font-size-based section detection.
- Added PyMuPDF table extraction.
- Added bounding-box exclusion.
- Added four additional tests.

The complete test suite was run after the changes and reported green.

**Final test breakdown:** 58 tests.

**Milestone: Member 1 — Ingestion Core Complete.**

---

# 🚀 Handoff to Member 2

The ingestion module's downstream contract is now:

```text
Validated Chunk objects
        ↓
IngestionResult
        ↓
Member 2 — Retrieval
```

Member 1's core responsibility ends at producing validated, metadata-rich `Chunk` objects through the ingestion pipeline.

The retrieval module can therefore consume a consistent output regardless of whether the original source was:

```text
CSV
DOCX
PDF
```

---

# 🏁 Completion Summary

As of **September 18, 2026**, Member 1's core ingestion workstream is complete.

The module evolved from a simple parser baseline into a tested ingestion pipeline supporting:

```text
CSV / DOCX / PDF
        ↓
Source Detection
        ↓
Format-Specific Parsing
        ↓
Section + Table Extraction
        ↓
Token-Aware Chunking
        ↓
SHA-256 Hashing
        ↓
Duplicate Detection
        ↓
IngestionResult
        ↓
Member 2 Retrieval
```

The implementation is backed by **58 unit and integration tests** according to the final test breakdown.

The remaining OCR functionality is intentionally deferred and documented as an open item rather than treated as an incomplete core ingestion requirement.

---

## 📌 Member 1 Status

**✅ COMPLETE — Ready for Retrieval Integration**

**Last updated:** September 18, 2026