import pytest
from uuid import uuid4
from pydantic import ValidationError

from app.schemas.api import ApiCitation, ChatRequest, ChatResponse


def test_top_k_defaults_to_8():
    assert ChatRequest(session_id=uuid4(), query="hi").top_k == 8


@pytest.mark.parametrize("bad", [0, 21, -1])
def test_top_k_out_of_range_rejected(bad):
    with pytest.raises(ValidationError):
        ChatRequest(session_id=uuid4(), query="hi", top_k=bad)


def test_citation_inherits_agent_fields_and_adds_source_file():
    c = ApiCitation(chunk_id="c1", document_id="d1", text_snippet="x")
    assert c.page_number is None
    assert c.source_file is None


def test_chat_response_carries_verification_status():
    r = ChatResponse(
        request_id=uuid4(),
        answer="a",
        citations=[],
        verification_status="verified",
        confidence=0.95,
        latency_ms=10,
    )
    assert r.verification_status == "verified"