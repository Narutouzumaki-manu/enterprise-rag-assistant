
import asyncio
import threading
import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.main import create_app
from app.api.runtime import AgentBusyError, AgentRuntime
from app.api.routes import health

from .mocks import MockAgent


class CountingAgent(MockAgent):
    """Records how many runs are active at the same moment."""

    def __init__(self, delay: float = 0.1):
        super().__init__(delay=delay)
        self.active = 0
        self.peak = 0
        self._lock = threading.Lock()

    def run(self, query, session_context=None, top_k=None):
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            return super().run(query, session_context, top_k)
        finally:
            with self._lock:
                self.active -= 1


@pytest.mark.asyncio
async def test_run_returns_response_and_passes_top_k():
    agent = MockAgent()
    runtime = AgentRuntime(agent, max_concurrent=2, wait_seconds=1)
    response = await runtime.run("hi", top_k=5)
    assert response.answer == "Mock answer."
    assert agent.calls == [{"query": "hi", "top_k": 5}]
    assert runtime.in_use == 0


@pytest.mark.asyncio
async def test_never_more_than_the_cap_run_at_once():
    agent = CountingAgent()
    runtime = AgentRuntime(agent, max_concurrent=2, wait_seconds=5)
    await asyncio.gather(*(runtime.run(f"q{i}") for i in range(4)))
    assert agent.peak == 2


@pytest.mark.asyncio
async def test_full_slots_give_busy_error_after_the_wait():
    runtime = AgentRuntime(MockAgent(delay=0.3), max_concurrent=1, wait_seconds=0.05)
    first = asyncio.create_task(runtime.run("one"))
    await asyncio.sleep(0.05)
    with pytest.raises(AgentBusyError):
        await runtime.run("two")
    await first
    assert runtime.in_use == 0


@pytest.mark.asyncio
async def test_slot_stays_held_after_the_caller_is_cancelled():
    runtime = AgentRuntime(MockAgent(delay=0.3), max_concurrent=1, wait_seconds=1)
    first = asyncio.create_task(runtime.run("one"))
    await asyncio.sleep(0.05)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert runtime.in_use == 1  # the thread is still running
    await asyncio.sleep(0.4)
    assert runtime.in_use == 0  # released when the thread finished


@pytest.mark.asyncio
async def test_agent_error_propagates_and_frees_the_slot():
    runtime = AgentRuntime(MockAgent(error=RuntimeError("boom")), max_concurrent=1, wait_seconds=1)
    with pytest.raises(RuntimeError):
        await runtime.run("hi")
    await asyncio.sleep(0)
    assert runtime.in_use == 0


@pytest.mark.asyncio
async def test_health_stays_responsive_while_an_agent_run_is_in_progress(monkeypatch):
    runtime = AgentRuntime(MockAgent(delay=0.5), max_concurrent=1, wait_seconds=1)
    transport = ASGITransport(app=create_app())

    async def fake_ok(request):
        return "ok"

    monkeypatch.setattr(health, "check_postgres", fake_ok)
    monkeypatch.setattr(health, "check_redis", fake_ok)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        running = asyncio.create_task(runtime.run("hi"))
        await asyncio.sleep(0.05)
        start = time.monotonic()
        response = await client.get("/health")
        elapsed = time.monotonic() - start
        await running
    assert response.status_code == 200
    assert elapsed < 0.2
