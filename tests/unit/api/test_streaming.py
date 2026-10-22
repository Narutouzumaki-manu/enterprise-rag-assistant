import asyncio
from uuid import uuid4

import pytest

from app.api.runtime import AgentRuntime
from app.api.streaming import HEARTBEAT, StreamEvent, build_chat_events, split_words

from .mocks import MockAgent, make_response, make_steps


def _names(events) -> list[str]:
    return ["heartbeat" if e is HEARTBEAT else e.event for e in events]


async def _collect(agent, request_id=None, heartbeat=15.0):
    runtime = AgentRuntime(agent, max_concurrent=2, wait_seconds=1)
    stream = build_chat_events(await runtime.stream("hi"), request_id or uuid4(), heartbeat)
    return [e async for e in stream]


def test_split_words_keeps_spacing_exactly():
    text = "Revenue grew  by 5%.\nNext line"
    assert "".join(split_words(text)) == text


@pytest.mark.asyncio
async def test_event_order_for_a_normal_answer():
    events = await _collect(MockAgent())
    assert _names(events) == [
        "status", "status", "status", "status",
        "source", "token", "token", "verification", "done",
    ]


@pytest.mark.asyncio
async def test_event_payloads():
    request_id = uuid4()
    events = await _collect(MockAgent(), request_id)
    assert events[0].data == {"step_type": "plan", "content": "Classified as simple; 1 sub-query"}
    source = next(e for e in events if e.event == "source")
    assert source.data == {
        "chunk_id": "chunk_1",
        "document_id": "doc_1",
        "page_number": 3,
        "text_snippet": "A mock snippet.",
        "source_file": None,
    }
    assert "".join(e.data["text"] for e in events if e.event == "token") == "Mock answer."
    verification = next(e for e in events if e.event == "verification")
    assert verification.data == {"status": "verified", "confidence": 0.95}
    assert events[-1] == StreamEvent(
        "done", {"request_id": str(request_id), "confidence": 0.95, "latency_ms": 10}
    )


@pytest.mark.asyncio
async def test_an_unverified_refusal_still_ends_with_done():
    refusal = make_response(
        answer="I don't have sufficient evidence in the provided documents.",
        status="unverified",
        confidence=0.0,
    )
    events = await _collect(MockAgent(response=refusal))
    assert events[-1].event == "done"
    verification = next(e for e in events if e.event == "verification")
    assert verification.data["status"] == "unverified"


@pytest.mark.asyncio
async def test_agent_error_ends_with_a_generic_error_event_and_no_done():
    events = await _collect(MockAgent(error=RuntimeError("secret detail")))
    assert _names(events) == ["status", "status", "status", "status", "error"]
    assert events[-1].data["code"] == "INTERNAL_ERROR"
    assert "secret detail" not in str(events[-1].data)


@pytest.mark.asyncio
async def test_a_stream_without_a_final_answer_ends_with_error():
    async def only_steps():
        yield make_steps()[0]

    events = [e async for e in build_chat_events(only_steps(), uuid4(), 15.0)]
    assert _names(events) == ["status", "error"]


@pytest.mark.asyncio
async def test_heartbeats_are_sent_while_the_agent_is_silent():
    async def slow_agent():
        await asyncio.sleep(0.3)
        yield make_response()

    events = [e async for e in build_chat_events(slow_agent(), uuid4(), 0.05)]
    names = _names(events)
    assert names.count("heartbeat") >= 2
    assert names[-1] == "done"
    assert names[0] == "heartbeat"