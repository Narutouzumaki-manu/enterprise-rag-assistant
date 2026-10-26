import asyncio
import time

import pytest

from app.api.shutdown import drain_background_tasks


@pytest.mark.asyncio
async def test_empty_set_returns_at_once():
    await drain_background_tasks(set(), grace_seconds=30)


@pytest.mark.asyncio
async def test_waits_for_tasks_that_finish_in_time():
    done = []

    async def work():
        await asyncio.sleep(0.05)
        done.append(1)

    tasks = {asyncio.create_task(work())}
    await drain_background_tasks(tasks, grace_seconds=2)
    assert done == [1]


@pytest.mark.asyncio
async def test_cancels_tasks_that_outlast_the_grace_period():
    async def forever():
        await asyncio.sleep(60)

    task = asyncio.create_task(forever())
    started = time.monotonic()
    await drain_background_tasks({task}, grace_seconds=0.1)
    assert task.cancelled()
    assert time.monotonic() - started < 3  # generous: Windows timers are coarse


@pytest.mark.asyncio
async def test_a_task_that_failed_does_not_break_the_drain():
    async def broken():
        raise ValueError("a bug")

    task = asyncio.create_task(broken())
    await drain_background_tasks({task}, grace_seconds=1)  # must not raise