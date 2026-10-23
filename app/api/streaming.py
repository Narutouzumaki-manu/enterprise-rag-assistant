import asyncio
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID
import json

from app.schemas.agent import AgentResponse, AgentStep
from app.schemas.api import ApiCitation

GENERIC_ERROR = "Something went wrong on our side. Please try again."


@dataclass(frozen=True)
class StreamEvent:
    event: str
    data: dict


class Heartbeat:
    """Marker: nothing happened for a while; the route sends a keep-alive comment."""


HEARTBEAT = Heartbeat()
_END = object()


def split_words(text: str) -> list[str]:
    return re.findall(r"\S+\s*", text)  # each word keeps its trailing spaces


async def _with_heartbeat(events: AsyncIterator, interval: float) -> AsyncIterator:
    iterator = events.__aiter__()

    async def _next():
        try:
            return await iterator.__anext__()
        except StopAsyncIteration:
            return _END

    pending = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(_next())
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield HEARTBEAT  # still waiting: keep the same pending task alive
                continue
            task, pending = pending, None
            item = task.result()  # re-raises an error from the agent stream
            if item is _END:
                return
            yield item
    finally:
        if pending is not None:
            pending.cancel()


def _error_event(message: str = GENERIC_ERROR, code: str = "INTERNAL_ERROR") -> StreamEvent:
    return StreamEvent("error", {"error": message, "code": code})


async def build_chat_events(
    agent_events: AsyncIterator,
    request_id: UUID,
    heartbeat_seconds: float,
    source_files: dict[str, str] | None = None,
) -> AsyncIterator[StreamEvent | Heartbeat]:
    """Agent events in, API stream events out. Always ends with exactly one done or error."""
    if source_files is None:
        source_files = {}  # NOT "source_files or {}": a caller's empty dict is filled later, on purpose
    final: AgentResponse | None = None
    try:
        async for item in _with_heartbeat(agent_events, heartbeat_seconds):
            if item is HEARTBEAT:
                yield HEARTBEAT
            elif isinstance(item, AgentStep):
                yield StreamEvent(
                    "status", {"step_type": item.step_type.value, "content": item.content}
                )
            elif isinstance(item, AgentResponse):
                final = item
    except Exception:  # the agent should not raise; the client never sees the details
        yield _error_event()
        return

    if final is None:
        yield _error_event()
        return

    for citation in final.citations:
        api_citation = ApiCitation.model_validate(
            {**citation.model_dump(), "source_file": source_files.get(citation.document_id)}
        )
        yield StreamEvent("source", api_citation.model_dump())
    for word in split_words(final.answer):
        yield StreamEvent("token", {"text": word})
    yield StreamEvent(
        "verification",
        {"status": final.verification_status, "confidence": final.confidence},
    )
    yield StreamEvent(
        "done",
        {
            "request_id": str(request_id),
            "confidence": final.confidence,
            "latency_ms": round(final.latency_ms),
        },
    )

def format_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def format_comment(text: str = "keep-alive") -> str:
    return f": {text}\n\n"


async def sse_lines(events: AsyncIterator[StreamEvent | Heartbeat]) -> AsyncIterator[str]:
    async for item in events:
        if item is HEARTBEAT:
            yield format_comment()
        else:
            yield format_sse(item.event, item.data)