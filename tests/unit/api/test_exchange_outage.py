import logging
from uuid import uuid4

import pytest

from app.api.exchange import ChatStore, open_saved_stream
from app.schemas.agent import AgentResponse, AgentStep

RESPONSE = AgentResponse(
    answer="593,314",
    citations=[],
    trace=[],
    verification_status="verified",
    confidence=0.95,
    latency_ms=1.0,
)


class BrokenFactory:
    """Stands in for the session factory when Postgres is down."""

    def __call__(self):
        return self

    async def __aenter__(self):
        raise ConnectionError("unexpected connection_lost() call")

    async def __aexit__(self, *exc_info):
        return False


class FakeRuntime:
    async def stream(self, question, top_k):
        async def events():
            yield AgentStep(step_type="plan", content="Classified as simple; 1 sub-query")
            yield RESPONSE

        return events()


@pytest.mark.asyncio
async def test_failed_save_is_reported_not_raised(caplog):
    store = ChatStore(BrokenFactory())
    with caplog.at_level(logging.ERROR):
        saved = await store.save(uuid4(), "question", RESPONSE, {})
    assert saved is False
    assert "Could not save the exchange" in caplog.text


@pytest.mark.asyncio
async def test_failed_lookup_gives_empty_mapping():
    store = ChatStore(BrokenFactory())
    assert await store.source_files_for(RESPONSE) == {}


@pytest.mark.asyncio
async def test_stream_still_delivers_the_answer_when_the_database_is_down():
    store = ChatStore(BrokenFactory())
    stream = await open_saved_stream(FakeRuntime(), store, set(), uuid4(), "question", 8, {})
    items = [item async for item in stream]
    assert isinstance(items[0], AgentStep)
    assert isinstance(items[-1], AgentResponse)
    assert items[-1].answer == "593,314"