import asyncio
import time

import pytest

from app.api.runtime import AgentBusyError, AgentRuntime
from app.schemas.agent import AgentResponse, AgentStep

from .mocks import MockAgent


@pytest.mark.asyncio
async def test_stream_yields_steps_then_one_final_response():
    agent = MockAgent()
    runtime = AgentRuntime(agent, max_concurrent=2, wait_seconds=1)
    events = [e async for e in await runtime.stream("hi", top_k=5)]
    assert len(events) == 5
    assert all(isinstance(e, AgentStep) for e in events[:-1])
    assert isinstance(events[-1], AgentResponse)
    assert agent.calls == [{"query": "hi", "top_k": 5}]
    await asyncio.sleep(0)
    assert runtime.in_use == 0


@pytest.mark.asyncio
async def test_events_arrive_progressively_not_all_at_the_end():
    runtime = AgentRuntime(MockAgent(delay=0.5), max_concurrent=1, wait_seconds=1)
    events = await runtime.stream("hi")
    start = time.monotonic()
    first = await anext(events)
    elapsed = time.monotonic() - start
    assert isinstance(first, AgentStep)
    assert elapsed < 0.3  # the whole run takes about 0.5 s
    async for _ in events:
        pass


@pytest.mark.asyncio
async def test_busy_error_is_raised_before_any_streaming_starts():
    runtime = AgentRuntime(MockAgent(delay=0.3), max_concurrent=1, wait_seconds=0.05)
    first = await runtime.stream("one")
    with pytest.raises(AgentBusyError):
        await runtime.stream("two")
    async for _ in first:
        pass
    await asyncio.sleep(0)
    assert runtime.in_use == 0


@pytest.mark.asyncio
async def test_slot_stays_held_when_the_consumer_stops_early():
    runtime = AgentRuntime(MockAgent(delay=0.3), max_concurrent=1, wait_seconds=1)
    events = await runtime.stream("hi")
    await anext(events)
    await events.aclose()  # like a client disconnecting
    assert runtime.in_use == 1  # the agent thread is still running
    await asyncio.sleep(0.5)
    assert runtime.in_use == 0  # freed when the thread finished


@pytest.mark.asyncio
async def test_agent_error_reaches_the_consumer_and_frees_the_slot():
    runtime = AgentRuntime(MockAgent(error=RuntimeError("boom")), max_concurrent=1, wait_seconds=1)
    events = await runtime.stream("hi")
    with pytest.raises(RuntimeError):
        async for _ in events:
            pass
    await asyncio.sleep(0)
    assert runtime.in_use == 0