import logging
from uuid import UUID

from app.db import repository
from app.schemas.agent import AgentResponse
import asyncio
from collections.abc import AsyncIterator

from app.api.runtime import AgentRuntime
from app.schemas.agent import AgentStep

logger = logging.getLogger(__name__)


class ChatStore:
    """The database side of a chat request.

    Every method opens its own short session, so no connection is held while the agent runs
    for minutes."""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    async def session_belongs_to(self, user_id: UUID, session_id: UUID) -> bool:
        async with self._session_factory() as db:
            return await repository.get_user_session(db, user_id, session_id) is not None

    async def source_files_for(self, response: AgentResponse) -> dict[str, str]:
        """document_id -> original filename. A failed lookup gives {} (the answer still goes out)."""
        document_ids = {citation.document_id for citation in response.citations}
        try:
            async with self._session_factory() as db:
                return await repository.get_source_files(db, document_ids)
        except Exception:
            logger.exception("Could not look up source files")
            return {}

    async def save(
        self,
        session_id: UUID,
        question: str,
        response: AgentResponse,
        source_files: dict[str, str],
    ) -> bool:
        """Saves the exchange. A failure is logged (session id only) and reported as False."""
        try:
            async with self._session_factory() as db:
                await repository.save_exchange(db, session_id, question, response, source_files)
            return True
        except Exception:
            logger.exception("Could not save the exchange for session %s", session_id)
            return False

_END = object()


async def open_saved_stream(
    runtime: AgentRuntime,
    store,
    background_tasks: set,
    session_id: UUID,
    question: str,
    top_k: int,
    source_files: dict[str, str],
) -> AsyncIterator[AgentStep | AgentResponse]:
    """Starts the agent and returns its events.

    A background task owns the agent's stream. It saves the answer even if the client leaves,
    and it saves BEFORE the final answer is forwarded, so a client that has seen the end of the
    stream can already find the exchange in its history."""
    agent_events = await runtime.stream(question, top_k=top_k)  # a busy error is raised here
    outbox: asyncio.Queue = asyncio.Queue()

    async def pump() -> None:
        try:
            async for item in agent_events:
                if isinstance(item, AgentResponse):
                    source_files.update(await store.source_files_for(item))
                    await store.save(session_id, question, item, source_files)  # failure is logged
                outbox.put_nowait(item)
        except Exception as exc:  # the agent should not raise; the client side decides what to show
            outbox.put_nowait(exc)
        finally:
            outbox.put_nowait(_END)

    task = asyncio.create_task(pump())
    background_tasks.add(task)  # a task nobody refers to can be garbage-collected mid-run
    task.add_done_callback(background_tasks.discard)
    return _read(outbox)


async def _read(outbox: asyncio.Queue) -> AsyncIterator[AgentStep | AgentResponse]:
    while True:
        item = await outbox.get()
        if item is _END:
            return
        if isinstance(item, Exception):
            raise item
        yield item