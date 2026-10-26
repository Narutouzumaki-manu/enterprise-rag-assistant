import asyncio
import logging

logger = logging.getLogger(__name__)


async def drain_background_tasks(tasks: set, grace_seconds: float) -> None:
    """Waits for in-flight work, then cancels what is left. Never raises.

    Cancelled ingestion leaves its document in progress; the startup sweep fails it at the next
    start. A cancelled chat pump loses its answer (the agent thread cannot be stopped and dies
    with the process)."""
    pending = set(tasks)  # a copy: finished tasks remove themselves from the original
    if not pending:
        return
    logger.info(
        "Shutdown: waiting up to %.0f s for %d background task(s)", grace_seconds, len(pending)
    )
    try:
        _, pending = await asyncio.wait(pending, timeout=grace_seconds)
        if not pending:
            logger.info("Shutdown: all background tasks finished")
            return
        logger.warning("Shutdown: cancelling %d task(s) that did not finish", len(pending))
        for task in pending:
            task.cancel()
        await asyncio.wait(pending, timeout=5)  # let the cancellations land
    except Exception as exc:
        logger.error("Shutdown drain problem (%s)", type(exc).__name__)