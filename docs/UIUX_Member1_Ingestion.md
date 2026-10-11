# UI/UX Notes
## Module: Document Ingestion & Data Pipeline
### Owner: Member 1 — Document Ingestion & Data Pipeline Engineer
### Project: Enterprise RAG Assistant
### Date: September 2026

---

## 1. Scope Note

The Ingestion module has **no direct end-user interface** — it runs invisibly in the background when a document is uploaded. The actual upload UI (drag-and-drop, progress bar, upload status) belongs to **Member 5 (Frontend)**.

This document instead covers:
1. The **developer-facing interface** this module exposes to other modules
2. The **status/feedback signals** this module must provide so Member 5 can build a good user experience around it
3. Recommendations for what the frontend should show, from an ingestion-awareness standpoint

---

## 2. Developer-Facing Interface (the "UX" for other engineers)

Other team members interact with this module through one function call:

```python
result: IngestionResult = ingest_document(file_path: str)
```

Design principles for this interface:
- **Predictable**: always returns an `IngestionResult`, never raises an unhandled exception
- **Informative on failure**: `error_message` must be human-readable, not a raw stack trace
- **Fast to fail**: corrupted/invalid files should fail within seconds, not hang
- **Idempotent**: calling it twice on the same file returns the same result without reprocessing

---

## 3. Status Signals Exposed to the Frontend (via Member 4's API)

To let Member 5 build a good upload experience, this module surfaces the following states, which Member 4 should relay via the `/ingest` endpoint and SSE events:

| Status | Meaning | Suggested frontend treatment |
|---|---|---|
| `queued` | File received, not yet processed | Show spinner: "Processing..." |
| `parsing` | Currently extracting text/tables | Show: "Reading document..." |
| `ocr_fallback` | Scanned PDF detected, running OCR | Show: "Scanning document (this may take longer)..." |
| `success` | Fully ingested, chunks created | Show: "✅ Document ready" |
| `partial` | Some pages/sections failed, rest succeeded | Show: "⚠️ Document partially processed — some pages couldn't be read" |
| `failed` | Could not process at all | Show: "❌ Upload failed: [error_message]" |
| `duplicate` | Same file already ingested (hash match) | Show: "This document was already uploaded" |

---

## 4. Recommended UX Behaviors (for Member 5 to consider)

- Show per-file progress if multiple files are uploaded at once — don't block the whole batch on one slow/failed file
- Surface OCR fallback clearly — scanned documents take noticeably longer, users should know why
- On `partial` success, let the user see *which* pages/sections failed, not just a generic warning
- Never let a raw Python exception or stack trace reach the user — always route through `error_message`

---

## 5. Metadata That Could Enhance the End-User Experience

These fields exist in `ChunkMetadata` and could be surfaced in the UI (Member 5's call):
- `page_number` — lets the frontend show "found on page 12" in citations
- `section_title` — lets the frontend show "found in 'Revenue' section"
- `source_type` — lets the frontend show a file-type icon (PDF/DOCX/CSV)

---

## 6. Out of Scope for This Module

- Upload widget, drag-and-drop, progress bars — Member 5
- Chat interface, citation rendering — Member 5
- Authentication/session handling around uploads — Member 4
