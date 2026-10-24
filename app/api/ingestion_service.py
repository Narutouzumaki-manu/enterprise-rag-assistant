import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from starlette.concurrency import run_in_threadpool

from app.db import repository
from app.schemas.document import IngestionResult

logger = logging.getLogger(__name__)

FAILED_GENERIC = "Processing failed. Please try uploading the file again."
INDEXING_FAILED = "The document could not be indexed. Please try uploading the file again."
NO_TEXT = "No text could be extracted from this file."


class IngestionRunner:
    """Takes a stored file from 'queued' to a final status. process() never raises."""

    def __init__(
        self,
        session_factory,
        retriever,
        ingest: Callable[[str], IngestionResult],
        max_concurrent: int = 1,
    ):
        self._session_factory = session_factory
        self._retriever = retriever
        self._ingest = ingest
        self._slots = asyncio.Semaphore(max_concurrent)

    async def process(self, document_id: str, path: Path) -> None:
        async with self._slots:  # documents wait here, still 'queued'
            try:
                await self._process(document_id, path)
            except Exception:
                logger.exception("Processing failed for document %s", document_id)
                await self._mark(document_id, "failed", FAILED_GENERIC)

    async def _mark(self, document_id: str, status: str, message: str | None = None) -> None:
        try:
            async with self._session_factory() as db:
                await repository.set_document_status(db, document_id, status, message)
        except Exception:
            logger.exception("Could not set status %s for document %s", status, document_id)

    async def _forget_in_index(self, document_id: str) -> None:
        try:
            await run_in_threadpool(self._retriever.delete_document, document_id)
        except Exception:
            logger.exception("Could not remove document %s from the index", document_id)

    async def _process(self, document_id: str, path: Path) -> None:
        await self._mark(document_id, "parsing")
        result = await run_in_threadpool(self._ingest, str(path))

        if result.document_id != document_id:  # the ids must match: a safety net
            logger.error("Ingestion returned id %s for document %s", result.document_id, document_id)
            await self._mark(document_id, "failed", FAILED_GENERIC)
            return
        if result.status not in ("success", "partial"):
            await self._mark(document_id, "failed", result.error_message or FAILED_GENERIC)
            return
        if not result.chunks:
            await self._mark(document_id, "failed", NO_TEXT)
            return

        await self._mark(document_id, "indexing")
        try:
            await run_in_threadpool(self._retriever.index_chunks, result.chunks)
        except Exception:
            logger.exception("Indexing failed for document %s", document_id)
            await self._forget_in_index(document_id)  # nothing half-indexed stays behind
            await self._mark(document_id, "failed", INDEXING_FAILED)
            return

        try:
            async with self._session_factory() as db:
                await repository.complete_document(
                    db, document_id, result.chunks, result.status, result.error_message
                )
        except Exception:
            logger.exception("Could not save the chunks of document %s", document_id)
            await self._forget_in_index(document_id)
            await self._mark(document_id, "failed", FAILED_GENERIC)