
import asyncio
import threading
from collections.abc import AsyncIterator

from starlette.concurrency import run_in_threadpool

from app.schemas.agent import AgentResponse, AgentStep


class AgentBusyError(Exception):
    """All agent slots are taken and the wait time ran out."""


class AgentRuntime:
    def __init__(self, agent, max_concurrent: int, wait_seconds: float):
        self._agent = agent
        self._wait_seconds = wait_seconds
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._in_use = 0

    @property
    def in_use(self) -> int: 
        return self._in_use

    async def _acquire(self) -> None:
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=self._wait_seconds,
            )
        except TimeoutError:
            raise AgentBusyError(
                "The service is busy. Please try again shortly."
            ) from None
        self._in_use += 1

    def _release(self, _future=None) -> None:
        self._in_use -= 1
        self._semaphore.release()

    async def run(
        self, question: str, top_k: int | None = None
    ) -> AgentResponse:
        await self._acquire()
        task = asyncio.ensure_future(
            run_in_threadpool(
                self._agent.run,
                question,
                top_k=top_k,
            )
        )
        task.add_done_callback(
            self._release
        )  # freed when the thread ends, not when the caller leaves
        return await asyncio.shield(
            task
        )  # a cancelled caller does not cancel the thread

    async def stream(
        self, question: str, top_k: int | None = None
    ) -> AsyncIterator[AgentStep | AgentResponse]:
        await self._acquire()  # busy error is raised here, before any streaming starts
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def worker() -> None:
            try:
                for event in self._agent.run_streaming(question, top_k=top_k):
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception as exc:  # the agent should not raise; defence in depth
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(self._release)  # slot freed when the thread ends
                loop.call_soon_threadsafe(queue.put_nowait, None)  # end-of-stream marker

        threading.Thread(target=worker, daemon=True).start()
        return self._drain(queue)

    async def _drain(
        self, queue: asyncio.Queue
    ) -> AsyncIterator[AgentStep | AgentResponse]:
        while True:
            event = await queue.get()
            if event is None:
                return
            if isinstance(event, Exception):
                raise event
            yield event
