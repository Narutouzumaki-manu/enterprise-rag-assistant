import logging

from starlette.concurrency import run_in_threadpool

from app.db import repository

logger = logging.getLogger(__name__)

INTERRUPTED = "Processing was interrupted by a server restart. Please upload the file again."


async def sweep_interrupted_documents(session_factory, retriever=None) -> int:
    """Fails documents a restart left in progress. Never raises: a sweep problem must not
    stop the server from starting. Single API process only (see the TRD)."""
    try:
        async with session_factory() as db:
            interrupted = await repository.fail_interrupted_documents(db, INTERRUPTED)
    except Exception as exc:
        logger.error("Startup sweep skipped (%s)", type(exc).__name__)
        return 0

    if interrupted:
        logger.warning(
            "Startup sweep failed %d interrupted document(s): %s",
            len(interrupted),
            [document_id for document_id, _ in interrupted],
        )
    if retriever is not None:
        for document_id, previous_status in interrupted:
            if previous_status != "indexing":  # earlier states never touched the index
                continue
            try:
                await run_in_threadpool(retriever.delete_document, document_id)
            except Exception as exc:
                logger.error(
                    "Could not clean the index for document %s (%s)", document_id, type(exc).__name__
                )
    return len(interrupted)