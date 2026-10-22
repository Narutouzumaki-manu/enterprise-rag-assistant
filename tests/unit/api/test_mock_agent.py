import time

import pytest

from app.schemas.agent import AgentResponse, AgentStep

from .mocks import MockAgent, make_response


def test_run_returns_response_and_records_call():
    agent = MockAgent()
    response = agent.run("hello", top_k=5)
    assert response.answer == "Mock answer."
    assert agent.calls == [{"query": "hello", "top_k": 5}]


def test_run_streaming_yields_steps_then_one_final_response():
    events = list(MockAgent().run_streaming("hello"))
    assert all(isinstance(e, AgentStep) for e in events[:-1])
    assert isinstance(events[-1], AgentResponse)
    assert len(events) == 5


def test_delay_really_blocks():
    start = time.perf_counter()
    MockAgent(delay=0.1).run("hello")
    assert time.perf_counter() - start >= 0.09  # small tolerance: Windows timers are not exact


def test_error_is_raised():
    with pytest.raises(RuntimeError):
        MockAgent(error=RuntimeError("boom")).run("hello")


def test_returned_response_is_a_copy():
    agent = MockAgent(response=make_response(answer="original"))
    first = agent.run("hello")
    first.answer = "changed"
    assert agent.run("hello").answer == "original"